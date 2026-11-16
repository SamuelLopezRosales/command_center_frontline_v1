"""Stack CcPipeline: CodePipeline y CodeBuild de un ambiente (design.md §12, §14.2; T-226).

**No se crea en ``test`` por defecto** (``infra/app.py``: solo con ``-c pipeline=true``): el
pipeline completo cuesta, crea una conexión que se autoriza a mano y despliega solo. En ``prod``
sí se crea. Es un stack aparte y **no referencia a ningún otro** (el diseño le da dependencia
ninguna): despliega a los demás por nombre y nunca a sí mismo (``CC_STACKS_*`` no lo incluyen).

Etapas: Fuente, Compilar, Aprobación manual, Respaldo (solo ``prod``: instantánea de RDS previa
a las migraciones), Base, Migraciones (tarea ``migrar``, orden de design.md §2.8) y Servicios.
Los buildspecs viven en ``infra/pipeline/buildspecs.py``.

Seguridad:
- Un rol de IAM por proyecto de CodeBuild con mínimo privilegio, acotado por ambiente y cuenta;
  ni ``AdministratorAccess`` ni ``PowerUserAccess``. ``cdk deploy`` asume los roles de bootstrap
  de CDK (``cdk-hnb659fds-*``); el poder de despliegue lo da el rol de ejecución de
  CloudFormation del bootstrap, no estos roles.
- Artefactos en un bucket cifrado con una llave propia (``cc-{env}-pipeline``), TLS obligatorio,
  sin acceso público y con expiración.
- Credenciales de GitHub por referencia: la conexión (CodeConnections) se crea en estado
  pendiente y **una persona la autoriza en la consola** (``docs/ambientes.md``); o se reutiliza
  una existente con ``-c conexion_codigo_arn=...``. Ningún token pasa por la plantilla.
- Quién aprueba: ``codepipeline:PutApprovalResult`` sobre la acción ``Aprobacion``; solo se
  concede a las personas que designe el cliente (no a los roles de CodeBuild).
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_codepipeline as codepipeline
from aws_cdk import aws_codepipeline_actions as actions
from aws_cdk import aws_codestarconnections as connections
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs import recuperacion
from infra.constructs.nag import id_nag, reconocer
from infra.constructs.retencion import politica_retencion
from infra.pipeline import buildspecs
from infra.stacks.compute_base import ETIQUETAS as ETIQUETAS_IMAGENES

CALIFICADOR_BOOTSTRAP = "hnb659fds"
ROLES_BOOTSTRAP = ("deploy", "file-publishing", "image-publishing", "lookup")
# Stacks que despliega cada etapa (sin ``-{env}``). CcPipeline no está: no se despliega a sí mismo.
STACKS_BASE = (
    "CcSecurity",
    "CcNetwork",
    "CcStorage",
    "CcData",
    "CcMessaging",
    "CcAuth",
    "CcComputeBase",
)
STACKS_SERVICIOS = (
    "CcCompute",
    "CcWorkersLambdas",
    "CcApi",
    "CcEdge",
    "CcFrontend",
    "CcObservability",
)
STACK_RECUPERACION = "CcBackupRecuperacion"
STACK_RESPALDO = "CcBackup"
# Contextos de ``-c`` que la síntesis del pipeline repite (ARN, dominios e identificadores: no son
# secretos). La llave pública de CloudFront viaja aparte, por un parámetro de SSM.
CONTEXTOS_CDK = (
    "certificado_alb_arn",
    "dominio_interno",
    "empresa_id_whatsapp",
    "dominio_origen_api",
    "certificado_origen_api_arn",
    "zona_hospedada_id",
)


def nombres_de_stacks(env: str, *, con_recuperacion: bool, con_respaldo: bool) -> tuple[list, list]:
    """``(stacks base, stacks de servicios)`` con el sufijo del ambiente."""
    base = list(STACKS_BASE)
    servicios = list(STACKS_SERVICIOS)
    if con_recuperacion:
        base.insert(0, STACK_RECUPERACION)
    if con_respaldo:
        servicios.append(STACK_RESPALDO)
    return [f"{n}-{env}" for n in base], [f"{n}-{env}" for n in servicios]


class PipelineStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        id_: str,
        *,
        ambiente: Ambiente,
        repositorio: str,
        rama: str = "main",
        conexion_arn: str | None = None,
        contextos_cdk: dict[str, str] | None = None,
        con_respaldo: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(scope, id_, **kwargs)
        propietario, _, nombre_repo = repositorio.partition("/")
        if not propietario or not nombre_repo or "/" in nombre_repo:
            raise ValueError(
                f"repositorio_pipeline debe ser 'propietario/repositorio', no '{repositorio}'"
            )
        env = ambiente.nombre
        ret = politica_retencion(ambiente)
        es_prod = recuperacion.recuperacion_habilitada(ambiente)
        self._env = env
        self._ret = ret

        # ----------------------------------------------------------------- cifrado y artefactos
        self.llave = kms.Key(
            self,
            "LlavePipeline",
            alias=f"alias/cc-{env}-pipeline",
            description="Cifrado de los artefactos y proyectos del pipeline de Command Center",
            enable_key_rotation=True,
            rotation_period=cdk.Duration.days(365),
            pending_window=cdk.Duration.days(ret.kms_dias_espera),
            removal_policy=ret.removal_policy,
        )
        self.bucket_artefactos = s3.Bucket(
            self,
            "Artefactos",
            bucket_name=f"cc-{env}-{self.account}-pipeline-artefactos",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.llave,
            bucket_key_enabled=True,
            enforce_ssl=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expirar-artefactos-30-dias",
                    expiration=cdk.Duration.days(30),
                    noncurrent_version_expiration=cdk.Duration.days(30),
                    abort_incomplete_multipart_upload_after=cdk.Duration.days(1),
                )
            ],
            removal_policy=ret.removal_policy,
            auto_delete_objects=ret.auto_borrar_objetos,
        )
        reconocer(
            self.bucket_artefactos,
            "AwsSolutions-S1",
            "Bucket temporal de artefactos del pipeline (30 días, cifrado con una llave propia y "
            "solo accesible por los roles del pipeline): su registro de acceso no aporta una "
            "auditoría que CloudTrail no dé ya, y no hay un bucket de registros de CcStorage al "
            "que este stack pueda apuntar sin una dependencia.",
        )

        # ------------------------------------------------------------------------- conexión
        if conexion_arn:
            self.conexion_arn = conexion_arn
            self.conexion: connections.CfnConnection | None = None
        else:
            self.conexion = connections.CfnConnection(
                self,
                "Conexion",
                connection_name=f"cc-{env}-github",
                provider_type="GitHub",
            )
            self.conexion_arn = self.conexion.attr_connection_arn
            cdk.CfnOutput(
                self,
                "PasoManualConexion",
                value=(
                    "La conexión nace PENDIENTE: autorícela en la consola de AWS (Herramientas "
                    "para "
                    "desarrolladores, Configuración, Conexiones) antes de la primera ejecución"
                ),
            )

        # --------------------------------------------------------------- proyectos de CodeBuild
        contextos = " ".join(
            f"-c {k}={v}" for k, v in sorted((contextos_cdk or {}).items()) if v not in (None, "")
        )
        base, servicios = nombres_de_stacks(
            env, con_recuperacion=es_prod, con_respaldo=con_respaldo
        )
        entorno: dict[str, str] = {
            "CC_AMBIENTE": env,
            "CC_CDK_CONTEXTO": contextos,
            "CDK_CLI_VERSION": buildspecs.VERSION_CLI_CDK,
            "CC_STACKS_BASE": " ".join(base),
            "CC_STACKS_SERVICIOS": " ".join(servicios),
            "CC_TAG_MIGRAR": ETIQUETAS_IMAGENES["migrar"],
            "CC_TAG_OPS": ETIQUETAS_IMAGENES["ops"],
            "CC_ETQ_PROYECTO": ambiente.etiquetas["proyecto"],
            "CC_ETQ_AMBIENTE": ambiente.etiquetas["ambiente"],
            "CC_ETQ_RESPONSABLE": ambiente.etiquetas["responsable"],
            "AWS_DEFAULT_REGION": ambiente.region,
        }
        self.proyectos: dict[str, codebuild.PipelineProject] = {}
        # La llave pública de CloudFront es obligatoria en prod y ``*.pem`` no se versiona: se lee
        # de un parámetro de SSM que se crea a mano una vez (``docs/ambientes.md``).
        parametros = (
            {"CC_CLAVE_PUBLICA_CLOUDFRONT": f"/cc/{env}/pipeline/clave-publica-cloudfront"}
            if es_prod
            else {}
        )
        self._proyecto(
            "ci",
            buildspecs.ci(),
            entorno,
            parametros=parametros,
            privilegiado=True,
            minutos=45,
            grande=True,
        )
        if es_prod:
            self._proyecto("respaldo", buildspecs.respaldo(), entorno, minutos=60)
        self._proyecto("base", buildspecs.base(), entorno, privilegiado=True, minutos=90)
        self._proyecto("migrar", buildspecs.migrar(), entorno, minutos=60)
        self._proyecto("servicios", buildspecs.servicios(), entorno, privilegiado=True, minutos=90)

        self._permisos(env, es_prod)

        # -------------------------------------------------------------------------- pipeline
        fuente = codepipeline.Artifact("Fuente")
        ensamblado = codepipeline.Artifact("Ensamblado")
        self.pipeline = codepipeline.Pipeline(
            self,
            "Pipeline",
            pipeline_name=f"cc-{env}",
            pipeline_type=codepipeline.PipelineType.V2,
            artifact_bucket=self.bucket_artefactos,
            restart_execution_on_update=False,
            cross_account_keys=False,
        )
        self.pipeline.add_stage(
            stage_name="Fuente",
            actions=[
                actions.CodeStarConnectionsSourceAction(
                    action_name="Fuente",
                    owner=propietario,
                    repo=nombre_repo,
                    branch=rama,
                    connection_arn=self.conexion_arn,
                    output=fuente,
                    trigger_on_push=True,
                    code_build_clone_output=False,
                )
            ],
        )
        self.pipeline.add_stage(
            stage_name="Compilar",
            actions=[
                actions.CodeBuildAction(
                    action_name="CI",
                    project=self.proyectos["ci"],
                    input=fuente,
                    outputs=[ensamblado],
                )
            ],
        )
        self.pipeline.add_stage(
            stage_name="Aprobacion",
            actions=[
                actions.ManualApprovalAction(
                    action_name="Aprobacion",
                    additional_information=(
                        f"Aprobar el despliegue de cc-{env}. Revise el resultado de la compilación "
                        "(pruebas y cdk-nag) y el cambio. Solo lo aprueba quien designó el cliente."
                    ),
                )
            ],
        )
        if es_prod:
            self.pipeline.add_stage(
                stage_name="Respaldo",
                actions=[self._accion("Instantanea", "respaldo", ensamblado)],
            )
        self.pipeline.add_stage(
            stage_name="Base", actions=[self._accion("DesplegarBase", "base", ensamblado)]
        )
        self.pipeline.add_stage(
            stage_name="Migraciones",
            actions=[self._accion("MigrarBaseDeDatos", "migrar", ensamblado)],
        )
        self.pipeline.add_stage(
            stage_name="Servicios",
            actions=[self._accion("DesplegarServicios", "servicios", ensamblado)],
        )

        cdk.CfnOutput(self, "PipelineNombre", value=self.pipeline.pipeline_name)
        cdk.CfnOutput(self, "ConexionArn", value=self.conexion_arn)
        cdk.CfnOutput(self, "BucketArtefactos", value=self.bucket_artefactos.bucket_name)
        self._reconocer()

    # ------------------------------------------------------------------------------ ayudas
    def _accion(
        self, nombre: str, proyecto: str, ensamblado: codepipeline.Artifact
    ) -> actions.CodeBuildAction:
        return actions.CodeBuildAction(
            action_name=nombre, project=self.proyectos[proyecto], input=ensamblado
        )

    def _proyecto(
        self,
        nombre: str,
        spec: dict,
        entorno: dict[str, str],
        *,
        parametros: dict[str, str] | None = None,
        privilegiado: bool = False,
        minutos: int = 30,
        grande: bool = False,
    ) -> None:
        env = self._env
        grupo = logs.LogGroup(
            self,
            f"Logs-{nombre}",
            log_group_name=f"/cc/{env}/pipeline/{nombre}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=self._ret.removal_policy,
        )
        self.proyectos[nombre] = codebuild.PipelineProject(
            self,
            f"Proyecto-{nombre}",
            project_name=f"cc-{env}-{nombre}",
            description=f"Pipeline de Command Center ({env}): {nombre}",
            # Linux ARM: las imágenes de los servicios son linux/arm64 (Fargate ARM64) y así se
            # construyen de forma nativa, sin emulación.
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxArmBuildImage.AMAZON_LINUX_2023_STANDARD_3_0,
                compute_type=codebuild.ComputeType.LARGE if grande else codebuild.ComputeType.SMALL,
                privileged=privilegiado,
                environment_variables={
                    **{n: codebuild.BuildEnvironmentVariable(value=v) for n, v in entorno.items()},
                    **{
                        n: codebuild.BuildEnvironmentVariable(
                            value=v, type=codebuild.BuildEnvironmentVariableType.PARAMETER_STORE
                        )
                        for n, v in (parametros or {}).items()
                    },
                },
            ),
            build_spec=codebuild.BuildSpec.from_object(spec),
            encryption_key=self.llave,
            timeout=cdk.Duration.minutes(minutos),
            check_secrets_in_plain_text_env_variables=True,
            logging=codebuild.LoggingOptions(
                cloud_watch=codebuild.CloudWatchLoggingOptions(log_group=grupo)
            ),
        )

    def _permisos(self, env: str, es_prod: bool) -> None:
        """Permisos de cada proyecto: solo lo que su buildspec ejecuta, acotado al ambiente."""
        cuenta, region, particion = self.account, self.region, self.partition
        regiones = [region] + ([recuperacion.REGION_RECUPERACION] if es_prod else [])
        stacks_cc = f"arn:{particion}:cloudformation:{region}:{cuenta}:stack/Cc*-{env}/*"

        def cdk_roles() -> iam.PolicyStatement:
            return iam.PolicyStatement(
                sid="AsumirRolesDeBootstrapDeCdk",
                actions=["sts:AssumeRole"],
                resources=[
                    f"arn:{particion}:iam::{cuenta}:role/cdk-{CALIFICADOR_BOOTSTRAP}-{rol}-role-"
                    f"{cuenta}-{r}"
                    for rol in ROLES_BOOTSTRAP
                    for r in regiones
                ],
            )

        def leer_stacks() -> iam.PolicyStatement:
            return iam.PolicyStatement(
                sid="LeerSalidasDeLosStacksDelAmbiente",
                actions=["cloudformation:DescribeStacks"],
                resources=[stacks_cc],
            )

        def version_bootstrap() -> iam.PolicyStatement:
            return iam.PolicyStatement(
                sid="LeerVersionDeBootstrap",
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:{particion}:ssm:{r}:{cuenta}:parameter/cdk-bootstrap/"
                    f"{CALIFICADOR_BOOTSTRAP}/version"
                    for r in regiones
                ],
            )

        for nombre in ("base", "servicios"):
            self.proyectos[nombre].add_to_role_policy(cdk_roles())
            self.proyectos[nombre].add_to_role_policy(leer_stacks())
            self.proyectos[nombre].add_to_role_policy(version_bootstrap())

        repos = f"arn:{particion}:ecr:{region}:{cuenta}:repository/cc-{env}/*"
        base = self.proyectos["base"]
        base.add_to_role_policy(
            iam.PolicyStatement(
                sid="ObtenerTokenDeEcr",
                actions=["ecr:GetAuthorizationToken"],
                resources=["*"],
            )
        )
        base.add_to_role_policy(
            iam.PolicyStatement(
                sid="PublicarImagenesMigrarYOps",
                actions=[
                    "ecr:DescribeImages",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:CompleteLayerUpload",
                    "ecr:PutImage",
                ],
                resources=[repos],
            )
        )

        migrar = self.proyectos["migrar"]
        cluster = f"arn:{particion}:ecs:{region}:{cuenta}:cluster/cc-{env}"
        migrar.add_to_role_policy(leer_stacks_de(f"CcComputeBase-{env}", particion, region, cuenta))
        migrar.add_to_role_policy(
            iam.PolicyStatement(
                sid="EjecutarSoloLaTareaMigrar",
                actions=["ecs:RunTask"],
                resources=[
                    f"arn:{particion}:ecs:{region}:{cuenta}:task-definition/cc-{env}-migrar:*"
                ],
                conditions={"ArnEquals": {"ecs:cluster": cluster}},
            )
        )
        migrar.add_to_role_policy(
            iam.PolicyStatement(
                sid="VerTareasDelClusterDelAmbiente",
                actions=["ecs:DescribeTasks"],
                resources=[f"arn:{particion}:ecs:{region}:{cuenta}:task/cc-{env}/*"],
            )
        )
        migrar.add_to_role_policy(
            iam.PolicyStatement(
                sid="PasarRolesDeLaTareaMigrar",
                actions=["iam:PassRole"],
                resources=[f"arn:{particion}:iam::{cuenta}:role/CcComputeBase-{env}-*"],
                conditions={"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}},
            )
        )

        if es_prod:
            respaldo = self.proyectos["respaldo"]
            respaldo.add_to_role_policy(leer_stacks_de(f"CcData-{env}", particion, region, cuenta))
            respaldo.add_to_role_policy(
                iam.PolicyStatement(
                    sid="InstantaneaDeLaInstanciaDelAmbiente",
                    actions=["rds:CreateDBSnapshot"],
                    resources=[f"arn:{particion}:rds:{region}:{cuenta}:db:*"],
                    conditions={"StringEquals": {"aws:ResourceTag/ambiente": env}},
                )
            )
            instantaneas = (
                f"arn:{particion}:rds:{region}:{cuenta}:snapshot:cc-{env}-pre-migracion-*"
            )
            respaldo.add_to_role_policy(
                iam.PolicyStatement(
                    sid="CrearYEsperarLaInstantanea",
                    actions=[
                        "rds:CreateDBSnapshot",
                        "rds:AddTagsToResource",
                        "rds:DescribeDBSnapshots",
                    ],
                    resources=[instantaneas],
                )
            )

    def _reconocer(self) -> None:
        env = self._env
        cuenta, region, particion = self.account, self.region, self.partition
        for nombre, proyecto in self.proyectos.items():
            if nombre in ("ci", "base", "servicios"):
                reconocer(
                    proyecto,
                    "AwsSolutions-CB3",
                    f"El proyecto cc-{env}-{nombre} construye imágenes de contenedor con Docker "
                    "(pruebas de integración o imágenes de ECS), que exige el modo privilegiado.",
                )

        # Permisos que CDK concede a los roles del pipeline sobre el bucket de artefactos y la llave
        # del propio pipeline (todos los roles de este stack, sin otro alcance).
        artefactos = self.get_logical_id(self.bucket_artefactos.node.default_child)
        for regla, motivo in (
            (
                f"Resource::<{artefactos}.Arn>/*",
                "los objetos del bucket de artefactos de este ambiente (no otro bucket)",
            ),
            *(
                (
                    f"Action::s3:{a}",
                    "lectura, escritura o borrado de los objetos del bucket de "
                    "artefactos que CDK concede como conjunto de acciones",
                )
                for a in ("Abort*", "DeleteObject*", "GetBucket*", "GetObject*", "List*")
            ),
            *(
                (
                    f"Action::kms:{a}",
                    "cifrado de sobre con la llave propia del pipeline "
                    f"(cc-{env}-pipeline), que es el único recurso de esas acciones",
                )
                for a in ("GenerateDataKey*", "ReEncrypt*")
            ),
        ):
            reconocer(
                self,
                f"AwsSolutions-IAM5[{regla}]",
                f"Roles del pipeline de cc-{env}: {motivo}.",
            )
        for nombre, proyecto in self.proyectos.items():
            logico = self.get_logical_id(proyecto.node.default_child)
            reconocer(
                self,
                "AwsSolutions-IAM5[Resource::"
                + id_nag(
                    self,
                    f"arn:{particion}:logs:{region}:{cuenta}:log-group:/aws/codebuild/<{logico}>:*",
                )
                + "]",
                f"Registros del proyecto cc-{env}-{nombre}: el sufijo :* es el de los flujos del "
                "grupo de logs de ese único proyecto.",
            )
            reconocer(
                self,
                "AwsSolutions-IAM5[Resource::"
                + id_nag(
                    self,
                    f"arn:{particion}:codebuild:{region}:{cuenta}:report-group/<{logico}>-*",
                )
                + "]",
                f"Informes de pruebas del proyecto cc-{env}-{nombre}: el sufijo identifica solo a "
                "los grupos de informes de ese proyecto.",
            )
        stacks = {
            f"arn:{particion}:cloudformation:{region}:{cuenta}:stack/Cc*-{env}/*": (
                "los stacks Cc*-{env} del ambiente: el ARN de un stack termina en su identificador"
            ),
            f"arn:{particion}:cloudformation:{region}:{cuenta}:stack/CcData-{env}/*": (
                "el stack CcData del ambiente: el ARN de un stack termina en su identificador"
            ),
            f"arn:{particion}:cloudformation:{region}:{cuenta}:stack/CcComputeBase-{env}/*": (
                "el stack CcComputeBase del ambiente (su ARN termina en un identificador)"
            ),
            f"arn:{particion}:ecr:{region}:{cuenta}:repository/cc-{env}/*": (
                "los repositorios cc-{env}/ (migrar y ops) donde se publican las imágenes"
            ),
            f"arn:{particion}:ecs:{region}:{cuenta}:task-definition/cc-{env}-migrar:*": (
                "las revisiones de la definición de la tarea migrar (cada revisión es un número)"
            ),
            f"arn:{particion}:ecs:{region}:{cuenta}:task/cc-{env}/*": (
                "las tareas del clúster del ambiente (el identificador de la tarea es aleatorio)"
            ),
            f"arn:{particion}:iam::{cuenta}:role/CcComputeBase-{env}-*": (
                "los roles de la tarea migrar, que CloudFormation nombra con el prefijo del stack"
            ),
            f"arn:{particion}:rds:{region}:{cuenta}:db:*": (
                "la instancia de RDS del ambiente (su identificador lo genera CloudFormation), "
                f"acotada por la etiqueta ambiente={env}"
            ),
            f"arn:{particion}:rds:{region}:{cuenta}:snapshot:cc-{env}-pre-migracion-*": (
                "las instantáneas previas a migrar (su sufijo es la fecha y hora)"
            ),
            "*": (
                "ecr:GetAuthorizationToken no admite un recurso específico; es la acción con la "
                "que se obtiene la credencial para subir las imágenes"
            ),
        }
        for recurso, motivo in stacks.items():
            reconocer(
                self,
                f"AwsSolutions-IAM5[Resource::{id_nag(self, recurso)}]",
                f"Pipeline de cc-{env}: el comodín cubre {motivo}.",
            )


def leer_stacks_de(stack: str, particion: str, region: str, cuenta: str) -> iam.PolicyStatement:
    """``cloudformation:DescribeStacks`` sobre un único stack (lee sus salidas)."""
    return iam.PolicyStatement(
        sid=f"LeerSalidasDe{stack.split('-')[0]}",
        actions=["cloudformation:DescribeStacks"],
        resources=[f"arn:{particion}:cloudformation:{region}:{cuenta}:stack/{stack}/*"],
    )
