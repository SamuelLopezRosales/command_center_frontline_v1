"""Stack CcWorkersLambdas: workers de ECS con escalado por cola y Lambdas de mensajería
(T-136; design.md §4, §12, §13.6; CC-NFR-005, 007, 008, 016).

**Workers** (Fargate ARM64 sin ALB; la imagen es la del servicio dueño, activo de CDK, y cambia solo
el comando): ``worker-pdf`` (constancias, 1 vCPU y 2 GB), ``worker-cargas`` (colaboradores, 0.5 vCPU
y 1 GB) y ``worker-whatsapp-entrada`` (whatsapp, 0.5 vCPU y 1 GB). Escalan por el trabajo pendiente
de su cola: ``ApproximateNumberOfMessagesVisible`` más los mensajes en proceso (así no se apaga una
tarea que todavía procesa el último mensaje). Mínimo de tareas: ``economia.workers_min_tareas`` (0
en ``test``, 1 en ``prod``; ``worker-whatsapp-entrada`` nunca baja de 2 en ``prod`` por alta
disponibilidad, §4.7). Máximo: 1 en ``test`` (presupuesto) y el de §4.7 en ``prod``.

**Lambdas** (Python 3.12, arm64, alias ``live``, registros de 30 días, concurrencia reservada):

=================  ======  =======  ==========  ===  ============================
Función            Memoria  Tiempo  Reservada   VPC  Disparador
=================  ======  =======  ==========  ===  ============================
webhook-meta         256 MB     5 s          20  no   API Gateway (T-225)
enviador             512 MB    30 s          10  sí   SQS wa-salida.fifo, lote 10
estados-entrega      256 MB    30 s           5  sí   SQS wa-estados, lote 10
despachador          512 MB   300 s           5  sí   SQS notif-despacho, lote 1
conciliador          256 MB   120 s           1  sí   EventBridge cada 5 minutos
respaldo-correo      512 MB   300 s           3  sí   SQS notif-respaldo, lote 1
=================  ======  =======  ==========  ===  ============================

Cada fuente SQS usa ``ReportBatchItemFailures`` y ``maximum concurrency`` igual a la concurrencia
reservada de la función: con un tope inferior al de los *pollers* de SQS, Lambda rechaza lotes por
límite de concurrencia y esos rechazos cuentan como recepciones hacia la DLQ de la cola.

**DLQ**: las funciones con cola como origen usan la DLQ de la propia cola (``CcMessaging``,
``maxReceiveCount`` de §4.1). El ``conciliador`` no la lleva (§4.5): el siguiente ciclo repite.
``webhook-meta`` responde síncrono a Meta, que reintenta (§4.2).

La concurrencia aprovisionada de ``webhook-meta`` es ``economia.concurrencia_aprovisionada_webhook``
(0 en ``test``: no se configura; CloudFormation no acepta 0).

El código sale de ``build/lambdas_wa`` y ``build/lambdas_notif`` (``scripts/empaquetar_lambdas.py
--whatsapp`` y ``--notificaciones``); sin ellos la síntesis falla (como en ``CcAuth``). Las pruebas
usan ``CC_LAMBDAS_DESDE_FUENTE=1``.

Todo lo de otros stacks (colas, bus, secretos, rol de Scheduler, tema de alertas) se importa por
nombre o ARN: ningún permiso se agrega a un recurso ajeno.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_applicationautoscaling as appscaling
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sqs as sqs

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs.nag import reconocer
from infra.constructs.retencion import politica_retencion
from infra.constructs.servicios import (
    GRUPO_SUBREDES_APLICACION,
    ContextoPermisos,
    Recursos,
    cluster_importado,
    como_lo_muestra_nag,
    comodines_servicio,
    entorno_base,
    imagen_servicio,
    reconocer_comodines,
    reconocer_tarea,
    sentencia,
    sentencia_secretos,
    sentencias_consumo,
    sentencias_servicio,
    tarea_fargate,
    variables_servicio,
)

RAIZ = Path(__file__).resolve().parents[2]
PAQUETE_WHATSAPP = RAIZ / "build" / "lambdas_wa"
PAQUETE_NOTIFICACIONES = RAIZ / "build" / "lambdas_notif"
FUENTE = RAIZ / "lambdas"


@dataclass(frozen=True)
class DefWorker:
    nombre: str
    servicio: str
    modulo: str
    cola: str
    cpu: int
    memoria: int
    minimo_prod: int
    maximo_prod: int
    mensajes_por_tarea: int  # objetivo de §4.7: define los escalones del escalado


# design.md §4.7. Los de ``cargas`` procesan un archivo completo por mensaje: 1 por tarea.
WORKERS: tuple[DefWorker, ...] = (
    DefWorker(
        "worker-pdf", "constancias", "cc_constancias.workers.worker_pdf", "cola-pdf",
        1024, 2048, 1, 4, 5,
    ),
    DefWorker(
        "worker-cargas", "colaboradores", "cc_colaboradores.workers.worker_cargas", "cola-cargas",
        512, 1024, 1, 2, 1,
    ),
    DefWorker(
        "worker-whatsapp-entrada", "whatsapp", "cc_whatsapp.workers.worker_entrada",
        "wa-entrada.fifo", 512, 1024, 2, 4, 20,
    ),
)  # fmt: skip


@dataclass(frozen=True)
class DefLambda:
    nombre: str
    paquete: str  # "wa" o "notif"
    handler: str
    memoria: int
    timeout_s: int
    reservada: int
    en_vpc: bool
    descripcion: str
    cola: str | None = None
    lote: int = 1


# design.md §4.2 a §4.5.
LAMBDAS: tuple[DefLambda, ...] = (
    DefLambda(
        "webhook-meta", "wa", "webhook_meta.handler.lambda_handler", 256, 5, 20, False,
        "LAM-01: recibe el webhook de Meta, valida la firma y encola",
    ),
    DefLambda(
        "enviador", "wa", "enviador.handler.lambda_handler", 512, 30, 10, True,
        "LAM-02: envía los mensajes de wa-salida.fifo por la API de Meta",
        cola="wa-salida.fifo", lote=10,
    ),
    DefLambda(
        "estados-entrega", "wa", "estados_entrega.handler.lambda_handler", 256, 30, 5, True,
        "LAM-03: aplica los estados de entrega de wa-estados",
        cola="wa-estados", lote=10,
    ),
    DefLambda(
        "despachador", "notif", "despachador.handler.lambda_handler", 512, 300, 5, True,
        "LAM-04: despacha una notificación hacia wa-salida.fifo",
        cola="notif-despacho", lote=1,
    ),
    DefLambda(
        "conciliador", "notif", "conciliador.handler.lambda_handler", 256, 120, 1, True,
        "LAM-05: red de seguridad de la programación (cada 5 minutos)",
    ),
    DefLambda(
        "respaldo-correo", "notif", "respaldo_correo.handler.lambda_handler", 512, 300, 3, True,
        "LAM-06: respaldo por correo (SES) y rebotes",
        cola="notif-respaldo", lote=1,
    ),
)  # fmt: skip


def _codigo(paquete: str) -> lambda_.Code:
    if os.environ.get("CC_LAMBDAS_DESDE_FUENTE") == "1":
        return lambda_.Code.from_asset(
            str(FUENTE), exclude=["**/tests/**", "**/__pycache__/**", "*.pyc", ".gitkeep"]
        )
    if paquete == "wa":
        carpeta, comando = PAQUETE_WHATSAPP, "--whatsapp"
    else:
        carpeta, comando = PAQUETE_NOTIFICACIONES, "--notificaciones"
    if not (carpeta / "cc_common").is_dir():
        raise FileNotFoundError(
            f"Falta {carpeta.relative_to(RAIZ)}. Ejecute: "
            f"uv run python scripts/empaquetar_lambdas.py {comando}"
        )
    return lambda_.Code.from_asset(str(carpeta))


class WorkersLambdasStack(cdk.Stack):
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
        sg_lambda: ec2.ISecurityGroup,
        bucket_plantillas: str,
        bucket_constancias: str,
        bucket_cargas: str,
        host_bd: str,
        host_bd_lambda: str,
        url_interna: str,
        user_pool_arn: str,
        user_pool_id: str,
        cliente_id: str,
        empresa_id_whatsapp: int | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, id_, **kwargs)
        env = ambiente.nombre
        eco = ambiente.economia
        ret = politica_retencion(ambiente)
        es_prod = not eco.permite_borrado
        self.r = Recursos(self, env)
        r = self.r
        self.llave_infra_arn = llave_infra.key_arn
        self.url_interna = url_interna
        self.host_bd_lambda = host_bd_lambda
        self.correo_origen = ambiente.presupuesto.correo  # remitente de prueba (PQ-22)
        self.ret = ret
        self.eco = eco
        self.es_prod = es_prod
        self.vpc = vpc
        self.sg_lambda = ec2.SecurityGroup.from_security_group_id(
            self, "SgLambdaImportado", sg_lambda.security_group_id, mutable=False
        )
        sg_servicio = ec2.SecurityGroup.from_security_group_id(
            self, "SgEcsImportado", sg_ecs.security_group_id, mutable=False
        )
        subredes = ec2.SubnetSelection(subnet_group_name=GRUPO_SUBREDES_APLICACION)
        ctx = ContextoPermisos(
            recursos=r,
            llave_infra_arn=self.llave_infra_arn,
            llave_datos_arn=llave_datos.key_arn,
            bucket_plantillas=r.arn_bucket(bucket_plantillas),
            bucket_constancias=r.arn_bucket(bucket_constancias),
            bucket_cargas=r.arn_bucket(bucket_cargas),
            user_pool_arn=user_pool_arn,
        )

        # ------------------------------------------------------------------ workers
        cluster = cluster_importado(self, vpc, env)
        self.tareas: dict[str, ecs.FargateTaskDefinition] = {}
        self.servicios: dict[str, ecs.FargateService] = {}
        for w in WORKERS:
            minimo = (
                max(eco.workers_min_tareas, w.minimo_prod) if es_prod else eco.workers_min_tareas
            )
            maximo = w.maximo_prod if es_prod else max(1, minimo)
            entorno = {
                **entorno_base(r, env, self.region, host_bd=host_bd, rol_bd=f"svc_{w.servicio}"),
                "CC_COGNITO_EMISOR": (
                    f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool_id}"
                ),
                "CC_COGNITO_CLIENT_ID": cliente_id,
                **variables_servicio(
                    w.servicio,
                    r,
                    env,
                    url_interna=url_interna,
                    bucket_plantillas=bucket_plantillas,
                    bucket_constancias=bucket_constancias,
                    bucket_cargas=bucket_cargas,
                    user_pool_id=user_pool_id,
                    empresa_id_whatsapp=empresa_id_whatsapp,
                    worker=True,
                ),
            }
            tarea = tarea_fargate(
                self,
                w.nombre,
                env,
                cpu=w.cpu,
                memoria=w.memoria,
                imagen=imagen_servicio(w.servicio),
                entorno=entorno,
                removal_policy=ret.removal_policy,
                comando=["python", "-m", w.modulo],
            )
            for st in sentencias_servicio(ctx, w.servicio, worker=True):
                tarea.add_to_task_role_policy(st)
            for st in sentencias_consumo(r, w.cola, self.llave_infra_arn):
                tarea.add_to_task_role_policy(st)
            self.tareas[w.nombre] = tarea

            servicio = ecs.FargateService(
                self,
                f"Servicio-{w.nombre}",
                service_name=f"cc-{env}-{w.nombre}",
                cluster=cluster,
                task_definition=tarea,
                desired_count=minimo,
                security_groups=[sg_servicio],
                vpc_subnets=subredes,
                assign_public_ip=False,
                min_healthy_percent=100,
                max_healthy_percent=200,
                circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True),
                enable_execute_command=False,
            )
            self.servicios[w.nombre] = servicio
            self._escalar_por_cola(servicio, w, minimo, maximo)
            reconocer_tarea(tarea, w.nombre, reconocer)
            reconocer_comodines(tarea.task_role, comodines_servicio(ctx, w.servicio), reconocer)

        # ------------------------------------------------------------------ Lambdas
        self.funciones: dict[str, lambda_.Function] = {}
        self.alias: dict[str, lambda_.Alias] = {}
        for d in LAMBDAS:
            self._lambda(d, subredes)
        self._regla_conciliador(env)
        self._permisos_lambdas()
        self._reconocer_lambdas(env)

        for nombre, svc in self.servicios.items():
            cdk.CfnOutput(self, f"Salida-{nombre}", value=svc.service_name)
        for nombre, alias in self.alias.items():
            cdk.CfnOutput(self, f"SalidaAlias-{nombre}", value=alias.function_arn)

    # ------------------------------------------------------------------------ workers
    def _escalar_por_cola(
        self, servicio: ecs.FargateService, w: DefWorker, minimo: int, maximo: int
    ) -> None:
        nombre_cola = self.r.nombre_cola(w.cola)

        def metrica(nombre: str) -> cloudwatch.Metric:
            return cloudwatch.Metric(
                namespace="AWS/SQS",
                metric_name=nombre,
                dimensions_map={"QueueName": nombre_cola},
                statistic="Maximum",
                period=cdk.Duration.minutes(1),
            )

        pendiente = cloudwatch.MathExpression(
            expression="visibles + en_proceso",
            using_metrics={
                "visibles": metrica("ApproximateNumberOfMessagesVisible"),
                "en_proceso": metrica("ApproximateNumberOfMessagesNotVisible"),
            },
            label=f"Trabajo pendiente de {w.cola}",
            period=cdk.Duration.minutes(1),
        )
        objetivo = w.mensajes_por_tarea
        escala = servicio.auto_scale_task_count(min_capacity=minimo, max_capacity=maximo)
        escala.scale_on_metric(
            "PorCola",
            metric=pendiente,
            adjustment_type=appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
            scaling_steps=[
                # Cola vacía y nada en proceso: baja de a una tarea (hasta el mínimo).
                appscaling.ScalingInterval(upper=0, change=-1),
                appscaling.ScalingInterval(lower=1, upper=objetivo * 2, change=1),
                appscaling.ScalingInterval(lower=objetivo * 2, upper=objetivo * 6, change=2),
                appscaling.ScalingInterval(lower=objetivo * 6, change=3),
            ],
            evaluation_periods=2,
            cooldown=cdk.Duration.minutes(2),
        )

    # ------------------------------------------------------------------------ Lambdas
    def _cola(self, nombre: str) -> sqs.IQueue:
        return sqs.Queue.from_queue_attributes(
            self,
            f"Cola-{nombre}",
            queue_arn=self.r.arn_cola(nombre),
            queue_url=self.r.url_cola(nombre),
            key_arn=self.llave_infra_arn,
            fifo=nombre.endswith(".fifo"),
        )

    def _entorno_lambda(self, d: DefLambda) -> dict[str, str]:
        r = self.r
        u = self.url_interna
        if d.nombre == "webhook-meta":
            return {
                "CC_AMBIENTE": r.env,
                "CC_REGION": self.region,
                "CC_META_SECRETO_ID": r.id_secreto("meta"),
                "CC_COLA_ENTRADA_URL": r.url_cola("wa-entrada.fifo"),
                "CC_COLA_ESTADOS_URL": r.url_cola("wa-estados"),
            }
        if d.paquete == "wa":
            base = entorno_base(
                r, r.env, self.region, host_bd=self.host_bd_lambda, rol_bd="svc_whatsapp"
            )
            base |= {"CC_BUS_EVENTOS": r.nombre_bus}
            if d.nombre == "enviador":
                base |= {
                    "CC_META_SECRETO_ID": r.id_secreto("meta"),
                    "CC_COLABORADORES_URL": u,
                    "CC_COLA_SALIDA_URL": r.url_cola("wa-salida.fifo"),
                }
            return base
        base = entorno_base(
            r, r.env, self.region, host_bd=self.host_bd_lambda, rol_bd="svc_notificaciones"
        )
        base |= {
            "CC_COLA_DESPACHO_URL": r.url_cola("notif-despacho"),
            "CC_COLA_RESPALDO_URL": r.url_cola("notif-respaldo"),
        }
        if d.nombre == "despachador":
            base |= {"CC_COLA_SALIDA_URL": r.url_cola("wa-salida.fifo"), "CC_COLABORADORES_URL": u}
        if d.nombre in ("despachador", "respaldo-correo"):
            base |= {
                "CC_SCHEDULER_DESPACHO_ARN": r.arn_cola("notif-despacho"),
                "CC_SCHEDULER_RESPALDO_ARN": r.arn_cola("notif-respaldo"),
                "CC_SCHEDULER_ROL_ARN": r.arn_rol_scheduler,
                "CC_SCHEDULER_GRUPO": r.nombre_grupo_scheduler,
            }
        if d.nombre == "respaldo-correo":
            base |= {
                "CC_COLABORADORES_URL": u,
                "CC_ALERTAS_TOPIC_ARN": r.arn_tema_alertas,
                "CC_SES_ORIGEN": self.correo_origen,
                "CC_SES_CONFIG_SET": r.nombre_conjunto_ses,
            }
        return base

    def _lambda(self, d: DefLambda, subredes: ec2.SubnetSelection) -> None:
        env = self.r.env
        extra: dict = {}
        if d.en_vpc:
            extra = {
                "vpc": self.vpc,
                "vpc_subnets": subredes,
                "security_groups": [self.sg_lambda],
            }
        fn = lambda_.Function(
            self,
            f"Fn-{d.nombre}",
            function_name=f"cc-{env}-{d.nombre}",
            description=d.descripcion,
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler=d.handler,
            code=_codigo(d.paquete),
            memory_size=d.memoria,
            timeout=cdk.Duration.seconds(d.timeout_s),
            reserved_concurrent_executions=d.reservada,
            environment=self._entorno_lambda(d),
            # Sin reintentos asíncronos en el conciliador: dos ejecuciones solapadas serían un
            # error de diseño (reservada 1) y el siguiente ciclo ya repite el trabajo.
            retry_attempts=0 if d.nombre == "conciliador" else None,
            log_group=logs.LogGroup(
                self,
                f"Logs-{d.nombre}",
                log_group_name=f"/aws/lambda/cc-{env}-{d.nombre}",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=self.ret.removal_policy,
            ),
            current_version_options=lambda_.VersionOptions(removal_policy=self.ret.removal_policy),
            **extra,
        )
        aprovisionada = (
            self.eco.concurrencia_aprovisionada_webhook if d.nombre == "webhook-meta" else 0
        )
        alias = lambda_.Alias(
            self,
            f"Alias-{d.nombre}",
            alias_name="live",
            version=fn.current_version,
            provisioned_concurrent_executions=aprovisionada or None,
        )
        self.funciones[d.nombre] = fn
        self.alias[d.nombre] = alias
        if d.cola:
            alias.add_event_source(
                sources.SqsEventSource(
                    self._cola(d.cola),
                    batch_size=d.lote,
                    report_batch_item_failures=True,
                    # Igual a la concurrencia reservada: evita rechazos por límite de concurrencia
                    # que contarían como recepciones hacia la DLQ (mínimo 2, lo que exige Lambda).
                    # En FIFO no se fija: la concurrencia la marcan los grupos de mensajes y el tope
                    # de la reservada (docs/desviaciones.md).
                    max_concurrency=None if d.cola.endswith(".fifo") else max(2, d.reservada),
                )
            )

    def _regla_conciliador(self, env: str) -> None:
        self.regla_conciliador = events.Rule(
            self,
            "ReglaConciliador",
            rule_name=f"cc-{env}-conciliador",
            description="Ejecuta el conciliador de notificaciones cada 5 minutos (design.md §4.5)",
            schedule=events.Schedule.rate(cdk.Duration.minutes(5)),
            targets=[
                targets.LambdaFunction(
                    self.alias["conciliador"],
                    retry_attempts=0,
                    max_event_age=cdk.Duration.minutes(5),
                )
            ],
        )

    # ------------------------------------------------------------------------ permisos
    def _permisos_lambdas(self) -> None:
        r = self.r
        llave = self.llave_infra_arn
        f = self.funciones

        def dar(nombre: str, sentencias: list) -> None:
            for s in sentencias:
                f[nombre].add_to_role_policy(s)

        def escribe_cifrado() -> list:
            # Colas, tema y secretos cifrados con la llave de infraestructura.
            return [sentencia(["kms:Decrypt", "kms:GenerateDataKey"], [llave])]

        def programa_schedules() -> list:
            return [
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
                    condiciones={
                        "StringEquals": {"iam:PassedToService": "scheduler.amazonaws.com"}
                    },
                ),
            ]

        dar(
            "webhook-meta",
            [
                sentencia(
                    ["sqs:SendMessage"],
                    [r.arn_cola("wa-entrada.fifo"), r.arn_cola("wa-estados")],
                ),
                *sentencia_secretos(r, ["meta"], llave),
                sentencia(["kms:GenerateDataKey"], [llave]),
            ],
        )
        dar(
            "enviador",
            [
                *sentencias_consumo(r, "wa-salida.fifo", llave),
                *sentencia_secretos(r, ["meta", "internal-auth", "db/svc_whatsapp"], llave),
            ],
        )
        dar(
            "estados-entrega",
            [
                *sentencias_consumo(r, "wa-estados", llave),
                *sentencia_secretos(r, ["db/svc_whatsapp"], llave),
            ],
        )
        dar(
            "despachador",
            [
                *sentencias_consumo(r, "notif-despacho", llave),
                sentencia(
                    ["sqs:SendMessage"],
                    [r.arn_cola("wa-salida.fifo"), r.arn_cola("notif-despacho")],
                ),
                *escribe_cifrado(),
                *programa_schedules(),
                *sentencia_secretos(r, ["internal-auth", "db/svc_notificaciones"], llave),
            ],
        )
        dar(
            "conciliador",
            [
                sentencia(
                    ["sqs:SendMessage"],
                    [r.arn_cola("notif-despacho"), r.arn_cola("notif-respaldo")],
                ),
                *escribe_cifrado(),
                *sentencia_secretos(r, ["db/svc_notificaciones"], llave),
            ],
        )
        dar(
            "respaldo-correo",
            [
                *sentencias_consumo(r, "notif-respaldo", llave),
                *escribe_cifrado(),
                *programa_schedules(),
                sentencia(
                    ["ses:SendEmail"],
                    [r.arn_identidad_ses(self.correo_origen), r.arn_conjunto_ses],
                ),
                sentencia(["sns:Publish"], [r.arn_tema_alertas]),
                *sentencia_secretos(r, ["internal-auth", "db/svc_notificaciones"], llave),
            ],
        )

    # ------------------------------------------------------------------------ cdk-nag
    def _reconocer_lambdas(self, env: str) -> None:
        for d in LAMBDAS:
            fn = self.funciones[d.nombre]
            reconocer(
                fn,
                "AwsSolutions-L1",
                "Python 3.12 es el tiempo de ejecución fijado por el diseño (restricción de "
                "stack, design.md §1.4) para todos los componentes.",
            )
            reconocer(
                fn.role,
                "AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/"
                "AWSLambdaBasicExecutionRole]",
                "Política administrada de AWS para que la función escriba sus registros.",
            )
            if d.nombre in ("despachador", "respaldo-correo"):
                reconocer_comodines(
                    fn.role,
                    [como_lo_muestra_nag(self.r, self.r.arn_schedules)],
                    reconocer,
                )
            if d.en_vpc:
                reconocer(
                    fn.role,
                    "AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/"
                    "AWSLambdaVPCAccessExecutionRole]",
                    "Política administrada de AWS para que una Lambda en la VPC cree sus "
                    "interfaces de red y escriba registros.",
                )
                reconocer(
                    fn.role,
                    "AwsSolutions-IAM5[Resource::*]",
                    "Las acciones ec2:CreateNetworkInterface, DescribeNetworkInterfaces y "
                    "DeleteNetworkInterface de una Lambda en VPC no admiten un recurso "
                    "específico.",
                )
