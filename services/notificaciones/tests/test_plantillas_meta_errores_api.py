"""Importar plantillas de Meta: errores de Meta y permisos en los endpoints, sin Docker.

El motor es un doble: ningún camino de error llega a la base. Un fallo de Meta (token, permisos,
cuenta, tasa, 5xx, tiempo agotado, red) nunca es un 500 ni filtra el token; sin credenciales es un
422 ``META_NO_CONFIGURADA``.
"""

import logging

import httpx
import pytest
from ayudantes_integraciones_meta import ACCESS_TOKEN, WABA_ID, MotorFalso
from ayudantes_notificaciones import cab, construir_app, emitir, simulador_meta
from cc_notificaciones.meta import CredencialesMeta, ErrorMeta, MetaPlantillasHttp

LISTA = "/api/v1/plantillas-mensaje/meta"
IMPORTAR = "/api/v1/plantillas-mensaje/importar"
H = cab(emitir("sub-a", 1, 5))
CUERPO = {"plantillas": [{"nombre": "bienvenida_colaborador", "idioma": "es_MX"}]}


@pytest.fixture(autouse=True)
def _registro(caplog):
    caplog.set_level(logging.DEBUG)


@pytest.fixture
def sim():
    s = simulador_meta().SimuladorMeta(access_token=ACCESS_TOKEN, waba_id=WABA_ID)
    s.cargar_catalogo_ejemplo()
    return s


def app_con(meta):
    return construir_app(MotorFalso(), meta=meta)


async def llamar(meta, metodo, url, **kw):
    app = app_con(meta)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.request(metodo, url, **kw)


def meta_con(transporte):
    async def cred():
        return CredencialesMeta(ACCESS_TOKEN, WABA_ID)

    return MetaPlantillasHttp(cred, transporte=transporte)


ERRORES = [
    ((400, 190), "rechazó el token"),
    ((403, 10), "permisos"),
    ((400, 100), "WABA ID"),
    ((429, 130429), "limitó"),
    ((503, 131000), "no pudo responder"),
]


@pytest.mark.parametrize(("error", "fragmento"), ERRORES)
@pytest.mark.parametrize(
    ("metodo", "url", "cuerpo"), [("GET", LISTA, None), ("POST", IMPORTAR, CUERPO)]
)
async def test_un_fallo_de_meta_es_502_con_mensaje_en_espanol(
    sim, caplog, metodo, url, cuerpo, error, fragmento
):
    sim.siguientes.append(error)
    r = await llamar(meta_con(sim.transporte()), metodo, url, json=cuerpo, headers=H)
    assert r.status_code == 502, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    d = r.json()
    assert d["codigo"] == "ERROR_PROVEEDOR_META" and fragmento in d["title"]
    assert ACCESS_TOKEN not in r.text and ACCESS_TOKEN not in caplog.text
    assert "sim" not in d["title"].split()


@pytest.mark.parametrize(
    ("falla", "fragmento"),
    [
        (lambda p: httpx.Response(401, json={"error": {"code": 190}}), "rechazó el token"),
        (lambda p: (_ for _ in ()).throw(httpx.ReadTimeout("x", request=p)), "a tiempo"),
        (
            lambda p: (_ for _ in ()).throw(httpx.ConnectError("x", request=p)),
            "No se pudo contactar",
        ),
        (lambda p: httpx.Response(200, text="<html>"), "inesperada"),
    ],
)
async def test_tiempo_agotado_red_y_respuestas_raras_tampoco_son_500(falla, fragmento):
    r = await llamar(meta_con(httpx.MockTransport(falla)), "GET", LISTA, headers=H)
    assert r.status_code == 502 and fragmento in r.json()["title"]


async def test_sin_credenciales_es_422_meta_no_configurada():
    async def sin():
        raise ErrorMeta("META_SIN_CREDENCIALES")

    meta = MetaPlantillasHttp(sin, transporte=httpx.MockTransport(lambda p: httpx.Response(500)))
    for metodo, url, cuerpo in (("GET", LISTA, None), ("POST", IMPORTAR, CUERPO)):
        r = await llamar(meta, metodo, url, json=cuerpo, headers=H)
        assert r.status_code == 422, r.text
        d = r.json()
        assert d["codigo"] == "META_NO_CONFIGURADA" and "Conexión con Meta" in d["title"]


async def test_permisos_y_validacion_antes_de_consultar_a_meta(sim):
    consultas = []

    def espia(p):
        consultas.append(p)
        return httpx.Response(200, json={"data": []})

    meta = meta_con(httpx.MockTransport(espia))
    sin_permiso = cab(emitir("sub-a", 1, 5, rol="OTRO"))
    for metodo, url, cuerpo in (("GET", LISTA, None), ("POST", IMPORTAR, CUERPO)):
        assert (
            await llamar(meta, metodo, url, json=cuerpo, headers=sin_permiso)
        ).status_code == 403
        assert (await llamar(meta, metodo, url, json=cuerpo)).status_code == 401
    r = await llamar(meta, "POST", IMPORTAR, json={"plantillas": []}, headers=H)
    assert r.status_code == 422
    assert consultas == []  # sin permiso o con cuerpo inválido, Meta ni se entera
