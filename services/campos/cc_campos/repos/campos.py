"""Repositorio de ``campos.campo_colaborador`` y su contador (design.md §2.2, §8.1).

Un campo nunca se borra: ``eliminado = true`` lo oculta y lo desactiva, y su clave no se reutiliza
(``UNIQUE (empresa_id, clave)`` incluye los eliminados). El código interno sale de
``contador_campo`` en la misma transacción, así que no hay huecos ni repetidos por concurrencia.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

COLUMNAS = (
    "id, nombre_campo, clave, codigo_interno, tipo_dato, formato_validacion, obligatorio, orden, "
    "activo, es_sensible, es_sugerido, eliminado"
)
EDITABLES = frozenset(
    {
        "nombre_campo",
        "clave",
        "tipo_dato",
        "formato_validacion",
        "obligatorio",
        "activo",
        "es_sensible",
    }
)


async def siguiente_codigo(conn: AsyncConnection, empresa_id: int) -> str:
    r = await conn.execute(
        text(
            "INSERT INTO campos.contador_campo (empresa_id, ultimo) VALUES (:e, 1) "
            "ON CONFLICT (empresa_id) DO UPDATE SET ultimo = contador_campo.ultimo + 1 "
            "RETURNING ultimo"
        ),
        {"e": empresa_id},
    )
    return f"CAMP-{int(r.scalar_one()):04d}"


async def siguiente_orden(conn: AsyncConnection) -> int:
    r = await conn.execute(
        text("SELECT coalesce(max(orden), 0) + 1 FROM campos.campo_colaborador WHERE NOT eliminado")
    )
    return int(r.scalar_one())


async def listar(
    conn: AsyncConnection, *, estado: str = "todos", tipo: str = "todos"
) -> list[dict[str, Any]]:
    filtros = ["NOT eliminado"]
    if estado == "activos":
        filtros.append("activo")
    elif estado == "inactivos":
        filtros.append("NOT activo")
    if tipo == "sugeridos":
        filtros.append("es_sugerido")
    elif tipo == "personalizados":
        filtros.append("NOT es_sugerido")
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM campos.campo_colaborador "  # noqa: S608
            f"WHERE {' AND '.join(filtros)} ORDER BY orden, id"
        )
    )
    return [dict(f) for f in r.mappings().all()]


async def obtener(
    conn: AsyncConnection, campo_id: int, *, bloquear: bool = False
) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM campos.campo_colaborador "  # noqa: S608
            "WHERE id = :id AND NOT eliminado" + (" FOR UPDATE" if bloquear else "")
        ),
        {"id": campo_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def por_claves(conn: AsyncConnection, claves: list[str]) -> dict[str, dict[str, Any]]:
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM campos.campo_colaborador "  # noqa: S608
            "WHERE clave = ANY(:claves)"
        ),
        {"claves": claves},
    )
    return {f["clave"]: dict(f) for f in r.mappings().all()}


async def insertar(
    conn: AsyncConnection, *, empresa_id: int, codigo_interno: str, datos: dict[str, Any]
) -> int:
    r = await conn.execute(
        text(
            """
            INSERT INTO campos.campo_colaborador
              (empresa_id, nombre_campo, clave, codigo_interno, tipo_dato, formato_validacion,
               obligatorio, orden, activo, es_sensible, es_sugerido)
            VALUES (:e, :nombre_campo, :clave, :codigo, :tipo_dato, :formato_validacion,
                    :obligatorio, :orden, :activo, :es_sensible, :es_sugerido)
            RETURNING id
            """
        ),
        {
            "e": empresa_id,
            "codigo": codigo_interno,
            "nombre_campo": datos["nombre_campo"],
            "clave": datos["clave"],
            "tipo_dato": datos["tipo_dato"],
            "formato_validacion": datos.get("formato_validacion"),
            "obligatorio": datos.get("obligatorio", False),
            "orden": datos["orden"],
            "activo": datos.get("activo", True),
            "es_sensible": datos.get("es_sensible", False),
            "es_sugerido": datos.get("es_sugerido", False),
        },
    )
    return int(r.scalar_one())


async def actualizar(conn: AsyncConnection, campo_id: int, cambios: dict[str, Any]) -> None:
    columnas = [c for c in cambios if c in EDITABLES]
    if not columnas:
        return
    asignaciones = ", ".join(f"{c} = :{c}" for c in columnas)  # nombres de una lista fija
    await conn.execute(
        text(f"UPDATE campos.campo_colaborador SET {asignaciones} WHERE id = :id"),  # noqa: S608
        {"id": campo_id, **{c: cambios[c] for c in columnas}},
    )


async def marcar_eliminado(conn: AsyncConnection, campo_id: int) -> None:
    await conn.execute(
        text("UPDATE campos.campo_colaborador SET eliminado = true, activo = false WHERE id = :id"),
        {"id": campo_id},
    )


async def fijar_orden(conn: AsyncConnection, items: list[tuple[int, int]]) -> int:
    """Asigna ``orden`` a cada ``(id, orden)``. Devuelve cuántos campos existen y se tocaron."""
    tocados = 0
    for campo_id, orden in items:
        r = await conn.execute(
            text("UPDATE campos.campo_colaborador SET orden = :o WHERE id = :id AND NOT eliminado"),
            {"id": campo_id, "o": orden},
        )
        tocados += r.rowcount
    return tocados


async def definiciones(
    conn: AsyncConnection, *, incluir_inactivos: bool = False
) -> list[dict[str, Any]]:
    """Campos no eliminados (por defecto solo activos) con todas sus opciones (INT-CAM-01)."""
    filtro = "" if incluir_inactivos else " AND activo"
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM campos.campo_colaborador "  # noqa: S608
            f"WHERE NOT eliminado{filtro} ORDER BY orden, id"
        )
    )
    campos = [dict(f) | {"opciones": []} for f in r.mappings().all()]
    por_id = {c["id"]: c for c in campos}
    if por_id:
        o = await conn.execute(
            text(
                "SELECT id, campo_id, etiqueta, valor, descripcion, orden, activo "
                "FROM campos.opcion_campo WHERE campo_id = ANY(:ids) ORDER BY orden, id"
            ),
            {"ids": list(por_id)},
        )
        for f in o.mappings().all():
            por_id[f["campo_id"]]["opciones"].append(
                {k: f[k] for k in ("id", "etiqueta", "valor", "descripcion", "orden", "activo")}
            )
    return campos
