"""T-205: esqueleto del servicio campos, catálogos estáticos y contrato OpenAPI (sin base)."""

import json

import pytest
import re2
from cc_campos import catalogo
from cc_campos.main import crear_app
from cc_common.auth import rutas_sin_permiso
from fastapi.testclient import TestClient

from scripts.exportar_openapi import generar, main


def _app():
    return crear_app(motor=object(), verificador=object())


def test_salud():
    r = TestClient(_app()).get("/salud")
    assert r.status_code == 200 and r.json()["servicio"] == "campos"


def test_todas_las_rutas_declaran_permiso():
    assert rutas_sin_permiso(_app()) == []


def test_openapi_determinista_y_contrato_al_dia():
    a, b = generar("campos"), generar("campos")
    assert a == b
    rutas = json.loads(a)["paths"]
    assert {
        "/api/v1/campos",
        "/api/v1/campos/{campo_id}",
        "/api/v1/campos/orden",
        "/api/v1/campos/{campo_id}/opciones",
        "/api/v1/campos/{campo_id}/opciones/{opcion_id}",
        "/internal/campos",
        "/internal/empresas/{empresa_id}/campos-sugeridos",
    } <= set(rutas)
    assert main(["exportar_openapi.py", "campos", "--verificar"]) == 0


def test_hay_once_fijos_y_once_sugeridos():
    assert len(catalogo.FIJOS) == 11 and len(catalogo.SUGERIDOS) == 11
    assert len({s.clave for s in catalogo.SUGERIDOS}) == 11
    # un sugerido no puede ser una variable reservada ni un fijo
    assert not catalogo.CLAVES_SUGERIDAS & catalogo.RESERVADAS


def test_los_formatos_sugeridos_compilan_en_re2_y_caben_en_200_caracteres():
    for s in catalogo.SUGERIDOS:
        if s.formato:
            assert len(s.formato) <= catalogo.FORMATO_MAXIMO
            re2.compile(s.formato)


@pytest.mark.parametrize(
    ("clave", "valor", "esperado"),
    [
        ("sueldo", "9500.0000", True),
        ("sueldo", "0.0100", True),
        ("sueldo", "0.0000", False),
        ("sueldo", "0", False),
        ("sueldo", "-5.0000", False),
        ("nss", "12345678901", True),
        ("nss", "1234567890", False),
        ("registro_patronal", "A0000000000", True),
        ("registro_patronal", "a0000000000", False),
        ("rfc", "XAXX010101000", True),
        ("rfc", "XAXX0101010", False),
        ("curp", "XEXX010101HNEXXXA4", True),
        ("curp", "XEXX010101HNEXXXA", False),
        ("correo", "maria@ejemplo.com", True),
        ("correo", "maria@ejemplo", False),
    ],
)
def test_formatos_de_los_sugeridos(clave, valor, esperado):
    s = next(x for x in catalogo.SUGERIDOS if x.clave == clave)
    assert (re2.compile(s.formato).fullmatch(valor) is not None) is esperado


def test_ruta_transporte_nace_inactiva_y_los_sensibles_son_cuatro():
    por_clave = {s.clave: s for s in catalogo.SUGERIDOS}
    assert por_clave["ruta_transporte"].activo is False
    assert sorted(s.clave for s in catalogo.SUGERIDOS if s.es_sensible) == [
        "curp",
        "nss",
        "rfc",
        "sueldo",
    ]
    assert [v for _, v in por_clave["periodicidad_sueldo"].opciones] == [
        "SEMANAL",
        "CATORCENAL",
        "QUINCENAL",
        "MENSUAL",
    ]
