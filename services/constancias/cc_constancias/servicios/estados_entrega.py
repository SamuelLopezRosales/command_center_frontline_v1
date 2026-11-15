"""Confirmación de entrega de la constancia (``wa.mensaje_estado``; design.md §3.8;
CC-REQ-084, 085).

``ENTREGADO`` o ``LEIDO`` pasan la constancia y su solicitud a ``ENTREGADA``. Un ``FALLIDO``
definitivo las pasa a ``FALLIDA`` y emite ``constancia.fallida`` (la regla de EventBridge lo lleva
a SNS para avisar a RH, CC-REQ-164). El evento no lleva datos personales: solo identificadores.

Es idempotente: repetir un evento o recibirlo fuera de orden no deja un estado peor. Una constancia
ya ``ENTREGADA`` no vuelve a ``FALLIDA``.
"""

from __future__ import annotations

import logging
from typing import Any

from cc_common.db import transaccion

from cc_constancias.repos import solicitudes as repo
from cc_constancias.servicios.solicitudes import registrar_fallo

log = logging.getLogger("cc.estados_entrega")

ORIGEN = "CONSTANCIA"
ENTREGADOS = frozenset({"ENTREGADO", "LEIDO"})
MOTIVO_ENTREGA_FALLIDA = "ENTREGA_FALLIDA"


async def aplicar(motor: Any, cfg: Any, evento: dict[str, Any]) -> bool:
    """Devuelve ``True`` si el evento cambió algo."""
    if evento.get("origen_tipo") != ORIGEN or evento.get("origen_id") is None:
        return False
    estado = evento.get("estado")
    constancia_id = int(evento["origen_id"])
    empresa_id = int(evento["empresa_id"])
    async with transaccion(motor, empresa_id) as conn:
        if estado in ENTREGADOS:
            c = await repo.marcar_entregada(conn, constancia_id)
            if c is None:
                return False
            await repo.cambiar_estado(
                conn, c["solicitud_id"], "ENTREGADA", desde=("GENERADA", "FALLIDA")
            )
            return True
        if estado == "FALLIDO":
            c = await repo.marcar_entrega_fallida(conn, constancia_id)
            if c is None:
                return False
            await registrar_fallo(
                conn,
                cfg,
                empresa_id=empresa_id,
                solicitud={"id": c["solicitud_id"], "colaborador_id": c["colaborador_id"]},
                motivo=MOTIVO_ENTREGA_FALLIDA,
                desde=("GENERADA",),
            )
            return True
    return False
