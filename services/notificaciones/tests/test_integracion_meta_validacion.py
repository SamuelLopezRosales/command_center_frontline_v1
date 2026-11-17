"""Unitarias de la conexión con Meta: formatos, mezcla del JSON, enmascarado y clasificación."""

from datetime import UTC, datetime

import pytest
from ayudantes_integraciones_meta import (
    ACCESS_TOKEN,
    APP_SECRET,
    COMPLETO,
    PATRON_TOKEN_VERIFICACION,
    VERIFY_TOKEN,
)
from cc_notificaciones import integracion_meta as im
from cc_notificaciones import sonda_meta
from cc_notificaciones.servicios.integraciones import generar_verify_token

AHORA = datetime(2026, 11, 17, 18, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("patron", "validos", "invalidos"),
    [
        (im.RE_ID_META, ["12345678", "1" * 25], ["1234567", "1" * 26, "12a45678", "", "1234 5678"]),
        (
            im.RE_VERSION,
            ["v21.0", "v9.1", "v10.10"],
            ["21.0", "v21", "v.1", "v21.0.1", "V21.0"],
        ),
        (
            im.RE_ACCESS_TOKEN,
            [ACCESS_TOKEN, "E" * 20, "E" * 1000],
            ["E" * 19, "E" * 1001, "EAA " + "a" * 30, "EAA\n" + "a" * 30, "EÁA" + "a" * 30],
        ),
        (im.RE_APP_SECRET, [APP_SECRET, "ABCDEF0123456789abcdef0123456789"], ["a" * 31, "g" * 32]),
        (
            im.RE_VERIFY_TOKEN,
            [VERIFY_TOKEN, "a" * 16, "a" * 128, "A-b_C" * 4],
            ["a" * 15, "a" * 129, "a b" * 8, "ñ" * 16, "a.b" * 8],
        ),
    ],
)
def test_formatos(patron, validos, invalidos):
    assert all(patron.match(v) for v in validos)
    assert not any(patron.match(v) for v in invalidos)


def test_un_patron_con_salto_de_linea_final_no_pasa():
    # ``$`` de ``re`` acepta un salto de línea al final; los formatos no deben aceptarlo.
    assert not im.RE_APP_SECRET.match(APP_SECRET + "\n")
    assert not im.RE_VERIFY_TOKEN.match(VERIFY_TOKEN + "\n")
    assert not im.RE_ID_META.match("12345678\n")


@pytest.mark.parametrize("crudo", [None, "", "no json", "[1]", '"x"', "7", "null", b"\xff"])
def test_interpretar_cualquier_cosa_que_no_sea_objeto_es_vacio(crudo):
    assert im.interpretar(crudo) == {}


def test_interpretar_un_objeto():
    assert im.interpretar('{"a": 1}') == {"a": 1}


def test_ultimos4_solo_si_el_valor_mide_12_o_mas():
    assert im.ultimos4("0123456789ab") == "89ab"
    assert im.ultimos4("0123456789a") is None
    assert im.ultimos4("") is None and im.ultimos4(None) is None


def test_guardado_vacio_o_con_cadenas_vacias_no_esta_configurado():
    for datos in ({}, {"waba_id": "", "phone_number_id": "  ", "token": "x"}):
        g = im.MetaGuardada.de_json(datos)
        assert g.configurada is False
    assert im.MetaGuardada.de_json(dict(COMPLETO)).configurada is True
    sin_uno = {k: v for k, v in COMPLETO.items() if k != "app_secret"}
    assert im.MetaGuardada.de_json(sin_uno).configurada is False


def test_repr_no_muestra_los_secretos():
    g = im.MetaGuardada.de_json(dict(COMPLETO))
    texto = repr(g)
    assert ACCESS_TOKEN not in texto and APP_SECRET not in texto and VERIFY_TOKEN not in texto


def test_mezclar_conserva_lo_no_enviado_y_descarta_claves_ajenas():
    actual = {"waba_id": "11111111", "token": "viejo", "graph_version": "", "_marcador": "x"}
    nuevo, cambiados = im.mezclar(
        actual, {"phone_number_id": "22222222"}, usuario_id=7, ahora=AHORA
    )
    assert cambiados == ["phone_number_id"]
    assert nuevo == {
        "waba_id": "11111111",
        "phone_number_id": "22222222",
        "actualizado_en": AHORA.isoformat(),
        "actualizado_por_usuario_id": 7,
    }


def test_mezclar_sin_cambios_no_toca_los_metadatos():
    antes = {"waba_id": "11111111", "actualizado_en": "2026-01-01T00:00:00+00:00"}
    nuevo, cambiados = im.mezclar(antes, {"waba_id": "11111111"}, usuario_id=7, ahora=AHORA)
    assert cambiados == [] and nuevo == antes


def test_mezclar_distingue_lo_que_de_verdad_cambio():
    actual = {"waba_id": "11111111", "phone_number_id": "22222222"}
    _, cambiados = im.mezclar(
        actual, {"waba_id": "11111111", "phone_number_id": "33333333"}, usuario_id=1, ahora=AHORA
    )
    assert cambiados == ["phone_number_id"]


def test_generar_verify_token_cumple_el_formato_y_no_se_repite():
    tokens = {generar_verify_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(PATRON_TOKEN_VERIFICACION.match(t) and im.RE_VERIFY_TOKEN.match(t) for t in tokens)


@pytest.mark.parametrize(
    ("status", "cuerpo", "esperada"),
    [
        (400, {"error": {"code": 190}}, sonda_meta.CAT_ACCESO),
        (401, {}, sonda_meta.CAT_ACCESO),
        (400, {"error": {"code": 463}}, sonda_meta.CAT_ACCESO),
        (403, {"error": {"code": 10}}, sonda_meta.PERMISOS),
        (400, {"error": {"code": 200}}, sonda_meta.PERMISOS),
        (403, {}, sonda_meta.PERMISOS),
        (400, {"error": {"code": 100}}, sonda_meta.NO_EXISTE),
        (400, {"error": {"code": 803}}, sonda_meta.NO_EXISTE),
        (404, {}, sonda_meta.NO_EXISTE),
        (400, {"error": {"code": 4}}, sonda_meta.TASA),
        (429, {}, sonda_meta.TASA),
        (500, {}, sonda_meta.TRANSITORIO),
        (503, {"error": {"code": 2}}, sonda_meta.TRANSITORIO),
        (400, {"error": {"code": "texto"}}, sonda_meta.OTRO),
        (400, {"error": "cadena"}, sonda_meta.OTRO),
    ],
)
def test_clasificacion_de_errores_de_meta(status, cuerpo, esperada):
    assert sonda_meta.clasificar(status, cuerpo) == esperada
