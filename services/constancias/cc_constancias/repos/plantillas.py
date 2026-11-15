"""Repositorio de ``constancias.plantilla_constancia`` y su borrador (design.md §2.2, §8.1).

Una plantilla nunca se borra: ``eliminada = true`` la oculta y la desactiva, y su nombre queda
libre (el índice único solo cuenta las no eliminadas). El estado visible sale de los datos:
``ACTIVA`` si está activa, ``BORRADOR`` si aún no tiene versión publicada e ``INACTIVA`` si la
tiene y está desactivada (CC-REQ-064, 069, 070).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_RESUMEN = """
    SELECT p.id, p.nombre, p.descripcion, p.activa, p.fecha_creacion, p.fecha_modificacion,
           (SELECT max(v.numero) FROM constancias.version_plantilla v
             WHERE v.plantilla_id = p.id) AS version,
           (SELECT count(*) FROM constancias.constancia_generada c
              JOIN constancias.version_plantilla v ON v.id = c.version_plantilla_id
             WHERE v.plantilla_id = p.id) AS emitidas,
           EXISTS (SELECT 1 FROM constancias.borrador_plantilla b
                    WHERE b.plantilla_id = p.id) AS tiene_borrador
    FROM constancias.plantilla_constancia p
    WHERE NOT p.eliminada
"""


def estado_visible(fila: dict[str, Any]) -> str:
    if fila["activa"]:
        return "ACTIVA"
    return "BORRADOR" if fila["version"] is None else "INACTIVA"


def _con_estado(fila: dict[str, Any]) -> dict[str, Any]:
    return {**fila, "estado": estado_visible(fila), "emitidas": int(fila["emitidas"])}


async def listar(conn: AsyncConnection) -> list[dict[str, Any]]:
    r = await conn.execute(text(_RESUMEN + " ORDER BY p.fecha_modificacion DESC, p.id DESC"))
    return [_con_estado(dict(f)) for f in r.mappings().all()]


async def obtener(
    conn: AsyncConnection, plantilla_id: int, *, bloquear: bool = False
) -> dict[str, Any] | None:
    """Con ``bloquear`` toma ``FOR UPDATE`` de la fila de la plantilla (y solo de ella)."""
    if bloquear:
        r = await conn.execute(
            text(
                "SELECT id FROM constancias.plantilla_constancia "
                "WHERE id = :id AND NOT eliminada FOR UPDATE"
            ),
            {"id": plantilla_id},
        )
        if r.first() is None:
            return None
    r = await conn.execute(text(_RESUMEN + " AND p.id = :id"), {"id": plantilla_id})
    f = r.mappings().first()
    return _con_estado(dict(f)) if f else None


async def nombres(conn: AsyncConnection) -> list[str]:
    r = await conn.execute(
        text("SELECT nombre FROM constancias.plantilla_constancia WHERE NOT eliminada")
    )
    return [n for (n,) in r.all()]


async def insertar(
    conn: AsyncConnection, *, empresa_id: int, nombre: str, descripcion: str | None
) -> int:
    r = await conn.execute(
        text(
            "INSERT INTO constancias.plantilla_constancia (empresa_id, nombre, descripcion) "
            "VALUES (:e, :n, :d) RETURNING id"
        ),
        {"e": empresa_id, "n": nombre, "d": descripcion},
    )
    return int(r.scalar_one())


async def actualizar(conn: AsyncConnection, plantilla_id: int, cambios: dict[str, Any]) -> None:
    columnas = [c for c in cambios if c in ("nombre", "descripcion", "activa")]
    asignaciones = "".join(f"{c} = :{c}, " for c in columnas)  # nombres de una lista fija
    await conn.execute(
        text(
            f"UPDATE constancias.plantilla_constancia SET {asignaciones}"  # noqa: S608
            "fecha_modificacion = clock_timestamp() WHERE id = :id"
        ),
        {"id": plantilla_id, **{c: cambios[c] for c in columnas}},
    )


async def tocar(conn: AsyncConnection, plantilla_id: int) -> None:
    await conn.execute(
        text(
            "UPDATE constancias.plantilla_constancia SET fecha_modificacion = clock_timestamp() "
            "WHERE id = :id"
        ),
        {"id": plantilla_id},
    )


async def marcar_eliminada(conn: AsyncConnection, plantilla_id: int) -> None:
    await conn.execute(
        text(
            "UPDATE constancias.plantilla_constancia SET eliminada = true, activa = false, "
            "fecha_modificacion = clock_timestamp() WHERE id = :id"
        ),
        {"id": plantilla_id},
    )


async def ultima_version(conn: AsyncConnection, plantilla_id: int) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            "SELECT numero, contenido_s3_key, hash_sha256 FROM constancias.version_plantilla "
            "WHERE plantilla_id = :id ORDER BY numero DESC LIMIT 1"
        ),
        {"id": plantilla_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None


# ------------------------------------------------------------------ borrador


async def obtener_borrador(conn: AsyncConnection, plantilla_id: int) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            "SELECT plantilla_id, contenido_s3_key, hash_sha256, fecha_modificacion "
            "FROM constancias.borrador_plantilla WHERE plantilla_id = :id"
        ),
        {"id": plantilla_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def guardar_borrador(
    conn: AsyncConnection,
    *,
    empresa_id: int,
    plantilla_id: int,
    clave: str,
    hash_sha256: str,
    usuario_id: int,
) -> dict[str, Any]:
    r = await conn.execute(
        text(
            """
            INSERT INTO constancias.borrador_plantilla
              (plantilla_id, empresa_id, contenido_s3_key, hash_sha256, actualizado_por_usuario_id)
            VALUES (:p, :e, :k, :h, :u)
            ON CONFLICT (plantilla_id) DO UPDATE SET
              contenido_s3_key = EXCLUDED.contenido_s3_key, hash_sha256 = EXCLUDED.hash_sha256,
              actualizado_por_usuario_id = EXCLUDED.actualizado_por_usuario_id,
              fecha_modificacion = clock_timestamp()
            RETURNING plantilla_id, contenido_s3_key, hash_sha256, fecha_modificacion
            """
        ),
        {"p": plantilla_id, "e": empresa_id, "k": clave, "h": hash_sha256, "u": usuario_id},
    )
    return dict(r.mappings().one())
