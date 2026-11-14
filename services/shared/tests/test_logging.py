import json

import pytest
from cc_common.logging import (
    REDACTADO,
    configurar_logging,
    enmascarar_texto,
    filtro_datos_personales,
    obtener_logger,
)


@pytest.mark.parametrize(
    "texto,marca",
    [
        ("celular 8112345678 registrado", "[NUMERO]"),
        ("tel +52 81 1234 5678", "[NUMERO]"),
        ("rfc XAXX010101000", "[RFC]"),
        ("curp XEXX010101HNEXXXA4", "[CURP]"),
        ("nss 12345678901", "[NSS]"),
        ("correo maria.ramirez@ejemplo.com", "[CORREO]"),
        ("llave AKIAZZZZZZZZZZZZZZZZ", "[LLAVE_AWS]"),
    ],
)
def test_enmascara_patrones(texto, marca):
    salida = enmascarar_texto(texto)
    assert marca in salida


def test_no_altera_identificadores():
    assert enmascarar_texto("colaborador_id=42 folio CG-2026-0142") == (
        "colaborador_id=42 folio CG-2026-0142"
    )


def test_redacta_claves_sensibles_anidadas():
    evento = {
        "event": "alta",
        "colaborador_id": 42,
        "celular": "8112345678",
        "datos": {"rfc": "XAXX010101000", "planta": "Apodaca", "lista": ["x 8112345678"]},
    }
    limpio = filtro_datos_personales(None, "info", evento)
    assert limpio["celular"] == REDACTADO
    assert limpio["datos"]["rfc"] == REDACTADO
    assert limpio["datos"]["planta"] == "Apodaca"
    assert limpio["datos"]["lista"] == ["x [NUMERO]"]
    assert limpio["colaborador_id"] == 42


def test_salida_json_sin_datos_personales(capsys):
    configurar_logging("prueba", "local")
    obtener_logger().info("fallo de envio a 8112345678", correo="a@b.com", folio="CG-2026-0001")
    linea = capsys.readouterr().out.strip().splitlines()[-1]
    datos = json.loads(linea)
    assert datos["servicio"] == "prueba"
    assert datos["folio"] == "CG-2026-0001"
    assert "8112345678" not in linea and "a@b.com" not in linea
