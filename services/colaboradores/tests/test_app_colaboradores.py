"""T-201: esqueleto del servicio colaboradores y su contrato OpenAPI."""

import json

from cc_colaboradores.main import crear_app
from cc_common.auth import rutas_sin_permiso
from fastapi.testclient import TestClient

from scripts.exportar_openapi import generar, main


def _app():
    return crear_app(motor=object(), verificador=object())


def test_salud():
    r = TestClient(_app()).get("/salud")
    assert r.status_code == 200 and r.json()["servicio"] == "colaboradores"


def test_no_hay_endpoints_de_borrado():
    """Organizaciones y plantas solo se desactivan (DS-04, CC-REQ-161)."""
    metodos = {m for ruta in _app().routes for m in getattr(ruta, "methods", set())}
    assert "DELETE" not in metodos
    c = TestClient(_app(), raise_server_exceptions=False)
    assert c.delete("/api/v1/organizaciones/1").status_code == 405
    assert c.delete("/api/v1/plantas/1").status_code == 405


def test_todas_las_rutas_declaran_permiso():
    assert rutas_sin_permiso(_app()) == []


def test_openapi_determinista_y_contrato_al_dia():
    a, b = generar("colaboradores"), generar("colaboradores")
    assert a == b
    rutas = json.loads(a)["paths"]
    assert {
        "/api/v1/organizaciones",
        "/api/v1/organizaciones/{organizacion_id}",
        "/api/v1/organizaciones/{organizacion_id}/logotipo",
        "/api/v1/organizaciones/{organizacion_id}/logotipo/confirmar",
        "/api/v1/plantas",
        "/api/v1/plantas/{planta_id}",
    } <= set(rutas)
    assert main(["exportar_openapi.py", "colaboradores", "--verificar"]) == 0
