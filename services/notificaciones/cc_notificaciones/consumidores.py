"""Consumidor de eventos de ``notificaciones`` (cola ``ev-notificaciones``; design.md §3.8).

Tipos que atiende (design.md §3.8):

- ``wa.plantilla_estado``: aprobación o rechazo de plantillas de Meta (T-216).
- ``wa.mensaje_estado``: estado de entrega de un mensaje de notificación; ``estado_service`` hace
  avanzar al destinatario y cierra la notificación (T-217). Los de otro ``origen_tipo`` se ignoran.
- ``wa.respuesta_recibida``: marca ``RESPONDIO`` y vincula la conversación (T-217).

``wa.numero_invalido`` **no** llega aquí: la regla de EventBridge lo entrega a ``ev-colaboradores``
(dueño de ``celular_invalido``). El consumidor no arranca por defecto (``CC_CONSUMIDOR_ACTIVO``). Un
tipo desconocido se **rechaza** (lanza ``EventoNoManejado``) en lugar de ignorarse, para que SQS lo
conserve y llegue a la DLQ si hay un error de enrutamiento.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from cc_common.tareas import consumidor_sqs

from cc_notificaciones.servicios import estado_service, plantillas

log = logging.getLogger("cc.consumidores")

PLANTILLA_ESTADO = "wa.plantilla_estado"
MENSAJE_ESTADO = "wa.mensaje_estado"
RESPUESTA_RECIBIDA = "wa.respuesta_recibida"


class EventoNoManejado(Exception):  # noqa: N818
    pass


async def manejar_evento(motor, evento: dict[str, Any]) -> bool:
    """``True`` si el evento tuvo efecto; lanza ``EventoNoManejado`` para un tipo desconocido."""
    tipo = evento.get("tipo")
    if tipo == PLANTILLA_ESTADO:
        return await plantillas.aplicar_evento(motor, evento) > 0
    if tipo == MENSAJE_ESTADO:
        return await estado_service.aplicar_mensaje_estado(motor, evento)
    if tipo == RESPUESTA_RECIBIDA:
        return await estado_service.aplicar_respuesta(motor, evento)
    raise EventoNoManejado(str(tipo))


async def ejecutar(app: Any, parar: asyncio.Event) -> None:
    """Lee ``ev-notificaciones`` hasta que ``parar`` se active."""
    import boto3

    cfg = app.state.config
    sqs = boto3.client("sqs", region_name=cfg.region, endpoint_url=cfg.aws_endpoint or None)

    async def manejador(evento: dict[str, Any]) -> None:
        await manejar_evento(app.state.motor, evento)

    await consumidor_sqs(sqs, cfg.cola_eventos_url, manejador, parar)
