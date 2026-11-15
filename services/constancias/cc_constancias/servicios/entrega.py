"""Enlaces de descarga de un solo uso (CON-20 y CON-21; design.md §5.6; CC-REQ-084).

El token tiene 256 bits aleatorios; solo se guarda su SHA-256 y caduca a las 24 horas. Entrar a la
página (CON-20) **no** lo consume, para que las vistas previas de enlaces no lo gasten; la descarga
(CON-21) lo consume con un ``UPDATE ... WHERE usado_en IS NULL`` atómico, así que dos descargas
simultáneas no pueden usarlo ambas. Las rutas son públicas y no conocen la empresa: se resuelven con
funciones de la base que solo ven lo mínimo (``infra/db/rls.sql``).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any

from cc_common import outbox
from cc_common.db import transaccion
from sqlalchemy import text

from cc_constancias.entrega.estrategia import Entrega, EstrategiaEntrega
from cc_constancias.repos import solicitudes as repo

FORMATO_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")  # token_urlsafe(32)


def nuevo_token() -> tuple[str, bytes]:
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode("ascii")).digest()


def hash_de(token: str) -> bytes | None:
    """``None`` si el texto no tiene la forma de un token (no se consulta la base)."""
    if not FORMATO_TOKEN.match(token):
        return None
    return hashlib.sha256(token.encode("ascii")).digest()


async def estado_token(motor: Any, token: str) -> str | None:
    """``VIGENTE``, ``USADO``, ``VENCIDO`` o ``None`` si no existe."""
    h = hash_de(token)
    if h is None:
        return None
    async with transaccion(motor, None) as conn:
        return (
            await conn.execute(text("SELECT constancias.estado_token(:h)"), {"h": h})
        ).scalar_one()


async def consumir_token(motor: Any, token: str) -> dict[str, Any] | None:
    h = hash_de(token)
    if h is None:
        return None
    async with transaccion(motor, None) as conn:
        r = await conn.execute(text("SELECT * FROM constancias.consumir_token(:h)"), {"h": h})
        f = r.mappings().first()
        return dict(f) if f and f["constancia_id"] is not None else None


async def preparar_entrega(
    conn,
    cfg,
    estrategia: EstrategiaEntrega,
    e: Entrega,
    *,
    generado_por: str,
    usuario_id: int | None = None,
) -> None:
    """Crea el token (si la modalidad lo usa) y escribe el mensaje de ``wa-salida`` en el
    ``outbox``, en la misma transacción del que la llama."""
    token = None
    if estrategia.requiere_token:
        token, h = nuevo_token()
        await repo.insertar_token(
            conn,
            empresa_id=e.empresa_id,
            constancia_id=e.constancia_id,
            token_hash=h,
            generado_por=generado_por,
            usuario_id=usuario_id,
        )
    cuerpo = estrategia.mensaje(e, token, cfg.cloudfront_dominio or cfg.dominio)
    await outbox.escribir(
        conn,
        "constancias",
        destino_tipo="SQS",
        destino=cfg.cola_wa_salida_url,
        tipo=cuerpo["tipo"],
        payload=cuerpo,
        empresa_id=e.empresa_id,
        grupo=str(e.colaborador_id),
        deduplicacion=cuerpo["mensaje_uuid"],
    )
