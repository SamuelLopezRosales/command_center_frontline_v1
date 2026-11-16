"""Stack CcEdge: CloudFront, WAF y firma de descargas (T-138; design.md §11.3, §11.4, §13.2,
§13.7; CC-REQ-088, CC-NFR-008).

**Región**: el stack se fija en ``us-east-1`` (las distribuciones, los ``WebACL`` de alcance
CloudFront y los certificados de CloudFront solo existen allí) y se crea con
``cross_region_references=True``: si la región principal cambia, las referencias a ``CcApi`` viajan
por parámetros de SSM de CDK. Hoy ambas son ``us-east-1`` y no hay recursos entre regiones. El
secreto ``cc/{env}/origin-verify`` se lee con una referencia dinámica de CloudFormation, que solo
resuelve secretos de la región del propio stack.

Comportamientos de la distribución (clase de precio 100, TLS 1.2 como mínimo con dominio propio):

======================  ===================  ===========================  ================
Ruta                    Origen               Caché                        Particularidades
======================  ===================  ===========================  ================
``/*`` (SPA)            S3 ``frontend``      CachingOptimized             función de reescritura
``/api/*``              API Gateway          ninguna                      encabezado de origen
``/webhook/*``          API Gateway          ninguna                      encabezado de origen
``/d/*``                API Gateway          ninguna                      sin registro de ruta
``/constancias/*.pdf``  S3 ``constancias``   ninguna                      grupo de claves
======================  ===================  ===========================  ================

Decisiones (``docs/desviaciones.md``):

- **Reescritura de la SPA**: una CloudFront Function de solicitud de visitante solo en el
  comportamiento predeterminado. No hay páginas de error globales (``CustomErrorResponses``), que
  también enmascararían los 403 y 404 de la API.
- **Encabezado secreto de origen**: ``X-Origin-Verify`` en los tres comportamientos de API; lo
  exige el ALB (``CcCompute``). Su valor es una referencia dinámica de Secrets Manager.
- **Descargas**: el servicio firma ``https://{dominio}/constancias/{empresa}/{año}/{folio}.pdf``
  (``firma_cloudfront.py`` usa la clave de S3 tal cual). Por eso el patrón es ``/constancias/*.pdf``
  y no ``/descargas/*`` del diseño: con ``/descargas`` habría que quitar el prefijo y la firma
  cubre la URL pedida. El patrón ``*.pdf`` evita chocar con las rutas ``/constancias/...`` de la
  SPA.
- **Sin registros de CloudFront ni de WAF**: ni la ruta ``/d/{token}`` ni las URL firmadas deben
  quedar en un registro (CC-REQ-162). Las métricas estándar de CloudFront bastan.
- **CSP**: ``default-src 'self'`` y ``connect-src`` con el origen propio, el punto de acceso de
  Cognito (la SPA inicia sesión con Amplify) y los buckets de cargas y plantillas (subidas
  prefirmadas). ``style-src`` admite ``'unsafe-inline'`` (TipTap y estilos de React, como la CSP
  de desarrollo de ``frontend/cabeceras.ts``); los scripts no.
- **Llave de firma**: ``-c cloudfront_public_key_pem=...`` carga la llave pública (la privada va a
  ``cc/{env}/cf-signing-key``). Sin ella, ``test`` usa una llave pública inerte cuyo par privado se
  descartó: las URL firmadas no validan hasta cargar la real. ``prod`` la exige.
- **WAF** (solo con ``waf_habilitado``): conjuntos administrados y reglas de tasa de §11.4; bloquea.
  ``CrossSiteScripting_BODY`` y ``SizeRestrictions_BODY`` van en conteo porque el editor de
  plantillas envía HTML en el cuerpo.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import aws_cdk as cdk
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_kms as kms
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as r53_targets
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_wafv2 as wafv2

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs.nag import reconocer
from infra.stacks.compute import ENCABEZADO_ORIGEN

REGION_EDGE = "us-east-1"
PATRON_DESCARGAS = "/constancias/*.pdf"

# Llave pública inerte (RSA 2048): el par privado se generó y se descartó. Hace que ``test`` sea
# desplegable antes de tener la llave real; ninguna URL firmada valida con ella.
CLAVE_PUBLICA_INERTE = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqZ+y/3xebHwsQ2vp1VfK
UXQf4pz1ZR7koGihDHQ0RdxTtAlGfIGPBNbsSzf+y78XpkT2JdMo/bBSi5qmwlun
NgjU4Qu5GsT1a86NI23h0mLzSihx6YiXD8xkAAteIugJop0tSrlJIp3R476uvU7I
xCP+tSlhDc1Hoy/uRWbj5YR84JCEP605PAFE7V/hyNami9oU+NHX3rwuj5ssbZk+
DpuXc+mB/UltEkBn2oe2GXAS0sCFFX4C+k/tbfeu+RQlKxoiwBuyiHlV+rhBUlAo
4oIh5mBFdWPJ4yqc87Z4MdpC1OwqPXFrFqc54JW8dE645sUfMibxX2WHHPFbcRzJ
BQIDAQAB
-----END PUBLIC KEY-----
"""

