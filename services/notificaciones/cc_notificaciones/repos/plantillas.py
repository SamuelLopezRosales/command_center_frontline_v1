"""Repositorio de ``notificaciones.plantilla_mensaje`` (design.md §2.2, §3.6; CC-REQ-117).

Estados: BORRADOR, EN_REVISION, APROBADA, RECHAZADA. Las transiciones de estado se hacen con
comparar y cambiar (``WHERE estado_meta = :esperado``) para que dos eventos o llamadas simultáneas
no se pisen. El nombre es único por empresa (restricción
``plantilla_mensaje_empresa_id_nombre_key``).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

COLUMNAS = (
    "id, nombre, categoria, idioma, texto_con_variables, estado_meta, id_plantilla_meta, "
    "motivo_rechazo, ejemplos_json, creada_por_usuario_id, fecha_creacion"
)
EDITABLES = {"nombre", "categoria", "idioma", "texto_con_variables", "ejemplos_json"}


def _fila(f: Any) -> dict[str, Any]:
    d = dict(f)
    if isinstance(d.get("ejemplos_json"), str):  # asyncpg entrega jsonb como texto
        d["ejemplos_json"] = json.loads(d["ejemplos_json"])
    return d


async def crear(
    conn: AsyncConnection,
    *,
    empresa_id: int,
    usuario_id: int,
    nombre: str,
    categoria: str,
    idioma: str,
    texto: str,
    ejemplos: list[str],
) -> dict[str, Any]:
    r = await conn.execute(
        text(
            "INSERT INTO notificaciones.plantilla_mensaje "  # noqa: S608
            "(empresa_id, creada_por_usuario_id, nombre, categoria, idioma, texto_con_variables, "
            f"ejemplos_json) VALUES (:e, :u, :n, :c, :i, :t, CAST(:j AS jsonb)) "
            f"RETURNING {COLUMNAS}"
        ),
        {
            "e": empresa_id,
            "u": usuario_id,
            "n": nombre,
            "c": categoria,
            "i": idioma,
            "t": texto,
            "j": json.dumps(ejemplos, ensure_ascii=False),
        },
    )
    return _fila(r.mappings().one())


async def obtener(
    conn: AsyncConnection, plantilla_id: int, *, bloquear: bool = False
) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM notificaciones.plantilla_mensaje WHERE id = :id"  # noqa: S608
            + (" FOR UPDATE" if bloquear else "")
        ),
        {"id": plantilla_id},
    )
    f = r.mappings().first()
    return _fila(f) if f else None


async def listar(
    conn: AsyncConnection, *, estado: str | None, despues_de: int | None, limite: int
) -> list[dict[str, Any]]:
    filtros: list[str] = []
    params: dict[str, Any] = {"lim": limite}
    if estado:
        filtros.append("estado_meta = :estado")
        params["estado"] = estado
    if despues_de is not None:
        filtros.append("id < :despues")
        params["despues"] = despues_de
    donde = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM notificaciones.plantilla_mensaje {donde} "  # noqa: S608
            "ORDER BY id DESC LIMIT :lim"
        ),
        params,
    )
    return [_fila(f) for f in r.mappings().all()]


async def actualizar(
    conn: AsyncConnection, plantilla_id: int, cambios: dict[str, Any]
) -> dict[str, Any]:
    """``cambios`` solo puede traer columnas de ``EDITABLES``."""
    sobrantes = set(cambios) - EDITABLES
    if sobrantes:
        raise ValueError("columnas no editables")
    asignaciones = []
    params: dict[str, Any] = {"id": plantilla_id}
    for k, v in cambios.items():
        if k == "ejemplos_json":
            asignaciones.append("ejemplos_json = CAST(:ejemplos_json AS jsonb)")
            params[k] = json.dumps(v, ensure_ascii=False)
        else:
            asignaciones.append(f"{k} = :{k}")
            params[k] = v
    r = await conn.execute(
        text(
            f"UPDATE notificaciones.plantilla_mensaje SET {', '.join(asignaciones)} "  # noqa: S608
            f"WHERE id = :id RETURNING {COLUMNAS}"
        ),
        params,
    )
    return _fila(r.mappings().one())


async def pasar_a_revision(
    conn: AsyncConnection, plantilla_id: int, *, id_meta: str, esperado: str
) -> bool:
    """BORRADOR o RECHAZADA -> EN_REVISION con el id de Meta; limpia el motivo anterior."""
    r = await conn.execute(
        text(
            "UPDATE notificaciones.plantilla_mensaje SET estado_meta = 'EN_REVISION', "
            "id_plantilla_meta = :m, motivo_rechazo = NULL "
            "WHERE id = :id AND estado_meta = :esperado"
        ),
        {"id": plantilla_id, "m": id_meta, "esperado": esperado},
    )
    return bool(r.rowcount)


async def resolver_revision(
    conn: AsyncConnection, plantilla_id: int, *, nuevo: str, motivo: str | None
) -> bool:
    """EN_REVISION -> APROBADA o RECHAZADA (comparar y cambiar). ``False`` si ya no estaba en
    revisión (evento repetido o tardío)."""
    r = await conn.execute(
        text(
            "UPDATE notificaciones.plantilla_mensaje SET estado_meta = :nuevo, "
            "motivo_rechazo = :motivo WHERE id = :id AND estado_meta = 'EN_REVISION'"
        ),
        {"id": plantilla_id, "nuevo": nuevo, "motivo": motivo},
    )
    return bool(r.rowcount)


async def en_revision_por_nombre(conn: AsyncConnection, nombre: str) -> list[tuple[int, int]]:
    """``(plantilla_id, empresa_id)`` de las plantillas EN_REVISION con ese nombre, de **todas**
    las empresas: el evento ``wa.plantilla_estado`` no trae empresa (la cuenta de WhatsApp es
    única). Usa la función ``SECURITY DEFINER`` de la migración 0002, que no expone más."""
    r = await conn.execute(
        text("SELECT id, empresa_id FROM notificaciones.plantillas_en_revision_por_nombre(:n)"),
        {"n": nombre},
    )
    return [(int(i), int(e)) for i, e in r.all()]
