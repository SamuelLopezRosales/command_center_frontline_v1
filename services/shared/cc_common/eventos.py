"""Consumo idempotente de eventos y mensajes (design.md §9.3; CC-NFR-007).

``procesar_una_vez`` registra el ``evento_id`` en ``{esquema}.evento_procesado`` dentro de la
misma transacción del efecto. Si el evento ya se procesó, el efecto no se ejecuta.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from cc_common.db import transaccion
from cc_common.outbox import esquema_valido


async def procesar_una_vez[T](
    motor: AsyncEngine,
    esquema: str,
    evento_id: uuid.UUID | str,
    efecto: Callable[[AsyncConnection], Awaitable[T]],
    *,
    empresa_id: int | None = None,
) -> tuple[bool, T | None]:
    """Devuelve ``(True, resultado)`` si se procesó ahora y ``(False, None)`` si ya estaba."""
    e = esquema_valido(esquema)
    async with transaccion(motor, empresa_id) as conn:
        r = await conn.execute(
            text(
                f"INSERT INTO {e}.evento_procesado (evento_id) VALUES (:id) "  # noqa: S608
                "ON CONFLICT (evento_id) DO NOTHING RETURNING evento_id"
            ),
            {"id": uuid.UUID(str(evento_id))},
        )
        if r.first() is None:
            return False, None
        return True, await efecto(conn)
