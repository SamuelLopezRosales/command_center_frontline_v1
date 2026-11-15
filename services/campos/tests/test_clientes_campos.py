"""T-205: clientes HTTP de INT-COL-10 e INT-CON-06 con un transporte simulado (sin red)."""

import httpx
import pytest
from cc_campos.clientes import ColaboradoresHttp, ConstanciasHttp, PlantillaUso
from cc_common.errores import ErrorProveedor
from cc_common.internal_client import ClienteInterno, verificar_token_interno

SECRETO = "secreto-interno-de-prueba-0123456789-abcdef"


def _cliente(manejador) -> ClienteInterno:
    return ClienteInterno(
        "http://servicio",
        servicio="campos",
        secreto=lambda: SECRETO,
        transporte=httpx.MockTransport(manejador),
        reintentos=0,
    )


async def test_campo_con_valores_envia_empresa_y_token_de_campos():
    vistas = []

    def manejador(req: httpx.Request) -> httpx.Response:
        vistas.append(req)
        return httpx.Response(200, json={"con_valores": True})

    assert await ColaboradoresHttp(_cliente(manejador)).campo_con_valores(7, 42) is True
    req = vistas[0]
    assert req.url.path == "/internal/campos/42/uso" and req.headers["x-empresa-id"] == "7"
    token = req.headers["authorization"].removeprefix("Bearer ")
    assert verificar_token_interno(token, SECRETO) == "campos"


async def test_uso_de_variables_agrupa_por_clave():
    def manejador(req: httpx.Request) -> httpx.Response:
        assert req.url.params.get_list("variable") == ["bono", "area"]
        return httpx.Response(200, json={"usos": {"bono": [{"id": 3, "nombre": "Constancia"}]}})

    usos = await ConstanciasHttp(_cliente(manejador)).uso_de_variables(7, ["bono", "area"])
    assert usos == {"bono": [PlantillaUso(3, "Constancia")], "area": []}


async def test_sin_claves_no_llama_y_un_error_del_servicio_es_error_de_proveedor():
    llamadas = []

    def manejador(req):
        llamadas.append(req)
        return httpx.Response(404)

    c = ConstanciasHttp(_cliente(manejador))
    assert await c.uso_de_variables(7, []) == {}
    assert llamadas == []
    with pytest.raises(ErrorProveedor):
        await c.uso_de_variables(7, ["bono"])
    with pytest.raises(ErrorProveedor):
        await ColaboradoresHttp(_cliente(manejador)).campo_con_valores(7, 1)
