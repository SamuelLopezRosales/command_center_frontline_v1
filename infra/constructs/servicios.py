"""Piezas compartidas por ``CcCompute`` y ``CcWorkersLambdas`` (T-224; design.md §4, §12, §13.6).

Los recursos de otros stacks se **importan por nombre o por ARN construido**, sin modificarlos
(lección de T-040 a T-047: una concesión de CDK sobre un recurso de otro stack lo modifica y crea
un ciclo de dependencias). Por eso los permisos se escriben aquí como sentencias explícitas con el
ARN exacto, no con ``grant_*``: cada sentencia es la que se revisa y la que prueban las aserciones.

Convenciones de nombres que este módulo da por fijadas (las crean ``CcMessaging`` y
``CcSecurity``): colas ``cc-{env}-{nombre}`` (las FIFO terminan en ``.fifo``), bus
``cc-{env}-eventos``, secretos ``cc/{env}/{nombre}`` y ``cc/{env}/db/{rol}``, tema
``cc-{env}-alertas-rh``, grupo de Scheduler ``cc-{env}-envios`` y rol
``cc-{env}-scheduler-destino``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs

from constructs import Construct

RAIZ = Path(__file__).resolve().parents[2]
GRUPO_SUBREDES_APLICACION = "aplicacion"
PUERTO_API = 8000
NOMBRE_BD = "command_center"

SERVICIOS = ("dashboard", "colaboradores", "campos", "constancias", "whatsapp", "notificaciones")

# Secretos de aplicación que lee cada servicio (además de ``db/svc_{servicio}``), design.md §12.
SECRETOS_SERVICIO: dict[str, tuple[str, ...]] = {
    "dashboard": ("internal-auth",),
    "colaboradores": ("internal-auth", "hmac-celular"),
    "campos": ("internal-auth",),
    "constancias": ("internal-auth", "cf-signing-key"),
    "notificaciones": ("internal-auth", "meta"),
    "whatsapp": ("internal-auth", "meta", "hmac-codigo"),
}
# Colas donde el servicio publica (``relay-outbox`` y envíos directos).
COLAS_ENVIO: dict[str, tuple[str, ...]] = {
    "colaboradores": ("cola-cargas",),
    "constancias": ("cola-pdf", "wa-salida.fifo"),
    "notificaciones": ("notif-despacho", "notif-respaldo"),
    "whatsapp": ("wa-salida.fifo",),
}
# Cola ``ev-*`` que consume el ``consumidor-eventos`` que corre dentro de la API (WRK-04).
COLA_EVENTOS: dict[str, str] = {
    "colaboradores": "ev-colaboradores",
    "constancias": "ev-constancias",
    "notificaciones": "ev-notificaciones",
}
# Servicios que publican en el bus (``publicador_aws`` usa EventBridge además de SQS).
PUBLICAN_EVENTOS = ("campos", "colaboradores", "constancias", "notificaciones", "whatsapp")
# Servicios que cifran con la llave de datos (contexto de cifrado ``servicio``).
USAN_LLAVE_DATOS = ("colaboradores", "constancias", "whatsapp")

# Contexto de la imagen: la raíz del repositorio, como lo exigen los Dockerfile (``COPY
# services/...``). Se deja pasar solo lo que el Dockerfile copia; así la huella del activo (y por
# tanto el redespliegue) solo cambia cuando cambia el código del servicio o ``cc_common``.
_EXCLUIR_SIEMPRE = ["**/__pycache__", "**/*.pyc", "**/tests", "**/.pytest_cache"]


def exclusiones_imagen(servicio: str) -> list[str]:
    """Patrones (sintaxis de ``.dockerignore``) del contexto de la imagen de ``servicio``."""
    return [
        "*",
        "!services",
        "services/*",
        "!services/shared",
        f"!services/{servicio}",
        "services/shared/*",
        "!services/shared/cc_common",
        f"services/{servicio}/*",
        f"!services/{servicio}/cc_{servicio}",
        f"!services/{servicio}/Dockerfile",
        *_EXCLUIR_SIEMPRE,
    ]


def imagen_servicio(servicio: str) -> ecs.ContainerImage:
    """Imagen del servicio como activo de CDK (D-11): ``cdk deploy`` la construye y la publica."""
    return ecs.ContainerImage.from_asset(
        str(RAIZ),
        file=f"services/{servicio}/Dockerfile",
        platform=ecr_assets.Platform.LINUX_ARM64,
        exclude=exclusiones_imagen(servicio),
        ignore_mode=cdk.IgnoreMode.DOCKER,
    )


class Recursos:
    """ARN y URL de los recursos de otros stacks, construidos a partir de su nombre."""

    def __init__(self, stack: cdk.Stack, env: str) -> None:
        self.stack = stack
        self.env = env

    def _arn(self, servicio: str, recurso: str, region: bool = True, cuenta: bool = True) -> str:
        s = self.stack
        return (
            f"arn:{s.partition}:{servicio}:{s.region if region else ''}"
            f":{s.account if cuenta else ''}:{recurso}"
        )

    def nombre_cola(self, cola: str) -> str:
        return f"cc-{self.env}-{cola}"

    def arn_cola(self, cola: str) -> str:
        return self._arn("sqs", self.nombre_cola(cola))

    def url_cola(self, cola: str) -> str:
        return f"https://sqs.{self.stack.region}.amazonaws.com/{self.stack.account}/{self.nombre_cola(cola)}"

    def arn_bucket(self, nombre: str) -> str:
        return f"arn:{self.stack.partition}:s3:::{nombre}"

    def arn_dlq(self, cola: str) -> str:
        base, punto, ext = cola.partition(".")
        return self._arn("sqs", f"cc-{self.env}-{base}-dlq{punto}{ext}")

    def id_secreto(self, nombre: str) -> str:
        return f"cc/{self.env}/{nombre}"

    def arn_secreto(self, nombre: str) -> str:
        # Los ARN de Secrets Manager terminan en un sufijo de 6 caracteres.
        return self._arn("secretsmanager", f"secret:{self.id_secreto(nombre)}-??????")

    @property
    def nombre_bus(self) -> str:
        return f"cc-{self.env}-eventos"

    @property
    def arn_bus(self) -> str:
        return self._arn("events", f"event-bus/{self.nombre_bus}")

    @property
    def arn_tema_alertas(self) -> str:
        return self._arn("sns", f"cc-{self.env}-alertas-rh")

    @property
    def nombre_grupo_scheduler(self) -> str:
        return f"cc-{self.env}-envios"

    @property
    def arn_schedules(self) -> str:
        return self._arn("scheduler", f"schedule/{self.nombre_grupo_scheduler}/*")

    @property
    def arn_rol_scheduler(self) -> str:
        return self._arn("iam", f"role/cc-{self.env}-scheduler-destino", region=False)

    @property
    def arn_grupo_scheduler(self) -> str:
        return self._arn("scheduler", f"schedule-group/{self.nombre_grupo_scheduler}")

    def arn_identidad_ses(self, correo: str) -> str:
        return self._arn("ses", f"identity/{correo}")

    @property
    def nombre_conjunto_ses(self) -> str:
        return f"cc-{self.env}-respaldo"

    @property
    def arn_conjunto_ses(self) -> str:
        return self._arn("ses", f"configuration-set/{self.nombre_conjunto_ses}")


def sentencia(
    acciones: list[str],
    recursos: list[str],
    *,
    condiciones: dict | None = None,
    sid: str | None = None,
) -> iam.PolicyStatement:
    return iam.PolicyStatement(
        sid=sid,
        effect=iam.Effect.ALLOW,
        actions=acciones,
        resources=recursos,
        conditions=condiciones,
    )


def sentencia_secretos(r: Recursos, secretos: list[str], llave_infra_arn: str) -> list:
    """Lectura de secretos cifrados: ``GetSecretValue`` más ``kms:Decrypt`` sobre la llave
    (lección de T-047: sin el descifrado el arranque falla con ``AccessDenied`` de KMS)."""
    return [
        sentencia(["secretsmanager:GetSecretValue"], [r.arn_secreto(s) for s in secretos]),
        sentencia(["kms:Decrypt"], [llave_infra_arn]),
    ]


def sentencias_consumo(r: Recursos, cola: str, llave_infra_arn: str) -> list:
    """Consumir una cola (worker): recibir, borrar y extender la visibilidad del mensaje."""
    return [
        sentencia(
            [
                "sqs:ReceiveMessage",
                "sqs:DeleteMessage",
                "sqs:ChangeMessageVisibility",
                "sqs:GetQueueAttributes",
                "sqs:GetQueueUrl",
            ],
            [r.arn_cola(cola)],
        ),
        sentencia(["kms:Decrypt"], [llave_infra_arn]),
    ]


@dataclass(frozen=True)
class ContextoPermisos:
    """Lo que el constructor de permisos necesita de los demás stacks (todo son ARN o nombres)."""

    recursos: Recursos
    llave_infra_arn: str
    llave_datos_arn: str
    bucket_plantillas: str  # ARN del bucket
    bucket_constancias: str
    bucket_cargas: str
    user_pool_arn: str


def sentencias_servicio(
    ctx: ContextoPermisos, servicio: str, *, worker: bool = False
) -> list[iam.PolicyStatement]:
    """Permisos del rol de tarea de ``servicio`` (design.md §12), solo lo que su código usa."""
    r = ctx.recursos
    llave = ctx.llave_infra_arn
    s: list[iam.PolicyStatement] = []
    s += sentencia_secretos(r, [f"db/svc_{servicio}", *SECRETOS_SERVICIO[servicio]], llave)

    cola_envio = COLAS_ENVIO.get(servicio, ())
    if cola_envio:
        s.append(sentencia(["sqs:SendMessage"], [r.arn_cola(c) for c in cola_envio]))
    if servicio in PUBLICAN_EVENTOS:
        s.append(sentencia(["events:PutEvents"], [r.arn_bus]))
    if servicio in COLA_EVENTOS and not worker:
        s += sentencias_consumo(r, COLA_EVENTOS[servicio], llave)

    if servicio in USAN_LLAVE_DATOS:
        s.append(
            sentencia(
                ["kms:Decrypt", "kms:GenerateDataKey"],
                [ctx.llave_datos_arn],
                condiciones={"StringEquals": {"kms:EncryptionContext:servicio": servicio}},
            )
        )
    s.extend(_sentencias_propias(ctx, servicio))
    # Las colas, el tema y los buckets están cifrados con la llave de infraestructura: quien
    # escribe en ellos necesita ``GenerateDataKey``. ``dashboard`` y ``campos`` solo leen secretos
    # (``Decrypt``) y publican en el bus, que no está cifrado con KMS.
    if cola_envio:
        s.append(sentencia(["kms:GenerateDataKey"], [llave]))
    return s


def _sentencias_propias(ctx: ContextoPermisos, servicio: str) -> list[iam.PolicyStatement]:
    r = ctx.recursos
    s: list[iam.PolicyStatement] = []
    if servicio == "dashboard":
        s.append(
            sentencia(
                [
                    "cognito-idp:AdminDisableUser",
                    "cognito-idp:AdminUserGlobalSignOut",
                    "cognito-idp:AdminGetUser",
                ],
                [ctx.user_pool_arn],
            )
        )
    elif servicio == "colaboradores":
        s += [
            sentencia(
                ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                [f"{ctx.bucket_cargas}/*"],
            ),
            # Sin ``ListBucket``, S3 responde 403 (no 404) a un ``HeadObject`` de una clave ausente.
            sentencia(["s3:ListBucket"], [ctx.bucket_cargas]),
            sentencia(["s3:GetObject", "s3:PutObject"], [f"{ctx.bucket_plantillas}/logotipos/*"]),
        ]
    elif servicio == "constancias":
        s += [
            sentencia(["s3:GetObject", "s3:PutObject"], [f"{ctx.bucket_plantillas}/*"]),
            sentencia(["s3:GetObject"], [f"{ctx.bucket_constancias}/*"]),
            # Sin ``DeleteObject`` sobre ``constancias``: los PDF son inmutables (CC-REQ-081).
            sentencia(
                ["s3:PutObject", "s3:PutObjectRetention"],
                [f"{ctx.bucket_constancias}/*"],
                condiciones={"StringEqualsIfExists": {"s3:object-lock-mode": "GOVERNANCE"}},
            ),
        ]
    elif servicio == "notificaciones":
        s += [
            sentencia(
                [
                    "scheduler:CreateSchedule",
                    "scheduler:UpdateSchedule",
                    "scheduler:DeleteSchedule",
                    "scheduler:GetSchedule",
                ],
                [r.arn_schedules],
            ),
            sentencia(
                ["iam:PassRole"],
                [r.arn_rol_scheduler],
                condiciones={"StringEquals": {"iam:PassedToService": "scheduler.amazonaws.com"}},
            ),
        ]
    elif servicio == "whatsapp":
        s.append(sentencia(["sns:Publish"], [r.arn_tema_alertas]))
    return s


def entorno_base(
    r: Recursos,
    ambiente: str,
    region: str,
    *,
    host_bd: str,
    rol_bd: str,
) -> dict[str, str]:
    """Variables ``CC_*`` comunes. Ningún valor es secreto: los secretos van por identificador."""
    return {
        "CC_AMBIENTE": ambiente,
        "CC_REGION": region,
        "CC_DB_HOST": host_bd,
        "CC_DB_PUERTO": "5432",
        "CC_DB_NOMBRE": NOMBRE_BD,
        "CC_DB_SSL": "true",
        "CC_DB_SECRETO_ID": r.id_secreto(f"db/{rol_bd}"),
        "CC_INTERNAL_AUTH_SECRETO_ID": r.id_secreto("internal-auth"),
    }


def variables_servicio(
    nombre: str,
    r: Recursos,
    env: str,
    *,
    url_interna: str,
    bucket_plantillas: str,
    bucket_constancias: str,
    bucket_cargas: str,
    user_pool_id: str,
    empresa_id_whatsapp: int | None = None,
    worker: bool = False,
) -> dict[str, str]:
    """Variables ``CC_*`` propias de cada servicio (los nombres salen de su ``config.py``).

    Las URL entre servicios son la del ALB interno: el ALB enruta por ruta (design.md §3.8).
    ``worker`` omite lo que solo usa la API (consumidor de eventos, ``CC_EVENTOS_ACTIVOS``).
    """
    u = url_interna
    e: dict[str, str] = {}
    if nombre in COLA_EVENTOS and not worker:
        e["CC_COLA_EVENTOS_URL"] = r.url_cola(COLA_EVENTOS[nombre])
    if nombre == "dashboard":
        e["CC_COGNITO_USER_POOL_ID"] = user_pool_id
    elif nombre == "colaboradores":
        e |= {
            "CC_BUCKET_PLANTILLAS": bucket_plantillas,
            "CC_BUCKET_CARGAS": bucket_cargas,
            "CC_HMAC_CELULAR_SECRETO_ID": r.id_secreto("hmac-celular"),
            "CC_KMS_LLAVE_DATOS": f"alias/cc-{env}-datos",
            "CC_COLA_CARGAS_URL": r.url_cola("cola-cargas"),
            "CC_CAMPOS_URL": u,
        }
    elif nombre == "campos":
        e |= {"CC_BUS_EVENTOS": r.nombre_bus, "CC_COLABORADORES_URL": u, "CC_CONSTANCIAS_URL": u}
    elif nombre == "constancias":
        e |= {
            "CC_BUCKET_PLANTILLAS": bucket_plantillas,
            "CC_BUCKET_CONSTANCIAS": bucket_constancias,
            "CC_KMS_LLAVE_DATOS": f"alias/cc-{env}-datos",
            "CC_COLA_PDF_URL": r.url_cola("cola-pdf"),
            "CC_COLA_WA_SALIDA_URL": r.url_cola("wa-salida.fifo"),
            "CC_BUS_EVENTOS": r.nombre_bus,
            "CC_CAMPOS_URL": u,
            "CC_COLABORADORES_URL": u,
            "CC_CLOUDFRONT_CLAVE_SECRETO_ID": r.id_secreto("cf-signing-key"),
        }
    elif nombre == "whatsapp":
        e |= {
            "CC_META_SECRETO_ID": r.id_secreto("meta"),
            "CC_CODIGO_HMAC_SECRETO_ID": r.id_secreto("hmac-codigo"),
            "CC_KMS_LLAVE_DATOS": f"alias/cc-{env}-datos",
            "CC_COLA_ENTRADA_URL": r.url_cola("wa-entrada.fifo"),
            "CC_COLA_SALIDA_URL": r.url_cola("wa-salida.fifo"),
            "CC_COLA_ESTADOS_URL": r.url_cola("wa-estados"),
            "CC_BUS_EVENTOS": r.nombre_bus,
            "CC_ALERTAS_TOPIC_ARN": r.arn_tema_alertas,
            "CC_COLABORADORES_URL": u,
            "CC_CONSTANCIAS_URL": u,
            "CC_NOTIFICACIONES_URL": u,
        }
        if empresa_id_whatsapp is not None:
            e["CC_EMPRESA_ID"] = str(empresa_id_whatsapp)
    elif nombre == "notificaciones":
        e |= {
            "CC_META_SECRETO_ID": r.id_secreto("meta"),
            "CC_CAMPOS_URL": u,
            "CC_COLABORADORES_URL": u,
            "CC_BUS_EVENTOS": r.nombre_bus,
            "CC_COLA_DESPACHO_URL": r.url_cola("notif-despacho"),
            "CC_SCHEDULER_DESTINO_ARN": r.arn_cola("notif-despacho"),
            "CC_SCHEDULER_ROL_ARN": r.arn_rol_scheduler,
            "CC_SCHEDULER_GRUPO": r.nombre_grupo_scheduler,
            "CC_CONSUMIDOR_ACTIVO": "true",
        }
    if not worker:
        e["CC_EVENTOS_ACTIVOS"] = "true"
    return e


def cluster_importado(scope: Construct, vpc: ec2.IVpc, env: str) -> ecs.ICluster:
    """El clúster lo crea ``CcComputeBase``; se importa por nombre para no modificarlo."""
    return ecs.Cluster.from_cluster_attributes(
        scope, "ClusterImportado", cluster_name=f"cc-{env}", vpc=vpc, security_groups=[]
    )


def grupo_de_logs(
    scope: Construct, nombre: str, env: str, removal_policy: cdk.RemovalPolicy
) -> logs.LogGroup:
    return logs.LogGroup(
        scope,
        f"Logs-{nombre}",
        log_group_name=f"/cc/{env}/{nombre}",
        retention=logs.RetentionDays.ONE_MONTH,
        removal_policy=removal_policy,
    )


def tarea_fargate(
    scope: Construct,
    nombre: str,
    env: str,
    *,
    cpu: int,
    memoria: int,
    imagen: ecs.ContainerImage,
    entorno: dict[str, str],
    removal_policy: cdk.RemovalPolicy,
    puerto: int | None = None,
    comando: list[str] | None = None,
) -> ecs.FargateTaskDefinition:
    """Tarea Fargate ARM64 con su rol de tarea propio (``cc-{env}-{nombre}``)."""
    rol = iam.Role(
        scope,
        f"RolTarea-{nombre}",
        role_name=f"cc-{env}-{nombre}",
        description=f"Rol de la tarea {nombre}: solo lo que su código usa (design.md §12)",
        assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    )
    tarea = ecs.FargateTaskDefinition(
        scope,
        f"Tarea-{nombre}",
        family=f"cc-{env}-{nombre}",
        cpu=cpu,
        memory_limit_mib=memoria,
        task_role=rol,
        runtime_platform=ecs.RuntimePlatform(
            cpu_architecture=ecs.CpuArchitecture.ARM64,
            operating_system_family=ecs.OperatingSystemFamily.LINUX,
        ),
    )
    salud = (
        ecs.HealthCheck(
            command=[
                "CMD-SHELL",
                'python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('
                f"'http://127.0.0.1:{puerto}/salud', timeout=2).status == 200 else 1)\"",
            ],
            interval=cdk.Duration.seconds(30),
            timeout=cdk.Duration.seconds(5),
            retries=3,
            start_period=cdk.Duration.seconds(60),
        )
        if puerto
        else None
    )
    tarea.add_container(
        nombre,
        image=imagen,
        command=comando,
        environment=entorno,
        essential=True,
        # Apagado ordenado: termina el mensaje en curso tras SIGTERM (design.md §4.7).
        stop_timeout=cdk.Duration.seconds(120),
        port_mappings=[ecs.PortMapping(container_port=puerto)] if puerto else None,
        health_check=salud,
        logging=ecs.LogDrivers.aws_logs(
            stream_prefix=nombre,
            log_group=grupo_de_logs(scope, nombre, env, removal_policy),
        ),
    )
    return tarea


def reconocer_tarea(tarea: ecs.FargateTaskDefinition, nombre: str, reconocer) -> None:
    """Reconocimientos de cdk-nag comunes a toda tarea Fargate de este módulo."""
    reconocer(
        tarea,
        "AwsSolutions-ECS2",
        f"{nombre}: las variables CC_* son configuración no sensible (nombres, URL y "
        "identificadores de colas, buckets y secretos). Los secretos nunca viajan por valor: el "
        "servicio los lee de Secrets Manager por identificador con su rol de tarea.",
    )
    reconocer(
        tarea.obtain_execution_role(),
        "AwsSolutions-IAM5[Resource::*]",
        "ecr:GetAuthorizationToken no admite un recurso específico; es la acción con la que la "
        "tarea obtiene su credencial para descargar la imagen.",
    )


def como_lo_muestra_nag(r: Recursos, arn: str) -> str:
    """cdk-nag escribe la partición como ``<AWS::Partition>`` si es un *token* y como el literal
    (``aws``) cuando ``cdk.json`` fija las particiones (``enablePartitionLiterals``)."""
    particion = r.stack.partition
    return arn.replace(particion, "<AWS::Partition>") if cdk.Token.is_unresolved(particion) else arn


def comodines_servicio(ctx: ContextoPermisos, servicio: str) -> list[str]:
    """ARN con comodín (``/*``) que el rol de ``servicio`` lleva, escritos como los muestra
    cdk-nag (``<AWS::Partition>``). Cada uno se reconoce con su motivo."""
    r = ctx.recursos
    if servicio == "colaboradores":
        crudos = [f"{ctx.bucket_cargas}/*", f"{ctx.bucket_plantillas}/logotipos/*"]
    elif servicio == "constancias":
        crudos = [f"{ctx.bucket_plantillas}/*", f"{ctx.bucket_constancias}/*"]
    elif servicio == "notificaciones":
        crudos = [r.arn_schedules]
    else:
        crudos = []
    return [como_lo_muestra_nag(r, c) for c in crudos]


def reconocer_comodines(rol: iam.IRole, arns: list[str], reconocer) -> None:
    for arn in arns:
        objetivo = "los schedules del grupo de envíos" if ":scheduler:" in arn else "S3"
        reconocer(
            rol,
            f"AwsSolutions-IAM5[Resource::{arn}]",
            f"El comodín final limita el acceso a {objetivo} dentro de un solo bucket o grupo, "
            "no a cualquier recurso (mínimo privilegio, design.md §12): las claves de los "
            "objetos y los nombres de los schedules no se conocen al sintetizar.",
        )
