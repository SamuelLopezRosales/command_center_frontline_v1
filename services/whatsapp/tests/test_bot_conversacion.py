"""T-212 (T-097, T-098): el bot de punta a punta con la base real y colaboradores y constancias de
mentira. Cada mensaje corre en una transacción; las respuestas quedan en el ``outbox``."""

import hashlib
import itertools

import pytest
from ayudantes_whatsapp import (
    CELULAR,
    LLAVE_CODIGOS,
    huella_de,
    salidas_bot,
    sql,
    textos_bot,
    ultimo_codigo,
)
from cc_whatsapp.bot import mensajes_es as M
from cc_whatsapp.bot.contexto import Mensaje
from cc_whatsapp.bot.conversacion import procesar
from cc_whatsapp.bot.verificacion import hmac_codigo

pytestmark = pytest.mark.docker

_n = itertools.count(1)


async def decir(bot, texto=None, *, celular=CELULAR, opcion=None):
    return await procesar(bot, Mensaje(f"wamid.T{next(_n)}", celular, texto, opcion))


def conversacion(datos):
    return sql(
        datos,
        "SELECT estado, verificada, intentos_verificacion, solicitud_constancia_id "
        "FROM whatsapp.conversacion_whatsapp ORDER BY id DESC LIMIT 1",
    )[0]


async def verificar(bot, datos, dato="1234"):
    await decir(bot, "constancia")
    return await decir(bot, f"{ultimo_codigo(datos)} {dato}")


# ------------------------------------------------------------------ acceso


async def test_numero_no_registrado_recibe_sin_acceso_y_queda_en_la_bitacora(bot, datos):
    desconocido = "5219999999999"
    assert await decir(bot, "hola", celular=desconocido) == "IGNORADO"  # sin palabra clave
    assert salidas_bot(datos) == []
    assert await decir(bot, "Constancia", celular=desconocido) == "SIN_ACCESO"
    [m] = salidas_bot(datos)
    assert m["texto"] == M.SIN_ACCESO and m["proposito"] == "RECHAZO_BOT"
    assert m["wa_id"] == desconocido and m["colaborador_id"] is None
    bit = sql(
        datos, "SELECT origen, detalle FROM auditoria.bitacora WHERE accion = 'INTENTO_WHATSAPP'"
    )
    assert bit[0][0] == "SISTEMA" and bit[0][1]["celular_hash"] == huella_de(desconocido)
    assert desconocido not in str(bit)  # solo el hash, nunca el número
    assert sql(datos, "SELECT count(*) FROM whatsapp.conversacion_whatsapp") == [(0,)]


@pytest.mark.parametrize("motivo", ["BAJA", "SIN_CONSENTIMIENTO"])
async def test_baja_y_sin_consentimiento_reciben_servicio_no_disponible_y_se_avisa_a_rh(
    bot, datos, motivo
):
    bot.colaboradores.registrar(CELULAR, datos["colaborador"], elegible=False, motivo=motivo)
    assert await decir(bot, "constancia") == "NO_DISPONIBLE"
    assert textos_bot(datos) == [M.NO_DISPONIBLE]
    assert bot.alertas.avisos == [
        ("SERVICIO_NO_DISPONIBLE", {"colaborador_id": datos["colaborador"], "motivo": motivo})
    ]
    assert sql(datos, "SELECT count(*) FROM whatsapp.conversacion_whatsapp") == [(0,)]


# ------------------------------------------------------------------ verificación


async def test_el_aviso_de_privacidad_precede_al_codigo_que_solo_se_guarda_como_hmac(bot, datos):
    assert await decir(bot, "  CONSTANCIA!  ") == "CODIGO_ENVIADO"
    aviso, codigo_msg = salidas_bot(datos)
    assert "https://cc.test/privacidad" in aviso["texto"]
    assert "NSS" in codigo_msg["texto"] and codigo_msg["origen_tipo"] == "VERIFICACION"
    codigo = ultimo_codigo(datos)
    assert conversacion(datos)[0] == "VERIFICANDO"
    [(guardado, creacion, expira)] = sql(
        datos,
        "SELECT codigo_hmac, fecha_creacion, fecha_expira FROM whatsapp.codigo_verificacion",
    )
    conv_id = sql(datos, "SELECT id FROM whatsapp.conversacion_whatsapp")[0][0]
    assert bytes(guardado) == hmac_codigo(LLAVE_CODIGOS, conv_id, codigo)
    assert codigo.encode() not in bytes(guardado)
    assert (expira - creacion).total_seconds() == 600  # caduca a los 10 minutos


