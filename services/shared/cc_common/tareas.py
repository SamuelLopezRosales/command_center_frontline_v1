"""Tareas de fondo de cada servicio: ``relay-outbox`` y ``consumidor-eventos`` (WRK-04;
design.md §4.7, §9.3; CC-NFR-007).

Corren dentro del proceso de la API (lifespan). Terminan cuando ``parar`` se activa; un mensaje en
curso se completa antes de salir. Un fallo en un ciclo se registra y no mata la tarea.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from cc_common.outbox import Publicador, publicar_pendientes

log = logging.getLogger("cc.tareas")

Manejador = Callable[[dict[str, Any]], Awaitable[None]]


async def relay_outbox(
    motor: Any,
    esquema: str,
    publicador: Publicador,
    parar: asyncio.Event,
    *,
    intervalo_s: float = 1.0,
    lote: int = 50,
) -> None:
    """Publica los mensajes pendientes del ``outbox`` cada ``intervalo_s`` (un lote tras otro
    mientras haya trabajo)."""
    while not parar.is_set():
        try:
            publicados = await publicar_pendientes(motor, esquema, publicador, lote=lote)
        except Exception:
            log.exception("falló un ciclo del relay-outbox")
            publicados = 0
        if publicados >= lote:
            continue
        try:
            await asyncio.wait_for(parar.wait(), timeout=intervalo_s)
        except TimeoutError:
            pass


def cuerpo_de_evento(cuerpo: dict[str, Any]) -> dict[str, Any]:
    """El mensaje puede llegar como lo escribe ``publicador_aws`` (directo a SQS) o dentro del
    sobre de EventBridge (``detail-type`` y ``detail``): ambos se reducen a ``{evento_id, tipo,
    ...payload}``."""
    detalle = cuerpo.get("detail")
    if isinstance(detalle, str):
        detalle = json.loads(detalle)
    if isinstance(detalle, dict):
        return {"tipo": cuerpo.get("detail-type"), **detalle}
    return cuerpo


async def consumidor_sqs(
    sqs: Any,
    cola_url: str,
    manejador: Manejador,
    parar: asyncio.Event,
    *,
    espera_s: int = 20,
) -> None:
    """Lee la cola y llama a ``manejador`` por mensaje; el mensaje se borra solo si el manejador
    termina sin error (si falla, SQS lo reentrega y, pasadas las recepciones, va a la DLQ)."""
    while not parar.is_set():
        try:
            r = await asyncio.to_thread(
                sqs.receive_message,
                QueueUrl=cola_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=espera_s,
            )
        except Exception:
            log.exception("falló la lectura de la cola de eventos")
            await asyncio.sleep(2)
            continue
        for m in r.get("Messages", []):
            try:
                await manejador(cuerpo_de_evento(json.loads(m["Body"])))
            except Exception:
                log.exception("falló el procesamiento de un evento")
                continue
            await asyncio.to_thread(
                sqs.delete_message, QueueUrl=cola_url, ReceiptHandle=m["ReceiptHandle"]
            )
