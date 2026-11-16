"""T-137: aserciones de CcApi (HTTP API, VPC Link, autorizador JWT, rutas y límites de tasa)."""

import json

import aws_cdk as cdk
import pytest

from infra.stacks.api import LIMITES, RUTAS, ApiStack, clave_ruta
from infra.tests.ayudas_borde import construir_borde_prod, propiedades, recursos, texto
from infra.tests.ayudas_computo import ENV_AWS, PERMITIDA, ambiente_prod, base_sintetica

PUBLICAS = {
    "GET /api/v1/publico/{proxy+}",
    "POST /api/v1/publico/{proxy+}",
    "GET /d/{proxy+}",
    "POST /d/{proxy+}",
}
WEBHOOK = {"GET /webhook/meta", "POST /webhook/meta"}


@pytest.fixture(scope="module")
def plantilla(ensamblado_test):
    return ensamblado_test[1]["api"]


@pytest.fixture(scope="module")
def plantilla_prod():
    return construir_borde_prod()["api"]


def _rutas(plantilla) -> dict[str, dict]:
    return {p["RouteKey"]: p for p in propiedades(plantilla, "AWS::ApiGatewayV2::Route")}


# ------------------------------------------------------------------------------ VPC Link y ALB
def test_vpc_link_a_las_subredes_de_aplicacion_con_su_grupo_de_seguridad(plantilla):
    (enlace,) = propiedades(plantilla, "AWS::ApiGatewayV2::VpcLink")
    assert enlace["Name"] == "cc-test"
    assert len(enlace["SubnetIds"]) == 2
    (sg,) = enlace["SecurityGroupIds"]
    assert "ImportValue" in texto(sg)  # sg-vpclink de CcNetwork, no uno nuevo


def test_las_rutas_de_la_aplicacion_van_al_listener_del_alb_por_el_vpc_link(plantilla):
    integraciones = propiedades(plantilla, "AWS::ApiGatewayV2::Integration")
    (i,) = (i for i in integraciones if i["IntegrationType"] == "HTTP_PROXY")
    assert i["ConnectionType"] == "VPC_LINK"
    assert "AlbListener" in texto(i["IntegrationUri"])  # exportación de CcCompute
    # El requestId de API Gateway es la correlacion_id de los servicios (§15.1).
    assert i["RequestParameters"] == {"overwrite:header.X-Correlation-Id": "$context.requestId"}


def test_el_alb_no_se_modifica_desde_api(plantilla):
    """Nada de grupos de seguridad ni reglas del ALB en este stack (lección de T-040 a T-047)."""
    for tipo in (
        "AWS::EC2::SecurityGroupIngress",
        "AWS::EC2::SecurityGroup",
        "AWS::ElasticLoadBalancingV2::ListenerRule",
    ):
        assert not recursos(plantilla, tipo)


# ------------------------------------------------------------------------------ autenticación
def test_autorizador_jwt_con_emisor_y_cliente_del_pool_de_cognito(plantilla):
    (a,) = propiedades(plantilla, "AWS::ApiGatewayV2::Authorizer")
    assert a["AuthorizerType"] == "JWT"
    assert a["IdentitySource"] == ["$request.header.Authorization"]
    assert "cognito-idp" in texto(a["JwtConfiguration"]["Issuer"])
    assert "CcAuth-test" in texto(a["JwtConfiguration"]["Issuer"])
    assert "CcAuth-test" in texto(a["JwtConfiguration"]["Audience"])


def test_solo_api_lleva_autorizador_y_solo_publico_d_y_webhook_no(plantilla):
    rutas = _rutas(plantilla)
    con_jwt = {k for k, p in rutas.items() if p["AuthorizationType"] == "JWT"}
    sin = {k for k, p in rutas.items() if p["AuthorizationType"] == "NONE"}
    assert con_jwt == {"ANY /api/{proxy+}"}
    assert sin == PUBLICAS | WEBHOOK
    assert set(rutas) == con_jwt | sin  # ninguna otra ruta


def test_las_rutas_publicas_son_mas_especificas_que_la_de_api():
    """API Gateway elige la ruta más específica: la pública gana a ``/api/{proxy+}``."""
    sin_jwt = [r for r in RUTAS if r.autenticacion == "ninguna" and r.destino == "alb"]
    assert {r.ruta for r in sin_jwt} == {"/api/v1/publico/{proxy+}", "/d/{proxy+}"}


