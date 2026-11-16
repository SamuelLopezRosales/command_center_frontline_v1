"""T-138: aserciones de CcEdge (CloudFront, WAF, política de encabezados y firma de descargas)."""

import aws_cdk as cdk
import pytest

from infra.stacks.edge import (
    CODIGO_REESCRITURA_SPA,
    CONJUNTOS_ADMINISTRADOS,
    LIMITES_WAF,
    EdgeStack,
    csp_spa,
)
from infra.tests.ayudas_borde import (
    ENV_EDGE,
    LLAVE_ARN,
    alarmas_por_nombre,
    construir_borde_prod,
    propiedades,
    recursos,
    texto,
)
from infra.tests.ayudas_computo import PERMITIDA, ambiente_prod

ID_CACHING_DISABLED = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
ID_CACHING_OPTIMIZED = "658327ea-f89d-4fab-a63d-7e88639e58f6"


@pytest.fixture(scope="module")
def plantilla(ensamblado_test):
    return ensamblado_test[1]["edge"]


@pytest.fixture(scope="module")
def prod():
    return construir_borde_prod()


def _config(plantilla) -> dict:
    (d,) = propiedades(plantilla, "AWS::CloudFront::Distribution")
    return d["DistributionConfig"]


def _comportamientos(plantilla) -> dict[str, dict]:
    return {c["PathPattern"]: c for c in _config(plantilla)["CacheBehaviors"]}


def _politicas_encabezados(plantilla) -> dict[str, dict]:
    return {
        p["ResponseHeadersPolicyConfig"]["Name"]: p["ResponseHeadersPolicyConfig"]
        for p in propiedades(plantilla, "AWS::CloudFront::ResponseHeadersPolicy")
    }


def _por_id(plantilla, tipo: str) -> dict[str, dict]:
    return {lid: r["Properties"] for lid, r in recursos(plantilla, tipo).items()}


# ------------------------------------------------------------------------------ región
def test_el_stack_se_fija_en_us_east_1(ensamblado_test):
    stacks, _ = ensamblado_test
    assert stacks["edge"].region == "us-east-1"


def test_el_stack_rechaza_otra_region():
    app = cdk.App()
    with pytest.raises(ValueError, match="us-east-1"):
        EdgeStack(
            app,
            "CcEdge-test",
            ambiente=ambiente_prod(),
            llave_infra_arn=LLAVE_ARN,
            bucket_frontend="f",
            bucket_constancias="c",
            bucket_cargas="a",
            bucket_plantillas="p",
            host_origen_api="x.execute-api.us-east-2.amazonaws.com",
            env=cdk.Environment(account=PERMITIDA, region="us-east-2"),
        )


def test_prod_exige_dominio_zona_y_llave_publica():
    app = cdk.App()
    with pytest.raises(ValueError, match="prod exige"):
        EdgeStack(
            app,
            "CcEdge-prod",
            ambiente=ambiente_prod(),
            llave_infra_arn=LLAVE_ARN,
            bucket_frontend="f",
            bucket_constancias="c",
            bucket_cargas="a",
            bucket_plantillas="p",
            host_origen_api="x.execute-api.us-east-1.amazonaws.com",
            env=ENV_EDGE,
        )


# ------------------------------------------------------------------------------ comportamientos
def test_comportamientos_de_la_distribucion(plantilla):
    cfg = _config(plantilla)
    assert set(_comportamientos(plantilla)) == {
        "/api/*",
        "/webhook/*",
        "/d/*",
        "/constancias/*.pdf",
    }
    assert cfg["PriceClass"] == "PriceClass_100"
    assert cfg["DefaultRootObject"] == "index.html"
    assert cfg["DefaultCacheBehavior"]["ViewerProtocolPolicy"] == "redirect-to-https"
    assert cfg["DefaultCacheBehavior"]["CachePolicyId"] == ID_CACHING_OPTIMIZED


def test_sin_paginas_de_error_globales_que_enmascaren_los_errores_de_la_api(plantilla):
    cfg = _config(plantilla)
    assert "CustomErrorResponses" not in cfg
    # La reescritura de la SPA es una función del comportamiento predeterminado, no de los demás.
    (asoc,) = cfg["DefaultCacheBehavior"]["FunctionAssociations"]
    assert asoc["EventType"] == "viewer-request"
    for c in _comportamientos(plantilla).values():
        assert "FunctionAssociations" not in c


