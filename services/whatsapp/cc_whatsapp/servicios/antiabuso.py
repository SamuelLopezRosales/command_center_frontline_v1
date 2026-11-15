"""Antiabuso por número (design.md §7.5, DS-17): 20 mensajes por minuto y 5 solicitudes de
constancia por día. Los contadores viven en ``uso_numero`` (ventana fija por minuto o por día de
México), así que valen aunque haya varias tareas del worker."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection

from cc_whatsapp.repos import conversaciones as repo


async def mensaje_permitido(conn: AsyncConnection, cfg, huella: bytes) -> tuple[bool, bool]:
    """``(permitido, primer_exceso)``. Cuenta el mensaje; ``primer_exceso`` es el primero que pasa
    del límite (el único al que se le avisa)."""
    total = await repo.sumar_uso(conn, cfg.empresa_id, huella, "MENSAJE")
    return total <= cfg.limite_mensajes_minuto, total == cfg.limite_mensajes_minuto + 1


async def solicitud_permitida(conn: AsyncConnection, cfg, huella: bytes) -> bool:
    total = await repo.sumar_uso(conn, cfg.empresa_id, huella, "SOLICITUD")
    return total <= cfg.limite_solicitudes_dia
