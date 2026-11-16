"""Atención de un mensaje entrante (design.md §7.1, §7.2, §7.4; CC-REQ-071 a 076, 091).

Todo el mensaje se procesa en **una** transacción: el registro del mensaje (que lo hace idempotente
por ``wamid``), los contadores, los cambios de la conversación y las respuestas en el ``outbox``.
Si algo falla, nada queda a medias y SQS reentrega el mensaje. Los avisos a RH se publican después
de confirmar.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from cc_common import bitacora, outbox
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


RESPUESTA = "RESPUESTA"  # respuesta a una notificación: abre la conversación del chat de RH
_ESPACIO_EVENTO = uuid.UUID("0b6f4a52-3c1d-4e7b-8f0a-6d9c2e1b7a34")
EVENTO_RESPUESTA = "wa.respuesta_recibida"


def evento_id_de(wamid: str) -> uuid.UUID:
    """``evento_id`` determinista del aviso de respuesta: repetir el mensaje no lo duplica."""
    return uuid.uuid5(_ESPACIO_EVENTO, wamid)


async def _nueva_conversacion_de_respuesta(t: Turno, busqueda) -> dict | None:
    """Un colaborador elegible que escribe sin conversación abierta y sin la palabra clave, y que
    recibió una notificación dentro de la ventana de 24 horas, está respondiéndola: nace una
    conversación ACTIVA, no verificada, de origen NOTIFICACION (design.md §7.1; no da acceso a
    datos). Un no elegible, o quien no recibió nada reciente, no abre nada."""
    if not (busqueda.encontrado and busqueda.elegible):
        return None
    if not await repo.notificacion_reciente(
        t.conn, busqueda.colaborador_id, t.ctx.cfg.ventana_horas
    ):
        return None
    return await repo.crear(
        t.conn, empresa_id=t.empresa_id, huella=t.huella,
        colaborador_id=busqueda.colaborador_id, estado=estados.ACTIVA, origen="NOTIFICACION",
    )  # fmt: skip


async def _guardar_para_chat(t: Turno, conv: dict, busqueda) -> None:
    """Liga el mensaje al chat de RH y, si hay cifrador, guarda su texto cifrado (AAD: la
    ``clave_idempotencia`` del mensaje y la empresa). Nunca se registra en logs."""
    cifrado = None
    ctx = t.ctx
    if ctx.cifrador is not None and t.msg.texto:
        async with ctx.cifrador.transaccion(t.conn, t.empresa_id):
            cifrado = ctx.cifrador.cifrar(
                t.msg.texto, empresa_id=t.empresa_id, clave=repo.clave_de(t.msg.wamid)
            )
    await repo.vincular_entrante(
        t.conn, t.msg.wamid, conversacion_id=conv["id"],
        colaborador_id=busqueda.colaborador_id, contenido_cifrado=cifrado,
    )  # fmt: skip


async def _avisar_respuesta(t: Turno, busqueda, conversacion_id: int | None) -> None:
    """``wa.respuesta_recibida`` (CC-REQ-115) en la MISMA transacción del mensaje. Solo ids y la
    hora: ni contenido, ni nombre, ni número."""
    await outbox.escribir(
        t.conn,
        "whatsapp",
        destino_tipo="EVENTBRIDGE",
        destino=t.ctx.cfg.bus_eventos,
        tipo=EVENTO_RESPUESTA,
        payload={
            "empresa_id": t.empresa_id,
            "colaborador_id": busqueda.colaborador_id,
            "conversacion_id": conversacion_id,
            "recibido_en": datetime.now(UTC).isoformat(),
        },
        empresa_id=t.empresa_id,
        evento_id=evento_id_de(t.msg.wamid),
    )


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
                conv = await _nueva_conversacion_de_respuesta(t, busqueda)
                resultado = RESPUESTA if conv is not None else "IGNORADO"
            else:
                resultado = await _sin_conversacion(t, busqueda)
        else:
            resultado = await _con_conversacion(t, busqueda, conv)
        # Respuesta libre de un colaborador registrado (no es parte del bot: ni palabra clave, ni
        # verificación, ni menú): se liga al chat de RH y se avisa a `notificaciones`. Un número
        # no registrado (``encontrado = False``) nunca emite el evento.
        if busqueda.encontrado and resultado in (RESPUESTA, "IGNORADO"):
            chat = conv if (conv and conv["estado"] == estados.ACTIVA) else None
            if chat is not None and not chat["verificada"]:
                await _guardar_para_chat(t, chat, busqueda)
            else:
                chat = None
            await _avisar_respuesta(t, busqueda, chat["id"] if chat else None)
        pendientes = t.alertas
    for tipo_alerta, datos in pendientes:  # después de confirmar; de mejor esfuerzo
        await ctx.alertas.avisar(cfg.empresa_id, tipo_alerta, datos)
    return resultado