def test_la_funcion_de_reescritura_envia_las_rutas_del_cliente_a_index_html(plantilla):
    (f,) = propiedades(plantilla, "AWS::CloudFront::Function")
    assert f["FunctionConfig"]["Runtime"] == "cloudfront-js-2.0"
    assert f["FunctionCode"] == CODIGO_REESCRITURA_SPA
    assert "/index.html" in f["FunctionCode"]
    assert f["AutoPublish"] is True


def test_origen_de_la_spa_y_de_los_pdf_por_oac_sin_identidad_de_acceso_antigua(plantilla):
    cfg = _config(plantilla)
    s3 = [o for o in cfg["Origins"] if "S3OriginConfig" in o]
    assert {o["DomainName"].split(".")[0] for o in s3} == {
        f"cc-test-{PERMITIDA}-frontend",
        f"cc-test-{PERMITIDA}-constancias",
    }
    for o in s3:
        assert o["S3OriginConfig"]["OriginAccessIdentity"] == ""
        assert "OriginAccessControlId" in o
    oacs = propiedades(plantilla, "AWS::CloudFront::OriginAccessControl")
    assert len(oacs) == 2
    for o in oacs:
        assert o["OriginAccessControlConfig"]["SigningBehavior"] == "always"
        assert o["OriginAccessControlConfig"]["SigningProtocol"] == "sigv4"


def test_origen_de_la_api_con_tls12_y_encabezado_secreto_como_referencia_dinamica(plantilla):
    (api,) = (o for o in _config(plantilla)["Origins"] if "CustomOriginConfig" in o)
    assert api["CustomOriginConfig"]["OriginProtocolPolicy"] == "https-only"
    assert api["CustomOriginConfig"]["OriginSSLProtocols"] == ["TLSv1.2"]
    (cabecera,) = api["OriginCustomHeaders"]
    assert cabecera["HeaderName"] == "X-Origin-Verify"
    # Solo la referencia a Secrets Manager: el valor no está en la plantilla.
    assert cabecera["HeaderValue"].startswith("{{resolve:secretsmanager:cc/test/origin-verify:")
    assert "execute-api" in texto(api["DomainName"])


def test_api_webhook_y_descargas_sin_cache_y_solo_https(plantilla):
    comp = _comportamientos(plantilla)
    for ruta in ("/webhook/*", "/d/*"):
        assert comp[ruta]["CachePolicyId"] == ID_CACHING_DISABLED
        assert comp[ruta]["ViewerProtocolPolicy"] == "https-only"
    api = comp["/api/*"]
    assert api["ViewerProtocolPolicy"] == "https-only"
    assert set(api["AllowedMethods"]) >= {"GET", "POST", "PUT", "PATCH", "DELETE"}
    # Sin cachear: TTL máximo de 1 s y la llave de caché incluye Authorization.
    politicas = _por_id(plantilla, "AWS::CloudFront::CachePolicy")
    cache = politicas[api["CachePolicyId"]["Ref"]]["CachePolicyConfig"]
    assert (cache["MinTTL"], cache["DefaultTTL"], cache["MaxTTL"]) == (0, 0, 1)
    assert cache["ParametersInCacheKeyAndForwardedToOrigin"]["HeadersConfig"]["Headers"] == [
        "Authorization"
    ]
    assert cache["ParametersInCacheKeyAndForwardedToOrigin"]["CookiesConfig"] == {
        "CookieBehavior": "none"
    }


