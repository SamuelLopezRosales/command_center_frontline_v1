"""T-207 (T-079): variables derivadas: sueldo mensual, importe en letra y fechas en texto."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from cc_constancias.render import derivadas as d


@pytest.mark.parametrize(
    ("sueldo", "periodicidad", "esperado"),
    [
        ("9500", "QUINCENAL", "19000.00"),  # ×2
        ("19000", "MENSUAL", "19000.00"),  # ×1
        ("1000", "SEMANAL", "4333.33"),  # ×52/12 = 4333.333…
        ("1000.01", "SEMANAL", "4333.38"),  # 4333.3766…
        ("5000", "CATORCENAL", "10833.33"),  # ×26/12 = 10833.333…
        ("2500.50", "catorcenal", "5417.75"),  # sin distinguir mayúsculas
        ("0.025", "MENSUAL", "0.03"),  # mitad hacia arriba (no hacia el par)
        ("0.035", "MENSUAL", "0.04"),
        ("12", "SEMANAL", "52.00"),  # 12 × 52/12 exacto
    ],
)
def test_sueldo_mensual_con_los_factores_del_diseno(sueldo, periodicidad, esperado):
    r = d.sueldo_mensual(Decimal(sueldo), periodicidad)
    assert r == Decimal(esperado) and r.as_tuple().exponent == -2


def test_sueldo_mensual_no_pierde_precision_con_importes_grandes():
    # con flotantes 999999999999.99 × 52/12 se desbordaría en el último centavo
    assert d.sueldo_mensual(Decimal("999999999999.99"), "SEMANAL") == Decimal("4333333333333.29")


def test_los_factores_y_su_version_quedan_declarados():
    assert d.FACTORES_VERSION == "1"
    assert set(d.FACTORES) == {"SEMANAL", "CATORCENAL", "QUINCENAL", "MENSUAL"}


@pytest.mark.parametrize("texto", ["abc", "", "0", "-5", "NaN", "Infinity", "1" + "0" * 20])
def test_sueldo_invalido(texto):
    with pytest.raises(d.SueldoInvalido):
        d.a_decimal(texto)


def test_periodicidad_desconocida():
    with pytest.raises(d.SueldoInvalido):
        d.sueldo_mensual(Decimal("100"), "ANUAL")


def test_a_decimal_acepta_formato_con_comas_y_signo_de_pesos():
    assert d.a_decimal("$9,500.50") == Decimal("9500.50")
    assert d.a_decimal(" 9500 ") == Decimal("9500")


@pytest.mark.parametrize(
    ("importe", "esperado"),
    [
        ("9500", "$9,500.00"),
        ("1234567.5", "$1,234,567.50"),
        ("0.03", "$0.03"),
        ("19000", "$19,000.00"),
    ],
)
def test_formato_de_moneda(importe, esperado):
    assert d.formato_moneda(Decimal(importe)) == esperado


@pytest.mark.parametrize(
    ("importe", "esperado"),
    [
        ("9500", "NUEVE MIL QUINIENTOS PESOS 00/100 MN"),
        ("0", "CERO PESOS 00/100 MN"),
        ("1", "UN PESO 00/100 MN"),
        ("2", "DOS PESOS 00/100 MN"),
        ("16", "DIECISÉIS PESOS 00/100 MN"),
        ("21", "VEINTIÚN PESOS 00/100 MN"),
        ("22", "VEINTIDÓS PESOS 00/100 MN"),
        ("31", "TREINTA Y UN PESOS 00/100 MN"),
        ("100", "CIEN PESOS 00/100 MN"),
        ("101", "CIENTO UN PESOS 00/100 MN"),
        ("115", "CIENTO QUINCE PESOS 00/100 MN"),
        ("1000", "MIL PESOS 00/100 MN"),
        ("1001", "MIL UN PESOS 00/100 MN"),
        ("19000", "DIECINUEVE MIL PESOS 00/100 MN"),
        ("21000", "VEINTIÚN MIL PESOS 00/100 MN"),
        ("100000", "CIEN MIL PESOS 00/100 MN"),
        ("101000", "CIENTO UN MIL PESOS 00/100 MN"),
        ("1000000", "UN MILLÓN DE PESOS 00/100 MN"),
        ("2000000", "DOS MILLONES DE PESOS 00/100 MN"),
        ("1500000", "UN MILLÓN QUINIENTOS MIL PESOS 00/100 MN"),
        ("21000000", "VEINTIÚN MILLONES DE PESOS 00/100 MN"),
        ("1000000000", "MIL MILLONES DE PESOS 00/100 MN"),
        ("12345.67", "DOCE MIL TRESCIENTOS CUARENTA Y CINCO PESOS 67/100 MN"),
        ("9500.5", "NUEVE MIL QUINIENTOS PESOS 50/100 MN"),
        ("0.99", "CERO PESOS 99/100 MN"),
        ("0.995", "UN PESO 00/100 MN"),  # el redondeo a centavos sube al peso
    ],
)
def test_importe_en_letra(importe, esperado):
    assert d.importe_en_letra(Decimal(importe)) == esperado


def test_el_importe_en_letra_ya_trae_el_sufijo_y_no_hay_dobles_espacios():
    for n in (0, 1, 21, 999, 1000, 12345, 1_000_001, 999_999_999_999):
        texto = d.importe_en_letra(Decimal(n))
        assert texto.endswith("00/100 MN") and texto == texto.upper() and "  " not in texto


def test_entero_en_letra_es_inyectivo_en_un_rango_amplio():
    textos = {d.entero_en_letra(n) for n in range(0, 3001)}
    assert len(textos) == 3001


def test_final_en_uno_o_apocopado():
    assert d.entero_en_letra(21) == "VEINTIUNO"
    assert d.entero_en_letra(21, apocopar_final=True) == "VEINTIÚN"
    assert d.entero_en_letra(1) == "UNO"
    with pytest.raises(ValueError, match="fuera de rango"):
        d.entero_en_letra(-1)
    with pytest.raises(ValueError, match="negativo"):
        d.importe_en_letra(Decimal("-1"))


def test_fechas_en_texto_con_meses_propios():
    esperados = [
        "1 de enero de 2026",
        "28 de febrero de 2026",
        "15 de marzo de 2021",
        "30 de abril de 2026",
        "31 de mayo de 2026",
        "1 de junio de 2026",
        "4 de julio de 2026",
        "9 de agosto de 2026",
        "16 de septiembre de 2026",
        "12 de octubre de 2026",
        "14 de noviembre de 2026",
        "25 de diciembre de 2026",
    ]
    fechas = [
        date(2026, 1, 1),
        date(2026, 2, 28),
        date(2021, 3, 15),
        date(2026, 4, 30),
        date(2026, 5, 31),
        date(2026, 6, 1),
        date(2026, 7, 4),
        date(2026, 8, 9),
        date(2026, 9, 16),
        date(2026, 10, 12),
        date(2026, 11, 14),
        date(2026, 12, 25),
    ]
    assert [d.fecha_en_texto(f) for f in fechas] == esperados


def test_fecha_iso_en_texto():
    assert d.fecha_iso_en_texto("2021-03-15") == "15 de marzo de 2021"
    assert d.fecha_iso_en_texto("15/03/2021") is None
    assert d.fecha_iso_en_texto("basura") is None


def test_fecha_de_emision_usa_la_zona_de_mexico():
    # 03:00 UTC del 15 es todavía el 14 a las 21:00 en México
    assert d.hoy_en_mexico(datetime(2026, 11, 15, 3, 0, tzinfo=UTC)) == date(2026, 11, 14)
    assert d.hoy_en_mexico(datetime(2026, 11, 15, 12, 0, tzinfo=UTC)) == date(2026, 11, 15)
    assert isinstance(d.hoy_en_mexico(), date)
