"""Evento ``campo.actualizado`` (design.md §3.8): se escribe en el ``outbox`` dentro de la misma
transacción del cambio; el relay lo publica en EventBridge. ``colaboradores`` y ``constancias``
invalidan su caché de definiciones y recalculan alertas al recibirlo."""

from __future__ import annotations

from typing import Any

from cc_common import outbox

TIPO = "campo.actualizado"


async def publicar(conn, cfg: Any, empresa_id: int, campo_id: int | None, accion: str) -> None:
    await outbox.escribir(
        conn,
        "campos",
        destino_tipo="EVENTBRIDGE",
        destino=cfg.bus_eventos,
        tipo=TIPO,
        payload={"empresa_id": empresa_id, "campo_id": campo_id, "accion": accion},
        empresa_id=empresa_id,
    )
