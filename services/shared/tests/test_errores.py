import json

import pytest
from cc_common.errores import (
    ErrorConflicto,
    ErrorDominio,
    ErrorNoEncontrado,
    desde_violacion,
    instalar_manejadores,
    problema,
)
from cc_common.tipos import Celular10, Rfc13
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

SECRETO = "5512349876X"


class Entrada(BaseModel):
    model_config = {"extra": "forbid"}
    celular: Celular10
    rfc: Rfc13


def _app() -> TestClient:
    app = FastAPI()
    instalar_manejadores(app)

    @app.post("/eco")
    def eco(e: Entrada):
        return {"ok": True}

    @app.get("/no-existe")
    def no_existe():
        raise ErrorNoEncontrado()

    @app.get("/duplicado")
    def duplicado():
        raise desde_violacion("colaborador_empresa_id_numero_empleado_key")

    @app.get("/explota")
    def explota():
        raise RuntimeError(f"fallo con dato {SECRETO}")

    return TestClient(app, raise_server_exceptions=False)


def test_validacion_problem_json_sin_eco_del_valor():
    r = _app().post("/eco", json={"celular": SECRETO, "rfc": "ZZZZ999999ZZ", "x": 1})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    cuerpo = r.json()
    assert cuerpo["codigo"] == "VALIDACION_FALLIDA"
    assert cuerpo["correlacion_id"]
    campos = {e["campo"]: e["codigo"] for e in cuerpo["errores"]}
    assert campos == {
        "celular": "FORMATO_INVALIDO",
        "rfc": "FORMATO_INVALIDO",
        "x": "CAMPO_NO_PERMITIDO",
    }
    texto = json.dumps(cuerpo)
    assert SECRETO not in texto and "ZZZZ999999ZZ" not in texto and '"input"' not in texto


def test_404_y_correlacion_propagada():
    r = _app().get("/no-existe", headers={"x-correlation-id": "abc-123"})
    assert r.status_code == 404
    assert r.json()["codigo"] == "RECURSO_NO_ENCONTRADO"
    assert r.json()["correlacion_id"] == "abc-123"


def test_violacion_de_unicidad_sin_texto_de_postgres():
    r = _app().get("/duplicado")
    assert r.status_code == 409
    assert r.json()["codigo"] == "NUMERO_EMPLEADO_DUPLICADO"
    assert r.json()["errores"][0]["campo"] == "numero_empleado"


def test_error_inesperado_es_500_generico():
    r = _app().get("/explota")
    assert r.status_code == 500
    assert r.json()["codigo"] == "ERROR_INTERNO"
    assert SECRETO not in r.text


def test_detalle_rechaza_claves_no_permitidas():
    with pytest.raises(ValueError, match="no permitidas"):
        ErrorConflicto(detalle={"nombre": "María"})


def test_restriccion_desconocida_es_conflicto_generico():
    e = desde_violacion("otra_restriccion")
    assert isinstance(e, ErrorDominio) and e.http == 409 and e.codigo == "CONFLICTO"


def test_problema_incluye_detalle_permitido():
    p = problema(ErrorConflicto("CLAVE_EN_USO", detalle={"plantillas": ["Laboral"]}))
    assert p["detalle"] == {"plantillas": ["Laboral"]} and p["status"] == 409
