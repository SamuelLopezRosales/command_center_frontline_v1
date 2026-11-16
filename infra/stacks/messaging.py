"""Stack CcMessaging: colas, bus de eventos, Scheduler, tema SNS y SES (design.md §4.1, §13.5).

- Colas SQS de §4.1, cada una con su cola de mensajes fallidos (DLQ, retención de 14 días),
  retención de 4 días, cifrado con la llave ``cc-{env}-infra`` y TLS obligatorio.
- Bus ``cc-{env}-eventos`` con archivo de 7 días y una regla por evento hacia las colas ``ev-*``.
- Grupo de Scheduler ``cc-{env}-envios`` y el rol que EventBridge Scheduler asume para escribir en
  ``notif-despacho`` y ``notif-respaldo``.
- Tema SNS ``alertas-rh`` cifrado. Las suscripciones dependen del canal elegido (PQ-17) y no se
  crean aquí.
- SES: identidad por correo y conjunto de configuración con eventos de rebote y queja hacia el tema
  ``ses-eventos``, al que se suscribe la cola ``notif-respaldo`` (la Lambda ``respaldo-correo``
  desenvuelve el sobre de SNS, design.md §4.5). Es un tema aparte de ``alertas-rh``: ese lo leen
  personas de RH y no debe recibir el JSON crudo de SES (T-224). La identidad de dominio con DKIM
  queda para cuando haya dominio (PQ-22).

Las alarmas de DLQ (CC-NFR-010) se crean en ``CcObservability``.

La llave se importa por ARN para no crear una dependencia circular con ``CcSecurity`` (los
permisos de uso van en los roles). Para que los servicios de AWS que no usan un rol (EventBridge
hacia las colas, SES y CloudWatch hacia SNS) puedan usar la llave, su política debe nombrarlos:
ver ``SecurityStack``.
"""

from __future__ import annotations

from dataclasses import dataclass

import aws_cdk as cdk
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_ses as ses
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from aws_cdk import aws_sqs as sqs

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs.nag import reconocer
from infra.constructs.retencion import politica_retencion


@dataclass(frozen=True)
class DefCola:
    nombre: str
    visibilidad_s: int
    max_recepciones: int
    fifo: bool = False


# design.md §4.1. ``cola-pdf``: 3 recepciones es un valor por confirmar (PQ-20).
COLAS: tuple[DefCola, ...] = (
    DefCola("cola-pdf", 180, 3),
    DefCola("cola-cargas", 900, 2),
    DefCola("wa-entrada", 60, 5, fifo=True),
    DefCola("wa-salida", 180, 3, fifo=True),
    DefCola("wa-estados", 180, 5),
    DefCola("notif-despacho", 1800, 3),
    DefCola("notif-respaldo", 360, 3),
    DefCola("ev-colaboradores", 120, 5),
    DefCola("ev-constancias", 120, 5),
    DefCola("ev-notificaciones", 120, 5),
)

# Evento (detail-type que publica el outbox) -> colas ``ev-*`` que lo consumen (§3.8).
RUTAS_EVENTOS: dict[str, tuple[str, ...]] = {
    "campo.actualizado": ("ev-colaboradores", "ev-constancias"),
    "wa.mensaje_estado": ("ev-constancias", "ev-notificaciones"),
    "wa.respuesta_recibida": ("ev-notificaciones",),
    "wa.plantilla_estado": ("ev-notificaciones",),
    "wa.numero_invalido": ("ev-colaboradores",),
}

RETENCION_COLA = cdk.Duration.days(4)
RETENCION_DLQ = cdk.Duration.days(14)
RETENCION_ARCHIVO_EVENTOS_DIAS = 7


class MessagingStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        id_: str,
        *,
        ambiente: Ambiente,
        llave_infra: kms.IKey,
        **kwargs,
    ) -> None:
        super().__init__(scope, id_, **kwargs)
        env = ambiente.nombre
        ret = politica_retencion(ambiente)
        llave = kms.Key.from_key_arn(self, "LlaveInfraImportada", llave_infra.key_arn)

        self.colas: dict[str, sqs.Queue] = {}
        self.dlqs: dict[str, sqs.Queue] = {}
        for d in COLAS:
            sufijo = ".fifo" if d.fifo else ""
            dlq = sqs.Queue(
                self,
                f"Dlq-{d.nombre}",
                queue_name=f"cc-{env}-{d.nombre}-dlq{sufijo}",
                fifo=d.fifo or None,
                retention_period=RETENCION_DLQ,
                encryption=sqs.QueueEncryption.KMS,
                encryption_master_key=llave,
                enforce_ssl=True,
                removal_policy=ret.removal_policy,
            )
            cola = sqs.Queue(
                self,
                f"Cola-{d.nombre}",
                queue_name=f"cc-{env}-{d.nombre}{sufijo}",
                fifo=d.fifo or None,
                visibility_timeout=cdk.Duration.seconds(d.visibilidad_s),
                retention_period=RETENCION_COLA,
                encryption=sqs.QueueEncryption.KMS,
                encryption_master_key=llave,
                enforce_ssl=True,
                dead_letter_queue=sqs.DeadLetterQueue(
                    queue=dlq, max_receive_count=d.max_recepciones
                ),
                removal_policy=ret.removal_policy,
            )
            self.dlqs[d.nombre] = dlq
            self.colas[d.nombre] = cola

        self.bus = events.EventBus(self, "Bus", event_bus_name=f"cc-{env}-eventos")
        self.bus.archive(
            "Archivo",
            archive_name=f"cc-{env}-eventos",
            description="Archivo de eventos (solo identificadores) para reprocesar",
            event_pattern=events.EventPattern(account=[self.account]),
            retention=cdk.Duration.days(RETENCION_ARCHIVO_EVENTOS_DIAS),
        )
        self.bus.apply_removal_policy(ret.removal_policy)
        for evento, destinos in RUTAS_EVENTOS.items():
            regla = events.Rule(
                self,
                f"Regla-{evento.replace('.', '-').replace('_', '-')}",
                rule_name=f"cc-{env}-{evento.replace('.', '-').replace('_', '-')}",
                event_bus=self.bus,
                event_pattern=events.EventPattern(detail_type=[evento]),
                description=f"Entrega {evento} a {', '.join(destinos)}",
            )
            for destino in destinos:
                regla.add_target(targets.SqsQueue(self.colas[destino]))

        self.grupo_scheduler = scheduler.CfnScheduleGroup(
            self, "GrupoEnvios", name=f"cc-{env}-envios"
        )
        self.rol_scheduler = iam.Role(
            self,
            "RolScheduler",
            role_name=f"cc-{env}-scheduler-destino",
            description="Rol que EventBridge Scheduler asume para escribir en las colas de envío",
            assumed_by=iam.ServicePrincipal(
                "scheduler.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {
                        "aws:SourceArn": (
                            f"arn:{self.partition}:scheduler:{self.region}:{self.account}"
                            f":schedule/cc-{env}-envios/*"
                        )
                    },
                },
            ),
        )
        for nombre in ("notif-despacho", "notif-respaldo"):
            self.colas[nombre].grant_send_messages(self.rol_scheduler)

        for accion in ("kms:GenerateDataKey*", "kms:ReEncrypt*"):
            reconocer(
                self.rol_scheduler,
                f"AwsSolutions-IAM5[Action::{accion}]",
                f"{accion} es el conjunto de acciones que CDK concede para escribir en una cola "
                "cifrada; el recurso es únicamente la llave cc-{env}-infra, no un comodín.".replace(
                    "{env}", env
                ),
            )

        self.tema_alertas = sns.Topic(
            self,
            "AlertasRh",
            topic_name=f"cc-{env}-alertas-rh",
            display_name="Command Center: alertas para RH",
            master_key=llave,
            enforce_ssl=True,
        )

        correo = ambiente.presupuesto.correo  # remitente de prueba hasta tener dominio (PQ-22)
        self.conjunto_ses = ses.ConfigurationSet(
            self,
            "ConjuntoSes",
            configuration_set_name=f"cc-{env}-respaldo",
            reputation_metrics=True,
            sending_enabled=True,
            tls_policy=ses.ConfigurationSetTlsPolicy.REQUIRE,
        )
        # Tema de los eventos de SES: lo consume la cola ``notif-respaldo`` (rebotes y quejas).
        self.tema_ses = sns.Topic(
            self,
            "SesEventos",
            topic_name=f"cc-{env}-ses-eventos",
            display_name="Command Center: eventos de SES (rebotes y quejas)",
            master_key=llave,
            enforce_ssl=True,
        )
        self.tema_ses.add_subscription(
            subs.SqsSubscription(self.colas["notif-respaldo"], raw_message_delivery=False)
        )
        self.conjunto_ses.add_event_destination(
            "RebotesYQuejas",
            destination=ses.EventDestination.sns_topic(self.tema_ses),
            events=[ses.EmailSendingEvent.BOUNCE, ses.EmailSendingEvent.COMPLAINT],
        )
        self.identidad_ses = ses.EmailIdentity(
            self,
            "IdentidadCorreo",
            identity=ses.Identity.email(correo),
            configuration_set=self.conjunto_ses,
        )

        for nombre, cola in self.colas.items():
            cdk.CfnOutput(self, f"Url-{nombre}", value=cola.queue_url)
        cdk.CfnOutput(self, "BusEventos", value=self.bus.event_bus_name)
        cdk.CfnOutput(self, "TemaAlertasRh", value=self.tema_alertas.topic_arn)
        cdk.CfnOutput(self, "TemaSesEventos", value=self.tema_ses.topic_arn)
        cdk.CfnOutput(self, "GrupoSchedulerEnvios", value=self.grupo_scheduler.name or "")
        cdk.CfnOutput(self, "RolSchedulerArn", value=self.rol_scheduler.role_arn)
