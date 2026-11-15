"""Solicitud de la constancia desde la conversación (design.md §7.1, §7.4; CC-REQ-075, 076, 091).

La solicitud se crea al mostrar el menú (INT-CON-02) y queda ligada a la conversación
(``solicitud_constancia_id``). Si la persona abandona antes de elegir, el cierre por inactividad la
cancela (INT-CON-05). Al elegir se cuenta contra el límite diario, se fija la plantilla (INT-CON-03)
y se pide generar (INT-CON-04): con datos faltantes responde "falta información" (RH recibe el aviso
desde `constancias`) y con todo completo avisa que la constancia viene en camino.
"""

from __future__ import annotations

import logging

from cc_whatsapp.bot import mensajes_es as M
from cc_whatsapp.bot.contexto import Turno
from cc_whatsapp.clientes import RespuestaError
from cc_whatsapp.repos import conversaciones as repo
from cc_whatsapp.servicios import antiabuso, salida

log = logging.getLogger("cc.bot")


async def _cancelar_en_silencio(t: Turno, solicitud_id: int | None) -> None:
    if solicitud_id is None:
        return
    try:
        await t.ctx.constancias.cancelar(t.empresa_id, solicitud_id)
    except RespuestaError:  # ya no estaba en RECIBIDA: no hay nada que cancelar
        log.info("la solicitud ya no se podía cancelar")


async def abrir(t: Turno, conv: dict, *, reiniciar: bool) -> dict | None:
    """Deja la conversación con una solicitud ``RECIBIDA``. ``None`` si ya hay una en proceso."""
    if conv.get("solicitud_constancia_id") and not reiniciar:
        return conv
    await _cancelar_en_silencio(t, conv.get("solicitud_constancia_id"))
    nombre = await t.ctx.colaboradores.nombre(t.empresa_id, conv["colaborador_id"])
    try:
        sid = await t.ctx.constancias.crear_solicitud(
            t.empresa_id, conv["colaborador_id"], conv["id"], nombre
        )
    except RespuestaError as e:
        if e.status == 409:
            await repo.fijar_solicitud(t.conn, conv["id"], None)
            await salida.enviar(
                t.conn, t.ctx.cfg, wa_id=t.msg.wa_id, conversacion_id=conv["id"],
                colaborador_id=conv["colaborador_id"], texto=M.SOLICITUD_EN_PROCESO,
            )  # fmt: skip
            return None
        raise
    await repo.fijar_solicitud(t.conn, conv["id"], sid)
    return {**conv, "solicitud_constancia_id": sid}


async def elegir(t: Turno, conv: dict, plantilla_id: int) -> str:
    cfg = t.ctx.cfg
    conv_id, colab = conv["id"], conv["colaborador_id"]
    conv = await abrir(t, conv, reiniciar=False)
    if conv is None:
        return "SOLICITUD_EN_PROCESO"
    sid = conv["solicitud_constancia_id"]

    async def responder(texto: str) -> None:
        await salida.enviar(
            t.conn, cfg, wa_id=t.msg.wa_id, conversacion_id=conv_id, colaborador_id=colab,
            texto=texto,
        )  # fmt: skip

    if not await antiabuso.solicitud_permitida(t.conn, cfg, t.huella):
        await _cancelar_en_silencio(t, sid)
        await repo.fijar_solicitud(t.conn, conv_id, None)
        await responder(M.LIMITE_DIA)
        return "LIMITE_DIARIO"
    try:
        await t.ctx.constancias.elegir_plantilla(t.empresa_id, sid, plantilla_id)
        await t.ctx.constancias.generar(t.empresa_id, sid)
    except RespuestaError as e:
        if e.status == 422 and e.codigo == "CAMPOS_FALTANTES":
            await repo.fijar_solicitud(t.conn, conv_id, None)  # quedó FALLIDA: RH recibe el aviso
            await responder(M.FALTA_INFORMACION)
            return "CAMPOS_FALTANTES"
        if e.status in (404, 409):
            await _cancelar_en_silencio(t, sid)
            await repo.fijar_solicitud(t.conn, conv_id, None)
            await responder(M.PLANTILLA_NO_DISPONIBLE)
            return "PLANTILLA_NO_DISPONIBLE"
        raise
    await repo.fijar_solicitud(t.conn, conv_id, None)  # ya se genera: nada que cancelar
    await responder(M.PREPARANDO)
    return "SOLICITADA"
