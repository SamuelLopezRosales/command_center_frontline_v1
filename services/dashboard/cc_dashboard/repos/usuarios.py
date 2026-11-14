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
