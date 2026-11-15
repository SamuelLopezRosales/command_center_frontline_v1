"""Consumidor de eventos de ``colaboradores`` (cola ``ev-colaboradores``; design.md §3.8).

- ``campo.actualizado``: invalida la caché de definiciones de la empresa para que el siguiente
  uso vuelva a pedirlas a `campos` (INT-CAM-01).

El evento se registra en ``colaboradores.evento_procesado`` en la misma transacción del efecto:
una repetición se ignora (CC-NFR-007). Invalidar es idempotente, así que registrarlo solo evita
trabajo repetido.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from cc_common.eventos import procesar_una_vez
from cc_common.tareas import consumidor_sqs

log = logging.getLogger("cc.consumidores")

CAMPO_ACTUALIZADO = "campo.actualizado"


async def manejar_evento(motor: Any, cache: Any, evento: dict[str, Any]) -> bool:
    """Devuelve ``True`` si el evento tuvo efecto (no era repetido ni desconocido)."""
    if evento.get("tipo") != CAMPO_ACTUALIZADO:
        log.info("evento ignorado")
        return False
    empresa_id = int(evento["empresa_id"])

    async def invalidar(_conn) -> None:
        cache.invalidar(empresa_id)

    if not evento.get("evento_id"):
        cache.invalidar(empresa_id)
        return True
    aplicado, _ = await procesar_una_vez(motor, "colaboradores", evento["evento_id"], invalidar)
    return aplicado


async def ejecutar(app: Any, parar: asyncio.Event) -> None:
    """Lee ``ev-colaboradores`` hasta que ``parar`` se active."""
    import boto3

    cfg = app.state.config
    sqs = boto3.client("sqs", region_name=cfg.region, endpoint_url=cfg.sqs_endpoint or None)

    async def manejador(evento: dict[str, Any]) -> None:
        from cc_colaboradores.dependencias import obtener_campos

        await manejar_evento(app.state.motor, obtener_campos(app), evento)

    await consumidor_sqs(sqs, cfg.cola_eventos_url, manejador, parar)