# ------------------------------------------------------------------------------ lo que NO se expone
def test_ninguna_ruta_internal_ni_ruta_predeterminada(plantilla):
    rutas = _rutas(plantilla)
    assert not [k for k in rutas if "internal" in k.lower()]
    assert not [k for k in rutas if k.endswith("$default")]
    # La definición tampoco: un cambio en RUTAS fallaría aquí antes que en el despliegue.
    assert not [r for r in RUTAS if "internal" in r.ruta]
    # Y tampoco hay un comodín que las alcance (``/{proxy+}`` cubriría /internal).
    assert not [k for k in rutas if k.split(" ", 1)[1].startswith("/{")]


# ------------------------------------------------------------------------------ webhook
def test_webhook_meta_va_a_la_lambda_con_el_alias_live(plantilla):
    integraciones = propiedades(plantilla, "AWS::ApiGatewayV2::Integration")
    (lam,) = (i for i in integraciones if i["IntegrationType"] == "AWS_PROXY")
    assert f"{PERMITIDA}:function:cc-test-webhook-meta:live" in texto(lam["IntegrationUri"])
    assert lam["PayloadFormatVersion"] == "2.0"  # el handler lee requestContext.http.method
    rutas = _rutas(plantilla)
    # Una sola integración para los dos métodos del webhook.
    assert len({texto(rutas[k]["Target"]) for k in WEBHOOK}) == 1


def test_api_gateway_puede_invocar_solo_el_alias_y_solo_esa_ruta(plantilla):
    permisos = propiedades(plantilla, "AWS::Lambda::Permission")
    assert permisos
    for p in permisos:
        assert p["Principal"] == "apigateway.amazonaws.com"
        assert texto(p["FunctionName"]).endswith(':function:cc-test-webhook-meta:live"]]}')
        assert "/webhook/meta" in texto(p["SourceArn"])


# ------------------------------------------------------------------------------ límites de tasa
def test_limites_de_tasa_por_etapa_y_por_ruta(plantilla):
    (etapa,) = propiedades(plantilla, "AWS::ApiGatewayV2::Stage")
    assert etapa["StageName"] == "$default"
    assert etapa["DefaultRouteSettings"] == {
        "ThrottlingRateLimit": LIMITES["etapa"].tasa,
        "ThrottlingBurstLimit": LIMITES["etapa"].rafaga,
    }
    por_ruta = etapa["RouteSettings"]
    assert set(por_ruta) == set(_rutas(plantilla))  # toda ruta tiene límite propio
    for d in RUTAS:
        for m in d.metodos:
            esperado = LIMITES[d.limite]
            assert por_ruta[clave_ruta(m, d.ruta)] == {
                "ThrottlingRateLimit": esperado.tasa,
                "ThrottlingBurstLimit": esperado.rafaga,
            }


def test_las_rutas_publicas_tienen_los_limites_mas_bajos():
    assert LIMITES["publico"].tasa < LIMITES["api"].tasa
    assert LIMITES["descarga"].tasa < LIMITES["api"].tasa
    assert LIMITES["webhook_post"].tasa >= LIMITES["api"].tasa  # Meta envía ráfagas


# ------------------------------------------------------------------------------ registros
def test_registro_de_acceso_sin_ruta_real_encabezados_ni_cuerpos(plantilla):
    (etapa,) = propiedades(plantilla, "AWS::ApiGatewayV2::Stage")
    formato = etapa["AccessLogSettings"]["Format"]
    datos = json.loads(formato)
    assert datos["requestId"] == "$context.requestId"
    # $context.path llevaría el token de /d/{token}; la clave de ruta lleva la plantilla.
    assert datos["ruta"] == "$context.routeKey"
    for prohibido in (
        "$context.path",
        "$context.requestoverride",
        "$context.authorizer",
        "$context.identity",
        "$context.httpmethod",
        "request.header",
        "request.querystring",
        "$context.domainname",
        "body",
        "token",
    ):
        assert prohibido not in formato.lower()
    (grupo,) = propiedades(plantilla, "AWS::Logs::LogGroup")
    assert grupo["LogGroupName"] == "/cc/test/api-gateway"
    assert grupo["RetentionInDays"] == 30


