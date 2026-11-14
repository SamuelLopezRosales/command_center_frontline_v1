"""Acceso a PostgreSQL: motor, transacciones con ``app.empresa_id`` y reintentos (design.md §2.1,
§3.1, §8.2; CC-REQ-150).

- Cada transacción fija ``app.empresa_id`` con ``set_config(..., true)``: el valor dura solo la
  transacción, lo que lo hace seguro con agrupadores de conexiones (y con RDS Proxy).
- Las políticas RLS de cada tabla usan ese valor; la aplicación además filtra por empresa.
- El host es configurable: instancia directa (``test``, cambio B) o RDS Proxy (``prod``).
- Se reintenta hasta 3 veces ante ``serialization_failure`` y ``deadlock_detected``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from urllib.parse import quote_plus

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from cc_common.config import Configuracion

ESTADOS_REINTENTABLES = frozenset({"40001", "40P01"})


def url_postgres(cfg: Configuracion, usuario: str, contrasena: str) -> str:
    return (
        f"postgresql+asyncpg://{quote_plus(usuario)}:{quote_plus(contrasena)}"
        f"@{cfg.db_host}:{cfg.db_puerto}/{cfg.db_nombre}"
    )


def crear_motor(
    url: str, *, tamano: int = 5, desborde: int = 5, ssl: bool = False, eco: bool = False
) -> AsyncEngine:
    argumentos = {"ssl": "require"} if ssl else {}
    return create_async_engine(
        url,
        pool_size=tamano,
        max_overflow=desborde,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=eco,
        connect_args=argumentos,
    )


@asynccontextmanager
async def transaccion(motor: AsyncEngine, empresa_id: int | None) -> AsyncIterator[AsyncConnection]:
    """Abre una transacción y fija la empresa para RLS. ``None`` solo para tareas de sistema
    que no leen datos por empresa (por ejemplo, migraciones o el relay del outbox)."""
    async with motor.begin() as conn:
        if empresa_id is not None:
            if not isinstance(empresa_id, int) or empresa_id <= 0:
                raise ValueError("empresa_id inválido")
            await conn.execute(
                text("SELECT set_config('app.empresa_id', :e, true)"), {"e": str(empresa_id)}
            )
        yield conn


def _sqlstate(exc: BaseException) -> str | None:
    for candidato in (exc, getattr(exc, "orig", None), getattr(exc, "__cause__", None)):
        if candidato is None:
            continue
        estado = getattr(candidato, "sqlstate", None) or getattr(candidato, "pgcode", None)
        if estado:
            return str(estado)
        causa = getattr(candidato, "__cause__", None)
        estado = getattr(causa, "sqlstate", None) if causa else None
        if estado:
            return str(estado)
    return None


async def con_reintento[T](
    operacion: Callable[[], Awaitable[T]], *, intentos: int = 3, espera_s: float = 0.05
) -> T:
    """Ejecuta ``operacion`` (que abre su propia transacción) con reintento por conflicto."""
    for intento in range(1, intentos + 1):
        try:
            return await operacion()
        except DBAPIError as exc:
            if _sqlstate(exc) not in ESTADOS_REINTENTABLES or intento == intentos:
                raise
            await asyncio.sleep(espera_s * intento)
    raise RuntimeError("inalcanzable")  # pragma: no cover
