"""Repositorio de la notificación (parte de la revisión) y de ``notificacion_destinatario``
(design.md §2.2, §6.1; CC-REQ-105, 106).

La revisión (NOT-18) reemplaza los renglones ``PENDIENTE`` y ``EXCLUIDO`` y guarda el snapshot de
criterios y los totales. Un renglón por colaborador seleccionado: ``colaborador_nombre``,
``planta_nombre`` y ``celular_ultimos4`` (el celular completo no existe en este servicio).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cc_notificaciones.clientes import ItemAudiencia


async def obtener_notificacion(
    conn: AsyncConnection, notificacion_id: int, *, bloquear: bool = False
) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            "SELECT n.id, n.estado, n.modo, n.audiencia_id, n.criterios_snapshot_json, "  # noqa: S608
            "n.zona_horaria, a.criterios_json AS criterios_audiencia "
            "FROM notificaciones.notificacion n "
            "LEFT JOIN notificaciones.audiencia a ON a.id = n.audiencia_id "
            "WHERE n.id = :id" + (" FOR UPDATE OF n" if bloquear else "")
        ),
        {"id": notificacion_id},
    )
    fila = r.mappings().first()
    if fila is None:
        return None
    d = dict(fila)
    for k in ("criterios_snapshot_json", "criterios_audiencia"):
        if isinstance(d[k], str):  # asyncpg entrega jsonb como texto
            d[k] = json.loads(d[k])
    return d


async def reemplazar(
    conn: AsyncConnection,
    *,
    empresa_id: int,
    notificacion_id: int,
    items: list[ItemAudiencia],
) -> int:
    """Borra los renglones pendientes y excluidos de la revisión anterior e inserta los nuevos.
    Devuelve cuántos renglones se borraron."""
    borrados = await conn.execute(
        text(
            "DELETE FROM notificaciones.notificacion_destinatario "
            "WHERE notificacion_id = :n AND estado_envio IN ('PENDIENTE', 'EXCLUIDO')"
        ),
        {"n": notificacion_id},
    )
    for i in range(0, len(items), 2000):
        lote = items[i : i + 2000]
        await conn.execute(
            text(
                "INSERT INTO notificaciones.notificacion_destinatario "
                "(empresa_id, notificacion_id, colaborador_id, estado_envio, motivo_exclusion, "
                "colaborador_nombre, planta_nombre, celular_ultimos4) "
                "SELECT :e, :n, t.colaborador_id, "
                "CASE WHEN t.motivo IS NULL THEN 'PENDIENTE' ELSE 'EXCLUIDO' END, t.motivo, "
                "t.nombre, t.planta, CAST(t.ultimos4 AS char(4)) "
                "FROM unnest(CAST(:ids AS bigint[]), CAST(:motivos AS text[]), "
                "CAST(:nombres AS text[]), CAST(:plantas AS text[]), CAST(:ultimos4 AS text[])) "
                "AS t(colaborador_id, motivo, nombre, planta, ultimos4) "
                "ON CONFLICT (notificacion_id, colaborador_id) DO NOTHING"
            ),
            {
                "e": empresa_id,
                "n": notificacion_id,
                "ids": [x.id for x in lote],
                "motivos": [x.motivo_exclusion for x in lote],
                "nombres": [x.nombre for x in lote],
                "plantas": [x.planta_nombre for x in lote],
                "ultimos4": [x.celular_ultimos4 for x in lote],
            },
        )
    return int(borrados.rowcount or 0)


async def guardar_revision(
    conn: AsyncConnection,
    notificacion_id: int,
    *,
    criterios: dict[str, Any],
    seleccionados: int,
    excluidos: int,
) -> Any:
    r = await conn.execute(
        text(
            "UPDATE notificaciones.notificacion SET criterios_snapshot_json = CAST(:c AS jsonb), "
            "total_seleccionados = :s, total_excluidos = :x, revisada_en = now() "
            "WHERE id = :id RETURNING revisada_en"
        ),
        {"c": json.dumps(criterios), "s": seleccionados, "x": excluidos, "id": notificacion_id},
    )
    return r.scalar_one()


async def listar_destinatarios(
    conn: AsyncConnection,
    notificacion_id: int,
    *,
    estado: str | None,
    despues_de: int | None,
    limite: int,
) -> list[dict[str, Any]]:
    """Renglones del detalle (NOT-21), por ``id`` ascendente. Solo trae los últimos 4 dígitos del
    celular (el completo no existe en este servicio)."""
    filtros = ["notificacion_id = :n"]
    params: dict[str, Any] = {"n": notificacion_id, "lim": limite}
    if estado:
        filtros.append("estado_envio = :estado")
        params["estado"] = estado
    if despues_de is not None:
        filtros.append("id > :despues")
        params["despues"] = despues_de
    r = await conn.execute(
        text(
            "SELECT id, colaborador_id, colaborador_nombre, planta_nombre, celular_ultimos4, "  # noqa: S608
            "estado_envio, motivo_exclusion, motivo_fallo, canal_usado, conversacion_id, "
            "intentos, fecha_estado FROM notificaciones.notificacion_destinatario "
            f"WHERE {' AND '.join(filtros)} ORDER BY id LIMIT :lim"
        ),
        params,
    )
    return [dict(f) for f in r.mappings().all()]