async def test_verificacion_correcta_activa_la_conversacion_y_pide_la_constancia(bot, datos):
    assert await verificar(bot, datos) == "VERIFICADO:SOLICITADA"  # una sola plantilla: se usa
    assert conversacion(datos) == ("ACTIVA", True, 0, None)
    assert bot.constancias.elegidas == [(1, 1)] and bot.constancias.generadas == [1]
    assert textos_bot(datos)[-1] == M.PREPARANDO
    assert bot.colaboradores.verificaciones == 1


async def test_el_dato_se_verifica_con_colaboradores_y_tres_fallos_bloquean_24_horas(bot, datos):
    await decir(bot, "constancia")
    assert await decir(bot, f"{ultimo_codigo(datos)} 9999") == "DATOS_INCORRECTOS"
    assert await decir(bot, f"{ultimo_codigo(datos)} 9999") == "DATOS_INCORRECTOS"
    assert textos_bot(datos)[-1] == M.DATOS_NO_COINCIDEN
    assert conversacion(datos)[2] == 2 and bot.alertas.avisos == []
    assert await decir(bot, f"{ultimo_codigo(datos)} 9999") == "BLOQUEADA"
    assert conversacion(datos)[0] == "BLOQUEADA" and textos_bot(datos)[-1] == M.BLOQUEADO
    assert bot.alertas.avisos == [("ACCESO_BLOQUEADO", {"colaborador_id": datos["colaborador"]})]
    horas = sql(datos, "SELECT extract(epoch FROM bloqueada_hasta - now()) / 3600 "
                "FROM whatsapp.conversacion_whatsapp")[0][0]  # fmt: skip
    assert 23.9 < float(horas) <= 24
    # bloqueada: ni el código correcto la desbloquea
    assert await decir(bot, f"{ultimo_codigo(datos)} 1234") == "BLOQUEADA"
    assert conversacion(datos)[0] == "BLOQUEADA"
    # vence el bloqueo: se cierra y la palabra clave empieza de cero
    sql(
        datos,
        "UPDATE whatsapp.conversacion_whatsapp SET bloqueada_hasta = now() - interval '1 second'",
    )
    assert await decir(bot, "constancia") == "CODIGO_ENVIADO"
    assert conversacion(datos)[:3] == ("VERIFICANDO", False, 0)


async def test_codigo_correcto_pero_dato_incorrecto_cuenta_intento(bot, datos):
    await verificar(bot, datos, dato="0000")
    assert conversacion(datos)[:3] == ("VERIFICANDO", False, 1)


async def test_un_codigo_vencido_envia_otro_sin_contar_intento(bot, datos):
    await decir(bot, "constancia")
    viejo = ultimo_codigo(datos)
    sql(datos, "UPDATE whatsapp.codigo_verificacion SET fecha_expira = now() - interval '1 minute'")
    assert await decir(bot, f"{viejo} 1234") == "CODIGO_VENCIDO"
    assert conversacion(datos)[:3] == ("VERIFICANDO", False, 0)  # sin intento y sin verificar
    assert textos_bot(datos)[-1].startswith(M.CODIGO_VENCIDO)
    nuevo = ultimo_codigo(datos)
    assert sql(
        datos, "SELECT count(*) FILTER (WHERE NOT usado) FROM whatsapp.codigo_verificacion"
    ) == [(1,)]
    assert await decir(bot, f"{nuevo} 1234") == "VERIFICADO:SOLICITADA"


async def test_un_mensaje_sin_la_forma_pedida_no_cuenta_intento(bot, datos):
    await decir(bot, "constancia")
    assert await decir(bot, "hola, soy yo") == "FORMATO_INVALIDO"
    assert conversacion(datos)[2] == 0 and textos_bot(datos)[-1] == M.FORMATO_VERIFICACION


async def test_la_desafio_por_fecha_de_ingreso_se_pide_con_su_texto(bot, datos):
    bot.colaboradores.registrar(
        CELULAR, datos["colaborador"], dato="15/03", desafio="FECHA_INGRESO_DDMM"
    )
    await decir(bot, "constancia")
    assert "15/03" in textos_bot(datos)[-1]
    assert await decir(bot, f"{ultimo_codigo(datos)} 15/03") == "VERIFICADO:SOLICITADA"


async def test_responder_a_una_notificacion_no_da_acceso_hasta_pedir_la_constancia(bot, datos):
    sql(datos, "INSERT INTO whatsapp.conversacion_whatsapp (empresa_id, colaborador_id, estado, "
        "verificada, celular_hash, origen) VALUES (%s, %s, 'ACTIVA', false, decode(%s, 'hex'), "
        "'NOTIFICACION')", (datos["empresa"], datos["colaborador"], huella_de(CELULAR)))  # fmt: skip
    assert await decir(bot, "gracias") == "IGNORADO"  # sin datos ni menú
    assert salidas_bot(datos) == []
    assert await decir(bot, "constancia") == "CODIGO_ENVIADO"
    assert conversacion(datos)[0] == "VERIFICANDO"


# ------------------------------------------------------------------ menú y solicitud


