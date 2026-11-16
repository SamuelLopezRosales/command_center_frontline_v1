"""Stack CcObservability: paneles, alarmas y CloudTrail (T-139; design.md §14.6, §15.1, §15.2;
CC-NFR-010, CC-NFR-012).

**Alarmas** (§15.2): una por cada fila de ``docs/runbooks/README.md``. Los identificadores son los
de ese índice (``cc-{env}-<tema>``) y la descripción de cada alarma enlaza su runbook. Los umbrales
están **todos** en la tabla ``UMBRALES`` (un solo lugar) y son **[POR CONFIRMAR]** (PQ-20): la
descripción de cada alarma lo dice. Las acciones van al tema ``cc-{env}-alertas-ops`` (guardia),
distinto de ``alertas-rh`` de ``CcMessaging``, que es para personas de RH (desviación 12).

Fuentes de las métricas:

- AWS: SQS, Lambda, RDS, ALB (por grupo de destino), SES y API Gateway.
- EMF de las Lambdas (``CommandCenter/WhatsApp`` y ``CommandCenter/Notificaciones``): hoy existen
  ``webhook_firma_invalida`` y ``programadas_atrasadas``.
- ``meta_error_*``: el nombre de la métrica lleva el código de error, así que un filtro de métricas
  del registro de ``enviador`` las suma en ``CommandCenter/Observabilidad``.
- **Aún no las emite ningún servicio** (la alarma queda en ``OK`` sin datos hasta que existan;
  ``treat_missing_data=NOT_BREACHING``): ``duracion_generacion_ms`` y
  ``solicitudes_render_fallidas``
  (``CommandCenter/Constancias``) y ``error_descifrado`` (``CommandCenter/Seguridad``).

**Paneles**: ``prod`` crea los cinco de §15.2 (Operación, Colas, WhatsApp, Constancias y Base de
datos). ``test`` los agrupa en tres (Operación con Base de datos, Colas con WhatsApp, Constancias):
los tres primeros paneles de una cuenta no cuestan y cada adicional cuesta unos 3 USD al mes.

**Retención de logs**: no se duplica. Los grupos de ``CcAuth``, ``CcCompute``, ``CcWorkersLambdas``
y ``CcApi`` ya fijan 30 días (§15.1); la prueba de este stack comprueba que ninguno quede sin
retención. **CloudTrail**: un trail de gestión (el primero es gratis) con validación de integridad
de archivos, bucket propio cifrado con la llave de infraestructura y 365 días de retención.

Todo lo de otros stacks llega por nombre o por referencia de salida (nombres de colas, funciones,
grupos de destino): ningún permiso ni recurso se modifica desde aquí.
"""

from __future__ import annotations

from dataclasses import dataclass

import aws_cdk as cdk
from aws_cdk import aws_cloudtrail as cloudtrail
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs.nag import reconocer
from infra.constructs.retencion import politica_retencion
from infra.constructs.servicios import SERVICIOS
from infra.stacks.messaging import COLAS

RETENCION_LOGS_DIAS = 30  # §15.1 [POR CONFIRMAR, PQ-12]
RETENCION_CLOUDTRAIL_DIAS = 365  # §15.1
CARPETA_RUNBOOKS = "docs/runbooks"

NS_WHATSAPP = "CommandCenter/WhatsApp"
NS_NOTIFICACIONES = "CommandCenter/Notificaciones"
NS_OBSERVABILIDAD = "CommandCenter/Observabilidad"
NS_CONSTANCIAS = "CommandCenter/Constancias"
NS_SEGURIDAD = "CommandCenter/Seguridad"

# ``max_connections`` por defecto de RDS PostgreSQL (memoria / 9531392 bytes, truncado). [POR
# CONFIRMAR] contra la instancia real (Performance Insights): sirve para el 80 % de §15.2.
MAX_CONEXIONES_RDS: dict[str, int] = {"db.t4g.micro": 112, "db.t4g.medium": 450}
# Mismos valores de ``DataStack`` (``allocated_storage``): 20 GB en test y 100 GB en prod.
ALMACENAMIENTO_RDS_GB = {"test": 20, "prod": 100}


@dataclass(frozen=True)
class Umbral:
    """Umbral de una alarma. Todos son [POR CONFIRMAR] (PQ-20, design.md §15.2)."""

    valor: float
    unidad: str
    periodo_min: int
    evaluaciones: int
    runbook: str
    severidad: str
    descripcion: str