def test_politica_de_origen_reenvia_ip_del_visitante_y_firma_pero_no_el_host(plantilla):
    (p,) = propiedades(plantilla, "AWS::CloudFront::OriginRequestPolicy")
    cabeceras = p["OriginRequestPolicyConfig"]["HeadersConfig"]
    assert cabeceras["HeaderBehavior"] == "whitelist"
    assert "CloudFront-Viewer-Address" in cabeceras["Headers"]
    assert "X-Hub-Signature-256" in cabeceras["Headers"]  # la firma HMAC del webhook de Meta
    assert "Host" not in cabeceras["Headers"]  # API Gateway exige su propio Host
    assert p["OriginRequestPolicyConfig"]["QueryStringsConfig"]["QueryStringBehavior"] == "all"
    assert p["OriginRequestPolicyConfig"]["CookiesConfig"]["CookieBehavior"] == "none"
    comp = _comportamientos(plantilla)
    for ruta in ("/api/*", "/webhook/*", "/d/*"):
        assert "OriginRequestPolicyId" in comp[ruta]


# ------------------------------------------------------------------------------ descargas firmadas
def test_los_pdf_se_sirven_solo_con_grupo_de_claves_y_sin_cache(plantilla):
    pdf = _comportamientos(plantilla)["/constancias/*.pdf"]
    assert pdf["ViewerProtocolPolicy"] == "https-only"
    assert pdf["AllowedMethods"] == ["GET", "HEAD"]
    assert pdf["CachePolicyId"] == ID_CACHING_DISABLED  # datos personales: nada en el borde
    (grupo,) = pdf["TrustedKeyGroups"]
    grupos = _por_id(plantilla, "AWS::CloudFront::KeyGroup")
    (llave_ref,) = grupos[grupo["Ref"]]["KeyGroupConfig"]["Items"]
    llaves = _por_id(plantilla, "AWS::CloudFront::PublicKey")
    assert llaves[llave_ref["Ref"]]["PublicKeyConfig"]["EncodedKey"].startswith(
        "-----BEGIN PUBLIC KEY-----"
    )


def test_la_clave_publica_nunca_es_una_clave_privada(plantilla):
    assert "PRIVATE KEY" not in texto(plantilla.to_json())


def test_el_patron_de_descargas_coincide_con_la_clave_que_firma_el_servicio():
    """El servicio firma ``https://{dominio}/{pdf_s3_key}`` con la clave de ``almacenamiento``."""
    import fnmatch

    from infra.stacks.edge import PATRON_DESCARGAS

    # Formato de ``cc_constancias.almacenamiento.clave_constancia``: constancias/{empresa}/{año}/{folio}.pdf
    ruta = "/constancias/12/2026/CC-2026-000001.pdf"
    assert fnmatch.fnmatchcase(ruta, PATRON_DESCARGAS)
    # Las rutas del cliente de la SPA no caen en el comportamiento de descargas.
    for spa in ("/constancias", "/constancias/historial", "/constancias/plantillas/3"):
        assert not fnmatch.fnmatchcase(spa, PATRON_DESCARGAS)


# ------------------------------------------------------------------------------ encabezados
def test_politica_de_encabezados_de_la_spa_con_csp_estricta(plantilla):
    p = _politicas_encabezados(plantilla)["cc-test-spa"]
    seg = p["SecurityHeadersConfig"]
    csp = seg["ContentSecurityPolicy"]["ContentSecurityPolicy"]
    assert csp == csp_spa(
        "us-east-1", f"cc-test-{PERMITIDA}-cargas", f"cc-test-{PERMITIDA}-plantillas"
    )
    directivas = dict(d.split(" ", 1) for d in csp.split("; "))
    assert directivas["default-src"] == "'self'"
    assert directivas["script-src"] == "'self'"  # sin unsafe-inline ni unsafe-eval en scripts
    assert directivas["object-src"] == "'none'"
    assert directivas["frame-ancestors"] == "'none'"
    assert directivas["img-src"] == "'self' data: blob:"
    assert "*" not in csp.replace("'self'", "")  # sin comodines de origen
    conectar = directivas["connect-src"].split()
    assert conectar[0] == "'self'"
    assert "https://cognito-idp.us-east-1.amazonaws.com" in conectar
    assert f"https://cc-test-{PERMITIDA}-cargas.s3.us-east-1.amazonaws.com" in conectar
    assert f"https://cc-test-{PERMITIDA}-plantillas.s3.us-east-1.amazonaws.com" in conectar
    assert all(c.startswith(("'self'", "https://")) for c in conectar)
    assert seg["StrictTransportSecurity"]["AccessControlMaxAgeSec"] >= 31536000
    assert seg["StrictTransportSecurity"]["IncludeSubdomains"] is True
    assert seg["ContentTypeOptions"] == {"Override": True}
    assert seg["ReferrerPolicy"]["ReferrerPolicy"] == "no-referrer"
    assert seg["FrameOptions"]["FrameOption"] == "DENY"


