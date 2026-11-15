"""Repositorio de ``constancias.version_plantilla`` (design.md §2.2, §2.7).

Las versiones son inmutables: un trigger rechaza todo ``UPDATE`` y ``DELETE`` (CC-REQ-066). Solo se
inserta. El número sale de ``max(numero) + 1`` bajo el bloqueo de la fila de la plantilla, así que
publicaciones simultáneas se ordenan y no repiten número.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

COLUMNAS = "numero, hash_sha256, contenido_s3_key, fecha_creacion, creada_por_usuario_id"


async def siguiente_numero(conn: AsyncConnection, plantilla_id: int) -> int:
    """Llamar con la plantilla ya bloqueada (``repo_plantillas.obtener(bloquear=True)``)."""
    r = await conn.execute(
        text(
            "SELECT coalesce(max(numero), 0) + 1 FROM constancias.version_plantilla "
            "WHERE plantilla_id = :p"
        ),
        {"p": plantilla_id},
    )
    return int(r.scalar_one())


async def insertar(
    conn: AsyncConnection,
    *,
    empresa_id: int,
    plantilla_id: int,
    numero: int,
    clave: str,
    hash_sha256: str,
    usuario_id: int,
) -> dict[str, Any]:
    r = await conn.execute(
        text(
            "INSERT INTO constancias.version_plantilla (empresa_id, plantilla_id, numero, "
            "contenido_s3_key, hash_sha256, creada_por_usuario_id) "
            "VALUES (:e, :p, :n, :k, :h, :u) RETURNING " + COLUMNAS  # noqa: S608
        ),
        {
            "e": empresa_id,
            "p": plantilla_id,
            "n": numero,
            "k": clave,
            "h": hash_sha256,
            "u": usuario_id,
        },
    )
    return dict(r.mappings().one())


async def listar(conn: AsyncConnection, plantilla_id: int) -> list[dict[str, Any]]:
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM constancias.version_plantilla "  # noqa: S608
            "WHERE plantilla_id = :p ORDER BY numero DESC"
        ),
        {"p": plantilla_id},
    )
    return [dict(f) for f in r.mappings().all()]


async def obtener(conn: AsyncConnection, plantilla_id: int, numero: int) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM constancias.version_plantilla "  # noqa: S608
            "WHERE plantilla_id = :p AND numero = :n"
        ),
        {"p": plantilla_id, "n": numero},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def activar(conn: AsyncConnection, plantilla_id: int) -> None:
    await conn.execute(
        text(
            "UPDATE constancias.plantilla_constancia SET activa = true, "
            "fecha_modificacion = clock_timestamp() WHERE id = :id"
        ),
        {"id": plantilla_id},
    )
