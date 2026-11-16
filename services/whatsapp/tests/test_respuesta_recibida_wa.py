"""T-218 (parte 1): el bot emite ``wa.respuesta_recibida`` (CC-REQ-115; deuda de T-217).

El aviso va al ``outbox`` en la misma transacción del mensaje, con ``evento_id`` determinista
(``uuid5`` del ``wamid``) y solo ids: ni contenido, ni nombre, ni número.
"""

import dataclasses
import uuid

import pytest
from ayudantes_whatsapp import (
    CELULAR,
    KmsFalso,
    crear_notificacion_enviada,
    eventos,
    sql,
)
from cc_common import outbox as cc_outbox
from cc_whatsapp.bot.contexto import Mensaje
from cc_whatsapp.bot.conversacion import EVENTO_RESPUESTA, evento_id_de, procesar
from cc_whatsapp.cifrado import Cifrador

pytestmark = pytest.mark.docker


async def decir(bot, texto, *, wamid=None, celular=CELULAR):
    return await procesar(bot, Mensaje(wamid or f"wamid.R{uuid.uuid4().hex}", celular, texto))


def respuestas(datos):
    return eventos(datos, EVENTO_RESPUESTA)


async def test_la_respuesta_de_un_colaborador_registrado_emite_el_evento_con_solo_ids(bot, datos):
    assert await decir(bot, "Gracias, ahí estaré", wamid="wamid.A1") == "IGNORADO"
    [carga] = respuestas(datos)
    assert set(carga) == {"empresa_id", "colaborador_id", "conversacion_id", "recibido_en"}
    assert carga["empresa_id"] == datos["empresa"]
    assert carga["colaborador_id"] == datos["colaborador"]
    assert carga["conversacion_id"] is None  # no recibió ninguna notificación reciente
    [(evento_id, tipo, destino_tipo, empresa)] = sql(
        datos,
        "SELECT evento_id, tipo, destino_tipo, empresa_id FROM whatsapp.outbox WHERE tipo = %s",
        (EVENTO_RESPUESTA,),
    )
    assert str(evento_id) == str(evento_id_de("wamid.A1"))
    assert (tipo, destino_tipo, empresa) == (EVENTO_RESPUESTA, "EVENTBRIDGE", datos["empresa"])
    texto = str(sql(datos, "SELECT * FROM whatsapp.outbox WHERE tipo = %s", (EVENTO_RESPUESTA,)))
    assert "Gracias" not in texto and CELULAR[-10:] not in texto and "Ana" not in texto


async def test_un_numero_no_registrado_no_emite_el_evento(bot, datos):
    assert await decir(bot, "hola", celular="5219999999999") == "IGNORADO"
    assert await decir(bot, "constancia", celular="5219999999999") == "SIN_ACCESO"
    assert respuestas(datos) == []


async def test_repetir_el_mensaje_no_duplica_el_evento(bot, datos):
    assert await decir(bot, "ok", wamid="wamid.B1") == "IGNORADO"
    assert await decir(bot, "ok", wamid="wamid.B1") == "DUPLICADO"
    assert len(respuestas(datos)) == 1
    assert await decir(bot, "ok", wamid="wamid.B2") == "IGNORADO"  # otro mensaje, otro evento
    assert len(respuestas(datos)) == 2


async def test_la_palabra_clave_es_del_bot_y_no_cuenta_como_respuesta(bot, datos):
    assert await decir(bot, "constancia") == "CODIGO_ENVIADO"
    assert respuestas(datos) == []


async def test_si_falla_el_outbox_el_mensaje_tampoco_queda_registrado(bot, datos, monkeypatch):
    original = cc_outbox.escribir

    async def falla(conn, esquema, **kw):
        if kw.get("tipo") == EVENTO_RESPUESTA:
            raise RuntimeError("outbox caído")
        return await original(conn, esquema, **kw)

    monkeypatch.setattr(cc_outbox, "escribir", falla)
    with pytest.raises(RuntimeError):
        await decir(bot, "hola", wamid="wamid.C1")
    monkeypatch.undo()
    assert sql(datos, "SELECT count(*) FROM whatsapp.mensaje_whatsapp") == [
        (0,)
    ]  # misma transacción
    assert await decir(bot, "hola", wamid="wamid.C1") == "IGNORADO"  # SQS lo reentrega y se rehace
    assert len(respuestas(datos)) == 1


