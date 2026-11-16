"""Consumidor de eventos de ``colaboradores`` (cola ``ev-colaboradores``; design.md §3.8).

- ``campo.actualizado``: invalida la caché de definiciones de la empresa para que el siguiente
  uso vuelva a pedirlas a `campos` (INT-CAM-01).
- ``wa.numero_invalido`` (``{colaborador_id, empresa_id}``; lo emiten ``estados-entrega`` y el
  ``enviador`` cuando Meta rechaza el número como inexistente, CC-REQ-118): marca
  ``celular_invalido`` del colaborador. Desde entonces ``contactos:resolver`` lo trata como no
  elegible por WhatsApp (``CELULAR_INVALIDO``), el embudo lo excluye (``SIN_CELULAR_VALIDO``) y
  NOT-22 no lo reintenta. Cambiar el celular lo limpia (``repos.colaborador.cambiar_celular``).
  Es idempotente (solo cambia si estaba en falso) y deja una ``MODIFICACION`` de origen ``SISTEMA``
  con el nombre del campo, sin valores. Un colaborador que no existe en la empresa no cambia nada
  (la RLS lo oculta).

El evento se registra en ``colaboradores.evento_procesado`` en la misma transacción del efecto:
una repetición se ignora (CC-NFR-007). Invalidar es idempotente, así que registrarlo solo evita
trabajo repetido.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from cc_common import bitacora
from cc_common.db import transaccion
from cc_common.eventos import procesar_una_vez
from cc_common.tareas import consumidor_sqs
from sqlalchemy import text

log = logging.getLogger("cc.consumidores")

CAMPO_ACTUALIZADO = "campo.actualizado"
NUMERO_INVALIDO = "wa.numero_invalido"


async def _marcar_celular_invalido(motor: Any, evento: dict[str, Any]) -> bool:
    try:
        empresa_id = int(evento["empresa_id"])
        colaborador_id = int(evento["colaborador_id"])
    except (KeyError, TypeError, ValueError):
        log.info("número inválido sin efecto: evento incompleto")
        return False

    async def efecto(conn) -> bool:
        r = await conn.execute(
            text(
                "UPDATE colaboradores.colaborador SET celular_invalido = true, "
                "fecha_modificacion = now() WHERE id = :id AND NOT celular_invalido"
            ),
            {"id": colaborador_id},
        )
        if not r.rowcount:
            return False
        await bitacora.registrar(
            conn,
            empresa_id=empresa_id,
            accion="MODIFICACION",
            entidad="colaborador",
            entidad_id=colaborador_id,
            colaborador_id=colaborador_id,
            origen="SISTEMA",
            detalle={"campos": ["celular_invalido"]},
        )
        log.info("colaborador %s: celular marcado como inválido", colaborador_id)
        return True

    if evento.get("evento_id"):
        aplicado, cambio = await procesar_una_vez(
            motor, "colaboradores", evento["evento_id"], efecto, empresa_id=empresa_id
        )
        return bool(aplicado and cambio)
    async with transaccion(motor, empresa_id) as conn:
        return await efecto(conn)


async def manejar_evento(motor: Any, cache: Any, evento: dict[str, Any]) -> bool:
    """Devuelve ``True`` si el evento tuvo efecto (no era repetido ni desconocido)."""
    if evento.get("tipo") == NUMERO_INVALIDO:
        return await _marcar_celular_invalido(motor, evento)
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