def test_encabezados_de_la_api_las_descargas_y_los_pdf_sin_cache(plantilla):
    politicas = _politicas_encabezados(plantilla)
    for nombre in ("cc-test-api", "cc-test-descarga", "cc-test-pdf"):
        p = politicas[nombre]
        (cab,) = p["CustomHeadersConfig"]["Items"]
        assert cab["Header"] == "Cache-Control"
        assert cab["Value"] == "no-store"
        assert p["SecurityHeadersConfig"]["ReferrerPolicy"]["ReferrerPolicy"] == "no-referrer"
        assert (
            "frame-ancestors 'none'"
            in (p["SecurityHeadersConfig"]["ContentSecurityPolicy"]["ContentSecurityPolicy"])
        )
    # La página de /d/{token} solo usa estilos en línea y un formulario hacia el mismo origen.
    csp = politicas["cc-test-descarga"]["SecurityHeadersConfig"]["ContentSecurityPolicy"]
    assert "form-action 'self'" in csp["ContentSecurityPolicy"]
    assert "script" not in csp["ContentSecurityPolicy"]


# ------------------------------------------------------------------------------ registros
def test_sin_registros_de_cloudfront_ni_de_waf_para_no_guardar_d_token(plantilla, prod):
    """CC-REQ-162: ni /d/{token} ni las URL firmadas deben quedar en un registro."""
    for t in (plantilla, prod["edge"]):
        assert "Logging" not in _config(t)
        assert not recursos(t, "AWS::WAFv2::LoggingConfiguration")
        assert not recursos(t, "AWS::CloudFront::RealtimeLogConfig")
        assert not recursos(t, "AWS::Logs::LogGroup")


# ------------------------------------------------------------------------------ WAF
def test_en_test_no_se_crea_waf(plantilla):
    assert not recursos(plantilla, "AWS::WAFv2::WebACL")
    assert "WebACLId" not in _config(plantilla)


def test_en_test_la_distribucion_usa_el_certificado_de_cloudfront(plantilla):
    cfg = _config(plantilla)
    # Sin ViewerCertificate CloudFront aplica su certificado predeterminado (*.cloudfront.net).
    assert "ViewerCertificate" not in cfg
    assert "Aliases" not in cfg
    assert not recursos(plantilla, "AWS::CertificateManager::Certificate")
    assert not recursos(plantilla, "AWS::Route53::RecordSet")


def test_en_prod_el_waf_tiene_los_conjuntos_administrados_y_las_reglas_de_tasa(prod):
    t = prod["edge"]
    (waf,) = propiedades(t, "AWS::WAFv2::WebACL")
    assert waf["Scope"] == "CLOUDFRONT"
    assert waf["DefaultAction"] == {"Allow": {}}
    reglas = {r["Name"]: r for r in waf["Rules"]}
    for nombre, _ in CONJUNTOS_ADMINISTRADOS:
        r = reglas[nombre]
        assert r["Statement"]["ManagedRuleGroupStatement"]["VendorName"] == "AWS"
        assert r["OverrideAction"] == {"None": {}}
    comunes = reglas["AWSManagedRulesCommonRuleSet"]["Statement"]["ManagedRuleGroupStatement"]
    assert {o["Name"]: o["ActionToUse"] for o in comunes["RuleActionOverrides"]} == {
        "SizeRestrictions_BODY": {"Count": {}},
        "CrossSiteScripting_BODY": {"Count": {}},
    }
    tasa = {n: r for n, r in reglas.items() if "RateBasedStatement" in r["Statement"]}
    assert set(tasa) == {limite.nombre for limite in LIMITES_WAF}
    for limite in LIMITES_WAF:
        r = tasa[limite.nombre]
        estado = r["Statement"]["RateBasedStatement"]
        assert estado["Limit"] == limite.solicitudes
        assert estado["AggregateKeyType"] == "IP"
        assert estado["EvaluationWindowSec"] == 300
        # Prod bloquea; el webhook solo cuenta para no bloquear a Meta (la firma ya protege).
        assert r["Action"] == ({"Block": {}} if limite.accion == "block" else {"Count": {}})
        for prefijo in limite.prefijos:
            assert prefijo in texto(estado["ScopeDownStatement"])
    por_nombre = {limite.nombre: limite for limite in LIMITES_WAF}
    assert por_nombre["tasa-publica"].solicitudes == 100  # design.md §11.4
    assert por_nombre["tasa-api"].solicitudes == 1000
    assert por_nombre["tasa-webhook"].accion == "count"
    prioridades = [r["Priority"] for r in waf["Rules"]]
    assert len(set(prioridades)) == len(prioridades)
    (cfg,) = propiedades(t, "AWS::CloudFront::Distribution")
    assert "WebACLId" in cfg["DistributionConfig"]


