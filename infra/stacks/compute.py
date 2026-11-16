"""Stack CcCompute: servicios de ECS Fargate y ALB interno con reglas por ruta (T-135;
design.md §3.8, §12, §13.6, §13.7; CC-NFR-005, 007, 008, 016).

Seis servicios de API (``dashboard``, ``colaboradores``, ``campos``, ``constancias``,
``whatsapp``, ``notificaciones``) en Fargate ARM64 sobre el clúster ``cc-{env}`` de
``CcComputeBase``. Cada uno tiene su definición de tarea, su rol de tarea con solo lo que su código
usa (``infra/constructs/servicios.py``), su grupo de logs y su grupo de destino en el ALB.

Decisiones (registradas en ``docs/desviaciones.md``):

- **Imágenes como activos de CDK (D-11)**: ``cdk deploy`` construye ``services/<x>/Dockerfile``
  con ``linux/arm64`` desde la raíz del repositorio y la publica; no hay etiquetas manuales.
- **Tamaño**: 0.5 vCPU y 1 GB; ``campos`` 0.25 vCPU y 0.5 GB (§13.6). Tareas por servicio: las de
  ``economia.tareas_por_servicio`` (1 en ``test``, 2 en ``prod``). En ``prod`` el autoescalado va
  de 2 a 6 tareas por CPU al 60 %; en ``test`` no hay autoescalado (una tarea y presupuesto fijo).
- **Despliegue**: actualización continua 100 %/200 % con corte de circuito y reversión; verificación
  de salud ``GET /salud`` en el ALB y en el contenedor; ``stopTimeout`` de 120 s.
- **ALB interno**: sin salida a internet. Las reglas por ruta de §13.7 llevan a cada servicio sus
  rutas públicas (las que API Gateway reenvía por el VPC Link) y sus rutas ``/internal/*``, que
  usan los demás servicios y las Lambdas con el token interno. API Gateway no define ninguna ruta
  ``/internal/*`` (T-225), así que el ALB no las expone al exterior; el acceso se limita por grupo
  de seguridad (``sg-vpclink``, ``sg-ecs`` y ``sg-lambda``).
- **Descubrimiento entre servicios**: todas las ``CC_*_URL`` apuntan a la dirección del ALB
  interno y el ALB enruta por ruta (design.md §3.8/§13.7). No se usa Cloud Map: un solo punto de
  entrada con grupos de seguridad ya definidos y sin un segundo mecanismo de descubrimiento que
  mantener.
- **HTTPS interno**: sin dominio (``test``, PQ-22) ACM no emite un certificado para el nombre del
  ALB, así que el listener es HTTP en el puerto 80 y el tráfico no sale de la VPC (grupos de
  seguridad cerrados; el token interno firma cada llamada). Si se entrega un certificado
  (``-c certificado_alb_arn=... -c dominio_interno=...``) el listener es HTTPS 443 con TLS 1.2 y
  1.3, y las URL usan ``dominio_interno``. ``prod`` exige el certificado.

Todo lo que viene de otros stacks se importa por nombre o por ARN construido: ningún permiso ni
regla se agrega a un recurso ajeno (lección de T-040 a T-047).
"""

from __future__ import annotations

from dataclasses import dataclass

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs.nag import reconocer
from infra.constructs.retencion import politica_retencion
from infra.constructs.servicios import (
    GRUPO_SUBREDES_APLICACION,
    PUERTO_API,
    SERVICIOS,
    ContextoPermisos,
    Recursos,
    cluster_importado,
    comodines_servicio,
    entorno_base,
    imagen_servicio,
    reconocer_comodines,
    reconocer_tarea,
    sentencias_servicio,
    tarea_fargate,
    variables_servicio,
)

# Encabezado secreto de origen (design.md §11.4, T-225): CloudFront lo agrega y las reglas públicas
# del ALB lo exigen. El valor vive en ``cc/{env}/origin-verify``; la plantilla solo lleva la
# referencia dinámica de CloudFormation, nunca el valor.
ENCABEZADO_ORIGEN = "X-Origin-Verify"
PRIORIDAD_PRIMERA_INTERNA = 100
PUERTO_HTTP_INTERNO = 80
PUERTO_HTTPS_INTERNO = 443
MAXIMO_TAREAS_PROD = 6
CPU_OBJETIVO_PCT = 60

