"""Consultas del bot sobre ``conversacion_whatsapp``, ``codigo_verificacion``, ``uso_numero`` y los
mensajes entrantes. Todo corre en la transacción de una empresa (RLS)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

ABIERTAS = "('VERIFICANDO', 'ACTIVA', 'BLOQUEADA')"
COLUMNAS = (
    "id, colaborador_id, estado, intentos_verificacion, verificada, celular_hash, "
    "solicitud_constancia_id, bloqueada_hasta, (bloqueada_hasta > now()) AS bloqueo_vigente"
)
_ESPACIO_WAMID = uuid.UUID("5d3f7e0a-7c1e-4a55-9a52-0f6d2b6d9c11")


def clave_de(wamid: str) -> uuid.UUID:
    """``clave_idempotencia`` del mensaje entrante: determinista a partir del ``wamid``."""
    return uuid.uuid5(_ESPACIO_WAMID, wamid)


async def registrar_entrante(conn: AsyncConnection, empresa_id: int, wamid: str, tipo: str) -> bool:
    """``False`` si el mensaje ya se había registrado (repetición). No guarda el contenido: en
    la verificación lleva códigos y datos personales."""
    r = await conn.execute(
        text(
            "INSERT INTO whatsapp.mensaje_whatsapp (empresa_id, direccion, tipo, "
            "clave_idempotencia, estado, origen_tipo, id_mensaje_proveedor) "
            "VALUES (:e, 'ENTRANTE', :t, :c, 'RECIBIDO', 'BOT', :w) "
            "ON CONFLICT (clave_idempotencia) DO NOTHING RETURNING id"
        ),
        {"e": empresa_id, "t": tipo, "c": clave_de(wamid), "w": wamid},
    )
    return r.first() is not None


async def abierta_por_hash(conn: AsyncConnection, huella: bytes) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            f"SELECT {COLUMNAS} FROM whatsapp.conversacion_whatsapp "  # noqa: S608
            f"WHERE celular_hash = :h AND estado IN {ABIERTAS} FOR UPDATE"
        ),
        {"h": huella},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def crear(
    conn: AsyncConnection, *, empresa_id: int, huella: bytes, colaborador_id: int, estado: str
) -> dict[str, Any]:
    r = await conn.execute(
        text(
            "INSERT INTO whatsapp.conversacion_whatsapp (empresa_id, colaborador_id, estado, "  # noqa: S608
            "celular_hash, origen, ultimo_mensaje_entrante_at) "
            f"VALUES (:e, :c, :s, :h, 'CONSTANCIA', now()) RETURNING {COLUMNAS}"  # noqa: S608
        ),
        {"e": empresa_id, "c": colaborador_id, "s": estado, "h": huella},
    )
    return dict(r.mappings().one())


async def tocar_entrante(conn: AsyncConnection, conversacion_id: int) -> None:
    await conn.execute(
        text(
            "UPDATE whatsapp.conversacion_whatsapp SET ultimo_mensaje_entrante_at = now(), "
            "fecha_ultimo_mensaje = now() WHERE id = :id"
        ),
        {"id": conversacion_id},
    )


async def cambiar_estado(
    conn: AsyncConnection,
    conversacion_id: int,
    estado: str,
    *,
    verificada: bool | None = None,
    bloqueo_horas: int | None = None,
    colaborador_id: int | None = None,
) -> None:
    await conn.execute(
        text(
            "UPDATE whatsapp.conversacion_whatsapp SET estado = :s, "
            "verificada = COALESCE(CAST(:v AS boolean), verificada), "
            "colaborador_id = COALESCE(CAST(:c AS bigint), colaborador_id), "
            "bloqueada_hasta = CASE WHEN CAST(:bh AS int) IS NULL THEN bloqueada_hasta "
            "                       ELSE now() + make_interval(hours => CAST(:bh AS int)) END, "
            "intentos_verificacion = CASE WHEN :s = 'ACTIVA' THEN 0 ELSE intentos_verificacion END "
            "WHERE id = :id"
        ),
        {"id": conversacion_id, "s": estado, "v": verificada, "c": colaborador_id,
         "bh": bloqueo_horas},
    )  # fmt: skip


async def sumar_intento(conn: AsyncConnection, conversacion_id: int) -> int:
    r = await conn.execute(
        text(
            "UPDATE whatsapp.conversacion_whatsapp "
            "SET intentos_verificacion = intentos_verificacion + 1 WHERE id = :id "
            "RETURNING intentos_verificacion"
        ),
        {"id": conversacion_id},
    )
    return int(r.scalar_one())


async def fijar_solicitud(
    conn: AsyncConnection, conversacion_id: int, solicitud_id: int | None
) -> None:
    await conn.execute(
        text(
            "UPDATE whatsapp.conversacion_whatsapp SET solicitud_constancia_id = :s WHERE id = :id"
        ),
        {"id": conversacion_id, "s": solicitud_id},
    )


# ------------------------------------------------------------------ códigos de verificación


async def invalidar_codigos(conn: AsyncConnection, conversacion_id: int) -> None:
    await conn.execute(
        text(
            "UPDATE whatsapp.codigo_verificacion SET usado = true "
            "WHERE conversacion_id = :c AND NOT usado"
        ),
        {"c": conversacion_id},
    )


async def guardar_codigo(
    conn: AsyncConnection,
    *,
    empresa_id: int,
    conversacion_id: int,
    codigo_hmac: bytes,
    minutos: int,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO whatsapp.codigo_verificacion (empresa_id, conversacion_id, codigo_hmac, "
            "fecha_creacion, fecha_expira) "
            "VALUES (:e, :c, :h, now(), now() + make_interval(mins => :m))"
        ),
        {"e": empresa_id, "c": conversacion_id, "h": codigo_hmac, "m": minutos},
    )


async def codigo_vigente(conn: AsyncConnection, conversacion_id: int) -> dict[str, Any] | None:
    """Último código sin usar, con ``expirado`` calculado por la base."""
    r = await conn.execute(
        text(
            "SELECT id, codigo_hmac, (fecha_expira <= now()) AS expirado "
            "FROM whatsapp.codigo_verificacion WHERE conversacion_id = :c AND NOT usado "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"c": conversacion_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def usar_codigo(conn: AsyncConnection, codigo_id: int) -> None:
    await conn.execute(
        text("UPDATE whatsapp.codigo_verificacion SET usado = true WHERE id = :id"),
        {"id": codigo_id},
    )


# ------------------------------------------------------------------ antiabuso

VENTANA = {
    "MENSAJE": "date_trunc('minute', now())",
    "SOLICITUD": "(date_trunc('day', now() AT TIME ZONE 'America/Mexico_City') "
    "AT TIME ZONE 'America/Mexico_City')",
}


async def sumar_uso(conn: AsyncConnection, empresa_id: int, huella: bytes, tipo: str) -> int:
    r = await conn.execute(
        text(
            "INSERT INTO whatsapp.uso_numero (empresa_id, celular_hash, tipo, ventana, total) "  # noqa: S608
            f"VALUES (:e, :h, :t, {VENTANA[tipo]}, 1) "
            "ON CONFLICT (empresa_id, celular_hash, tipo, ventana) "
            "DO UPDATE SET total = uso_numero.total + 1 RETURNING total"
        ),
        {"e": empresa_id, "h": huella, "t": tipo},
    )
    return int(r.scalar_one())


async def depurar_uso(conn: AsyncConnection) -> int:
    r = await conn.execute(
        text("DELETE FROM whatsapp.uso_numero WHERE ventana < now() - interval '2 days'")
    )
    return r.rowcount


# ------------------------------------------------------------------ cierres


async def inactivas(conn: AsyncConnection, minutos: int) -> list[int]:
    r = await conn.execute(
        text(
            "SELECT id FROM whatsapp.conversacion_whatsapp "
            "WHERE estado IN ('VERIFICANDO', 'ACTIVA') "
            "AND fecha_ultimo_mensaje < now() - make_interval(mins => :m) ORDER BY id LIMIT 200"
        ),
        {"m": minutos},
    )
    return [int(x) for x in r.scalars().all()]


async def bloqueos_vencidos(conn: AsyncConnection) -> int:
    r = await conn.execute(
        text(
            "UPDATE whatsapp.conversacion_whatsapp SET estado = 'CERRADA' "
            "WHERE estado = 'BLOQUEADA' AND bloqueada_hasta <= now()"
        )
    )
    return r.rowcount


async def obtener_para_cierre(conn: AsyncConnection, conversacion_id: int) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            "SELECT id, estado, solicitud_constancia_id FROM whatsapp.conversacion_whatsapp "
            "WHERE id = :id AND estado IN ('VERIFICANDO', 'ACTIVA') FOR UPDATE SKIP LOCKED"
        ),
        {"id": conversacion_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None