# Tabla única de umbrales. La clave es el identificador de la alarma sin ``cc-{env}-`` (las de una
# por cola o por servicio llevan el sufijo al crearse). Coincide con ``docs/runbooks/README.md``.
UMBRALES: dict[str, Umbral] = {
    "dlq": Umbral(
        0, "mensajes visibles", 1, 1, "dlq-con-mensajes.md", "Crítica",
        "La DLQ tiene mensajes (ApproximateNumberOfMessagesVisible mayor a 0)",
    ),
    "cola-antigua-wa-salida": Umbral(
        300, "segundos", 5, 1, "mensajes-antiguos.md", "Alta",
        "El mensaje más antiguo de wa-salida tiene más de 5 minutos",
    ),
    "cola-antigua-cola-pdf": Umbral(
        600, "segundos", 5, 1, "mensajes-antiguos.md", "Alta",
        "El mensaje más antiguo de cola-pdf tiene más de 10 minutos",
    ),
    "webhook-firma-invalida": Umbral(
        10, "firmas inválidas en 5 min", 5, 1, "webhook-firma-invalida.md", "Alta",
        "Más de 10 firmas inválidas en el webhook de Meta en 5 minutos",
    ),
    "webhook-5xx": Umbral(
        0, "errores de la Lambda en 5 min", 5, 1, "webhook-firma-invalida.md", "Crítica",
        "webhook-meta tuvo errores (5xx): Meta reintentará, hay que reprocesar",
    ),
    "meta-errores": Umbral(
        10, "% de envíos con error de Meta", 5, 2, "meta-autenticacion-y-errores.md", "Crítica",
        "Más de 10 % de los lotes de envío con meta_error_* durante 10 minutos (incluye token "
        "inválido o vencido). Aproximación: errores entre invocaciones de enviador",
    ),
    "pdf-lento": Umbral(
        5000, "ms (p95)", 5, 1, "worker-pdf.md", "Alta",
        "La generación del PDF tiene p95 mayor a 5 s (CC-NFR-001)",
    ),
    "worker-pdf-fallos": Umbral(
        0, "solicitudes en 5 min", 5, 1, "worker-pdf.md", "Alta",
        "Solicitudes FALLIDA con ERROR_RENDER (el diseño no fija umbral en §15.2)",
    ),
    "rds-cpu": Umbral(
        80, "% de CPU", 5, 3, "rds.md", "Alta", "CPU de RDS mayor a 80 % durante 15 minutos"
    ),
    "rds-conexiones": Umbral(
        0.8, "fracción de max_connections", 5, 3, "rds.md", "Alta",
        "Conexiones de RDS mayores a 80 % del máximo durante 15 minutos",
    ),
    "rds-almacenamiento": Umbral(
        0.2, "fracción del almacenamiento asignado", 5, 1, "rds.md", "Crítica",
        "Almacenamiento libre de RDS menor a 20 %",
    ),
    "rds-conmutacion": Umbral(
        1, "evento", 1, 1, "rds.md", "Crítica",
        "Evento de conmutación por error (failover) de RDS",
    ),
    "programadas-atrasadas": Umbral(
        0, "notificaciones", 5, 3, "notificaciones-atrasadas.md", "Alta",
        "Hay notificaciones programadas atrasadas durante 15 minutos",
    ),
    "cognito-pre-token-errores": Umbral(
        0, "errores en 5 min", 5, 1, "cognito-pre-token.md", "Crítica",
        "Errores de la Lambda cognito-pre-token: nadie puede iniciar sesión",
    ),
    "ses-rebotes": Umbral(
        0.05, "tasa de rebote", 60, 1, "ses-rebotes-y-quejas.md", "Media",
        "La tasa de rebote de SES es mayor a 5 %",
    ),
    "error-descifrado": Umbral(
        0, "errores en 5 min", 5, 1, "error-descifrado.md", "Crítica",
        "Hubo errores de descifrado de datos sensibles",
    ),
    "5xx": Umbral(
        5, "% de respuestas 5xx (con al menos 10 solicitudes)", 5, 1, "api-5xx-y-latencia.md",
        "Alta", "Más de 5 % de respuestas 5xx durante 5 minutos",
    ),
    "latencia": Umbral(
        2, "segundos (p95)", 5, 2, "api-5xx-y-latencia.md", "Media",
        "Latencia p95 mayor a 2 s durante 10 minutos",
    ),
}  # fmt: skip

