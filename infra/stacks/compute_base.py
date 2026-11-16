"""Stack CcComputeBase: clúster ECS, repositorios ECR y las tareas ``migrar`` y ``ops``
(design.md §13.6, §2.8, §13.9).

- Clúster ``cc-{env}`` sobre Fargate. Container Insights solo en ``prod`` (en ``test`` cuesta
  métricas de CloudWatch que el prototipo no necesita).
- Repositorios ``cc-{env}/migrar`` y ``cc-{env}/ops``: escaneo al subir, etiquetas inmutables,
  cifrado con KMS y ciclo de vida (sin etiqueta a 7 días; se conservan las 10 más recientes). Los
  repositorios de los servicios se agregan con ellos (Fase 2 en adelante).
- Tareas Fargate ARM64: ``migrar`` (un solo uso, ``ecs run-task``) y ``ops`` (en espera, se opera
  con ECS Exec). Ambas toman las credenciales de Secrets Manager; ninguna lleva valores en la
  definición de la tarea.

Decisiones (registradas en progreso.md):
- ``migrar`` y ``ops`` se conectan con el usuario propietario ``cc_admin`` (secreto
  ``cc/{env}/db/admin``): el rol ``migrador`` no tiene contraseña hasta que ``ops`` las asigne y las
  tablas deben tener un solo dueño.
- ECS no compone una URL a partir de un secreto, así que ``migrar`` la arma al arrancar
  (``ops`` lo hace en ``ops.sh``).
- El registro de sesiones de ECS Exec en CloudWatch queda desactivado: grabaría el código de
  invitación que T-049 muestra una sola vez. Quién abrió cada sesión queda en CloudTrail.
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as sm

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs.nag import reconocer
from infra.constructs.retencion import politica_retencion

GRUPO_SUBREDES_APLICACION = "aplicacion"
# Etiqueta publicada de cada imagen (los repositorios son inmutables: un cambio exige otra).
# migrar 0.1.1: roles.sql sin ALTER ROLE innecesario (T-047).
# migrar 0.1.2: función identidad.empresa_unica() para el registro abierto.
ETIQUETAS: dict[str, str] = {"migrar": "0.1.2", "ops": "0.1.0"}
REPOSITORIOS = ("migrar", "ops")
ROLES_BD = (
    "svc_dashboard",
    "svc_colaboradores",
    "svc_campos",
    "svc_constancias",
    "svc_notificaciones",
    "svc_whatsapp",
    "migrador",
)

# La contraseña generada por Secrets Manager excluye los caracteres reservados de una URL.
COMANDO_MIGRAR = (
    'export CC_MIGRAR_URL="postgresql+psycopg://$CC_DB_USER:$CC_DB_PASSWORD@$CC_DB_HOST'
    ':$CC_DB_PORT/$CC_DB_NAME?sslmode=require"; exec python scripts/migrar_todo.py'
)


class ComputeBaseStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        id_: str,
        *,
        ambiente: Ambiente,
        llave_infra: kms.IKey,
        vpc: ec2.IVpc,
        sg_ecs: ec2.ISecurityGroup,
        secreto_admin: sm.ISecret,
        secretos_roles: dict[str, sm.ISecret],
        **kwargs,
    ) -> None:
        super().__init__(scope, id_, **kwargs)
        env = ambiente.nombre
        ret = politica_retencion(ambiente)
        es_prod = not ambiente.economia.permite_borrado
        llave = kms.Key.from_key_arn(self, "LlaveInfraImportada", llave_infra.key_arn)
        self.sg_ecs = ec2.SecurityGroup.from_security_group_id(
            self, "SgEcsImportado", sg_ecs.security_group_id, mutable=False
        )

        self.cluster = ecs.Cluster(
            self,
            "Cluster",
            cluster_name=f"cc-{env}",
            vpc=vpc,
            container_insights_v2=(
                ecs.ContainerInsights.ENABLED if es_prod else ecs.ContainerInsights.DISABLED
            ),
            enable_fargate_capacity_providers=True,
        )

        self.repos: dict[str, ecr.Repository] = {}
        for nombre in REPOSITORIOS:
            self.repos[nombre] = ecr.Repository(
                self,
                f"Repo-{nombre}",
                repository_name=f"cc-{env}/{nombre}",
                image_scan_on_push=True,
                image_tag_mutability=ecr.TagMutability.IMMUTABLE,
                encryption=ecr.RepositoryEncryption.KMS,
                encryption_key=llave,
                lifecycle_rules=[
                    ecr.LifecycleRule(
                        rule_priority=1,
                        description="Imágenes sin etiqueta: 7 días",
                        tag_status=ecr.TagStatus.UNTAGGED,
                        max_image_age=cdk.Duration.days(7),
                    ),
                    ecr.LifecycleRule(
                        rule_priority=2,
                        description="Se conservan las 10 imágenes más recientes",
                        tag_status=ecr.TagStatus.ANY,
                        max_image_count=10,
                    ),
                ],
                removal_policy=ret.removal_policy,
                empty_on_delete=ret.auto_borrar_objetos,
            )

        credenciales_admin = {
            "CC_DB_HOST": ecs.Secret.from_secrets_manager(secreto_admin, "host"),
            "CC_DB_PORT": ecs.Secret.from_secrets_manager(secreto_admin, "port"),
            "CC_DB_NAME": ecs.Secret.from_secrets_manager(secreto_admin, "dbname"),
            "CC_DB_USER": ecs.Secret.from_secrets_manager(secreto_admin, "username"),
            "CC_DB_PASSWORD": ecs.Secret.from_secrets_manager(secreto_admin, "password"),
        }

        self.tarea_migrar = self._tarea(
            "migrar",
            env,
            ret.removal_policy,
            self.repos["migrar"],
            secrets=credenciales_admin,
            entry_point=["sh", "-c"],
            command=[COMANDO_MIGRAR],
        )

        contrasenas_roles = {
            f"CC_PWD_{rol.upper()}": ecs.Secret.from_secrets_manager(secreto, "password")
            for rol, secreto in secretos_roles.items()
        }
        self.tarea_ops = self._tarea(
            "ops",
            env,
            ret.removal_policy,
            self.repos["ops"],
            secrets={**credenciales_admin, **contrasenas_roles},
            exec=True,
        )

        # El secreto adjunto a la instancia no expone su llave, así que CDK concede leerlo pero no
        # descifrarlo: ECS fallaba con "Access to KMS is not allowed" (T-047).
        for tarea in (self.tarea_migrar, self.tarea_ops):
            llave.grant_decrypt(tarea.obtain_execution_role())

        self._reconocer_reglas(env, es_prod)

        subredes = vpc.select_subnets(subnet_group_name=GRUPO_SUBREDES_APLICACION).subnet_ids
        cdk.CfnOutput(self, "NombreCluster", value=self.cluster.cluster_name)
        cdk.CfnOutput(self, "TareaMigrar", value=self.tarea_migrar.family)
        cdk.CfnOutput(self, "TareaOps", value=self.tarea_ops.family)
        cdk.CfnOutput(self, "RepoMigrarUri", value=self.repos["migrar"].repository_uri)
        cdk.CfnOutput(self, "RepoOpsUri", value=self.repos["ops"].repository_uri)
        cdk.CfnOutput(self, "SubredesAplicacion", value=cdk.Fn.join(",", subredes))
        cdk.CfnOutput(self, "SgEcsId", value=self.sg_ecs.security_group_id)

    def _tarea(
        self,
        nombre: str,
        env: str,
        removal_policy: cdk.RemovalPolicy,
        repo: ecr.IRepository,
        *,
        secrets: dict[str, ecs.Secret],
        entry_point: list[str] | None = None,
        command: list[str] | None = None,
        exec: bool = False,  # noqa: A002
    ) -> ecs.FargateTaskDefinition:
        tarea = ecs.FargateTaskDefinition(
            self,
            f"Tarea-{nombre}",
            family=f"cc-{env}-{nombre}",
            cpu=256,
            memory_limit_mib=512,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )
        tarea.add_container(
            nombre,
            image=ecs.ContainerImage.from_ecr_repository(repo, ETIQUETAS[nombre]),
            entry_point=entry_point,
            command=command,
            secrets=secrets,
            essential=True,
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix=nombre,
                log_group=logs.LogGroup(
                    self,
                    f"Logs-{nombre}",
                    log_group_name=f"/cc/{env}/{nombre}",
                    retention=logs.RetentionDays.ONE_MONTH,
                    removal_policy=removal_policy,
                ),
            ),
            linux_parameters=(
                ecs.LinuxParameters(self, f"Linux-{nombre}", init_process_enabled=True)
                if exec
                else None
            ),
        )
        if exec:
            # Canal de ECS Exec (sesión interactiva). Estas acciones no admiten un recurso concreto.
            tarea.add_to_task_role_policy(
                iam.PolicyStatement(
                    actions=[
                        "ssmmessages:CreateControlChannel",
                        "ssmmessages:CreateDataChannel",
                        "ssmmessages:OpenControlChannel",
                        "ssmmessages:OpenDataChannel",
                    ],
                    resources=["*"],
                )
            )
        return tarea

    def _reconocer_reglas(self, env: str, es_prod: bool) -> None:
        if not es_prod:
            reconocer(
                self.cluster,
                "AwsSolutions-ECS4",
                "Container Insights genera métricas de pago que el prototipo de test (50 USD) no "
                "necesita; se activa en producción.",
            )
        reconocer(
            self.tarea_ops.task_role,
            "AwsSolutions-IAM5[Resource::*]",
            "ECS Exec exige acciones ssmmessages sobre cualquier recurso (documentación de AWS). "
            "El acceso a la tarea se controla con ecs:ExecuteCommand en el rol del operador.",
        )
        for tarea in (self.tarea_migrar, self.tarea_ops):
            reconocer(
                tarea.obtain_execution_role(),
                "AwsSolutions-IAM5[Resource::*]",
                "ecr:GetAuthorizationToken no admite un recurso específico; es la acción con la "
                "que la tarea obtiene su credencial para descargar la imagen.",
            )