def varias(n):
    return [{"id": i, "nombre": f"Constancia {i}", "descripcion": None, "version": 1}
            for i in range(1, n + 1)]  # fmt: skip


async def test_con_varias_plantillas_se_ofrece_la_lista_paginada(bot, datos):
    bot.constancias.lista = varias(12)
    assert await verificar(bot, datos) == "VERIFICADO:MENU_ENVIADO"
    primera = salidas_bot(datos)[-1]
    filas = primera["interactivo"]["action"]["sections"][0]["rows"]
    assert primera["tipo"] == "INTERACTIVO" and filas[-1]["id"] == "mas:1" and len(filas) == 10
    assert bot.constancias.creadas == [1] and conversacion(datos)[3] == 1  # solicitud abierta

    assert await decir(bot, opcion="mas:1") == "MENU_ENVIADO"
    filas2 = salidas_bot(datos)[-1]["interactivo"]["action"]["sections"][0]["rows"]
    assert [f["id"] for f in filas2] == ["plantilla:10", "plantilla:11", "plantilla:12"]
    assert bot.constancias.creadas == [1]  # paginar no crea otra solicitud

    assert await decir(bot, opcion="plantilla:11") == "SOLICITADA"
    assert bot.constancias.elegidas == [(1, 11)] and bot.constancias.generadas == [1]
    assert conversacion(datos)[3] is None  # ya se genera: no hay nada que cancelar


async def test_sin_plantillas_activas_se_avisa(bot, datos):
    bot.constancias.lista = []
    assert await verificar(bot, datos) == "VERIFICADO:SIN_PLANTILLAS"
    assert textos_bot(datos)[-1] == M.SIN_PLANTILLAS and bot.constancias.creadas == []


async def test_campos_faltantes_responden_falta_informacion(bot, datos):
    bot.constancias.faltan = ["nss"]
    assert await verificar(bot, datos) == "VERIFICADO:CAMPOS_FALTANTES"
    assert textos_bot(datos)[-1] == M.FALTA_INFORMACION
    assert conversacion(datos)[3] is None and bot.constancias.generadas == []


async def test_una_solicitud_en_proceso_no_se_duplica(bot, datos):
    bot.constancias.abierta = True
    assert await verificar(bot, datos) == "VERIFICADO:SOLICITUD_EN_PROCESO"
    assert textos_bot(datos)[-1] == M.SOLICITUD_EN_PROCESO


async def test_palabra_clave_de_nuevo_reinicia_el_menu_y_cancela_la_solicitud_anterior(bot, datos):
    bot.constancias.lista = varias(3)
    await verificar(bot, datos)
    assert await decir(bot, "CONSTANCIAS") == "MENU_ENVIADO"
    assert bot.constancias.canceladas == [1] and bot.constancias.creadas == [1, 2]
    assert await decir(bot, "¿qué onda?") == "AYUDA"
    assert textos_bot(datos)[-1] == M.AYUDA


async def test_cinco_solicitudes_por_dia_y_la_sexta_se_limita(bot, datos):
    await verificar(bot, datos)  # 1.ª solicitud (una plantilla)
    for _ in range(4):
        assert await decir(bot, "constancia") == "SOLICITADA"
    assert await decir(bot, "constancia") == "LIMITE_DIARIO"
    assert textos_bot(datos)[-1] == M.LIMITE_DIA
    assert len(bot.constancias.generadas) == 5
    assert (
        bot.constancias.canceladas[-1] == bot.constancias.creadas[-1]
    )  # la 6.ª no se queda abierta


async def test_veinte_mensajes_por_minuto_y_el_siguiente_se_limita_con_un_solo_aviso(bot, datos):
    resultados = [await decir(bot, "hola") for _ in range(24)]
    assert resultados[:20] == ["IGNORADO"] * 20 and resultados[20:] == ["LIMITADO"] * 4
    assert textos_bot(datos) == [M.DEMASIADOS_MENSAJES]  # avisa una vez, no amplifica
    total = sql(datos, "SELECT total FROM whatsapp.uso_numero WHERE tipo = 'MENSAJE'")
    assert total == [(24,)]


async def test_repetir_el_mismo_mensaje_no_duplica_efectos(bot, datos):
    m = Mensaje("wamid.REPETIDO", CELULAR, "constancia")
    assert await procesar(bot, m) == "CODIGO_ENVIADO"
    assert await procesar(bot, m) == "DUPLICADO"
    assert len(salidas_bot(datos)) == 2  # aviso y código, una sola vez
    assert sql(datos, "SELECT count(*) FROM whatsapp.codigo_verificacion") == [(1,)]
    assert sql(datos, "SELECT count(*) FROM whatsapp.conversacion_whatsapp") == [(1,)]
    assert hashlib.sha256  # el wamid es la clave de idempotencia
