"""Cierre por inactividad y mantenimiento (design.md §7.1; CC-REQ-091, DS-14).

A los 30 minutos sin mensajes, una conversación ``ACTIVA`` o ``VERIFICANDO`` pasa a ``CERRADA`` y
su solicitud sin confirmar queda ``CANCELADA`` (INT-CON-05). Un bloqueo vencido también cierra la
conversación. Cada conversación se cierra en su propia transacción: si `constancias` no responde,
solo esa queda para la siguiente pasada.
"""

from __future__ import annotations

import logging

from cc_common.db import transaccion

from cc_whatsapp.bot import maquina_estados as estados
from cc_whatsapp.bot.contexto import Contexto
from cc_whatsapp.clientes import RespuestaError
from cc_whatsapp.repos import conversaciones as repo

log = logging.getLogger("cc.bot")


async def cerrar_inactivas(ctx: Contexto) -> int:
    cfg = ctx.cfg
    async with transaccion(ctx.motor, cfg.empresa_id) as conn:
        ids = await repo.inactivas(conn, cfg.inactividad_minutos)
        await repo.bloqueos_vencidos(conn)
    cerradas = 0
    for conversacion_id in ids:
        try:
            async with transaccion(ctx.motor, cfg.empresa_id) as conn:
                conv = await repo.obtener_para_cierre(conn, conversacion_id)
                if conv is None:  # otro la tomó o cambió de estado
                    continue
                if conv["solicitud_constancia_id"]:
                    try:
                        await ctx.constancias.cancelar(
                            cfg.empresa_id, conv["solicitud_constancia_id"]
                        )
                    except RespuestaError:  # ya no estaba en RECIBIDA
                        log.info("la solicitud ya no se podía cancelar")
                    await repo.fijar_solicitud(conn, conversacion_id, None)
                estados.validar(conv["estado"], estados.CERRADA)
                await repo.cambiar_estado(conn, conversacion_id, estados.CERRADA)
                cerradas += 1
        except Exception:  # noqa: BLE001
            log.warning("no se pudo cerrar una conversación; se reintenta en la siguiente pasada")
    return cerradas


async def depurar_contadores(ctx: Contexto) -> int:
    async with transaccion(ctx.motor, ctx.cfg.empresa_id) as conn:
        return await repo.depurar_uso(conn)
