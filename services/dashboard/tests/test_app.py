"""T-033: esqueleto del servicio dashboard y exportación de OpenAPI."""

import json

from cc_common.auth import rutas_sin_permiso
from cc_dashboard.main import crear_app
from fastapi.testclient import TestClient

from scripts.exportar_openapi import generar, main


def _cliente() -> TestClient:
    return TestClient(
        crear_app(motor=object(), verificador=object()), raise_server_exceptions=False
    )


def test_salud():
    r = _cliente().get("/salud")
    assert r.status_code == 200
    assert r.json()["estado"] == "ok" and r.json()["servicio"] == "dashboard"


def test_error_problem_json_con_correlacion():
    r = _cliente().get("/api/v1/no-existe", headers={"x-correlation-id": "corr-1"})
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["codigo"] == "RECURSO_NO_ENCONTRADO" and r.json()["correlacion_id"] == "corr-1"
    r = _cliente().delete("/salud")
    assert r.status_code == 405 and r.json()["codigo"] == "METODO_NO_PERMITIDO"


def test_openapi_determinista():
    a, b = generar("dashboard"), generar("dashboard")
    assert a == b
    datos = json.loads(a)
    assert datos["info"]["title"] == "Command Center - dashboard"
    assert "/salud" not in datos["paths"]


def test_contrato_del_repositorio_al_dia():
    assert main(["exportar_openapi.py", "dashboard", "--verificar"]) == 0


def test_todas_las_rutas_declaran_permiso():
    assert rutas_sin_permiso(crear_app(motor=object(), verificador=object())) == []
