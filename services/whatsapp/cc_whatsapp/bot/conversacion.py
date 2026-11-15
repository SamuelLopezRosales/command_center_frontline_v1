"""Atención de un mensaje entrante (design.md §7.1, §7.2, §7.4; CC-REQ-071 a 076, 091).

Todo el mensaje se procesa en **una** transacción: el registro del mensaje (que lo hace idempotente
por ``wamid``), los contadores, los cambios de la conversación y las respuestas en el ``outbox``.
Si algo falla, nada queda a medias y SQS reentrega el mensaje. Los avisos a RH se publican después
de confirmar.
"""

from __future__ import annotations

import logging

from cc_common import bitacora
from cc_common.db import transaccion

from cc_whatsapp.bot import maquina_estados as estados
from cc_whatsapp.bot import mensajes_es as M
from cc_whatsapp.bot import menu, texto, verificacion
from cc_whatsapp.bot.contexto import Contexto, Mensaje, Turno
from cc_whatsapp.repos import conversaciones as repo
from cc_whatsapp.servicios import alertas, antiabuso, salida

log = logging.getLogger("cc.bot")


async def _sin_conversacion(t: Turno, busqueda) -> str:
    """Número sin conversación abierta que escribió la palabra clave."""
    cfg = t.ctx.cfg
    if not busqueda.encontrado:
        await bitacora.registrar(
            t.conn, empresa_id=t.empresa_id, accion="INTENTO_WHATSAPP",
            entidad="conversacion_whatsapp", origen="SISTEMA",
            detalle={"celular_hash": t.huella.hex(), "motivo": "NO_REGISTRADO"},
        )  # fmt: skip
        await salida.enviar(
            t.conn, cfg, wa_id=t.msg.wa_id, texto=M.SIN_ACCESO, proposito=salida.RECHAZO_BOT
        )
        return "SIN_ACCESO"
    if not busqueda.elegible:
        await bitacora.registrar(
            t.conn, empresa_id=t.empresa_id, accion="INTENTO_WHATSAPP",
            entidad="conversacion_whatsapp", colaborador_id=busqueda.colaborador_id,
            origen="SISTEMA",
            detalle={"celular_hash": t.huella.hex(), "motivo": busqueda.motivo or "NO_ELEGIBLE"},
        )  # fmt: skip
        t.alertas.append(
            (alertas.NO_DISPONIBLE, {"colaborador_id": busqueda.colaborador_id,
                                     "motivo": busqueda.motivo})
        )  # fmt: skip
        await salida.enviar(
            t.conn, cfg, wa_id=t.msg.wa_id, texto=M.NO_DISPONIBLE, proposito=salida.RECHAZO_BOT
        )
        return "NO_DISPONIBLE"
    conv = await repo.crear(
        t.conn, empresa_id=t.empresa_id, huella=t.huella,
        colaborador_id=busqueda.colaborador_id, estado=estados.VERIFICANDO,
    )  # fmt: skip
    return await verificacion.iniciar(t, conv)


async def _con_conversacion(t: Turno, busqueda, conv: dict) -> str:
    if conv["estado"] == estados.BLOQUEADA:
        if conv["bloqueo_vigente"]:
            await salida.enviar(
                t.conn, t.ctx.cfg, wa_id=t.msg.wa_id, conversacion_id=conv["id"],
                texto=M.BLOQUEADO, proposito=salida.RECHAZO_BOT,
            )  # fmt: skip
            return "BLOQUEADA"
        estados.validar(conv["estado"], estados.CERRADA)  # venció el bloqueo: empieza de cero
        await repo.cambiar_estado(t.conn, conv["id"], estados.CERRADA)
        if not texto.es_palabra_clave(t.msg.texto):
            return "IGNORADO"
        return await _sin_conversacion(t, busqueda)

    await repo.tocar_entrante(t.conn, conv["id"])
    if conv["estado"] == estados.VERIFICANDO:
        return await verificacion.responder(t, conv, menu.mostrar)
    if not conv["verificada"]:  # nació de la respuesta a una notificación
        if not texto.es_palabra_clave(t.msg.texto):
            return "IGNORADO"
        estados.validar(estados.ACTIVA, estados.VERIFICANDO)
        await repo.cambiar_estado(t.conn, conv["id"], estados.VERIFICANDO)
        return await verificacion.iniciar(t, {**conv, "estado": estados.VERIFICANDO})
    return await menu.atender(t, conv)


async def procesar(ctx: Contexto, msg: Mensaje) -> str:
    """Devuelve el resultado (para las pruebas y las métricas); una falla técnica se propaga."""
    cfg = ctx.cfg
    pendientes: list = []
    async with transaccion(ctx.motor, cfg.empresa_id) as conn:
        tipo = "INTERACTIVO" if msg.interactivo_id else "TEXTO"
        if not await repo.registrar_entrante(conn, cfg.empresa_id, msg.wamid, tipo):
            return "DUPLICADO"
        busqueda = await ctx.colaboradores.buscar_por_celular(cfg.empresa_id, msg.wa_id)
        huella = bytes.fromhex(busqueda.celular_hash)
        t = Turno(ctx, conn, msg, huella)
        permitido, primer_exceso = await antiabuso.mensaje_permitido(conn, cfg, huella)
        if not permitido:
            if primer_exceso:
                await salida.enviar(
                    conn, cfg, wa_id=msg.wa_id, texto=M.DEMASIADOS_MENSAJES,
                    proposito=salida.RECHAZO_BOT,
                )  # fmt: skip
            return "LIMITADO"
        conv = await repo.abierta_por_hash(conn, huella)
        if conv is None:
            if not texto.es_palabra_clave(msg.texto):
                return "IGNORADO"
            resultado = await _sin_conversacion(t, busqueda)
        else:
            resultado = await _con_conversacion(t, busqueda, conv)
        pendientes = t.alertas
    for tipo_alerta, datos in pendientes:  # después de confirmar; de mejor esfuerzo
        await ctx.alertas.avisar(cfg.empresa_id, tipo_alerta, datos)
    return resultado
