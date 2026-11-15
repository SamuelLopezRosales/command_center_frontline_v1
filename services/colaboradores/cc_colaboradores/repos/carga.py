"""Repositorio de ``carga_colaboradores`` y ``fila_carga`` (design.md §2.2, §4.7).

``fila_carga`` guarda por fila su resultado y los mensajes de error (``CODIGO: texto``, uno por
línea, sin datos personales). ``UNIQUE (carga_id, numero_fila)`` da la idempotencia del worker.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

COLUMNAS = (
    "id, nombre_archivo, version_plantilla, hash_archivo, total_filas, filas_ok, filas_error, "
    "estado, fecha_carga, fecha_fin, motivo_cierre, s3_key, usuario_id"
)


async def crear(
    conn: AsyncConnection, *, empresa_id: int, usuario_id: int, nombre_archivo: str, s3_key: str
) -> dict[str, Any]:
    r = await conn.execute(
        text(
            "INSERT INTO colaboradores.carga_colaboradores "
            "(empresa_id, usuario_id, nombre_archivo, version_plantilla, s3_key) "
            "VALUES (:e, :u, :n, 'PENDIENTE', :k) RETURNING " + COLUMNAS  # noqa: S608
        ),
        {"e": empresa_id, "u": usuario_id, "n": nombre_archivo, "k": s3_key},
    )
    return dict(r.mappings().one())


async def obtener(
    conn: AsyncConnection, carga_id: int, *, bloquear: bool = False
) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM colaboradores.carga_colaboradores "  # noqa: S608
            "WHERE id = :id" + (" FOR UPDATE" if bloquear else "")
        ),
        {"id": carga_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def listar(
    conn: AsyncConnection, *, pagina: int, limite: int
) -> tuple[list[dict[str, Any]], int]:
    total = (
        await conn.execute(text("SELECT count(*) FROM colaboradores.carga_colaboradores"))
    ).scalar_one()
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM colaboradores.carga_colaboradores "  # noqa: S608
            "ORDER BY fecha_carga DESC, id DESC LIMIT :l OFFSET :o"
        ),
        {"l": limite, "o": (pagina - 1) * limite},
    )
    return [dict(f) for f in r.mappings().all()], int(total)


async def confirmar(
    conn: AsyncConnection, carga_id: int, *, hash_archivo: str, total_filas: int, version: str
) -> None:
    await conn.execute(
        text(
            "UPDATE colaboradores.carga_colaboradores SET hash_archivo = :h, total_filas = :t, "
            "version_plantilla = :v WHERE id = :id"
        ),
        {"id": carga_id, "h": hash_archivo, "t": total_filas, "v": version},
    )


async def cerrar(
    conn: AsyncConnection,
    carga_id: int,
    *,
    estado: str,
    motivo: str | None = None,
    desde_estado: str = "EN_PROCESO",
) -> bool:
    """Pasa la carga a ``TERMINADA`` o ``CANCELADA`` solo si sigue en ``desde_estado``."""
    r = await conn.execute(
        text(
            "UPDATE colaboradores.carga_colaboradores SET estado = :estado, "
            "motivo_cierre = :motivo, fecha_fin = now(), s3_key = NULL "
            "WHERE id = :id AND estado = :desde"
        ),
        {"id": carga_id, "estado": estado, "motivo": motivo, "desde": desde_estado},
    )
    return r.rowcount == 1


async def cancelar_vencidas(conn: AsyncConnection, segundos: int) -> list[dict[str, Any]]:
    """Cancela las cargas que nunca se confirmaron (``NO_CONFIRMADA``). Devuelve ``id`` y
    ``s3_key`` para borrar el archivo y registrar la bitácora."""
    r = await conn.execute(
        text(
            "UPDATE colaboradores.carga_colaboradores SET estado = 'CANCELADA', "
            "motivo_cierre = 'NO_CONFIRMADA', fecha_fin = now() "
            "WHERE estado = 'EN_PROCESO' AND hash_archivo IS NULL "
            "AND fecha_carga < now() - make_interval(secs => :s) "
            "RETURNING id, s3_key, usuario_id"
        ),
        {"s": segundos},
    )
    return [dict(f) for f in r.mappings().all()]


async def estado(conn: AsyncConnection, carga_id: int) -> str | None:
    r = await conn.execute(
        text("SELECT estado FROM colaboradores.carga_colaboradores WHERE id = :id"),
        {"id": carga_id},
    )
    return r.scalar_one_or_none()


async def actualizar_conteos(conn: AsyncConnection, carga_id: int) -> tuple[int, int]:
    r = await conn.execute(
        text(
            "UPDATE colaboradores.carga_colaboradores c SET "
            "filas_ok = n.ok, filas_error = n.err FROM ("
            "  SELECT count(*) FILTER (WHERE resultado IN ('NUEVO', 'ACTUALIZADO')) AS ok, "
            "         count(*) FILTER (WHERE resultado = 'ERROR') AS err "
            "  FROM colaboradores.fila_carga WHERE carga_id = :id) n "
            "WHERE c.id = :id RETURNING c.filas_ok, c.filas_error"
        ),
        {"id": carga_id},
    )
    ok, err = r.one()
    return int(ok), int(err)


# ------------------------------------------------------------------ filas


async def filas_registradas(conn: AsyncConnection, carga_id: int) -> set[int]:
    r = await conn.execute(
        text("SELECT numero_fila FROM colaboradores.fila_carga WHERE carga_id = :id"),
        {"id": carga_id},
    )
    return {int(n) for (n,) in r.all()}


async def registrar_fila(
    conn: AsyncConnection,
    *,
    empresa_id: int,
    carga_id: int,
    numero_fila: int,
    numero_empleado: str | None,
    resultado: str,
    colaborador_id: int | None = None,
    mensaje: str | None = None,
) -> bool:
    """Registra el resultado de una fila; ``False`` si ya estaba (mensaje repetido)."""
    r = await conn.execute(
        text(
            "INSERT INTO colaboradores.fila_carga "
            "(empresa_id, carga_id, colaborador_id, numero_fila, numero_empleado, resultado, "
            "mensaje) "
            "VALUES (:e, :c, :col, :n, :num, :r, :m) "
            "ON CONFLICT (carga_id, numero_fila) DO NOTHING"
        ),
        {
            "e": empresa_id,
            "c": carga_id,
            "col": colaborador_id,
            "n": numero_fila,
            "num": numero_empleado,
            "r": resultado,
            "m": mensaje,
        },
    )
    return r.rowcount == 1


async def listar_filas(
    conn: AsyncConnection,
    carga_id: int,
    *,
    resultado: str | None,
    pagina: int,
    limite: int,
) -> tuple[list[dict[str, Any]], int]:
    filtro = "carga_id = :c" + (" AND resultado = :r" if resultado else "")
    params: dict[str, Any] = {"c": carga_id, "r": resultado}
    total = (
        await conn.execute(
            text(f"SELECT count(*) FROM colaboradores.fila_carga WHERE {filtro}"),  # noqa: S608
            params,
        )
    ).scalar_one()
    r = await conn.execute(
        text(
            "SELECT numero_fila, resultado, mensaje FROM colaboradores.fila_carga "  # noqa: S608
            f"WHERE {filtro} ORDER BY numero_fila LIMIT :l OFFSET :o"
        ),
        {**params, "l": limite, "o": (pagina - 1) * limite},
    )
    return [dict(f) for f in r.mappings().all()], int(total)


async def filas_con_error(conn: AsyncConnection, carga_id: int) -> list[dict[str, Any]]:
    r = await conn.execute(
        text(
            "SELECT numero_fila, mensaje FROM colaboradores.fila_carga "
            "WHERE carga_id = :c AND resultado = 'ERROR' ORDER BY numero_fila"
        ),
        {"c": carga_id},
    )
    return [dict(f) for f in r.mappings().all()]


async def referencias(conn: AsyncConnection) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Claves de organizaciones y nombres de plantas activas de la empresa (por RLS)."""
    o = await conn.execute(text("SELECT clave, id FROM colaboradores.organizacion WHERE activa"))
    p = await conn.execute(text("SELECT nombre, id FROM colaboradores.planta WHERE activa"))
    return [(c, int(i)) for c, i in o.all()], [(n, int(i)) for n, i in p.all()]


async def existente(conn: AsyncConnection, numero_empleado: str) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            "SELECT id, estatus, celular_hash, fecha_ingreso FROM colaboradores.colaborador "
            "WHERE numero_empleado = :n FOR UPDATE"
        ),
        {"n": numero_empleado},
    )
    f = r.mappings().first()
    return dict(f) if f else None