async def test_con_una_notificacion_reciente_nace_la_conversacion_del_chat_y_el_evento_la_liga(
    bot, datos
):
    crear_notificacion_enviada(datos, datos["colaborador"])
    assert await decir(bot, "Sí, voy", wamid="wamid.D1") == "RESPUESTA"
    [conv] = sql(
        datos,
        "SELECT id, estado, verificada, origen, ultimo_mensaje_entrante_at IS NOT NULL "
        "FROM whatsapp.conversacion_whatsapp",
    )
    assert conv[1:] == ("ACTIVA", False, "NOTIFICACION", True)
    [carga] = respuestas(datos)
    assert carga["conversacion_id"] == conv[0]
    # el mensaje entrante queda ligado a la conversación, sin contenido (el bot no tiene cifrador)
    [(cid, contenido)] = sql(
        datos,
        "SELECT conversacion_id, contenido_cifrado FROM whatsapp.mensaje_whatsapp "
        "WHERE direccion = 'ENTRANTE'",
    )
    assert cid == conv[0] and contenido is None
    # otra respuesta usa la misma conversación (no abre una segunda)
    assert await decir(bot, "gracias") == "IGNORADO"
    assert sql(datos, "SELECT count(*) FROM whatsapp.conversacion_whatsapp") == [(1,)]
    assert {c["conversacion_id"] for c in respuestas(datos)} == {conv[0]}
    # y la palabra clave la pasa a verificación, como dice el diseño
    assert await decir(bot, "constancia") == "CODIGO_ENVIADO"


async def test_una_notificacion_antigua_o_fallida_no_abre_conversacion(bot, datos):
    crear_notificacion_enviada(datos, datos["colaborador"], hace="30 hours")
    crear_notificacion_enviada(datos, datos["colaborador"], estado="FALLIDO")
    assert await decir(bot, "hola") == "IGNORADO"
    assert sql(datos, "SELECT count(*) FROM whatsapp.conversacion_whatsapp") == [(0,)]


async def test_un_colaborador_no_elegible_no_abre_conversacion(bot, datos):
    bot.colaboradores.registrar(
        CELULAR, datos["colaborador"], elegible=False, motivo="SIN_CONSENTIMIENTO"
    )
    crear_notificacion_enviada(datos, datos["colaborador"])
    assert await decir(bot, "hola") == "IGNORADO"
    assert sql(datos, "SELECT count(*) FROM whatsapp.conversacion_whatsapp") == [(0,)]


async def test_con_cifrador_el_texto_de_la_respuesta_se_guarda_cifrado_y_ligado_a_su_fila(
    bot, datos
):
    ctx = dataclasses.replace(bot, cifrador=Cifrador(KmsFalso(), "llave-de-prueba"))
    crear_notificacion_enviada(datos, datos["colaborador"])
    privado = "Llego tarde por una cita médica"
    assert await procesar(ctx, Mensaje("wamid.E1", CELULAR, privado)) == "RESPUESTA"
    [(blob, clave)] = sql(
        datos,
        "SELECT contenido_cifrado, clave_idempotencia FROM whatsapp.mensaje_whatsapp "
        "WHERE direccion = 'ENTRANTE'",
    )
    assert blob is not None and privado.encode() not in bytes(blob)
    assert privado not in str(sql(datos, "SELECT * FROM whatsapp.outbox"))
    assert privado not in str(sql(datos, "SELECT detalle FROM auditoria.bitacora"))
    # descifra con su fila y su empresa; con otra clave de idempotencia u otra empresa, no
    from cc_common.crypto import ErrorCifrado
    from cc_common.db import transaccion

    async with transaccion(ctx.motor, datos["empresa"]) as conn:
        async with ctx.cifrador.transaccion(conn, datos["empresa"]):
            assert (
                ctx.cifrador.descifrar(bytes(blob), empresa_id=datos["empresa"], clave=clave)
                == privado
            )
            with pytest.raises(ErrorCifrado):
                ctx.cifrador.descifrar(
                    bytes(blob), empresa_id=datos["empresa"], clave=str(uuid.uuid4())
                )
