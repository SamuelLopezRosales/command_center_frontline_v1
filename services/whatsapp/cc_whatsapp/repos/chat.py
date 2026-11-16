"""Consultas del chat de RH (WAP-01 a WAP-05) sobre ``conversacion_whatsapp`` y
``mensaje_whatsapp``. Todo corre en la transacción de una empresa (RLS). Ninguna consulta lee ni
devuelve el celular: la conversación solo guarda su huella."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

COLUMNAS_CONVERSACION = (
    "c.id, c.colaborador_id, c.estado, c.origen, c.verificada, c.ultimo_mensaje_entrante_at, "
    "c.fecha_ultimo_mensaje, c.asignada_a_usuario_id, c.fecha_asignacion, "
    "(SELECT max(m.origen_id) FROM whatsapp.mensaje_whatsapp m "
    " WHERE m.colaborador_id = c.colaborador_id AND m.direccion = 'SALIENTE' "
    " AND m.origen_tipo = 'NOTIFICACION') AS ultima_notificacion_id"
)


async def listar(
    conn: AsyncConnection,
    *,
    notificacion_id: int | None,
    asignada_a: int | None,
    estado: str | None,
    cursor: tuple[datetime, int] | None,
    limite: int,
) -> list[dict[str, Any]]:
    """Conversaciones con colaborador, de la más reciente a la más antigua (keyset)."""
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS_CONVERSACION} FROM whatsapp.conversacion_whatsapp c "  # noqa: S608
            "WHERE c.colaborador_id IS NOT NULL "
            "AND (CAST(:estado AS text) IS NULL OR c.estado = :estado) "
            "AND (CAST(:asignada AS bigint) IS NULL OR c.asignada_a_usuario_id = :asignada) "
            "AND (CAST(:nid AS bigint) IS NULL OR EXISTS ("
            "  SELECT 1 FROM whatsapp.mensaje_whatsapp n WHERE n.colaborador_id = c.colaborador_id "
            "  AND n.direccion = 'SALIENTE' AND n.origen_tipo = 'NOTIFICACION' "
            "  AND n.origen_id = :nid)) "
            "AND (CAST(:cf AS timestamptz) IS NULL "
            "     OR (c.fecha_ultimo_mensaje, c.id) < (CAST(:cf AS timestamptz), :ci)) "
            "ORDER BY c.fecha_ultimo_mensaje DESC, c.id DESC LIMIT :lim"
        ),
        {
            "estado": estado,
            "asignada": asignada_a,
            "nid": notificacion_id,
            "cf": cursor[0] if cursor else None,
            "ci": cursor[1] if cursor else 0,
            "lim": limite,
        },
    )
    return [dict(f) for f in r.mappings().all()]


async def obtener(conn: AsyncConnection, conversacion_id: int) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS_CONVERSACION} FROM whatsapp.conversacion_whatsapp c "  # noqa: S608
            "WHERE c.id = :id AND c.colaborador_id IS NOT NULL"
        ),
        {"id": conversacion_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def mensajes(
    conn: AsyncConnection,
    conversacion: dict[str, Any],
    *,
    cursor: tuple[datetime, int] | None,
    limite: int,
) -> list[dict[str, Any]]:
    """Hilo de la conversación, del más reciente al más antiguo. Incluye lo que RH y el colaborador
    escribieron en ella y las notificaciones enviadas al colaborador que aún no tenían conversación
    (el contexto de su respuesta); no incluye los mensajes del bot (verificación, menú, constancias)
    porque llevan códigos y datos personales."""
    r = await conn.execute(
        text(
            "SELECT id, direccion, tipo, plantilla_meta, contenido_cifrado, clave_idempotencia, "
            "estado, error_codigo, origen_tipo, origen_id, enviado_por_usuario_id, fecha_hora "
            "FROM whatsapp.mensaje_whatsapp "
            "WHERE ((conversacion_id = :c AND (direccion = 'ENTRANTE' "
            "                                  OR origen_tipo IN ('CHAT', 'NOTIFICACION'))) "
            "       OR (conversacion_id IS NULL AND colaborador_id = :col "
            "           AND direccion = 'SALIENTE' AND origen_tipo = 'NOTIFICACION')) "
            "AND (CAST(:cf AS timestamptz) IS NULL "
            "     OR (fecha_hora, id) < (CAST(:cf AS timestamptz), :ci)) "
            "ORDER BY fecha_hora DESC, id DESC LIMIT :lim"
        ),
        {
            "c": conversacion["id"],
            "col": conversacion["colaborador_id"],
            "cf": cursor[0] if cursor else None,
            "ci": cursor[1] if cursor else 0,
            "lim": limite,
        },
    )
    return [dict(f) for f in r.mappings().all()]


async def insertar_saliente(
    conn: AsyncConnection,
    *,
    empresa_id: int,
    conversacion_id: int,
    colaborador_id: int,
    clave: uuid.UUID,
    tipo: str,
    plantilla: str | None,
    contenido_cifrado: bytes,
    usuario_id: int,
) -> int:
    """Fila del mensaje de RH en ``ENCOLADO``: el ``enviador`` la encuentra por la clave y la
    avanza (su ``INSERT ... ON CONFLICT DO NOTHING`` no la toca)."""
    r = await conn.execute(
        text(
            "INSERT INTO whatsapp.mensaje_whatsapp (empresa_id, conversacion_id, colaborador_id, "
            "direccion, tipo, plantilla_meta, contenido_cifrado, clave_idempotencia, estado, "
            "origen_tipo, origen_id, enviado_por_usuario_id) "
            "VALUES (:e, :c, :col, 'SALIENTE', :t, :p, :b, :k, 'ENCOLADO', 'CHAT', :c, :u) "
            "RETURNING id"
        ),
        {
            "e": empresa_id,
            "c": conversacion_id,
            "col": colaborador_id,
            "t": tipo,
            "p": plantilla,
            "b": contenido_cifrado,
            "k": clave,
            "u": usuario_id,
        },
    )
    return int(r.scalar_one())


async def usuario_asignable(conn: AsyncConnection, empresa_id: int, usuario_id: int) -> bool:
    r = await conn.execute(
        text("SELECT whatsapp.usuario_asignable(:e, :u)"), {"e": empresa_id, "u": usuario_id}
    )
    return bool(r.scalar_one())


async def asignar(conn: AsyncConnection, conversacion_id: int, usuario_id: int) -> None:
    await conn.execute(
        text(
            "UPDATE whatsapp.conversacion_whatsapp SET asignada_a_usuario_id = :u, "
            "fecha_asignacion = now() WHERE id = :id"
        ),
        {"id": conversacion_id, "u": usuario_id},
    )


async def tocar_saliente(conn: AsyncConnection, conversacion_id: int) -> None:
    """RH escribió: la conversación sube en el listado."""
    await conn.execute(
        text(
            "UPDATE whatsapp.conversacion_whatsapp SET fecha_ultimo_mensaje = now() WHERE id = :id"
        ),
        {"id": conversacion_id},
    )
