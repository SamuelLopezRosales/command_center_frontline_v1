"""Repositorio de ``notificaciones.notificacion`` (design.md §2.2, §3.6, §6.2; CC-REQ-102 a 122).

Las consultas de lectura traen la audiencia y la plantilla (nombre, estado) y los contadores de
destinatarios calculados al leer con ``count(*) FILTER`` sobre el índice
``(notificacion_id, estado_envio)`` (design.md §6.2: no hay contadores persistidos, así que no hay
condiciones de carrera). Los contadores son **acumulados**: un destinatario ``LEIDO`` también cuenta
como enviado y entregado.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

ENVIADOS = "('ENVIADO', 'ENTREGADO', 'LEIDO', 'RESPONDIO')"
ENTREGADOS = "('ENTREGADO', 'LEIDO', 'RESPONDIO')"
LEIDOS = "('LEIDO', 'RESPONDIO')"

# Pestañas de ``cv1_08``: la cancelada se conserva en Envíos como historial.
PESTANAS: dict[str, tuple[str, ...]] = {
    "envios": ("ENVIANDO", "COMPLETADA", "CON_FALLAS", "CANCELADA"),
    "programadas": ("PROGRAMADA",),
    "borradores": ("BORRADOR",),
}

_SELECT = f"""
SELECT n.id, n.usuario_id, n.titulo, n.modo, n.estado, n.canal, n.audiencia_id,
       a.nombre AS audiencia_nombre, a.criterios_json AS criterios_audiencia,
       n.criterios_snapshot_json, n.plantilla_mensaje_id, p.nombre AS plantilla_nombre,
       p.estado_meta AS plantilla_estado, p.texto_con_variables AS plantilla_texto,
       n.variables_json, n.respaldo_correo, n.programada_para, n.zona_horaria, n.modo_envio,
       n.total_seleccionados, n.total_excluidos, n.revisada_en, n.confirmada_fuera_horario,
       n.confirmada_en, n.confirmada_por_usuario_id, n.fecha_creacion, n.fecha_envio,
       n.motivo_cancelacion, n.schedule_nombre,
       COALESCE(c.renglones, 0) AS renglones, COALESCE(c.excluidos, 0) AS excluidos,
       COALESCE(c.pendientes, 0) AS pendientes, COALESCE(c.enviados, 0) AS enviados,
       COALESCE(c.entregados, 0) AS entregados, COALESCE(c.leidos, 0) AS leidos,
       COALESCE(c.respondieron, 0) AS respondieron, COALESCE(c.fallidos, 0) AS fallidos
