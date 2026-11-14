"""Acceso a ``identidad.usuario`` e ``identidad.invitacion_registro`` (design.md §2.2, §8.1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class FilaUsuario:
    id: int
    empresa_id: int
    nombre: str
    correo: str
    rol: str
    activo: bool
    ultima_actividad: datetime | None


async def por_sub(conn: AsyncConnection, sub: str) -> FilaUsuario | None:
    fila = (
        (
            await conn.execute(
                text(
                    "SELECT id, empresa_id, nombre, correo, rol, activo, ultima_actividad "
                    "FROM identidad.usuario WHERE cognito_sub = :sub"
                ),
                {"sub": sub},
            )
        )
        .mappings()
        .first()
    )
    return FilaUsuario(**fila) if fila else None


async def tocar_actividad(conn: AsyncConnection, usuario_id: int) -> None:
    """Actualiza ``ultima_actividad`` como máximo una vez por minuto (design.md §11.2)."""
    await conn.execute(
        text(
            "UPDATE identidad.usuario SET ultima_actividad = now() WHERE id = :id "
            "AND (ultima_actividad IS NULL OR ultima_actividad < now() - interval '1 minute')"
        ),
        {"id": usuario_id},
    )


async def crear_invitacion(
    conn: AsyncConnection,
    *,
    empresa_id: int,
    codigo_hash: bytes,
    horas: int,
    creada_por: int,
    correo_destino: str | None,
) -> tuple[int, datetime]:
    fila = (
        await conn.execute(
            text(
                "INSERT INTO identidad.invitacion_registro "
                "(empresa_id, codigo_hash, correo_destino, creada_por_usuario_id, fecha_expira) "
                "VALUES (:e, :h, :c, :u, now() + make_interval(hours => :horas)) "
                "RETURNING id, fecha_expira"
            ),
            {
                "e": empresa_id,
                "h": codigo_hash,
                "c": correo_destino,
                "u": creada_por,
                "horas": horas,
            },
        )
    ).one()
    return int(fila[0]), fila[1]


async def login_ya_registrado(conn: AsyncConnection, empresa_id: int, jti: str) -> bool:
    r = await conn.execute(
        text(
            "SELECT 1 FROM auditoria.bitacora WHERE empresa_id = :e AND accion = 'LOGIN' "
            "AND detalle ->> 'jti' = :jti LIMIT 1"
        ),
        {"e": empresa_id, "jti": jti},
    )
    return r.first() is not None


@dataclass(frozen=True)
class FilaUsuarioLista:
    id: int
    nombre: str
    correo: str
    rol: str
    activo: bool
    ultima_actividad: datetime | None
    fecha_creacion: datetime
    cognito_sub: str


async def listar(conn: AsyncConnection) -> list[FilaUsuarioLista]:
    """Usuarios de la empresa en curso (la política RLS filtra por empresa)."""
    filas = (
        (
            await conn.execute(
                text(
                    "SELECT id, nombre, correo, rol, activo, ultima_actividad, fecha_creacion, "
                    "cognito_sub FROM identidad.usuario ORDER BY activo DESC, lower(nombre), id"
                )
            )
        )
        .mappings()
        .all()
    )
    return [FilaUsuarioLista(**f) for f in filas]


async def bloquear_activos(conn: AsyncConnection) -> list[int]:
    """Bloquea las filas de usuarios activos para serializar desactivaciones simultáneas."""
    r = await conn.execute(
        text("SELECT id FROM identidad.usuario WHERE activo ORDER BY id FOR UPDATE")
    )
    return [int(x[0]) for x in r.all()]


async def por_id(conn: AsyncConnection, usuario_id: int) -> FilaUsuarioLista | None:
    fila = (
        (
            await conn.execute(
                text(
                    "SELECT id, nombre, correo, rol, activo, ultima_actividad, fecha_creacion, "
                    "cognito_sub FROM identidad.usuario WHERE id = :id"
                ),
                {"id": usuario_id},
            )
        )
        .mappings()
        .first()
    )
    return FilaUsuarioLista(**fila) if fila else None


async def marcar_inactivo(conn: AsyncConnection, usuario_id: int) -> None:
    await conn.execute(
        text("UPDATE identidad.usuario SET activo = false WHERE id = :id"), {"id": usuario_id}
    )
