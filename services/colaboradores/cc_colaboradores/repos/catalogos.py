"""Repositorios de ``organizacion`` y ``planta`` (COL-08 a COL-15).

No hay borrado: solo ``activa = false`` (DS-04, CC-REQ-161). La clave de la organización no se
actualiza nunca (no está en las columnas editables).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

COLUMNAS_ORG = (
    "id, clave, razon_social, rfc, registro_patronal, domicilio_fiscal, ciudad, "
    "logotipo_s3_key, nombre_firmante, cargo_firmante, correo_firmante, activa"
)
EDITABLES_ORG = frozenset(
    {
        "razon_social",
        "rfc",
        "registro_patronal",
        "domicilio_fiscal",
        "ciudad",
        "nombre_firmante",
        "cargo_firmante",
        "correo_firmante",
        "activa",
    }
)
EDITABLES_PLANTA = frozenset({"nombre", "activa"})


async def listar_organizaciones(
    conn: AsyncConnection, *, solo_activas: bool = False
) -> list[dict[str, Any]]:
    filtro = " WHERE activa" if solo_activas else ""
    r = await conn.execute(
        text(f"SELECT {COLUMNAS_ORG} FROM colaboradores.organizacion{filtro} ORDER BY clave")  # noqa: S608
    )
    return [dict(f) for f in r.mappings().all()]


async def organizacion(conn: AsyncConnection, organizacion_id: int) -> dict[str, Any] | None:
    r = await conn.execute(
        text(f"SELECT {COLUMNAS_ORG} FROM colaboradores.organizacion WHERE id = :id"),  # noqa: S608
        {"id": organizacion_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def crear_organizacion(
    conn: AsyncConnection, *, empresa_id: int, datos: dict[str, Any]
) -> int:
    r = await conn.execute(
        text(
            """
            INSERT INTO colaboradores.organizacion
              (empresa_id, clave, razon_social, rfc, registro_patronal, domicilio_fiscal, ciudad,
               nombre_firmante, cargo_firmante, correo_firmante)
            VALUES (:e, :clave, :razon_social, :rfc, :registro_patronal, :domicilio_fiscal,
                    :ciudad, :nombre_firmante, :cargo_firmante, :correo_firmante)
            RETURNING id
            """
        ),
        {
            "e": empresa_id,
            **{
                k: datos.get(k)
                for k in (
                    "clave",
                    "razon_social",
                    "rfc",
                    "registro_patronal",
                    "domicilio_fiscal",
                    "ciudad",
                    "nombre_firmante",
                    "cargo_firmante",
                    "correo_firmante",
                )
            },
        },
    )
    return int(r.scalar_one())


async def _actualizar(
    conn: AsyncConnection, tabla: str, editables: frozenset[str], fila_id: int, cambios: dict
) -> bool:
    columnas = [c for c in cambios if c in editables]
    if not columnas:
        return True
    asignaciones = ", ".join(f"{c} = :{c}" for c in columnas)  # nombres de una lista fija
    r = await conn.execute(
        text(f"UPDATE colaboradores.{tabla} SET {asignaciones} WHERE id = :id"),  # noqa: S608
        {"id": fila_id, **{c: cambios[c] for c in columnas}},
    )
    return r.rowcount == 1


async def actualizar_organizacion(
    conn: AsyncConnection, organizacion_id: int, cambios: dict
) -> bool:
    return await _actualizar(conn, "organizacion", EDITABLES_ORG, organizacion_id, cambios)


async def fijar_logotipo(conn: AsyncConnection, organizacion_id: int, clave_s3: str) -> None:
    await conn.execute(
        text("UPDATE colaboradores.organizacion SET logotipo_s3_key = :k WHERE id = :id"),
        {"k": clave_s3, "id": organizacion_id},
    )


async def listar_plantas(
    conn: AsyncConnection, *, solo_activas: bool = False
) -> list[dict[str, Any]]:
    filtro = " WHERE activa" if solo_activas else ""
    r = await conn.execute(
        text(f"SELECT id, nombre, activa FROM colaboradores.planta{filtro} ORDER BY lower(nombre)")  # noqa: S608
    )
    return [dict(f) for f in r.mappings().all()]


async def planta(conn: AsyncConnection, planta_id: int) -> dict[str, Any] | None:
    r = await conn.execute(
        text("SELECT id, nombre, activa FROM colaboradores.planta WHERE id = :id"),
        {"id": planta_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def crear_planta(conn: AsyncConnection, *, empresa_id: int, nombre: str) -> int:
    r = await conn.execute(
        text("INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (:e, :n) RETURNING id"),
        {"e": empresa_id, "n": nombre},
    )
    return int(r.scalar_one())


async def actualizar_planta(conn: AsyncConnection, planta_id: int, cambios: dict) -> bool:
    return await _actualizar(conn, "planta", EDITABLES_PLANTA, planta_id, cambios)
