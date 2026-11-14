"""Consulta de ``auditoria.bitacora``: filtros y cursor (DSH-05; design.md §2.4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class FiltroBitacora:
    desde: datetime | None = None
    hasta: datetime | None = None
    usuario_id: int | None = None
    colaborador_id: int | None = None
    accion: str | None = None
    orden: Literal["asc", "desc"] = "desc"
    cursor: tuple[Any, ...] | None = None
    limite: int = 20


async def consultar(conn: AsyncConnection, f: FiltroBitacora) -> list[dict[str, Any]]:
    """Devuelve hasta ``limite + 1`` filas para saber si existe otra página.

    El orden total es ``(fecha_hora, id)``, de modo que el cursor es estable aunque varios
    registros compartan la misma marca de tiempo.
    """
    condiciones = ["TRUE"]
    params: dict[str, Any] = {"lim": f.limite + 1}
    if f.desde is not None:
        condiciones.append("b.fecha_hora >= :desde")
        params["desde"] = f.desde
    if f.hasta is not None:
        condiciones.append("b.fecha_hora <= :hasta")
        params["hasta"] = f.hasta
    if f.usuario_id is not None:
        condiciones.append("b.usuario_id = :usuario_id")
        params["usuario_id"] = f.usuario_id
    if f.colaborador_id is not None:
        condiciones.append("b.colaborador_id = :colaborador_id")
        params["colaborador_id"] = f.colaborador_id
    if f.accion is not None:
        condiciones.append("b.accion = :accion")
        params["accion"] = f.accion
    comparador = "<" if f.orden == "desc" else ">"
    if f.cursor is not None:
        condiciones.append(f"(b.fecha_hora, b.id) {comparador} (:c_fecha, :c_id)")
        params["c_fecha"], params["c_id"] = f.cursor
    sentido = "DESC" if f.orden == "desc" else "ASC"
    # Solo se interpolan fragmentos fijos y ASC/DESC elegido aquí; los valores van enlazados.
    sql = (
        "SELECT b.id, b.fecha_hora, b.usuario_id, u.nombre AS usuario_nombre, "  # noqa: S608
        "b.colaborador_id, b.accion, b.entidad, b.entidad_id, host(b.ip) AS ip, b.origen, "
        "b.detalle FROM auditoria.bitacora b "
        "LEFT JOIN identidad.usuario u ON u.id = b.usuario_id "
        f"WHERE {' AND '.join(condiciones)} "
        f"ORDER BY b.fecha_hora {sentido}, b.id {sentido} LIMIT :lim"
    )
    return [dict(r) for r in (await conn.execute(text(sql), params)).mappings().all()]