FROM notificaciones.notificacion n
LEFT JOIN notificaciones.audiencia a ON a.id = n.audiencia_id
LEFT JOIN notificaciones.plantilla_mensaje p ON p.id = n.plantilla_mensaje_id
LEFT JOIN LATERAL (
  SELECT count(*) AS renglones,
         count(*) FILTER (WHERE d.estado_envio = 'EXCLUIDO') AS excluidos,
         count(*) FILTER (WHERE d.estado_envio = 'PENDIENTE') AS pendientes,
         count(*) FILTER (WHERE d.estado_envio IN {ENVIADOS}) AS enviados,
         count(*) FILTER (WHERE d.estado_envio IN {ENTREGADOS}) AS entregados,
         count(*) FILTER (WHERE d.estado_envio IN {LEIDOS}) AS leidos,
         count(*) FILTER (WHERE d.estado_envio = 'RESPONDIO') AS respondieron,
         count(*) FILTER (WHERE d.estado_envio = 'FALLIDO') AS fallidos
  FROM notificaciones.notificacion_destinatario d WHERE d.notificacion_id = n.id
) c ON true
"""  # noqa: S608 - constantes del código


def _json(valor: Any) -> Any:
    return (
        json.loads(valor) if isinstance(valor, str) else valor
    )  # asyncpg entrega jsonb como texto


def _fila(f: Any) -> dict[str, Any]:
    d = dict(f)
    for k in ("criterios_audiencia", "criterios_snapshot_json", "variables_json"):
        d[k] = _json(d[k])
    return d


async def crear(
    conn: AsyncConnection,
    *,
    empresa_id: int,
    usuario_id: int,
    titulo: str,
    modo: str,
    audiencia_id: int | None,
    criterios: dict[str, Any] | None,
    plantilla_id: int,
    variables: dict[str, Any],
    respaldo_correo: bool,
    zona_horaria: str,
) -> int:
    r = await conn.execute(
        text(
            "INSERT INTO notificaciones.notificacion (empresa_id, usuario_id, titulo, modo, "
            "audiencia_id, criterios_snapshot_json, plantilla_mensaje_id, variables_json, "
            "respaldo_correo, zona_horaria) VALUES (:e, :u, :t, :m, :a, CAST(:c AS jsonb), :p, "
            "CAST(:v AS jsonb), :r, :z) RETURNING id"
        ),
        {
            "e": empresa_id,
            "u": usuario_id,
            "t": titulo,
            "m": modo,
            "a": audiencia_id,
            "c": json.dumps(criterios) if criterios is not None else None,
            "p": plantilla_id,
            "v": json.dumps(variables, ensure_ascii=False),
            "r": respaldo_correo,
            "z": zona_horaria,
        },
    )
    return int(r.scalar_one())


async def obtener(
    conn: AsyncConnection, notificacion_id: int, *, bloquear: bool = False
) -> dict[str, Any] | None:
    r = await conn.execute(
        text(_SELECT + " WHERE n.id = :id" + (" FOR UPDATE OF n" if bloquear else "")),
        {"id": notificacion_id},
    )
    f = r.mappings().first()
    return _fila(f) if f else None


async def listar(
    conn: AsyncConnection,
    *,
    estados: tuple[str, ...],
    despues_de: int | None,
    limite: int,
) -> list[dict[str, Any]]:
    filtros = ["n.estado = ANY(CAST(:estados AS text[]))"]
    params: dict[str, Any] = {"estados": list(estados), "lim": limite}
    if despues_de is not None:
        filtros.append("n.id < :despues")
        params["despues"] = despues_de
    r = await conn.execute(
        text(_SELECT + " WHERE " + " AND ".join(filtros) + " ORDER BY n.id DESC LIMIT :lim"),
        params,
    )
    return [_fila(f) for f in r.mappings().all()]


async def actualizar(conn: AsyncConnection, notificacion_id: int, cambios: dict[str, Any]) -> None:
    """``cambios`` con columnas de ``COLUMNAS_EDITABLES`` (``*_json`` ya como objetos)."""
    asignaciones = []
    params: dict[str, Any] = {"id": notificacion_id}
    for k, v in cambios.items():
        if k not in COLUMNAS_EDITABLES:
            raise ValueError("columna no editable")
        if k.endswith("_json"):
            asignaciones.append(f"{k} = CAST(:{k} AS jsonb)")
            params[k] = json.dumps(v, ensure_ascii=False) if v is not None else None
        else:
            asignaciones.append(f"{k} = :{k}")
            params[k] = v
    if asignaciones:
        await conn.execute(
            text(
                f"UPDATE notificaciones.notificacion SET {', '.join(asignaciones)} "  # noqa: S608
                "WHERE id = :id"
            ),
            params,
        )


COLUMNAS_EDITABLES = frozenset(
    {
        "titulo",
        "modo",
        "audiencia_id",
        "criterios_snapshot_json",
        "plantilla_mensaje_id",
        "variables_json",
        "respaldo_correo",
        "zona_horaria",
    }
)


async def invalidar_revision(conn: AsyncConnection, notificacion_id: int) -> None:
    """Cambió la audiencia: la revisión anterior ya no vale (renglones y totales)."""
    await conn.execute(
        text(
            "DELETE FROM notificaciones.notificacion_destinatario "
            "WHERE notificacion_id = :n AND estado_envio IN ('PENDIENTE', 'EXCLUIDO')"
        ),
        {"n": notificacion_id},
    )
    await conn.execute(
        text(
            "UPDATE notificaciones.notificacion SET revisada_en = NULL, "
            "total_seleccionados = NULL, total_excluidos = NULL WHERE id = :n"
        ),
        {"n": notificacion_id},
    )


async def marcar_confirmada(
    conn: AsyncConnection,
    notificacion_id: int,
    *,
    estado_nuevo: str,
    modo_envio: str,
    programada_para: datetime | None,
    schedule_nombre: str | None,
    respaldo_correo: bool,
    fuera_horario: bool,
    usuario_id: int,
) -> bool:
    """BORRADOR -> PROGRAMADA o ENVIANDO con comparar y cambiar. ``False`` si otro lo hizo antes."""
    r = await conn.execute(
        text(
            "UPDATE notificaciones.notificacion SET estado = :est, modo_envio = :mo, "
            "programada_para = :pp, schedule_nombre = :sn, respaldo_correo = :rc, "
            "confirmada_fuera_horario = :fh, confirmada_por_usuario_id = :u, confirmada_en = now() "
            "WHERE id = :id AND estado = 'BORRADOR'"
        ),
        {
            "id": notificacion_id,
            "est": estado_nuevo,
            "mo": modo_envio,
            "pp": programada_para,
            "sn": schedule_nombre,
            "rc": respaldo_correo,
            "fh": fuera_horario,
            "u": usuario_id,
        },
    )
    return bool(r.rowcount)


async def duplicar(
    conn: AsyncConnection, origen: dict[str, Any], *, empresa_id: int, usuario_id: int, titulo: str
) -> int:
    """Copia plantilla, variables y criterios; no copia revisión, destinatarios ni programación."""
    criterios = origen["criterios_snapshot_json"]
    return await crear(
        conn,
        empresa_id=empresa_id,
        usuario_id=usuario_id,
        titulo=titulo,
        modo=origen["modo"],
        audiencia_id=origen["audiencia_id"],
        criterios=criterios,
        plantilla_id=origen["plantilla_mensaje_id"],
        variables=origen["variables_json"] or {},
        respaldo_correo=origen["respaldo_correo"],
        zona_horaria=origen["zona_horaria"],
    )


async def conteo_pestanas(conn: AsyncConnection) -> dict[str, int]:
    r = await conn.execute(
        text(
            "SELECT count(*) FILTER (WHERE estado = ANY(CAST(:env AS text[]))), "
            "count(*) FILTER (WHERE estado = 'PROGRAMADA'), "
            "count(*) FILTER (WHERE estado = 'BORRADOR') FROM notificaciones.notificacion"
        ),
        {"env": list(PESTANAS["envios"])},
    )
    envios, programadas, borradores = r.one()
    return {"envios": envios, "programadas": programadas, "borradores": borradores}


async def indicadores_mes(conn: AsyncConnection, inicio: datetime, fin: datetime) -> dict[str, int]:
    """Destinatarios de las notificaciones enviadas en ``[inicio, fin)`` (fecha de envío o, si el
    despacho sigue en curso, la de confirmación)."""
    r = await conn.execute(
        text(
            f"SELECT count(*) FILTER (WHERE d.estado_envio IN {ENVIADOS}), "  # noqa: S608
            f"count(*) FILTER (WHERE d.estado_envio IN {ENTREGADOS}), "
            f"count(*) FILTER (WHERE d.estado_envio IN {LEIDOS}), "
            "count(*) FILTER (WHERE d.estado_envio = 'FALLIDO') "
            "FROM notificaciones.notificacion_destinatario d "
            "JOIN notificaciones.notificacion n ON n.id = d.notificacion_id "
            "WHERE COALESCE(n.fecha_envio, n.confirmada_en) >= :ini "
            "AND COALESCE(n.fecha_envio, n.confirmada_en) < :fin"
        ),
        {"ini": inicio, "fin": fin},
    )
    enviadas, entregadas, leidas, fallidas = r.one()
    return {
        "enviadas": enviadas,
        "entregadas": entregadas,
        "leidas": leidas,
        "fallidas": fallidas,
    }
