"""Stack CcApi: HTTP API de API Gateway, VPC Link y autorizador JWT (T-137; design.md §11.1,
§11.4, §13.1, §13.7; CC-REQ-088, CC-REQ-158, CC-NFR-008).

Rutas (una integración por destino y una ruta por prefijo):

========================================  ===================  ======================
Ruta                                      Autenticación        Destino
========================================  ===================  ======================
``ANY /api/{proxy+}``                     JWT de Cognito       VPC Link, ALB interno
``GET|POST /api/v1/publico/{proxy+}``     ninguna (pública)    VPC Link, ALB interno
``GET|POST /d/{proxy+}``                  ninguna (pública)    VPC Link, ALB interno
``GET|POST /webhook/meta``                ninguna (HMAC)       Lambda ``webhook-meta``
========================================  ===================  ======================

API Gateway elige la ruta más específica: ``/api/v1/publico/{proxy+}`` gana a ``/api/{proxy+}``.
**No hay ninguna ruta ``/internal/*`` ni ruta predeterminada** (``$default``): lo que no coincide
recibe 404 de API Gateway, así que el VPC Link nunca alcanza las rutas internas del ALB.

Decisiones (``docs/desviaciones.md``):

- **Encabezado secreto de origen**: CloudFront agrega ``X-Origin-Verify`` y las reglas públicas del
  ALB (``CcCompute``) lo exigen; el valor vive en ``cc/{env}/origin-verify`` y solo las referencias
  dinámicas de CloudFormation lo leen. API Gateway (HTTP API) no admite WAF ni condiciones por
  encabezado, y un autorizador Lambda no puede convivir con el JWT en la misma ruta. La Lambda
  ``webhook-meta`` no recibe esa verificación: la protege la firma HMAC de Meta (CC-REQ-158).
- **Punto de acceso predeterminado**: en ``test`` (sin dominio, PQ-22) se usa el de ``execute-api``;
  con dominio propio se crea el dominio regional de origen y se deshabilita el predeterminado.
- **Limitación de tasa**: por etapa y por ruta (no por IP: eso lo hace WAF en ``prod``). Los valores
  son **[POR CONFIRMAR]** (PQ-20) y viven en ``LIMITES``.
- **Registro de acceso**: sin ruta real (``$context.path`` llevaría el token de ``/d/{token}``),
  sin encabezados, sin consulta y sin cuerpos; solo la clave de ruta con plantilla, estado y
  latencia. ``requestId`` es la ``correlacion_id`` (§15.1) y se propaga al ALB.
- **CORS**: mismo origen (CloudFront sirve la SPA y ``/api``). Con dominio propio solo se admite
  ese origen; sin dominio (``test``, ``samuel``) no se configura CORS: API Gateway no admite
  comodines (``https://*.cloudfront.net``) y con el mismo origen no hay preflight.

Todo lo de otros stacks llega por ARN o por referencia de salida: ningún permiso ni regla se
agrega a un recurso ajeno.
"""

from __future__ import annotations

from dataclasses import dataclass

import aws_cdk as cdk
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs.nag import reconocer
from infra.constructs.retencion import politica_retencion

GRUPO_SUBREDES_APLICACION = "aplicacion"
ENCABEZADO_CORRELACION = "X-Correlation-Id"


@dataclass(frozen=True)
class LimiteRuta:
    """Límite de tasa de una ruta: solicitudes por segundo y ráfaga. [POR CONFIRMAR] (PQ-20)."""

    tasa: int
    rafaga: int
    nota: str


# Valores propuestos, a confirmar con la carga real (PQ-20). Las rutas públicas son las más
# estrictas (CC-REQ-084, 090); el webhook admite las ráfagas de Meta.
LIMITES: dict[str, LimiteRuta] = {
    "etapa": LimiteRuta(100, 200, "Predeterminado de la etapa: cualquier ruta sin límite propio"),
    "api": LimiteRuta(50, 100, "Rutas con sesión (JWT)"),
    "publico": LimiteRuta(5, 10, "Verificación pública de constancias (sin sesión)"),
    "descarga": LimiteRuta(5, 10, "Enlaces de un solo uso /d/{token}"),
    "webhook_get": LimiteRuta(2, 5, "Verificación de la suscripción de Meta (poco frecuente)"),
    "webhook_post": LimiteRuta(50, 100, "Mensajes y estados de Meta; la firma HMAC ya protege"),
}


@dataclass(frozen=True)
class DefRuta:
    ruta: str
    metodos: tuple[str, ...]
    destino: str  # "alb" o "lambda"
    autenticacion: str  # "jwt" o "ninguna"
    limite: str


