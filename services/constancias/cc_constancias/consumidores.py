"""Consumidor de eventos de ``constancias`` (cola ``ev-constancias``; design.md §3.8).

- ``campo.actualizado``: recalcula las alertas de campos vacíos de las plantillas de la empresa.
  Recalcular es idempotente, así que repetir el evento solo repite el cálculo.

``wa.mensaje_estado`` (confirmación de entrega) lo agrega la tarea del conector de WhatsApp.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

from cc_common.tareas import consumidor_sqs

from cc_constancias.workers.alertas_plantilla import recalcular

log = logging.getLogger("cc.consumidores")

CAMPO_ACTUALIZADO = "campo.actualizado"


async def manejar_evento(motor, almacen, campos, colaboradores, evento: dict[str, Any]) -> bool:
    """Devuelve ``True`` si el evento tuvo efecto (no era de otro tipo)."""
    if evento.get("tipo") != CAMPO_ACTUALIZADO:
        log.info("evento ignorado")
        return False
    await recalcular(motor, almacen, campos, colaboradores, int(evento["empresa_id"]))
    return True


async def ejecutar(app: Any, parar: asyncio.Event) -> None:
    """Lee ``ev-constancias`` hasta que ``parar`` se active."""
    import boto3

    from cc_constancias import dependencias as dep

    cfg = app.state.config
    sqs = boto3.client("sqs", region_name=cfg.region, endpoint_url=cfg.aws_endpoint or None)
    peticion = SimpleNamespace(app=app)

    async def manejador(evento: dict[str, Any]) -> None:
        await manejar_evento(
            app.state.motor,
            dep.almacen(peticion),
            dep.campos(peticion),
            dep.colaboradores(peticion),
            evento,
        )

    await consumidor_sqs(sqs, cfg.cola_eventos_url, manejador, parar)
