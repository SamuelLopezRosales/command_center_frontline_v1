"""T-212 (T-097, T-098): texto, máquina de estados, código y menú del bot (sin base de datos)."""

import pytest
from cc_whatsapp.bot import maquina_estados as ME
from cc_whatsapp.bot import mensajes_es as M
from cc_whatsapp.bot import texto
from cc_whatsapp.bot.menu import lista_interactiva
from cc_whatsapp.bot.verificacion import generar_codigo, hmac_codigo


@pytest.mark.parametrize(
    "crudo",
    ["constancia", "CONSTANCIA", "  Constancia!! ", "constancías", "¡Constancias?", "*constancia*"],
)
def test_las_palabras_clave_se_normalizan_sin_acentos_ni_signos(crudo):
    assert texto.es_palabra_clave(crudo)


@pytest.mark.parametrize("crudo", ["", None, "quiero mi constancia", "constanci", "hola"])
def test_otras_palabras_no_son_clave(crudo):
    assert not texto.es_palabra_clave(crudo)


def test_lectura_de_la_respuesta_de_verificacion():
    assert texto.leer_respuesta_de_verificacion("123456 1234") == ("123456", "1234")
    assert texto.leer_respuesta_de_verificacion(" 123456   15/03 ") == ("123456", "15/03")
    for malo in ("12345 1234", "1234567 1234", "123456", "abcdef 1234", "", None):
        assert texto.leer_respuesta_de_verificacion(malo) is None


def test_el_codigo_tiene_seis_digitos_y_su_hmac_depende_de_la_conversacion():
    codigos = {generar_codigo() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codigos) and len(codigos) > 150
    llave = b"k" * 32
    a = hmac_codigo(llave, 1, "123456")
    assert (
        len(a) == 32
        and a != hmac_codigo(llave, 2, "123456")
        and a != hmac_codigo(llave, 1, "123457")
    )
    assert a != hmac_codigo(b"j" * 32, 1, "123456")
    assert b"123456" not in a


def test_transiciones_validas_e_invalidas():
    for origen, destino in [
        (ME.VERIFICANDO, ME.ACTIVA), (ME.VERIFICANDO, ME.BLOQUEADA), (ME.VERIFICANDO, ME.CERRADA),
        (ME.ACTIVA, ME.VERIFICANDO), (ME.ACTIVA, ME.CERRADA), (ME.BLOQUEADA, ME.CERRADA),
    ]:  # fmt: skip
        ME.validar(origen, destino)
    for origen, destino in [
        (ME.CERRADA, ME.ACTIVA), (ME.CERRADA, ME.VERIFICANDO), (ME.BLOQUEADA, ME.ACTIVA),
        (ME.BLOQUEADA, ME.VERIFICANDO), (ME.ACTIVA, ME.BLOQUEADA), (ME.ACTIVA, ME.ACTIVA),
    ]:  # fmt: skip
        with pytest.raises(ME.TransicionInvalida):
            ME.validar(origen, destino)


def _plantillas(n):
    return [{"id": i, "nombre": f"Constancia número {i} " + "x" * 30, "descripcion": "d" * 100}
            for i in range(1, n + 1)]  # fmt: skip


def test_la_lista_se_pagina_con_ver_mas():
    p = _plantillas(12)
    primera = lista_interactiva(p, 0, 9)["action"]["sections"][0]["rows"]
    assert [r["id"] for r in primera] == [f"plantilla:{i}" for i in range(1, 10)] + ["mas:1"]
    assert primera[-1]["title"] == M.VER_MAS and len(primera) <= 10  # límite de Meta
    segunda = lista_interactiva(p, 1, 9)["action"]["sections"][0]["rows"]
    assert [r["id"] for r in segunda] == ["plantilla:10", "plantilla:11", "plantilla:12"]
    assert all(len(r["title"]) <= 24 and len(r.get("description", "")) <= 72 for r in primera)
    exacta = lista_interactiva(_plantillas(9), 0, 9)["action"]["sections"][0]["rows"]
    assert len(exacta) == 9 and not any(r["id"].startswith("mas:") for r in exacta)


def test_los_mensajes_fijos_no_llevan_datos_personales():
    assert "Ana" not in M.SIN_ACCESO + M.NO_DISPONIBLE + M.BLOQUEADO + M.FALTA_INFORMACION
    assert "123456" in M.codigo_y_desafio("123456", "NSS_ULTIMOS4") and "NSS" in M.codigo_y_desafio(
        "1", "NSS_ULTIMOS4"
    )
    assert "15/03" in M.codigo_y_desafio("1", "FECHA_INGRESO_DDMM")
    assert "https://cc.test/p" in M.aviso_privacidad("https://cc.test/p")