# ------------------------------------------------------------------------------ test y prod
def test_en_test_se_usa_el_endpoint_predeterminado_y_sin_cors_con_comodines(plantilla):
    (api,) = propiedades(plantilla, "AWS::ApiGatewayV2::Api")
    assert api["ProtocolType"] == "HTTP"
    assert not api.get("DisableExecuteApiEndpoint")  # PQ-22: sin dominio propio en test
    assert not recursos(plantilla, "AWS::ApiGatewayV2::DomainName")
    # API Gateway rechaza comodines en CORS (falla vista al desplegar `samuel`): mismo origen, sin CORS
    assert "CorsConfiguration" not in api
    assert "*" not in json.dumps(api)


def test_prod_deshabilita_el_endpoint_predeterminado_y_usa_dominio_regional_tls12(plantilla_prod):
    (api,) = propiedades(plantilla_prod, "AWS::ApiGatewayV2::Api")
    assert api["DisableExecuteApiEndpoint"] is True
    assert api["CorsConfiguration"]["AllowOrigins"] == ["https://cc.example.com"]
    (dominio,) = propiedades(plantilla_prod, "AWS::ApiGatewayV2::DomainName")
    assert dominio["DomainName"] == "origen.cc.example.com"
    (cfg,) = dominio["DomainNameConfigurations"]
    assert cfg["SecurityPolicy"] == "TLS_1_2"
    assert cfg["EndpointType"] == "REGIONAL"
    assert len(propiedades(plantilla_prod, "AWS::ApiGatewayV2::ApiMapping")) == 1


def test_prod_con_https_interno_verifica_el_nombre_del_certificado_del_alb(plantilla_prod):
    integraciones = propiedades(plantilla_prod, "AWS::ApiGatewayV2::Integration")
    (alb,) = (i for i in integraciones if i["IntegrationType"] == "HTTP_PROXY")
    assert alb["TlsConfig"] == {"ServerNameToVerify": "interno.cc.example.com"}


def test_prod_exige_dominio_de_origen():
    app = cdk.App()
    b = base_sintetica(app)
    with pytest.raises(ValueError, match="prod exige"):
        ApiStack(
            app,
            "CcApi-prod",
            ambiente=ambiente_prod(),
            vpc=b["vpc"],
            sg_vpclink=b["sg_lambda"],
            sg_alb=b["sg_alb"],
            listener_arn="arn:aws:elasticloadbalancing:us-east-1:1:listener/app/x/y/z",
            user_pool_id="p",
            cliente_id="c",
            env=ENV_AWS,
        )


# ------------------------------------------------------------------------------ orden de despliegue
def test_orden_de_despliegue_sin_ciclos_y_con_las_dependencias_del_diseno(ensamblado_test):
    stacks, _ = ensamblado_test
    nombre = {id(s): n for n, s in stacks.items()}

    def dependencias(s):
        return {nombre[id(d)] for d in s.dependencies}

    assert {"compute", "auth", "workers", "network"} <= dependencias(stacks["api"])
    assert {"api", "storage", "security"} <= dependencias(stacks["edge"])
    assert {"edge", "storage", "auth"} <= dependencias(stacks["frontend"])
    assert {"api", "edge", "compute", "data", "messaging"} <= dependencias(stacks["observability"])
    # Ningún stack depende (directa o indirectamente) de sí mismo.
    for s in stacks.values():
        visto: set = set()
        pila = list(s.dependencies)
        while pila:
            d = pila.pop()
            assert d is not s, f"ciclo en {s.stack_name}"
            if id(d) not in visto:
                visto.add(id(d))
                pila += list(d.dependencies)


def test_la_plantilla_no_lleva_secretos(plantilla):
    t = texto(plantilla.to_json()).lower()
    assert "origin-verify" not in t
    assert "akia" not in t
    assert "secretsmanager:" not in t


def test_la_etapa_se_crea_despues_de_todas_las_rutas(plantilla):
    """Los ajustes por ruta de la etapa nombran rutas por texto; sin DependsOn, CloudFormation
    podía crear la etapa antes (falla vista al desplegar `samuel`)."""
    (etapa,) = recursos(plantilla, "AWS::ApiGatewayV2::Stage").values()
    rutas = recursos(plantilla, "AWS::ApiGatewayV2::Route")
    assert rutas and set(rutas) <= set(etapa["DependsOn"])