_MINIMO_SOLICITUDES_5XX = 10


def nombre_dlq(env: str, cola: str) -> str:
    base, punto, ext = cola.partition(".")
    return f"cc-{env}-{base}-dlq{punto}{ext}"


def nombre_cola(env: str, cola: str) -> str:
    return f"cc-{env}-{cola}"


class ObservabilityStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        id_: str,
        *,
        ambiente: Ambiente,
        llave_infra_arn: str,
        instancia_bd_id: str,
        alb_nombre_completo: str,
        grupos_destino: dict[str, str],
        api_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, id_, **kwargs)
        env = ambiente.nombre
        eco = ambiente.economia
        ret = politica_retencion(ambiente)
        self.es_prod = not eco.permite_borrado
        self.env_nombre = env
        if eco.rds_clase not in MAX_CONEXIONES_RDS:
            raise ValueError(f"falta max_connections de {eco.rds_clase} en MAX_CONEXIONES_RDS")
        if set(grupos_destino) != set(SERVICIOS):
            raise ValueError("grupos_destino debe traer los seis servicios de API")
        llave = kms.Key.from_key_arn(self, "LlaveInfraImportada", llave_infra_arn)
        self.instancia_bd_id = instancia_bd_id
        self.alb = alb_nombre_completo
        self.grupos = grupos_destino
        self.api_id = api_id
        self.clase_rds = eco.rds_clase
        self.almacenamiento_gb = ALMACENAMIENTO_RDS_GB["prod" if self.es_prod else "test"]

        self.tema = sns.Topic(
            self,
            "AlertasOps",
            topic_name=f"cc-{env}-alertas-ops",
            display_name="Command Center: alertas de operación (guardia)",
            master_key=llave,
            enforce_ssl=True,
        )
        self.alarmas: dict[str, cloudwatch.Alarm] = {}
        self._alarmas_dlq_y_colas()
        self._alarmas_webhook_y_meta()
        self._alarmas_constancias()
        self._alarmas_rds()
        self._alarmas_plataforma()
        self._alarmas_servicios()
        self.paneles: dict[str, cloudwatch.Dashboard] = {}
        self._paneles()
        self._cloudtrail(env, llave, ret)

        cdk.CfnOutput(self, "TemaAlertasOps", value=self.tema.topic_arn)
        cdk.CfnOutput(self, "Paneles", value=",".join(sorted(self.paneles)))

    # ------------------------------------------------------------------------ alarmas
    def _crear(
        self,
        ident: str,
        clave: str,
        metrica: cloudwatch.IMetric,
        *,
        comparacion: cloudwatch.ComparisonOperator = (
            cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD
        ),
        valor: float | None = None,
        detalle: str = "",
    ) -> cloudwatch.Alarm:
        u = UMBRALES[clave]
        umbral = u.valor if valor is None else valor
        alarma = cloudwatch.Alarm(
            self,
            f"Alarma-{ident}",
            alarm_name=f"cc-{self.env_nombre}-{ident}",
            alarm_description=(
                f"[POR CONFIRMAR, PQ-20] {u.descripcion}{detalle}. Umbral: {u.valor} {u.unidad}. "
                f"Severidad: {u.severidad}. Runbook: {CARPETA_RUNBOOKS}/{u.runbook}"
            ),
            metric=metrica,
            threshold=umbral,
            evaluation_periods=u.evaluaciones,
            datapoints_to_alarm=u.evaluaciones,
            comparison_operator=comparacion,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        alarma.add_alarm_action(cw_actions.SnsAction(self.tema))
        self.alarmas[ident] = alarma
        return alarma

    @staticmethod
    def _m(
        espacio: str,
        nombre: str,
        dims: dict[str, str] | None = None,
        *,
        estadistica: str = "Sum",
        minutos: int = 5,
    ) -> cloudwatch.Metric:
        return cloudwatch.Metric(
            namespace=espacio,
            metric_name=nombre,
            dimensions_map=dims or {},
            statistic=estadistica,
            period=cdk.Duration.minutes(minutos),
        )

    def _sqs(self, cola: str, nombre: str, estadistica: str, minutos: int = 1, dlq: bool = False):
        env = self.env_nombre
        return self._m(
            "AWS/SQS",
            nombre,
            {"QueueName": nombre_dlq(env, cola) if dlq else nombre_cola(env, cola)},
            estadistica=estadistica,
            minutos=minutos,
        )

    def _alarmas_dlq_y_colas(self) -> None:
        u = UMBRALES["dlq"]
        for d in COLAS:
            # Las colas FIFO terminan en ".fifo", también su DLQ (cc-{env}-wa-salida-dlq.fifo).
            fisico = f"{d.nombre}.fifo" if d.fifo else d.nombre
            self._crear(
                f"dlq-{d.nombre}",
                "dlq",
                self._sqs(
                    fisico, "ApproximateNumberOfMessagesVisible", "Maximum", u.periodo_min, True
                ),
                detalle=f" ({d.nombre})",
            )
        for cola in ("wa-salida", "cola-pdf"):
            clave = f"cola-antigua-{cola}"
            d = next(c for c in COLAS if c.nombre == cola)
            nombre = f"{cola}.fifo" if d.fifo else cola
            self._crear(
                clave,
                clave,
                self._sqs(
                    nombre, "ApproximateAgeOfOldestMessage", "Maximum", UMBRALES[clave].periodo_min
                ),
            )

    def _alarmas_webhook_y_meta(self) -> None:
        env = self.env_nombre
        self._crear(
            "webhook-firma-invalida",
            "webhook-firma-invalida",
            self._m(NS_WHATSAPP, "webhook_firma_invalida"),
        )
        self._crear(
            "webhook-5xx",
            "webhook-5xx",
            self._m("AWS/Lambda", "Errors", {"FunctionName": f"cc-{env}-webhook-meta"}),
        )
        # meta_error_{codigo}: el nombre varía, así que el filtro suma todas las que empiezan así.
        logs.MetricFilter(
            self,
            "FiltroMetaErrores",
            log_group=logs.LogGroup.from_log_group_name(
                self, "LogsEnviador", f"/aws/lambda/cc-{env}-enviador"
            ),
            filter_pattern=logs.FilterPattern.literal(
                '{ $._aws.CloudWatchMetrics[0].Metrics[0].Name = "meta_error_*" }'
            ),
            metric_namespace=NS_OBSERVABILIDAD,
            metric_name="meta_errores",
            metric_value="1",
        )
        u = UMBRALES["meta-errores"]
        tasa = cloudwatch.MathExpression(
            expression="IF(invocaciones > 0, 100 * errores / invocaciones, 0)",
            using_metrics={
                "errores": self._m(NS_OBSERVABILIDAD, "meta_errores", minutos=u.periodo_min),
                "invocaciones": self._m(
                    "AWS/Lambda",
                    "Invocations",
                    {"FunctionName": f"cc-{env}-enviador"},
                    minutos=u.periodo_min,
                ),
            },
            period=cdk.Duration.minutes(u.periodo_min),
            label="% de envíos con error de Meta",
        )
        self._crear("meta-errores", "meta-errores", tasa)

    def _alarmas_constancias(self) -> None:
        u = UMBRALES["pdf-lento"]
        self._crear(
            "pdf-lento",
            "pdf-lento",
            self._m(
                NS_CONSTANCIAS,
                "duracion_generacion_ms",
                estadistica="p95",
                minutos=u.periodo_min,
            ),
        )
        self._crear(
            "worker-pdf-fallos",
            "worker-pdf-fallos",
            self._m(NS_CONSTANCIAS, "solicitudes_render_fallidas"),
        )
        self._crear(
            "error-descifrado", "error-descifrado", self._m(NS_SEGURIDAD, "error_descifrado")
        )

    def _alarmas_rds(self) -> None:
        dims = {"DBInstanceIdentifier": self.instancia_bd_id}
        cpu = UMBRALES["rds-cpu"]
        self._crear(
            "rds-cpu",
            "rds-cpu",
            self._m(
                "AWS/RDS", "CPUUtilization", dims, estadistica="Average", minutos=cpu.periodo_min
            ),
        )
        con = UMBRALES["rds-conexiones"]
        maximo = MAX_CONEXIONES_RDS[self.clase_rds]
        self._crear(
            "rds-conexiones",
            "rds-conexiones",
            self._m(
                "AWS/RDS",
                "DatabaseConnections",
                dims,
                estadistica="Maximum",
                minutos=con.periodo_min,
            ),
            valor=con.valor * maximo,
            detalle=f" (máximo estimado {maximo} en {self.clase_rds})",
        )
        alm = UMBRALES["rds-almacenamiento"]
        total_bytes = self.almacenamiento_gb * 2**30
        self._crear(
            "rds-almacenamiento",
            "rds-almacenamiento",
            self._m(
                "AWS/RDS",
                "FreeStorageSpace",
                dims,
                estadistica="Minimum",
                minutos=alm.periodo_min,
            ),
            comparacion=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            valor=alm.valor * total_bytes,
            detalle=f" (de {self.almacenamiento_gb} GB asignados)",
        )
        # La conmutación no es una métrica sino un evento de RDS: una regla de EventBridge hacia el
        # mismo tema (categoría failover). RDS-EVENT-0013/0015/0034/0049/0050 son sus códigos.
        u = UMBRALES["rds-conmutacion"]
        regla = events.Rule(
            self,
            "Alarma-rds-conmutacion",
            rule_name=f"cc-{self.env_nombre}-rds-conmutacion",
            description=(
                f"[POR CONFIRMAR, PQ-20] {u.descripcion}. Severidad: {u.severidad}. "
                f"Runbook: {CARPETA_RUNBOOKS}/{u.runbook}"
            ),
            event_pattern=events.EventPattern(
                source=["aws.rds"],
                detail_type=["RDS DB Instance Event"],
                detail={
                    "EventCategories": ["failover"],
                    "SourceIdentifier": [self.instancia_bd_id],
                },
            ),
            targets=[targets.SnsTopic(self.tema)],
        )
        self.regla_conmutacion = regla

    def _alarmas_plataforma(self) -> None:
        env = self.env_nombre
        self._crear(
            "programadas-atrasadas",
            "programadas-atrasadas",
            self._m(NS_NOTIFICACIONES, "programadas_atrasadas", estadistica="Maximum"),
        )
        self._crear(
            "cognito-pre-token-errores",
            "cognito-pre-token-errores",
            self._m("AWS/Lambda", "Errors", {"FunctionName": f"cc-{env}-cognito-pre-token"}),
        )
        # Métrica de reputación de la cuenta (SES): se publica por hora.
        s = UMBRALES["ses-rebotes"]
        self._crear(
            "ses-rebotes",
            "ses-rebotes",
            self._m(
                "AWS/SES", "Reputation.BounceRate", estadistica="Maximum", minutos=s.periodo_min
            ),
        )

    def _alarmas_servicios(self) -> None:
        for servicio in SERVICIOS:
            dims = {"LoadBalancer": self.alb, "TargetGroup": self.grupos[servicio]}
            cinco = UMBRALES["5xx"]
            tasa = cloudwatch.MathExpression(
                expression=(
                    f"IF(solicitudes >= {_MINIMO_SOLICITUDES_5XX}, 100 * errores / solicitudes, 0)"
                ),
                using_metrics={
                    "errores": self._m(
                        "AWS/ApplicationELB",
                        "HTTPCode_Target_5XX_Count",
                        dims,
                        minutos=cinco.periodo_min,
                    ),
                    "solicitudes": self._m(
                        "AWS/ApplicationELB", "RequestCount", dims, minutos=cinco.periodo_min
                    ),
                },
                period=cdk.Duration.minutes(cinco.periodo_min),
                label=f"% 5xx de {servicio}",
            )
            self._crear(f"5xx-{servicio}", "5xx", tasa, detalle=f" ({servicio})")
            lat = UMBRALES["latencia"]
            self._crear(
                f"latencia-{servicio}",
                "latencia",
                self._m(
                    "AWS/ApplicationELB",
                    "TargetResponseTime",
                    dims,
                    estadistica="p95",
                    minutos=lat.periodo_min,
                ),
                detalle=f" ({servicio})",
            )

    # ------------------------------------------------------------------------ paneles
    def _grafica(self, titulo: str, izq, ancho: int = 12, alto: int = 6, **kw):
        return cloudwatch.GraphWidget(title=titulo, left=izq, width=ancho, height=alto, **kw)

    def _panel_operacion(self) -> list[cloudwatch.IWidget]:
        p50 = cdk.Duration.minutes(5)
        latencia = []
        errores = []
        for s in SERVICIOS:
            dims = {"LoadBalancer": self.alb, "TargetGroup": self.grupos[s]}
            for est in ("p50", "p95"):
                latencia.append(
                    cloudwatch.Metric(
                        namespace="AWS/ApplicationELB",
                        metric_name="TargetResponseTime",
                        dimensions_map=dims,
                        statistic=est,
                        period=p50,
                        label=f"{s} {est}",
                    )
                )
            errores.append(
                cloudwatch.Metric(
                    namespace="AWS/ApplicationELB",
                    metric_name="HTTPCode_Target_5XX_Count",
                    dimensions_map=dims,
                    statistic="Sum",
                    period=p50,
                    label=s,
                )
            )
        api = {"ApiId": self.api_id}
        return [
            cloudwatch.TextWidget(
                markdown="# Operación\nLatencia p50/p95 y 5xx por servicio (§15.2)",
                width=24,
                height=1,
            ),
            self._grafica("Latencia por servicio (s)", latencia, 12),
            self._grafica("Errores 5xx por servicio", errores, 12, stacked=True),
            self._grafica(
                "API Gateway: solicitudes y errores",
                [
                    self._m("AWS/ApiGateway", "Count", api, minutos=5),
                    self._m("AWS/ApiGateway", "4xx", api, minutos=5),
                    self._m("AWS/ApiGateway", "5xx", api, minutos=5),
                ],
                24,
            ),
        ]

    def _panel_colas(self) -> list[cloudwatch.IWidget]:
        env = self.env_nombre
        colas = [f"{c.nombre}{'.fifo' if c.fifo else ''}" for c in COLAS]
        dlqs = [
            (c.nombre, nombre_dlq(env, f"{c.nombre}{'.fifo' if c.fifo else ''}")) for c in COLAS
        ]
        p = cdk.Duration.minutes(1)
        return [
            cloudwatch.TextWidget(
                markdown="# Colas\nProfundidad, edad del mensaje más antiguo y DLQ",
                width=24,
                height=1,
            ),
            self._grafica(
                "Profundidad",
                [
                    cloudwatch.Metric(
                        namespace="AWS/SQS",
                        metric_name="ApproximateNumberOfMessagesVisible",
                        dimensions_map={"QueueName": nombre_cola(env, c)},
                        statistic="Maximum",
                        period=p,
                        label=c,
                    )
                    for c in colas
                ],
                12,
            ),
            self._grafica(
                "Edad del mensaje más antiguo (s)",
                [
                    cloudwatch.Metric(
                        namespace="AWS/SQS",
                        metric_name="ApproximateAgeOfOldestMessage",
                        dimensions_map={"QueueName": nombre_cola(env, c)},
                        statistic="Maximum",
                        period=p,
                        label=c,
                    )
                    for c in colas
                ],
                12,
            ),
            self._grafica(
                "Mensajes en DLQ",
                [
                    cloudwatch.Metric(
                        namespace="AWS/SQS",
                        metric_name="ApproximateNumberOfMessagesVisible",
                        dimensions_map={"QueueName": nombre},
                        statistic="Maximum",
                        period=p,
                        label=corto,
                    )
                    for corto, nombre in dlqs
                ],
                24,
            ),
        ]

    def _panel_whatsapp(self) -> list[cloudwatch.IWidget]:
        def serie(nombres: tuple[str, ...], espacio: str = NS_WHATSAPP):
            return [self._m(espacio, n, minutos=5) for n in nombres]

        return [
            cloudwatch.TextWidget(
                markdown="# WhatsApp\nEnvíos, fallos, ventana cerrada y estados", width=24, height=1
            ),
            self._grafica("Envíos", serie(("envios_ok", "envios_fallidos", "ventana_cerrada")), 12),
            self._grafica(
                "Webhook y estados",
                serie(
                    (
                        "webhook_mensajes_encolados",
                        "webhook_firma_invalida",
                        "estados_procesados",
                        "estados_desconocidos",
                    )
                ),
                12,
            ),
        ]

    def _panel_constancias(self) -> list[cloudwatch.IWidget]:
        env = self.env_nombre
        p = cdk.Duration.minutes(5)
        return [
            cloudwatch.TextWidget(
                markdown="# Constancias\nDuración del PDF, solicitudes fallidas y folios",
                width=24,
                height=1,
            ),
            self._grafica(
                "Duración de generación del PDF (ms)",
                [
                    cloudwatch.Metric(
                        namespace=NS_CONSTANCIAS,
                        metric_name="duracion_generacion_ms",
                        statistic=est,
                        period=p,
                        label=est,
                    )
                    for est in ("p50", "p95")
                ],
                12,
            ),
            self._grafica(
                "Solicitudes fallidas y folios",
                [
                    self._m(NS_CONSTANCIAS, "solicitudes_render_fallidas"),
                    self._m(NS_CONSTANCIAS, "folios_emitidos"),
                ],
                12,
            ),
            self._grafica(
                "worker-pdf: CPU y memoria (%)",
                [
                    cloudwatch.Metric(
                        namespace="AWS/ECS",
                        metric_name=nombre,
                        dimensions_map={
                            "ClusterName": f"cc-{env}",
                            "ServiceName": f"cc-{env}-worker-pdf",
                        },
                        statistic="Average",
                        period=p,
                    )
                    for nombre in ("CPUUtilization", "MemoryUtilization")
                ],
                24,
            ),
        ]

    def _panel_bd(self) -> list[cloudwatch.IWidget]:
        dims = {"DBInstanceIdentifier": self.instancia_bd_id}
        p = cdk.Duration.minutes(5)

        def metrica(nombre: str, est: str = "Average"):
            return cloudwatch.Metric(
                namespace="AWS/RDS",
                metric_name=nombre,
                dimensions_map=dims,
                statistic=est,
                period=p,
            )

        return [
            cloudwatch.TextWidget(
                markdown="# Base de datos\nCPU, conexiones, almacenamiento y operaciones",
                width=24,
                height=1,
            ),
            self._grafica("CPU (%)", [metrica("CPUUtilization")], 8),
            self._grafica("Conexiones", [metrica("DatabaseConnections", "Maximum")], 8),
            self._grafica(
                "Almacenamiento y memoria libres (bytes)",
                [metrica("FreeStorageSpace", "Minimum"), metrica("FreeableMemory", "Minimum")],
                8,
            ),
            self._grafica("Operaciones de disco", [metrica("ReadIOPS"), metrica("WriteIOPS")], 24),
        ]

    def _paneles(self) -> None:
        env = self.env_nombre
        if self.es_prod:
            grupos = {
                "operacion": self._panel_operacion,
                "colas": self._panel_colas,
                "whatsapp": self._panel_whatsapp,
                "constancias": self._panel_constancias,
                "base-de-datos": self._panel_bd,
            }
        else:
            # Tres paneles gratuitos: cada uno por debajo de 50 métricas.
            grupos = {
                "operacion": lambda: self._panel_operacion() + self._panel_bd(),
                "colas-whatsapp": lambda: self._panel_colas() + self._panel_whatsapp(),
                "constancias": self._panel_constancias,
            }
        for nombre, construir in grupos.items():
            panel = cloudwatch.Dashboard(
                self,
                f"Panel-{nombre}",
                dashboard_name=f"cc-{env}-{nombre}",
                default_interval=cdk.Duration.hours(3),
                period_override=cloudwatch.PeriodOverride.AUTO,
            )
            panel.add_widgets(*construir())
            self.paneles[f"cc-{env}-{nombre}"] = panel

    # ------------------------------------------------------------------------ CloudTrail
    def _cloudtrail(self, env: str, llave: kms.IKey, ret) -> None:
        self.bucket_trail = s3.Bucket(
            self,
            "BucketCloudTrail",
            bucket_name=f"cc-{env}-{self.account}-cloudtrail",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=llave,
            bucket_key_enabled=True,
            enforce_ssl=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="retencion-cloudtrail",
                    expiration=cdk.Duration.days(RETENCION_CLOUDTRAIL_DIAS),
                    noncurrent_version_expiration=cdk.Duration.days(30),
                    abort_incomplete_multipart_upload_after=cdk.Duration.days(1),
                )
            ],
            removal_policy=ret.removal_policy,
            auto_delete_objects=ret.auto_borrar_objetos,
        )
        reconocer(
            self.bucket_trail,
            "AwsSolutions-S1",
            "Es el destino de los archivos de CloudTrail: su propio registro de acceso agregaría "
            "un bucket más sin valor (CloudTrail ya audita las llamadas a la API de S3). El "
            "registro de datos de S3 no se activa por costo.",
        )
        self.trail = cloudtrail.Trail(
            self,
            "Trail",
            trail_name=f"cc-{env}-gestion",
            bucket=self.bucket_trail,
            encryption_key=llave,
            enable_file_validation=True,
            include_global_service_events=True,
            is_multi_region_trail=True,
            management_events=cloudtrail.ReadWriteType.ALL,
            send_to_cloud_watch_logs=False,
        )
        cdk.CfnOutput(self, "TrailArn", value=self.trail.trail_arn)
