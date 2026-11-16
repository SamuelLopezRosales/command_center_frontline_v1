"""Repositorio de ``notificaciones.audiencia`` (design.md §2.2; CC-REQ-100, 101).

Una audiencia nunca se borra: ``activa = false`` la oculta. El nombre es único entre las activas
sin distinguir mayúsculas (índice ``audiencia_nombre_key``).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

COLUMNAS = "id, nombre, activa, criterios_json, creada_por_usuario_id, fecha_creacion"


def _fila(f: Any) -> dict[str, Any]:
    d = dict(f)
    if isinstance(d.get("criterios_json"), str):  # asyncpg entrega jsonb como texto
        d["criterios_json"] = json.loads(d["criterios_json"])
    return d


async def crear(
    conn: AsyncConnection,
    *,
    empresa_id: int,
    nombre: str,
    criterios: dict[str, Any],
    usuario_id: int,
) -> dict[str, Any]:
    r = await conn.execute(
        text(
            "INSERT INTO notificaciones.audiencia "  # noqa: S608
            "(empresa_id, nombre, criterios_json, creada_por_usuario_id) "
            f"VALUES (:e, :n, CAST(:c AS jsonb), :u) RETURNING {COLUMNAS}"
        ),
        {"e": empresa_id, "n": nombre, "c": json.dumps(criterios), "u": usuario_id},
    )
    return _fila(r.mappings().one())


async def obtener(
    conn: AsyncConnection, audiencia_id: int, *, bloquear: bool = False
) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM notificaciones.audiencia WHERE id = :id"  # noqa: S608
            + (" FOR UPDATE" if bloquear else "")
        ),
        {"id": audiencia_id},
    )
    fila = r.mappings().first()
    return _fila(fila) if fila else None


async def listar(
    conn: AsyncConnection, *, estado: str, despues_de: int | None, limite: int
) -> list[dict[str, Any]]:
    filtros = []
    if estado == "activas":
        filtros.append("activa")
    elif estado == "inactivas":
        filtros.append("NOT activa")
    params: dict[str, Any] = {"lim": limite}
    if despues_de is not None:
        filtros.append("id < :despues")
        params["despues"] = despues_de
    donde = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM notificaciones.audiencia {donde} "  # noqa: S608
            "ORDER BY id DESC LIMIT :lim"
        ),
        params,
    )
    return [_fila(f) for f in r.mappings().all()]


async def actualizar(
    conn: AsyncConnection, audiencia_id: int, cambios: dict[str, Any]
) -> dict[str, Any]:
    """``cambios`` solo puede traer ``nombre``, ``criterios_json`` y ``activa``."""
    asignaciones = []
    params: dict[str, Any] = {"id": audiencia_id}
    if "nombre" in cambios:
        asignaciones.append("nombre = :nombre")
        params["nombre"] = cambios["nombre"]
    if "criterios_json" in cambios:
        asignaciones.append("criterios_json = CAST(:criterios AS jsonb)")
        params["criterios"] = json.dumps(cambios["criterios_json"])
    if "activa" in cambios:
        asignaciones.append("activa = :activa")
        params["activa"] = cambios["activa"]
    r = await conn.execute(
        text(
            f"UPDATE notificaciones.audiencia SET {', '.join(asignaciones)} "  # noqa: S608
            f"WHERE id = :id RETURNING {COLUMNAS}"
        ),
        params,
    )
    return _fila(r.mappings().one())
