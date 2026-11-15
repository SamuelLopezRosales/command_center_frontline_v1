"""Mensajes del bot hacia ``wa-salida.fifo`` (design.md §4.1, §4.3).

Se escriben en el ``outbox`` en la misma transacción que el cambio de la conversación: si algo
falla, ni el cambio ni el mensaje existen, y la repetición del mensaje de entrada lo rehace. Cada
respuesta lleva el ``wa_id`` de quien escribió (el bot responde a un mensaje reciente) y
``entrante_at``, para que el `enviador` calcule la ventana de 24 horas aun si no hay conversación.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from cc_common import outbox
from sqlalchemy.ext.asyncio import AsyncConnection

from cc_whatsapp.normalizacion import grupo_de

RECHAZO_BOT = "RECHAZO_BOT"


async def enviar(
    conn: AsyncConnection,
    cfg,
    *,
    wa_id: str,
    conversacion_id: int | None = None,
    colaborador_id: int | None = None,
    texto: str | None = None,
    interactivo: dict[str, Any] | None = None,
    proposito: str = "BOT",
    origen_tipo: str = "BOT",
) -> str:
    """Encola un mensaje de salida. ``proposito = RECHAZO_BOT`` marca la respuesta fija a quien no
    es elegible (no resuelve contacto; solo sale dentro de la ventana)."""
    mensaje_uuid = str(uuid.uuid4())
    cuerpo = {
        "mensaje_uuid": mensaje_uuid,
        "origen_tipo": origen_tipo,
        "origen_id": conversacion_id,
        "colaborador_id": colaborador_id,
        "conversacion_id": conversacion_id,
        "wa_id": wa_id,
        "tipo": "INTERACTIVO" if interactivo else "TEXTO",
        "texto": texto,
        "interactivo": interactivo,
        "proposito": proposito,
        "max_intentos": 3,
        "empresa_id": cfg.empresa_id,
        "entrante_at": datetime.now(UTC).isoformat(),
    }
    await outbox.escribir(
        conn,
        "whatsapp",
        destino_tipo="SQS",
        destino=cfg.cola_salida_url,
        tipo="mensaje_salida",
        payload=cuerpo,
        empresa_id=cfg.empresa_id,
        grupo=grupo_de(wa_id),
        deduplicacion=mensaje_uuid,
    )
    return mensaje_uuid
