"""Lecturas de las vistas contractuales (design.md §2.6; CC-REQ-011 a 013, 087).

``svc_dashboard`` solo puede leer estas vistas, nunca las tablas de ``colaboradores`` ni de
``constancias``. Cada vista filtra por ``app.empresa_id`` (la fija ``transaccion``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def resumen(conn: AsyncConnection) -> dict[str, int]:
    c = (
        (await conn.execute(text("SELECT colaboradores_activos FROM colaboradores.v_resumen")))
        .mappings()
        .first()
    )
    k = (
        (
            await conn.execute(
                text(
                    "SELECT constancias_mes, solicitudes_en_proceso, plantillas_activas "
                    "FROM constancias.v_resumen"
                )
            )
        )
        .mappings()
        .first()
    )
    return {
        "colaboradores_activos": int(c["colaboradores_activos"]) if c else 0,
        "constancias_mes": int(k["constancias_mes"]) if k else 0,
        "solicitudes_en_proceso": int(k["solicitudes_en_proceso"]) if k else 0,
        "plantillas_activas": int(k["plantillas_activas"]) if k else 0,
    }


async def solicitudes_recientes(conn: AsyncConnection, limite: int) -> list[dict[str, Any]]:
    r = await conn.execute(
        text(
            "SELECT id, colaborador_nombre, plantilla_nombre, version, estado "
            "FROM constancias.v_solicitudes_recientes "
            "ORDER BY fecha_solicitud DESC, id DESC LIMIT :n"
        ),
        {"n": limite},
    )
    return [dict(f) for f in r.mappings().all()]


async def constancias_recientes(conn: AsyncConnection, limite: int) -> list[dict[str, Any]]:
    r = await conn.execute(
        text(
            "SELECT id, folio, colaborador_nombre, plantilla_nombre, version, fecha, "
            "estado_entrega "
            "FROM constancias.v_historial ORDER BY fecha DESC, id DESC LIMIT :n"
        ),
        {"n": limite},
    )
    return [dict(f) for f in r.mappings().all()]


async def alertas_consentimiento(conn: AsyncConnection) -> tuple[int, list[str]]:
    """Total de colaboradores activos sin consentimiento vigente y los nombres más recientes."""
    total = (await conn.execute(text("SELECT count(*) FROM colaboradores.v_alertas"))).scalar_one()
    r = await conn.execute(
        text(
            "SELECT dato FROM colaboradores.v_alertas WHERE tipo = 'SIN_CONSENTIMIENTO' "
            "ORDER BY fecha DESC, referencia_id DESC LIMIT 3"
        )
    )
    return int(total), [f[0] for f in r.all()]


async def alertas_constancias(conn: AsyncConnection) -> list[dict[str, Any]]:
    r = await conn.execute(
        text(
            "SELECT tipo, referencia_id, dato, total, fecha FROM constancias.v_alertas "
            "ORDER BY fecha DESC, referencia_id DESC LIMIT 100"
        )
    )
    return [dict(f) for f in r.mappings().all()]


@dataclass(frozen=True)
class FiltroHistorial:
    desde: date | None = None
    hasta: date | None = None
    plantilla_id: int | None = None
    colaborador_id: int | None = None
    estado: str | None = None
    q: str | None = None
    cursor: tuple[Any, ...] | None = None
    limite: int = 20


def _como_patron(q: str) -> str:
    """Escapa ``%``, ``_`` y ``\\`` para que ``q`` se busque como texto literal."""
    escapado = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escapado}%"


async def historial(conn: AsyncConnection, f: FiltroHistorial) -> list[dict[str, Any]]:
    """Hasta ``limite + 1`` filas por ``(fecha, id)`` descendente (cursor estable)."""
    condiciones = ["TRUE"]
    params: dict[str, Any] = {"lim": f.limite + 1}
    if f.desde is not None:
        condiciones.append("h.fecha >= CAST(:desde AS date)")
        params["desde"] = f.desde
    if f.hasta is not None:
        condiciones.append("h.fecha < CAST(:hasta AS date) + 1")
        params["hasta"] = f.hasta
    if f.plantilla_id is not None:
        condiciones.append("h.plantilla_id = :plantilla_id")
        params["plantilla_id"] = f.plantilla_id
    if f.colaborador_id is not None:
        condiciones.append("h.colaborador_id = :colaborador_id")
        params["colaborador_id"] = f.colaborador_id
    if f.estado is not None:
        condiciones.append("h.estado_entrega = :estado")
        params["estado"] = f.estado
    if f.q:
        condiciones.append(
            "(lower(h.folio) LIKE :q ESCAPE '\\' "
            "OR lower(h.colaborador_nombre) LIKE :q ESCAPE '\\')"
        )
        params["q"] = _como_patron(f.q)
    if f.cursor is not None:
        condiciones.append("(h.fecha, h.id) < (:c_fecha, :c_id)")
        params["c_fecha"], params["c_id"] = f.cursor
    sql = (
        "SELECT h.id, h.folio, h.colaborador_nombre, h.plantilla_nombre, h.version, h.fecha, "  # noqa: S608
        "h.canal, h.estado_entrega FROM constancias.v_historial h "
        f"WHERE {' AND '.join(condiciones)} ORDER BY h.fecha DESC, h.id DESC LIMIT :lim"
    )
    return [dict(r) for r in (await conn.execute(text(sql), params)).mappings().all()]
