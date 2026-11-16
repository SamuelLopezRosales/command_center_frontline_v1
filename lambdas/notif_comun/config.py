"""Configuración de las Lambdas de notificaciones (variables ``CC_*``)."""

from __future__ import annotations

from datetime import time
from functools import lru_cache

from cc_common.config import Configuracion


class ConfigNotifLambdas(Configuracion):
    servicio: str = "notificaciones"
    aws_endpoint: str | None = None  # LocalStack en local; vacío en AWS

    # Colas (URL en AWS, nombre en local)
    cola_salida_url: str = "wa-salida.fifo"
    cola_despacho_url: str = "notif-despacho"
    cola_respaldo_url: str = "notif-respaldo"

    # EventBridge Scheduler: ARN de las colas destino y rol que asume Scheduler.
    scheduler_despacho_arn: str | None = None
    scheduler_respaldo_arn: str | None = None
    scheduler_rol_arn: str | None = None
    scheduler_grupo: str = "default"

    # Alertas a RH (SNS ``alertas-rh``) y correo (SES).
    alertas_topic_arn: str | None = None
    ses_origen: str | None = None  # dirección verificada en SES
    ses_config_set: str | None = None  # conjunto de configuración (rebotes y quejas hacia SNS)
    ses_asunto: str = "Aviso de Recursos Humanos"

    # INT-COL-05 (`colaboradores`).
    colaboradores_url: str | None = None

    # Horario permitido (design.md §6.3; PQ-06): igual que el servicio `notificaciones`.
    horario_inicio: time = time(8, 0)
    horario_fin: time = time(20, 0)  # inclusivo

    # Despachador
    bloque_destinatarios: int = 500  # SELECT ... FOR UPDATE SKIP LOCKED
    margen_tiempo_ms: int = 60_000  # se corta con este margen antes del timeout de la Lambda
    max_intentos_mensaje: int = 3  # CC-REQ-111
    adelanto_tolerado_s: int = 60  # un INICIO antes de ``programada_para`` se ignora

    # Conciliador
    atraso_programada_min: int = 10
    atascado_min: int = 30
    reencolado_min: int = 30  # no se vuelve a reencolar antes de este tiempo (idempotencia)

    # Respaldo por correo
    respaldo_horas: int = 24
    respaldo_gracia_min: int = 10  # el conciliador actúa pasada la hora + esta gracia
    respaldo_bloque: int = 50


@lru_cache(maxsize=1)
def obtener() -> ConfigNotifLambdas:
    return ConfigNotifLambdas()