# Un solo lugar con todas las rutas expuestas. Ninguna empieza por /internal.
RUTAS: tuple[DefRuta, ...] = (
    DefRuta("/api/{proxy+}", ("ANY",), "alb", "jwt", "api"),
    DefRuta("/api/v1/publico/{proxy+}", ("GET", "POST"), "alb", "ninguna", "publico"),
    DefRuta("/d/{proxy+}", ("GET", "POST"), "alb", "ninguna", "descarga"),
    DefRuta("/webhook/meta", ("GET",), "lambda", "ninguna", "webhook_get"),
    DefRuta("/webhook/meta", ("POST",), "lambda", "ninguna", "webhook_post"),
)

# Sin ``$context.path``, ``$context.requestOverride``, encabezados, consulta ni claims del JWT.
FORMATO_REGISTRO_ACCESO = (
    '{"requestId":"$context.requestId","ts":"$context.requestTimeEpoch",'
    '"ruta":"$context.routeKey","estado":"$context.status",'
    '"latenciaMs":"$context.responseLatency","integracionMs":"$context.integrationLatency",'
    '"estadoIntegracion":"$context.integrationStatus",'
    '"errorIntegracion":"$context.integrationErrorMessage"}'
)


def clave_ruta(metodo: str, ruta: str) -> str:
    return f"{metodo} {ruta}"


class ApiStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        id_: str,
        *,
        ambiente: Ambiente,
        vpc: ec2.IVpc,
        sg_vpclink: ec2.ISecurityGroup,
        sg_alb: ec2.ISecurityGroup,
        listener_arn: str,
        user_pool_id: str,
        cliente_id: str,
        dominio_interno: str | None = None,
        dominio_origen: str | None = None,
        certificado_origen_arn: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, id_, **kwargs)
        env = ambiente.nombre
        ret = politica_retencion(ambiente)
        es_prod = not ambiente.economia.permite_borrado
        if es_prod and not (dominio_origen and certificado_origen_arn and ambiente.dominio):
            raise ValueError(
                "prod exige el dominio propio y el dominio de origen de la API: pase "
                "-c dominio_origen_api=... -c certificado_origen_api_arn=... "
                "(certificado de ACM de la región principal)"
            )
        if bool(dominio_origen) != bool(certificado_origen_arn):
            raise ValueError("dominio_origen y certificado_origen_arn van juntos")
        self.dominio_origen = dominio_origen

        # ------------------------------------------------------------------ VPC Link y ALB
        sg_enlace = ec2.SecurityGroup.from_security_group_id(
            self, "SgVpcLinkImportado", sg_vpclink.security_group_id, mutable=False
        )
        sg_balanceador = ec2.SecurityGroup.from_security_group_id(
            self, "SgAlbImportado", sg_alb.security_group_id, mutable=False
        )
        self.vpc_link = apigw.VpcLink(
            self,
            "VpcLink",
            vpc_link_name=f"cc-{env}",
            vpc=vpc,
            subnets=ec2.SubnetSelection(subnet_group_name=GRUPO_SUBREDES_APLICACION),
            security_groups=[sg_enlace],
        )
        listener = elbv2.ApplicationListener.from_application_listener_attributes(
            self, "ListenerAlb", listener_arn=listener_arn, security_group=sg_balanceador
        )
        integracion_alb = integrations.HttpAlbIntegration(
            "IntegracionAlb",
            listener,
            vpc_link=self.vpc_link,
            # Con HTTPS interno el VPC Link verifica el nombre del certificado del ALB.
            secure_server_name=dominio_interno,
            # El requestId de API Gateway es la correlacion_id de los servicios (§15.1).
            parameter_mapping=apigw.ParameterMapping().overwrite_header(
                ENCABEZADO_CORRELACION, apigw.MappingValue.context_variable("requestId")
            ),
        )

        # ------------------------------------------------------------------ webhook-meta
        # Alias ``live`` de la Lambda de CcWorkersLambdas, importado por ARN construido.
        arn_alias = (
            f"arn:{self.partition}:lambda:{self.region}:{self.account}"
            f":function:cc-{env}-webhook-meta:live"
        )
        webhook = lambda_.Function.from_function_attributes(
            self, "WebhookMeta", function_arn=arn_alias, same_environment=True
        )
        integracion_lambda = integrations.HttpLambdaIntegration("IntegracionWebhook", webhook)

        # ------------------------------------------------------------------ API
        # Con dominio propio solo se admite ese origen. Sin dominio (test, samuel) el origen de
        # CloudFront no se conoce al crear la API y API Gateway no admite comodines: no se
        # configura CORS, porque la SPA y `/api` salen por el mismo dominio (sin preflight).
        cors = (
            apigw.CorsPreflightOptions(
                allow_origins=[f"https://{ambiente.dominio}"],
                allow_methods=[
                    apigw.CorsHttpMethod.GET,
                    apigw.CorsHttpMethod.POST,
                    apigw.CorsHttpMethod.PUT,
                    apigw.CorsHttpMethod.PATCH,
                    apigw.CorsHttpMethod.DELETE,
                ],
                allow_headers=["Authorization", "Content-Type", "Accept", ENCABEZADO_CORRELACION],
                max_age=cdk.Duration.hours(1),
            )
            if ambiente.dominio
            else None
        )
        self.api = apigw.HttpApi(
            self,
            "Api",
            api_name=f"cc-{env}",
            description="Command Center: API pública (JWT de Cognito, rutas públicas y webhook)",
            create_default_stage=False,
            disable_execute_api_endpoint=bool(dominio_origen),
            cors_preflight=cors,
        )
        autorizador = authorizers.HttpJwtAuthorizer(
            "Jwt",
            jwt_issuer=f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool_id}",
            jwt_audience=[cliente_id],
            authorizer_name=f"cc-{env}-cognito",
            identity_source=["$request.header.Authorization"],
        )
        self.rutas: list[apigw.HttpRoute] = []
        for d in RUTAS:
            rutas = self.api.add_routes(
                path=d.ruta,
                methods=[apigw.HttpMethod(m) for m in d.metodos],
                integration=integracion_alb if d.destino == "alb" else integracion_lambda,
                authorizer=autorizador if d.autenticacion == "jwt" else None,
            )
            for r in rutas:
                self.rutas.append(r)
                if d.autenticacion != "jwt":
                    reconocer(
                        r,
                        "AwsSolutions-APIG4",
                        "Ruta pública por diseño (design.md §11.1): "
                        + (
                            "el webhook de Meta se autentica con la firma HMAC en la Lambda "
                            "(CC-REQ-158)."
                            if d.destino == "lambda"
                            else "verificación pública y enlaces de un solo uso con tokens de "
                            "alta entropía, límite de tasa en API Gateway y WAF."
                        ),
                    )

        # ------------------------------------------------------------------ etapa y registros
        grupo_logs = logs.LogGroup(
            self,
            "RegistroAcceso",
            log_group_name=f"/cc/{env}/api-gateway",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=ret.removal_policy,
        )
        etapa_limite = LIMITES["etapa"]
        self.etapa = apigw.HttpStage(
            self,
            "Etapa",
            http_api=self.api,
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(
                rate_limit=etapa_limite.tasa, burst_limit=etapa_limite.rafaga
            ),
        )
        cfn_etapa = self.etapa.node.default_child
        cfn_etapa.access_log_settings = apigw.CfnStage.AccessLogSettingsProperty(
            destination_arn=grupo_logs.log_group_arn, format=FORMATO_REGISTRO_ACCESO
        )
        # Se escribe con las claves de CloudFormation: el mapa de estructuras del L1 de CDK emite
        # las propiedades en camelCase y CloudFormation las rechazaría.
        configuracion: dict[str, dict[str, int]] = {}
        for d in RUTAS:
            limite = LIMITES[d.limite]
            for m in d.metodos:
                configuracion[clave_ruta(m, d.ruta)] = {
                    "ThrottlingRateLimit": limite.tasa,
                    "ThrottlingBurstLimit": limite.rafaga,
                }
        cfn_etapa.add_property_override("RouteSettings", configuracion)
        # Los ajustes por ruta nombran las rutas con texto: CloudFormation no ve esa dependencia y
        # podía crear la etapa antes (error "Unable to find Route by key ANY /api/{proxy+}").
        for ruta in self.rutas:
            cfn_etapa.node.add_dependency(ruta)

        # ------------------------------------------------------------------ dominio de origen
        if dominio_origen and certificado_origen_arn:
            self.dominio = apigw.DomainName(
                self,
                "DominioOrigen",
                domain_name=dominio_origen,
                certificate=acm.Certificate.from_certificate_arn(
                    self, "CertificadoOrigen", certificado_origen_arn
                ),
                security_policy=apigw.SecurityPolicy.TLS_1_2,
            )
            apigw.ApiMapping(
                self, "MapeoOrigen", api=self.api, domain_name=self.dominio, stage=self.etapa
            )
            self.host_origen = dominio_origen
            cdk.CfnOutput(self, "DominioRegional", value=self.dominio.regional_domain_name)
            cdk.CfnOutput(self, "ZonaDominioRegional", value=self.dominio.regional_hosted_zone_id)
        else:
            self.dominio = None
            self.host_origen = f"{self.api.api_id}.execute-api.{self.region}.{self.url_suffix}"

        cdk.CfnOutput(self, "ApiId", value=self.api.api_id)
        cdk.CfnOutput(self, "HostOrigen", value=self.host_origen)
        cdk.CfnOutput(self, "VpcLinkId", value=self.vpc_link.vpc_link_id)
