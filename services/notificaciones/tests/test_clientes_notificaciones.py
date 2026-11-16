"""T-215: clientes HTTP de INT-CAM-01 e INT-COL-06 con un transporte simulado (sin red)."""

import json

import httpx
import pytest
from cc_common.errores import ErrorProveedor, ErrorValidacion
from cc_common.internal_client import ClienteInterno, verificar_token_interno
from cc_notificaciones.clientes import CamposHttp, ColaboradoresHttp

SECRETO = "secreto-interno-de-prueba-0123456789-abcdef"


def _cliente(manejador) -> ClienteInterno:
    return ClienteInterno(
        "http://servicio",
        servicio="notificaciones",
        secreto=lambda: SECRETO,
        transporte=httpx.MockTransport(manejador),
        reintentos=0,
    )


async def test_campos_http_pide_solo_activos_y_mapea_opciones():
    vistas = []

    def manejador(req: httpx.Request) -> httpx.Response:
        vistas.append(req)
        return httpx.Response(
            200,
            json={
                "campos": [
                    {
                        "id": 2,
                        "codigo_interno": "CAMP-0002",
                        "nombre_campo": "Área",
                        "tipo_dato": "LISTA",
                        "es_sensible": False,
                        "activo": True,
                        "opciones": [
                            {"id": 10, "valor": "VENTAS", "etiqueta": "Ventas", "activo": True}
                        ],
                    }
                ]
            },
        )

    defs = await CamposHttp(_cliente(manejador)).definiciones(7)
    assert defs[0].codigo_interno == "CAMP-0002" and defs[0].opciones[0].valor == "VENTAS"
    req = vistas[0]
    assert req.url.path == "/internal/campos" and "incluir_inactivos" not in str(req.url)
    assert req.headers["x-empresa-id"] == "7"
    token = req.headers["authorization"].removeprefix("Bearer ")
    assert verificar_token_interno(token, SECRETO) == "notificaciones"


async def test_evaluar_audiencia_envia_el_cuerpo_y_mapea_la_respuesta():
    vistas = []

    def manejador(req: httpx.Request) -> httpx.Response:
        vistas.append(req)
        return httpx.Response(
            200,
            json={
                "total": 2,
                "embudo": {
                    "seleccionados": 2,
                    "con_consentimiento": 1,
                    "activos": 1,
                    "celular_valido": 1,
                },
                "items": [
                    {
                        "id": 1,
                        "nombre": "Ana",
                        "planta_nombre": "Norte",
                        "celular_ultimos4": "1234",
                        "motivo_exclusion": None,
                    },
                    {
                        "id": 2,
                        "nombre": "Beto",
                        "planta_nombre": None,
                        "celular_ultimos4": "0000",
                        "motivo_exclusion": "SIN_CONSENTIMIENTO",
                    },
                ],
                "siguiente_cursor": "abc",
            },
        )

    criterios = {"op": "Y", "items": [{"campo": "planta_id", "operador": "es", "valor": 1}]}
    r = await ColaboradoresHttp(_cliente(manejador)).evaluar_audiencia(
        7, criterios, limite=50, zona_horaria="America/Mexico_City"
    )
    assert r.total == 2 and r.embudo.con_consentimiento == 1 and r.siguiente_cursor == "abc"
    assert r.items[1].motivo_exclusion == "SIN_CONSENTIMIENTO"
    req = vistas[0]
    assert req.method == "POST" and req.url.path == "/internal/colaboradores/audiencias:evaluar"
    assert json.loads(req.content) == {
        "criterios": criterios,
        "solo_conteo": False,
        "limite": 50,
        "zona_horaria": "America/Mexico_City",
    }
    assert req.headers["x-empresa-id"] == "7"


async def test_errores_del_servicio():
    def manejador(req):
        return httpx.Response(422 if req.url.path.endswith(":evaluar") else 500)

    c = _cliente(manejador)
    with pytest.raises(ErrorValidacion):
        await ColaboradoresHttp(c).evaluar_audiencia(1, {})
    with pytest.raises(ErrorProveedor):
        await CamposHttp(c).definiciones(1)
    with pytest.raises(ErrorProveedor):
        await ColaboradoresHttp(_cliente(lambda r: httpx.Response(503))).evaluar_audiencia(1, {})


async def test_elegibilidad_pide_solo_elegibilidad_sin_contacto():
    vistas = []

    def manejador(req: httpx.Request) -> httpx.Response:
        vistas.append(req)
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": 1, "elegible": True, "motivo": None, "celular": None},
                    {"id": 2, "elegible": False, "motivo": "CELULAR_INVALIDO"},
                    {"id": 3, "elegible": False, "motivo": None},
                ]
            },
        )

    r = await ColaboradoresHttp(_cliente(manejador)).elegibilidad(7, [1, 2, 3])
    assert r == {1: None, 2: "CELULAR_INVALIDO", 3: "NO_ELEGIBLE"}
    (req,) = vistas
    assert req.url.path == "/internal/colaboradores/contactos:resolver"
    assert req.headers["x-empresa-id"] == "7"
    assert json.loads(req.content) == {
        "ids": [1, 2, 3],
        "proposito": "NOTIFICACION",
        "solo_elegibilidad": True,
    }


async def test_elegibilidad_con_error_del_servicio_da_502():
    cliente = ColaboradoresHttp(_cliente(lambda _r: httpx.Response(500)))
    with pytest.raises(ErrorProveedor):
        await cliente.elegibilidad(7, [1])
