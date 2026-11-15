"""T-207: esqueleto del servicio constancias y su contrato OpenAPI (sin base de datos)."""

import json

import httpx
import pytest
from cc_common.auth import rutas_sin_permiso
from cc_common.errores import ErrorNoEncontrado, ErrorProveedor
from cc_common.internal_client import ClienteInterno, verificar_token_interno
from cc_constancias.clientes import ColaboradoresHttp, StubColaboradores
from cc_constancias.main import crear_app
from fastapi.testclient import TestClient

from scripts.exportar_openapi import generar, main


def _app():
    return crear_app(motor=object(), verificador=object())


def test_salud():
    r = TestClient(_app()).get("/salud")
    assert r.status_code == 200 and r.json()["servicio"] == "constancias"


def test_todas_las_rutas_declaran_permiso():
    assert rutas_sin_permiso(_app()) == []


def test_openapi_determinista_y_contrato_al_dia():
    a, b = generar("constancias"), generar("constancias")
    assert a == b
    doc = json.loads(a)
    assert {
        "/api/v1/plantillas",
        "/api/v1/plantillas/{plantilla_id}",
        "/api/v1/plantillas/{plantilla_id}/duplicar",
        "/api/v1/plantillas/{plantilla_id}/borrador",
        "/api/v1/constancias/variables",
    } <= set(doc["paths"])
    assert "ContenidoPlantilla" in doc["components"]["schemas"]  # el cuerpo de CON-08
    put = doc["paths"]["/api/v1/plantillas/{plantilla_id}/borrador"]["put"]
    ref = put["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert ref == "#/components/schemas/ContenidoPlantilla"
    assert main(["exportar_openapi.py", "constancias", "--verificar"]) == 0


def test_no_hay_borrado_fisico_de_versiones_ni_constancias():
    """Las plantillas se eliminan de forma lógica y las versiones no tienen ruta de borrado."""
    paths = _app().openapi()["paths"]
    borrados = {ruta for ruta, metodos in paths.items() if "delete" in metodos}
    assert borrados == {"/api/v1/plantillas/{plantilla_id}"}


def test_sin_url_de_servicios_solo_en_local_se_usan_sustitutos():
    from cc_constancias.config import ConfigConstancias

    app = crear_app(ConfigConstancias(ambiente="test"), motor=object(), verificador=object())
    cliente = TestClient(app, raise_server_exceptions=False)
    assert cliente.get("/salud").status_code == 200


SECRETO = "secreto-interno-de-prueba-0123456789-abcdef"


def _cliente(manejador) -> ClienteInterno:
    return ClienteInterno(
        "http://servicio",
        servicio="constancias",
        secreto=lambda: SECRETO,
        transporte=httpx.MockTransport(manejador),
        reintentos=0,
    )


async def test_cliente_de_colaboradores_envia_empresa_variables_y_token():
    vistas = []

    def manejador(req: httpx.Request) -> httpx.Response:
        vistas.append(req)
        return httpx.Response(200, json={"valores": {"puesto": "Op"}, "faltantes": ["nss"]})

    valores, faltantes = await ColaboradoresHttp(_cliente(manejador)).datos_constancia(
        7, 42, ["puesto", "nss"]
    )
    assert (valores, faltantes) == ({"puesto": "Op"}, ["nss"])
    req = vistas[0]
    assert req.url.path == "/internal/colaboradores/42/datos-constancia"
    assert json.loads(req.content) == {"variables": ["puesto", "nss"]}
    assert req.headers["x-empresa-id"] == "7"
    token = req.headers["authorization"].removeprefix("Bearer ")
    assert verificar_token_interno(token, SECRETO) == "constancias"


async def test_cliente_de_colaboradores_sin_variables_no_llama_y_traduce_errores():
    llamadas = []

    def manejador(req):
        llamadas.append(req)
        return httpx.Response(404 if req.url.path.endswith("/1/datos-constancia") else 500)

    c = ColaboradoresHttp(_cliente(manejador))
    assert await c.datos_constancia(7, 1, []) == ({}, [])
    assert llamadas == []
    with pytest.raises(ErrorNoEncontrado):
        await c.datos_constancia(7, 1, ["puesto"])
    with pytest.raises(ErrorProveedor):
        await c.datos_constancia(7, 2, ["puesto"])


async def test_cliente_de_campos_lee_las_definiciones_con_inactivas():
    from cc_constancias.clientes import CamposHttp

    def manejador(req: httpx.Request) -> httpx.Response:
        assert req.url.params["incluir_inactivos"] == "true"
        return httpx.Response(
            200,
            json={
                "campos": [
                    {
                        "id": 1,
                        "nombre_campo": "Área",
                        "clave": "area",
                        "codigo_interno": "CAMP-0001",
                        "tipo_dato": "LISTA",
                        "es_sensible": False,
                        "activo": False,
                        "obligatorio": False,
                        "orden": 1,
                        "opciones": [
                            {
                                "id": 5,
                                "etiqueta": "A",
                                "valor": "A",
                                "descripcion": "x",
                                "activo": True,
                            }
                        ],
                    }
                ]
            },
        )

    [d] = await CamposHttp(_cliente(manejador)).definiciones(7)
    assert (d.clave, d.activo, d.opciones[0].descripcion) == ("area", False, "x")


async def test_stub_de_colaboradores_filtra_a_lo_pedido():
    s = StubColaboradores({1: {"a": "1", "b": "2"}})
    assert await s.datos_constancia(9, 1, ["a", "c"]) == ({"a": "1"}, ["c"])
    assert await s.datos_constancia(9, 2, ["a"]) == ({}, ["a"])