# (vCPU en unidades de ECS, memoria en MiB) por servicio, §13.6.
TAMANOS: dict[str, tuple[int, int]] = {
    "dashboard": (512, 1024),
    "colaboradores": (512, 1024),
    "campos": (256, 512),
    "constancias": (512, 1024),
    "whatsapp": (512, 1024),
    "notificaciones": (512, 1024),
}


@dataclass(frozen=True)
class ReglaAlb:
    """Una regla del listener. Un ALB admite hasta 5 valores y 5 comodines por regla."""

    prioridad: int
    destino: str
    patrones: tuple[str, ...]
    nota: str


# Prioridad menor = se evalúa antes. Las de ``/internal`` empiezan en 110 (design.md §13.7).
REGLAS_ALB: tuple[ReglaAlb, ...] = (
    ReglaAlb(
        10,
        "dashboard",
        ("/api/v1/constancias/historial", "/api/v1/constancias/historial/*"),
        "El historial lo sirve dashboard y va antes que /api/v1/constancias/* (constancias)",
    ),
    ReglaAlb(
        20,
        "dashboard",
        ("/api/v1/dashboard*", "/api/v1/usuarios*", "/api/v1/sesion*", "/api/v1/bitacora*"),
        "Dashboard, usuarios, sesión y bitácora",
    ),
    ReglaAlb(
        30,
        "colaboradores",
        (
            "/api/v1/colaboradores*",
            "/api/v1/cargas*",
            "/api/v1/organizaciones*",
            "/api/v1/plantas*",
        ),
        "Colaboradores, cargas masivas, organizaciones y plantas",
    ),
    ReglaAlb(40, "campos", ("/api/v1/campos*",), "Campos personalizados"),
    ReglaAlb(
        50,
        "constancias",
        (
            "/api/v1/plantillas",
            "/api/v1/plantillas/*",
            "/api/v1/constancias",
            "/api/v1/constancias/*",
        ),
        "Plantillas de constancia y constancias (salvo historial). /plantillas/* no coincide "
        "con /plantillas-mensaje",
    ),
    ReglaAlb(
        55,
        "constancias",
        ("/api/v1/publico/*", "/d/*"),
        "Verificación pública y descarga por enlace de un solo uso",
    ),
    ReglaAlb(
        60,
        "notificaciones",
        ("/api/v1/audiencias*", "/api/v1/plantillas-mensaje*", "/api/v1/notificaciones*"),
        "Audiencias, plantillas de mensaje y notificaciones",
    ),
    ReglaAlb(70, "whatsapp", ("/api/v1/conversaciones*",), "Chat de RH"),
    # Rutas internas (token de servicio). La más específica va primero.
    ReglaAlb(
        110,
        "colaboradores",
        ("/internal/campos/*/uso",),
        "INT-COL-10: uso de un campo (campos lo consulta a colaboradores)",
    ),
    ReglaAlb(
        120,
        "campos",
        ("/internal/campos*", "/internal/empresas/*"),
        "INT-CAM-01 y INT-CAM-02",
    ),
    ReglaAlb(
        130,
        "colaboradores",
        ("/internal/colaboradores*", "/internal/organizaciones*"),
        "INT-COL-01 a 09",
    ),
    ReglaAlb(
        140,
        "notificaciones",
        ("/internal/plantillas-mensaje*",),
        "INT-NOT-01; antes que /internal/plantillas* (constancias)",
    ),
    ReglaAlb(
        150,
        "constancias",
        ("/internal/plantillas*", "/internal/solicitudes*"),
        "INT-CON-01 a 06",
    ),
)


class ComputeStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        id_: str,
        *,
        ambiente: Ambiente,
        llave_infra: kms.IKey,
        llave_datos: kms.IKey,
        vpc: ec2.IVpc,
        sg_ecs: ec2.ISecurityGroup,
        sg_alb: ec2.ISecurityGroup,
        bucket_plantillas: str,
        bucket_constancias: str,
        bucket_cargas: str,
        host_bd: str,
        user_pool_id: str,
        user_pool_arn: str,
        cliente_id: str,
        certificado_arn: str | None = None,
        dominio_interno: str | None = None,
        empresa_id_whatsapp: int | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, id_, **kwargs)
        env = ambiente.nombre
        eco = ambiente.economia
        ret = politica_retencion(ambiente)
        es_prod = not eco.permite_borrado
        if es_prod and not (certificado_arn and dominio_interno):
            raise ValueError(
                "prod exige HTTPS interno: pase certificado_arn y dominio_interno "
                "(-c certificado_alb_arn=... -c dominio_interno=...)"
            )
        if bool(certificado_arn) != bool(dominio_interno):
            raise ValueError("certificado_arn y dominio_interno van juntos")
        self.r = Recursos(self, env)
        r = self.r

        # Importados por ARN o por ID: no se modifican desde aquí.
        llave_infra_arn = llave_infra.key_arn
        sg_servicio = ec2.SecurityGroup.from_security_group_id(
            self, "SgEcsImportado", sg_ecs.security_group_id, mutable=False
        )
        sg_balanceador = ec2.SecurityGroup.from_security_group_id(
            self, "SgAlbImportado", sg_alb.security_group_id, mutable=False
        )
        cluster = cluster_importado(self, vpc, env)
        subredes = ec2.SubnetSelection(subnet_group_name=GRUPO_SUBREDES_APLICACION)

        # ------------------------------------------------------------------ ALB interno
        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "Alb",
            load_balancer_name=f"cc-{env}-interno",
            vpc=vpc,
            internet_facing=False,
            vpc_subnets=subredes,
            security_group=sg_balanceador,
            drop_invalid_header_fields=True,
            deletion_protection=es_prod,
            idle_timeout=cdk.Duration.seconds(60),
        )
        respuesta_no_encontrada = elbv2.ListenerAction.fixed_response(
            404, content_type="application/json", message_body='{"codigo":"RUTA_NO_ENCONTRADA"}'
        )
        if certificado_arn:
            self.listener = self.alb.add_listener(
                "ListenerHttps",
                port=PUERTO_HTTPS_INTERNO,
                protocol=elbv2.ApplicationProtocol.HTTPS,
                certificates=[elbv2.ListenerCertificate.from_arn(certificado_arn)],
                ssl_policy=elbv2.SslPolicy.RECOMMENDED_TLS,
                open=False,
                default_action=respuesta_no_encontrada,
            )
            self.url_interna = f"https://{dominio_interno}"
        else:
            self.listener = self.alb.add_listener(
                "ListenerHttp",
                port=PUERTO_HTTP_INTERNO,
                protocol=elbv2.ApplicationProtocol.HTTP,
                open=False,
                default_action=respuesta_no_encontrada,
            )
            self.url_interna = f"http://{self.alb.load_balancer_dns_name}"

        # ------------------------------------------------------------------ servicios
        ctx = ContextoPermisos(
            recursos=r,
            llave_infra_arn=llave_infra_arn,
            llave_datos_arn=llave_datos.key_arn,
            bucket_plantillas=r.arn_bucket(bucket_plantillas),
            bucket_constancias=r.arn_bucket(bucket_constancias),
            bucket_cargas=r.arn_bucket(bucket_cargas),
            user_pool_arn=user_pool_arn,
        )
        emisor = f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool_id}"
        self.tareas: dict[str, ecs.FargateTaskDefinition] = {}
        self.servicios: dict[str, ecs.FargateService] = {}
        self.grupos_destino: dict[str, elbv2.ApplicationTargetGroup] = {}

        for nombre in SERVICIOS:
            cpu, memoria = TAMANOS[nombre]
            entorno = {
                **entorno_base(r, env, self.region, host_bd=host_bd, rol_bd=f"svc_{nombre}"),
                "CC_COGNITO_EMISOR": emisor,
                "CC_COGNITO_CLIENT_ID": cliente_id,
                **variables_servicio(
                    nombre,
                    r,
                    env,
                    url_interna=self.url_interna,
                    bucket_plantillas=bucket_plantillas,
                    bucket_constancias=bucket_constancias,
                    bucket_cargas=bucket_cargas,
                    user_pool_id=user_pool_id,
                    empresa_id_whatsapp=empresa_id_whatsapp,
                ),
            }
            tarea = tarea_fargate(
                self,
                nombre,
                env,
                cpu=cpu,
                memoria=memoria,
                imagen=imagen_servicio(nombre),
                entorno=entorno,
                removal_policy=ret.removal_policy,
                puerto=PUERTO_API,
            )
            for s in sentencias_servicio(ctx, nombre):
                tarea.add_to_task_role_policy(s)
            self.tareas[nombre] = tarea

            servicio = ecs.FargateService(
                self,
                f"Servicio-{nombre}",
                service_name=f"cc-{env}-{nombre}",
                cluster=cluster,
                task_definition=tarea,
                desired_count=eco.tareas_por_servicio,
                security_groups=[sg_servicio],
                vpc_subnets=subredes,
                assign_public_ip=False,
                min_healthy_percent=100,
                max_healthy_percent=200,
                circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True),
                health_check_grace_period=cdk.Duration.seconds(60),
                enable_execute_command=False,
            )
            self.servicios[nombre] = servicio
            if es_prod:
                escala = servicio.auto_scale_task_count(
                    min_capacity=eco.tareas_por_servicio, max_capacity=MAXIMO_TAREAS_PROD
                )
                escala.scale_on_cpu_utilization(
                    "Cpu",
                    target_utilization_percent=CPU_OBJETIVO_PCT,
                    scale_in_cooldown=cdk.Duration.minutes(5),
                    scale_out_cooldown=cdk.Duration.minutes(1),
                )

            self.grupos_destino[nombre] = elbv2.ApplicationTargetGroup(
                self,
                f"Destino-{nombre}",
                target_group_name=f"cc-{env}-{nombre}"[:32],
                vpc=vpc,
                port=PUERTO_API,
                protocol=elbv2.ApplicationProtocol.HTTP,
                target_type=elbv2.TargetType.IP,
                targets=[servicio],
                deregistration_delay=cdk.Duration.seconds(30),
                health_check=elbv2.HealthCheck(
                    path="/salud",
                    healthy_http_codes="200",
                    interval=cdk.Duration.seconds(15),
                    timeout=cdk.Duration.seconds(5),
                    healthy_threshold_count=2,
                    unhealthy_threshold_count=3,
                ),
            )
            reconocer_tarea(tarea, nombre, reconocer)
            reconocer_comodines(tarea.task_role, comodines_servicio(ctx, nombre), reconocer)

        secreto_origen = cdk.SecretValue.secrets_manager(f"cc/{env}/origin-verify").unsafe_unwrap()
        for regla in REGLAS_ALB:
            condiciones = [elbv2.ListenerCondition.path_patterns(list(regla.patrones))]
            if regla.prioridad < PRIORIDAD_PRIMERA_INTERNA:
                # Las rutas públicas solo se atienden si vienen de CloudFront (vía API Gateway).
                # Las ``/internal/*`` no pasan por CloudFront: las protege el grupo de seguridad.
                condiciones.append(
                    elbv2.ListenerCondition.http_header(ENCABEZADO_ORIGEN, [secreto_origen])
                )
            elbv2.ApplicationListenerRule(
                self,
                f"Regla-{regla.prioridad}-{regla.destino}",
                listener=self.listener,
                priority=regla.prioridad,
                conditions=condiciones,
                action=elbv2.ListenerAction.forward([self.grupos_destino[regla.destino]]),
            )

        self._registro_acceso_alb(env, es_prod, ret)

        cdk.CfnOutput(self, "AlbDns", value=self.alb.load_balancer_dns_name)
        cdk.CfnOutput(self, "AlbListenerArn", value=self.listener.listener_arn)
        cdk.CfnOutput(self, "UrlInterna", value=self.url_interna)
        for nombre, svc in self.servicios.items():
            cdk.CfnOutput(self, f"Salida-{nombre}", value=svc.service_name)

    # -------------------------------------------------------------------------- cdk-nag
    def _registro_acceso_alb(self, env: str, es_prod: bool, ret) -> None:
        if es_prod:
            # El registro de acceso del ALB solo admite cifrado S3 administrado. Bucket propio para
            # no modificar el bucket ``logs`` de CcStorage desde este stack.
            registros = s3.Bucket(
                self,
                "RegistrosAlb",
                encryption=s3.BucketEncryption.S3_MANAGED,
                enforce_ssl=True,
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                lifecycle_rules=[s3.LifecycleRule(expiration=cdk.Duration.days(90))],
                removal_policy=ret.removal_policy,
                auto_delete_objects=ret.auto_borrar_objetos,
            )
            self.alb.log_access_logs(registros, "alb-interno")
            reconocer(
                registros,
                "AwsSolutions-S1",
                "Es el destino de los registros del ALB; registrar sus propios accesos crearía un "
                "ciclo sin valor adicional (como el bucket logs de CcStorage).",
            )
        else:
            reconocer(
                self.alb,
                "AwsSolutions-ELB2",
                "Prototipo de 1 a 2 semanas con presupuesto de 50 USD: ALB interno sin registro de "
                "acceso (el almacenamiento y la gestión del bucket no se justifican). Producción "
                "lo activa en un bucket propio.",
            )