def test_en_prod_dominio_propio_tls12_certificado_y_registros(prod):
    t = prod["edge"]
    cfg = _config(t)
    assert cfg["Aliases"] == ["cc.example.com"]
    assert cfg["ViewerCertificate"]["MinimumProtocolVersion"] == "TLSv1.2_2021"
    assert cfg["ViewerCertificate"]["SslSupportMethod"] == "sni-only"
    (cert,) = propiedades(t, "AWS::CertificateManager::Certificate")
    assert cert["DomainName"] == "cc.example.com"
    assert cert["ValidationMethod"] == "DNS"
    tipos = sorted(r["Type"] for r in propiedades(t, "AWS::Route53::RecordSet"))
    assert tipos == ["A", "A", "AAAA"]  # sitio (A y AAAA) y origen regional de la API
    # En prod el origen es el dominio propio de la API, no el endpoint predeterminado.
    (api,) = (o for o in cfg["Origins"] if "CustomOriginConfig" in o)
    assert "origen.cc.example.com" in texto(api["DomainName"])


# ------------------------------------------------------------------------------ alarma y políticas de buckets
def test_alarma_de_5xx_de_cloudfront_con_runbook_y_tema_del_borde(plantilla):
    alarmas = alarmas_por_nombre(plantilla)
    a = alarmas["cc-test-edge-5xx"]
    assert a["Namespace"] == "AWS/CloudFront"
    assert a["MetricName"] == "5xxErrorRate"
    assert a["Threshold"] == 5
    assert "docs/runbooks/api-5xx-y-latencia.md" in a["AlarmDescription"]
    assert "POR CONFIRMAR" in a["AlarmDescription"]
    (topic,) = propiedades(plantilla, "AWS::SNS::Topic")
    assert topic["TopicName"] == "cc-test-alertas-edge"
    assert "KmsMasterKeyId" in topic


def test_cloudfront_lee_los_buckets_con_oac_desde_ccstorage(ensamblado_test):
    """La política OAC vive en CcStorage (un bucket admite una sola política)."""
    _, plantillas = ensamblado_test
    politicas = propiedades(plantillas["storage"], "AWS::S3::BucketPolicy")
    sentencias = [
        s
        for p in politicas
        for s in p["PolicyDocument"]["Statement"]
        if s.get("Sid") == "CloudFrontLeeConOac"
    ]
    assert len(sentencias) == 2
    recursos_leidos = sorted(texto(s["Resource"]) for s in sentencias)
    assert any("/constancias/*" in r for r in recursos_leidos)  # solo los PDF
    for s in sentencias:
        assert s["Principal"] == {"Service": "cloudfront.amazonaws.com"}
        assert s["Action"] == "s3:GetObject"
        assert PERMITIDA in texto(s["Condition"]["StringLike"]["aws:SourceArn"])
    # CcEdge no define políticas de bucket ni modifica los buckets importados.
    assert not recursos(ensamblado_test[1]["edge"], "AWS::S3::BucketPolicy")


def test_la_plantilla_no_lleva_secretos(plantilla, prod):
    for t in (plantilla, prod["edge"]):
        s = texto(t.to_json())
        assert "AKIA" not in s
        assert "PRIVATE KEY" not in s
