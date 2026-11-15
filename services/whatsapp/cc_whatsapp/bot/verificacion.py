"""Verificación del colaborador (design.md §7.2; CC-REQ-073, 074, 159).

1. El **aviso de privacidad** va antes de todo.
2. El **código** es de seis dígitos (``secrets.randbelow``), caduca a los 10 minutos y es de un solo
   uso. En la base solo se guarda ``HMAC-SHA256(llave, conversacion_id || código)``.
3. El **dato adicional** (últimos 4 del NSS o día/mes de ingreso) lo valida `colaboradores`
   (INT-COL-03). Cada respuesta con forma válida cuenta un intento; el tercer fallo bloquea la
   conversación 24 horas y avisa a RH. Un código vencido envía otro **sin** contar intento.
"""

from __future__ import annotations

import secrets

from cc_common.crypto import hmac_texto, iguales

from cc_whatsapp.bot import maquina_estados as estados
from cc_whatsapp.bot import mensajes_es as M
from cc_whatsapp.bot import texto
from cc_whatsapp.bot.contexto import Turno
from cc_whatsapp.repos import conversaciones as repo
from cc_whatsapp.servicios import alertas, salida


def generar_codigo() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def hmac_codigo(llave: bytes, conversacion_id: int, codigo: str) -> bytes:
    return hmac_texto(llave, f"{conversacion_id}||{codigo}")


async def _emitir_codigo(t: Turno, conv: dict, prefijo: str | None = None) -> None:
    """Invalida los códigos anteriores, guarda el nuevo (solo su HMAC) y lo envía."""
    codigo = generar_codigo()
    await repo.invalidar_codigos(t.conn, conv["id"])
    await repo.guardar_codigo(
        t.conn,
        empresa_id=t.empresa_id,
        conversacion_id=conv["id"],
        codigo_hmac=hmac_codigo(t.ctx.llave_codigos, conv["id"], codigo),
        minutos=t.ctx.cfg.codigo_minutos,
    )
    desafio = await t.ctx.colaboradores.desafio(t.empresa_id, conv["colaborador_id"])
    cuerpo = M.codigo_y_desafio(codigo, desafio)
    await salida.enviar(
        t.conn, t.ctx.cfg, wa_id=t.msg.wa_id, conversacion_id=conv["id"],
        colaborador_id=conv["colaborador_id"], texto=f"{prefijo} {cuerpo}" if prefijo else cuerpo,
        proposito="VERIFICACION", origen_tipo="VERIFICACION",
    )  # fmt: skip


async def iniciar(t: Turno, conv: dict) -> str:
    """Aviso de privacidad primero y después el código con su desafío."""
    await salida.enviar(
        t.conn, t.ctx.cfg, wa_id=t.msg.wa_id, conversacion_id=conv["id"],
        colaborador_id=conv["colaborador_id"],
        texto=M.aviso_privacidad(t.ctx.cfg.aviso_privacidad_url),
        proposito="VERIFICACION", origen_tipo="VERIFICACION",
    )  # fmt: skip
    await _emitir_codigo(t, conv)
    return "CODIGO_ENVIADO"


async def responder(t: Turno, conv: dict, menu) -> str:
    """Atiende un mensaje de una conversación ``VERIFICANDO``. ``menu`` es ``menu.mostrar``."""
    if texto.es_palabra_clave(t.msg.texto):  # empezar de nuevo: otro código, sin contar intento
        await _emitir_codigo(t, conv)
        return "CODIGO_REENVIADO"
    vigente = await repo.codigo_vigente(t.conn, conv["id"])
    if vigente is None or vigente["expirado"]:
        await _emitir_codigo(t, conv, prefijo=M.CODIGO_VENCIDO)
        return "CODIGO_VENCIDO"
    leido = texto.leer_respuesta_de_verificacion(t.msg.texto)
    if leido is None:
        await salida.enviar(
            t.conn, t.ctx.cfg, wa_id=t.msg.wa_id, conversacion_id=conv["id"],
            texto=M.FORMATO_VERIFICACION, proposito="VERIFICACION", origen_tipo="VERIFICACION",
        )  # fmt: skip
        return "FORMATO_INVALIDO"
    codigo, dato = leido
    intentos = await repo.sumar_intento(t.conn, conv["id"])
    codigo_ok = iguales(
        hmac_codigo(t.ctx.llave_codigos, conv["id"], codigo), bytes(vigente["codigo_hmac"])
    )
    dato_ok = await t.ctx.colaboradores.verificar(t.empresa_id, conv["colaborador_id"], dato)
    if codigo_ok and dato_ok:
        estados.validar(conv["estado"], estados.ACTIVA)
        await repo.usar_codigo(t.conn, vigente["id"])
        await repo.cambiar_estado(t.conn, conv["id"], estados.ACTIVA, verificada=True)
        conv = {**conv, "estado": estados.ACTIVA, "verificada": True}
        return "VERIFICADO:" + await menu(t, conv)
    if intentos >= t.ctx.cfg.intentos_verificacion:
        estados.validar(conv["estado"], estados.BLOQUEADA)
        await repo.cambiar_estado(
            t.conn, conv["id"], estados.BLOQUEADA, bloqueo_horas=t.ctx.cfg.bloqueo_horas
        )
        t.alertas.append((alertas.ACCESO_BLOQUEADO, {"colaborador_id": conv["colaborador_id"]}))
        await salida.enviar(
            t.conn, t.ctx.cfg, wa_id=t.msg.wa_id, conversacion_id=conv["id"], texto=M.BLOQUEADO,
            proposito="RECHAZO_BOT",
        )  # fmt: skip
        return "BLOQUEADA"
    await salida.enviar(
        t.conn, t.ctx.cfg, wa_id=t.msg.wa_id, conversacion_id=conv["id"],
        texto=M.DATOS_NO_COINCIDEN, proposito="VERIFICACION", origen_tipo="VERIFICACION",
    )  # fmt: skip
    return "DATOS_INCORRECTOS"
