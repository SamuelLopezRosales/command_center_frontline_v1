"""Repositorio de ``campos.opcion_campo`` (design.md §2.2).

El ``valor`` de una opción no cambia (lo impide un trigger) y una opción no se borra: se desactiva
y los valores históricos que la usan se conservan (CC-REQ-047, 050).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

COLUMNAS = "id, campo_id, etiqueta, valor, descripcion, orden, activo"
EDITABLES = frozenset({"etiqueta", "descripcion", "orden", "activo"})


async def listar(conn: AsyncConnection, campo_id: int) -> list[dict[str, Any]]:
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM campos.opcion_campo "  # noqa: S608
            "WHERE campo_id = :c ORDER BY orden, id"
        ),
        {"c": campo_id},
    )
    return [dict(f) for f in r.mappings().all()]


async def obtener(conn: AsyncConnection, campo_id: int, opcion_id: int) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM campos.opcion_campo "  # noqa: S608
            "WHERE campo_id = :c AND id = :id"
        ),
        {"c": campo_id, "id": opcion_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def crear(
    conn: AsyncConnection, *, empresa_id: int, campo_id: int, datos: dict[str, Any]
) -> int:
    r = await conn.execute(
        text(
            "INSERT INTO campos.opcion_campo (empresa_id, campo_id, etiqueta, valor, descripcion, "
            "orden) VALUES (:e, :c, :etiqueta, :valor, :descripcion, :orden) RETURNING id"
        ),
        {
            "e": empresa_id,
            "c": campo_id,
            "etiqueta": datos["etiqueta"],
            "valor": datos["valor"],
            "descripcion": datos.get("descripcion"),
            "orden": datos["orden"],
        },
    )
    return int(r.scalar_one())


async def siguiente_orden(conn: AsyncConnection, campo_id: int) -> int:
    r = await conn.execute(
        text("SELECT coalesce(max(orden), 0) + 1 FROM campos.opcion_campo WHERE campo_id = :c"),
        {"c": campo_id},
    )
    return int(r.scalar_one())


async def actualizar(conn: AsyncConnection, opcion_id: int, cambios: dict[str, Any]) -> None:
    columnas = [c for c in cambios if c in EDITABLES]
    if not columnas:
        return
    asignaciones = ", ".join(f"{c} = :{c}" for c in columnas)  # nombres de una lista fija
    await conn.execute(
        text(f"UPDATE campos.opcion_campo SET {asignaciones} WHERE id = :id"),  # noqa: S608
        {"id": opcion_id, **{c: cambios[c] for c in columnas}},
    )