# Reescribe las rutas del cliente (sin extensión) a index.html. Solo se asocia al comportamiento
# predeterminado: /api, /webhook, /d y los PDF nunca pasan por aquí.
CODIGO_REESCRITURA_SPA = """function handler(event) {
  var request = event.request;
  var uri = request.uri;
  var ultimo = uri.substring(uri.lastIndexOf('/') + 1);
  if (uri.charAt(uri.length - 1) === '/' || ultimo.indexOf('.') === -1) {
    request.uri = '/index.html';
  }
  return request;
}
"""


@dataclass(frozen=True)
class LimiteWaf:
    """Límite por IP en una ventana de 5 minutos. [POR CONFIRMAR] (PQ-20, design.md §11.4)."""

    nombre: str
    prefijos: tuple[str, ...]
    solicitudes: int
    accion: str  # "block" o "count"


LIMITES_WAF: tuple[LimiteWaf, ...] = (
    LimiteWaf("tasa-publica", ("/api/v1/publico/", "/d/"), 100, "block"),
    LimiteWaf("tasa-api", ("/api/",), 1000, "block"),
    # Meta envía desde pocas IP: se cuenta, no se bloquea (la firma HMAC ya protege).
    LimiteWaf("tasa-webhook", ("/webhook/",), 5000, "count"),
)

# (nombre del conjunto administrado, reglas en conteo por el editor de plantillas)
CONJUNTOS_ADMINISTRADOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AWSManagedRulesAmazonIpReputationList", ()),
    ("AWSManagedRulesCommonRuleSet", ("SizeRestrictions_BODY", "CrossSiteScripting_BODY")),
    ("AWSManagedRulesKnownBadInputsRuleSet", ()),
)


def csp_spa(region: str, bucket_cargas: str, bucket_plantillas: str) -> str:
    """CSP de la SPA: solo recursos propios más Cognito y las subidas prefirmadas a S3."""
    subidas: list[str] = []
    for bucket in (bucket_cargas, bucket_plantillas):
        # boto3 prefirma con el punto de acceso regional o con el global según la región.
        subidas += [
            f"https://{bucket}.s3.{region}.amazonaws.com",
            f"https://{bucket}.s3.amazonaws.com",
        ]
    conectar = " ".join(["'self'", f"https://cognito-idp.{region}.amazonaws.com", *subidas])
    return "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "font-src 'self'",
            f"connect-src {conectar}",
            "frame-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )


CSP_API = "default-src 'none'; frame-ancestors 'none'"
# La página de descarga de /d/{token} usa estilos en línea y un formulario hacia el mismo origen.
CSP_DESCARGA = (
    "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; "
    "frame-ancestors 'none'"
)
CSP_PDF = "default-src 'none'; frame-ancestors 'none'; sandbox"


class EdgeStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        id_: str,
        *,
        ambiente: Ambiente,
        llave_infra_arn: str,
        bucket_frontend: str,
        bucket_constancias: str,
        bucket_cargas: str,
        bucket_plantillas: str,
        host_origen_api: str,
        clave_publica_pem: str | None = None,
        zona_hospedada_id: str | None = None,
        dominio_regional_api: str | None = None,
        zona_dominio_regional_api: str | None = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("cross_region_references", True)
        super().__init__(scope, id_, **kwargs)
        if self.region != REGION_EDGE:
            raise ValueError(
                f"CcEdge se fija en {REGION_EDGE} (CloudFront, WAF y ACM; design.md §13.2); "
                f"se recibió {self.region!r}"
            )
        env = ambiente.nombre
        eco = ambiente.economia
        es_prod = not eco.permite_borrado
        dominio = ambiente.dominio
        if es_prod and not (dominio and zona_hospedada_id and clave_publica_pem):
            raise ValueError(
                "prod exige el dominio propio, la zona alojada y la llave pública de CloudFront: "
                "-c zona_hospedada_id=... -c cloudfront_public_key_pem=..."
            )
        if es_prod and not eco.waf_habilitado:
            raise ValueError("prod exige waf_habilitado")

        # ------------------------------------------------------------------ buckets (por nombre)
        spa = s3.Bucket.from_bucket_name(self, "BucketSpa", bucket_frontend)
        constancias = s3.Bucket.from_bucket_name(self, "BucketConstancias", bucket_constancias)
        # La política de los buckets (OAC) vive en CcStorage: ver ``docs/desviaciones.md``.
        origen_spa = origins.S3BucketOrigin.with_origin_access_control(spa)
        origen_pdf = origins.S3BucketOrigin.with_origin_access_control(constancias)

        # ------------------------------------------------------------------ origen de la API
        secreto_origen = cdk.SecretValue.secrets_manager(f"cc/{env}/origin-verify").unsafe_unwrap()
        origen_api = origins.HttpOrigin(
            host_origen_api,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
            origin_ssl_protocols=[cloudfront.OriginSslPolicy.TLS_V1_2],
            read_timeout=cdk.Duration.seconds(30),
            keepalive_timeout=cdk.Duration.seconds(5),
            custom_headers={ENCABEZADO_ORIGEN: secreto_origen},
        )
        politica_origen_api = cloudfront.OriginRequestPolicy(
            self,
            "PoliticaOrigenApi",
            origin_request_policy_name=f"cc-{env}-api-origen",
            comment="Reenvía la IP del visitante y la firma de Meta; no el Host",
            header_behavior=cloudfront.OriginRequestHeaderBehavior.allow_list(
                "CloudFront-Viewer-Address",
                "Content-Type",
                "Accept",
                "Origin",
                "X-Hub-Signature-256",
            ),
            query_string_behavior=cloudfront.OriginRequestQueryStringBehavior.all(),
            cookie_behavior=cloudfront.OriginRequestCookieBehavior.none(),
        )
        # CloudFront no deja pasar ``Authorization`` por una política de origen: debe ir en la de
        # caché. TTL de 0 a 1 s con ``Authorization`` en la llave: no se guarda nada útil y, si el
        # origen pidiera cachear, la entrada sería por token (nunca compartida entre personas).
        politica_cache_api = cloudfront.CachePolicy(
            self,
            "PoliticaCacheApi",
            cache_policy_name=f"cc-{env}-api-sin-cache",
            comment="Sin caché; reenvía Authorization (design.md §13.7)",
            min_ttl=cdk.Duration.seconds(0),
            default_ttl=cdk.Duration.seconds(0),
            max_ttl=cdk.Duration.seconds(1),
            header_behavior=cloudfront.CacheHeaderBehavior.allow_list("Authorization"),
            query_string_behavior=cloudfront.CacheQueryStringBehavior.all(),
            cookie_behavior=cloudfront.CacheCookieBehavior.none(),
            enable_accept_encoding_gzip=True,
            enable_accept_encoding_brotli=True,
        )

        # ------------------------------------------------------------------ encabezados
        region = self.region
        politica_spa = self._politica_encabezados(
            "PoliticaSpa",
            f"cc-{env}-spa",
            csp_spa(region, bucket_cargas, bucket_plantillas),
            sin_cache=False,
        )
        politica_api = self._politica_encabezados(
            "PoliticaApi", f"cc-{env}-api", CSP_API, sin_cache=True
        )
        politica_descarga = self._politica_encabezados(
            "PoliticaDescarga", f"cc-{env}-descarga", CSP_DESCARGA, sin_cache=True
        )
        politica_pdf = self._politica_encabezados(
            "PoliticaPdf", f"cc-{env}-pdf", CSP_PDF, sin_cache=True
        )

        # ------------------------------------------------------------------ firma de descargas
        pem = clave_publica_pem or CLAVE_PUBLICA_INERTE
        huella = hashlib.sha256(pem.encode()).hexdigest()[:8]
        # El identificador incluye la huella: rotar la llave crea una nueva y no reemplaza en sitio.
        self.llave_publica = cloudfront.PublicKey(
            self,
            f"LlavePublica-{huella}",
            encoded_key=pem,
            comment=f"cc-{env}: verificación de URL firmadas de constancias",
        )
        self.grupo_claves = cloudfront.KeyGroup(
            self,
            f"GrupoClaves-{huella}",
            items=[self.llave_publica],
            comment=f"cc-{env}: llaves confiables para /constancias/*.pdf",
        )

        # ------------------------------------------------------------------ dominio y WAF
        certificado = None
        zona = None
        if dominio and zona_hospedada_id:
            zona = route53.PublicHostedZone.from_hosted_zone_attributes(
                self, "Zona", hosted_zone_id=zona_hospedada_id, zone_name=dominio
            )
            certificado = acm.Certificate(
                self,
                "Certificado",
                domain_name=dominio,
                validation=acm.CertificateValidation.from_dns(zona),
            )
        elif dominio:
            raise ValueError("el ambiente tiene dominio: pase -c zona_hospedada_id=...")

        self.web_acl = self._waf(env) if eco.waf_habilitado else None

        # ------------------------------------------------------------------ distribución
        funcion_spa = cloudfront.Function(
            self,
            "ReescrituraSpa",
            function_name=f"cc-{env}-reescritura-spa",
            comment="Rutas del cliente a index.html (sin páginas de error globales)",
            code=cloudfront.FunctionCode.from_inline(CODIGO_REESCRITURA_SPA),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
        )

        def comportamiento_api(
            politica: cloudfront.ResponseHeadersPolicy, con_autorizacion: bool = False
        ):
            return cloudfront.BehaviorOptions(
                origin=origen_api,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=(
                    politica_cache_api
                    if con_autorizacion
                    else cloudfront.CachePolicy.CACHING_DISABLED
                ),
                origin_request_policy=politica_origen_api,
                response_headers_policy=politica,
                compress=True,
            )

        self.distribucion = cloudfront.Distribution(
            self,
            "Distribucion",
            comment=f"Command Center {env}",
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
            enable_logging=False,
            enable_ipv6=True,
            web_acl_id=self.web_acl.attr_arn if self.web_acl else None,
            domain_names=[dominio] if certificado and dominio else None,
            certificate=certificado,
            minimum_protocol_version=(
                cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021 if certificado else None
            ),
            default_behavior=cloudfront.BehaviorOptions(
                origin=origen_spa,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                cached_methods=cloudfront.CachedMethods.CACHE_GET_HEAD,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                response_headers_policy=politica_spa,
                compress=True,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=funcion_spa, event_type=cloudfront.FunctionEventType.VIEWER_REQUEST
                    )
                ],
            ),
            additional_behaviors={
                "/api/*": comportamiento_api(politica_api, con_autorizacion=True),
                "/webhook/*": comportamiento_api(politica_api),
                "/d/*": comportamiento_api(politica_descarga),
                PATRON_DESCARGAS: cloudfront.BehaviorOptions(
                    origin=origen_pdf,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                    cached_methods=cloudfront.CachedMethods.CACHE_GET_HEAD,
                    # Son datos personales: sin caché en el borde. Solo se sirve con URL firmada.
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    response_headers_policy=politica_pdf,
                    trusted_key_groups=[self.grupo_claves],
                    compress=False,
                ),
            },
        )

        if zona is not None and dominio:
            destino = r53_targets.CloudFrontTarget(self.distribucion)
            route53.ARecord(
                self,
                "RegistroA",
                zone=zona,
                record_name=dominio,
                target=route53.RecordTarget.from_alias(destino),
            )
            route53.AaaaRecord(
                self,
                "RegistroAaaa",
                zone=zona,
                record_name=dominio,
                target=route53.RecordTarget.from_alias(destino),
            )
        if zona is not None and dominio_regional_api and zona_dominio_regional_api:
            route53.ARecord(
                self,
                "RegistroOrigenApi",
                zone=zona,
                record_name=host_origen_api,
                target=route53.RecordTarget.from_alias(
                    r53_targets.ApiGatewayv2DomainProperties(
                        dominio_regional_api, zona_dominio_regional_api
                    )
                ),
            )

        self.dominio_publico = dominio or self.distribucion.distribution_domain_name
        self._alarma_edge(env, llave_infra_arn)
        self._reconocimientos(env, es_prod)
        # Las políticas de OAC viven en CcStorage (un bucket admite una sola política).
        cdk.Annotations.of(self).acknowledge_warning(
            "@aws-cdk/aws-cloudfront-origins:updateImportedBucketPolicyOac",
            "La política OAC de los buckets frontend y constancias la define CcStorage "
            "(desviaciones.md): un bucket admite una sola política y evita un ciclo.",
        )

        cdk.CfnOutput(self, "DistribucionId", value=self.distribucion.distribution_id)
        cdk.CfnOutput(self, "DistribucionDominio", value=self.distribucion.distribution_domain_name)
        cdk.CfnOutput(self, "DominioPublico", value=self.dominio_publico)
        # Es el ``key_pair_id`` de ``cc/{env}/cf-signing-key`` y de ``CC_CLOUDFRONT_KEY_PAIR_ID``.
        cdk.CfnOutput(self, "LlavePublicaId", value=self.llave_publica.public_key_id)

    # ------------------------------------------------------------------------ piezas
    def _politica_encabezados(
        self, id_: str, nombre: str, csp: str, *, sin_cache: bool
    ) -> cloudfront.ResponseHeadersPolicy:
        personalizados = (
            [
                cloudfront.ResponseCustomHeader(
                    header="Cache-Control", value="no-store", override=False
                )
            ]
            if sin_cache
            else []
        )
        return cloudfront.ResponseHeadersPolicy(
            self,
            id_,
            response_headers_policy_name=nombre,
            comment="Encabezados de seguridad (design.md §11.4)",
            security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                strict_transport_security=cloudfront.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=cdk.Duration.days(730),
                    include_subdomains=True,
                    override=True,
                ),
                content_type_options=cloudfront.ResponseHeadersContentTypeOptions(override=True),
                frame_options=cloudfront.ResponseHeadersFrameOptions(
                    frame_option=cloudfront.HeadersFrameOption.DENY, override=True
                ),
                referrer_policy=cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=cloudfront.HeadersReferrerPolicy.NO_REFERRER, override=True
                ),
                content_security_policy=cloudfront.ResponseHeadersContentSecurityPolicy(
                    content_security_policy=csp, override=True
                ),
            ),
            custom_headers_behavior=cloudfront.ResponseCustomHeadersBehavior(
                custom_headers=personalizados
            )
            if personalizados
            else None,
        )

    def _waf(self, env: str) -> wafv2.CfnWebACL:
        """WAF de alcance CloudFront: conjuntos administrados y reglas de tasa (§11.4)."""

        def visibilidad(nombre: str) -> wafv2.CfnWebACL.VisibilityConfigProperty:
            return wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True,
                metric_name=f"cc-{env}-{nombre}",
                sampled_requests_enabled=False,
            )

        reglas: list[wafv2.CfnWebACL.RuleProperty] = []
        prioridad = 10
        for limite in LIMITES_WAF:
            alcances = [
                wafv2.CfnWebACL.StatementProperty(
                    byte_match_statement=wafv2.CfnWebACL.ByteMatchStatementProperty(
                        search_string=prefijo,
                        field_to_match=wafv2.CfnWebACL.FieldToMatchProperty(uri_path={}),
                        positional_constraint="STARTS_WITH",
                        text_transformations=[
                            wafv2.CfnWebACL.TextTransformationProperty(priority=0, type="NONE")
                        ],
                    )
                )
                for prefijo in limite.prefijos
            ]
            alcance = (
                alcances[0]
                if len(alcances) == 1
                else wafv2.CfnWebACL.StatementProperty(
                    or_statement=wafv2.CfnWebACL.OrStatementProperty(statements=alcances)
                )
            )
            reglas.append(
                wafv2.CfnWebACL.RuleProperty(
                    name=limite.nombre,
                    priority=prioridad,
                    action=wafv2.CfnWebACL.RuleActionProperty(
                        **({"block": {}} if limite.accion == "block" else {"count": {}})
                    ),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                            limit=limite.solicitudes,
                            aggregate_key_type="IP",
                            evaluation_window_sec=300,
                            scope_down_statement=alcance,
                        )
                    ),
                    visibility_config=visibilidad(limite.nombre),
                )
            )
            prioridad += 10
        for nombre, en_conteo in CONJUNTOS_ADMINISTRADOS:
            reglas.append(
                wafv2.CfnWebACL.RuleProperty(
                    name=nombre,
                    priority=prioridad,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS",
                            name=nombre,
                            rule_action_overrides=[
                                wafv2.CfnWebACL.RuleActionOverrideProperty(
                                    name=regla,
                                    action_to_use=wafv2.CfnWebACL.RuleActionProperty(count={}),
                                )
                                for regla in en_conteo
                            ]
                            or None,
                        )
                    ),
                    visibility_config=visibilidad(nombre),
                )
            )
            prioridad += 10
        return wafv2.CfnWebACL(
            self,
            "Waf",
            name=f"cc-{env}-cloudfront",
            description="Conjuntos administrados y límites de tasa de Command Center (§11.4)",
            scope="CLOUDFRONT",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            rules=reglas,
            visibility_config=visibilidad("cloudfront"),
        )

    def _alarma_edge(self, env: str, llave_infra_arn: str) -> None:
        """Tema ``alertas-edge`` y alarma de 5xx de CloudFront (las métricas viven en us-east-1)."""
        self.tema_edge = sns.Topic(
            self,
            "AlertasEdge",
            topic_name=f"cc-{env}-alertas-edge",
            display_name="Command Center: alertas del borde",
            master_key=kms.Key.from_key_arn(self, "LlaveInfraImportada", llave_infra_arn),
            enforce_ssl=True,
        )
        alarma = cloudwatch.Alarm(
            self,
            "Alarma5xx",
            alarm_name=f"cc-{env}-edge-5xx",
            alarm_description=(
                "[POR CONFIRMAR, PQ-20] CloudFront: más de 5 % de respuestas 5xx durante 5 "
                "minutos. Runbook: docs/runbooks/api-5xx-y-latencia.md"
            ),
            metric=cloudwatch.Metric(
                namespace="AWS/CloudFront",
                metric_name="5xxErrorRate",
                dimensions_map={
                    "DistributionId": self.distribucion.distribution_id,
                    "Region": "Global",
                },
                statistic="Average",
                period=cdk.Duration.minutes(5),
            ),
            threshold=5,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        alarma.add_alarm_action(cw_actions.SnsAction(self.tema_edge))

    def _reconocimientos(self, env: str, es_prod: bool) -> None:
        reconocer(
            self.distribucion,
            "AwsSolutions-CFR1",
            "Sin restricción geográfica: el webhook de Meta, las personas colaboradoras de viaje "
            "y el personal de RH pueden conectarse desde cualquier país; la autenticación y WAF "
            "(prod) son los controles.",
        )
        reconocer(
            self.distribucion,
            "AwsSolutions-CFR3",
            "Sin registro de acceso de CloudFront a propósito: guardaría la ruta /d/{token} y las "
            "URL firmadas (design.md §11, CC-REQ-162). Quedan las métricas estándar.",
        )
        if not es_prod:
            reconocer(
                self.distribucion,
                "AwsSolutions-CFR2",
                "WAF no se crea en test (economia.waf_habilitado=false; presupuesto de 50 USD). "
                "prod lo crea y bloquea.",
            )
            reconocer(
                self.distribucion,
                "AwsSolutions-CFR4",
                "Sin dominio propio (PQ-22) la distribución usa el certificado predeterminado de "
                "CloudFront, que no permite fijar TLS 1.2 como mínimo; con dominio se fija "
                "TLSv1.2_2021.",
            )
