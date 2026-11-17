"""Importar plantillas de Meta: ``MetaPlantillasHttp.listar`` y ``obtener`` con el simulador.

Sin Docker ni red: paginación por cursor, tope de 500, solo lectura, errores de Meta (190, 10, 100,
tiempo agotado, red) traducidos a mensajes en español y sin credenciales.
"""

import logging

import httpx
import pytest
from ayudantes_integraciones_meta import ACCESS_TOKEN, WABA_ID
from ayudantes_notificaciones import simulador_meta
from cc_common.errores import ErrorProveedor, ErrorValidacion
from cc_notificaciones.meta import (
    MAX_PLANTILLAS_LISTADO,
    CredencialesMeta,
    ErrorMeta,
    MetaPlantillasHttp,
    StubPlantillasMeta,
)
from cc_notificaciones.servicios.plantillas_meta import traducir_error_meta

BASE = "https://graph.prueba.invalid"


@pytest.fixture(autouse=True)
def _registro(caplog):
    caplog.set_level(logging.DEBUG)


@pytest.fixture
def sim():
    return simulador_meta().SimuladorMeta(access_token=ACCESS_TOKEN, waba_id=WABA_ID)


def cliente_para(transporte, *, credenciales=None):
    async def cred():
        return CredencialesMeta(ACCESS_TOKEN, WABA_ID, "v22.0")

    return MetaPlantillasHttp(credenciales or cred, base=BASE, transporte=transporte)


class Registro(httpx.AsyncBaseTransport):
    """Anota cada petición y la atiende con el simulador."""

    def __init__(self, sim):
        self.sim = sim
        self.peticiones: list[httpx.Request] = []
        self._t = sim.transporte()

    async def handle_async_request(self, request):
        self.peticiones.append(request)
        return await self._t.handle_async_request(request)


@pytest.fixture
def registro(sim):
    return Registro(sim)


def llenar(sim, n):
    for i in range(n):
        sim.agregar_catalogo(f"plantilla_{i:04d}", cuerpo="Hola {{1}}.", ejemplo=["Ana"])


async def test_lista_lo_que_hay_y_lo_interpreta(sim, registro):
    sim.cargar_catalogo_ejemplo()
    r = await cliente_para(registro).listar()
    assert not r.truncado and len(r.items) == 13
    b = next(t for t in r.items if t.nombre == "bienvenida_colaborador")
    assert (b.id, b.idioma, b.categoria, b.estado) == (
        "800000000000001",
        "es_MX",
        "UTILITY",
        "APPROVED",
    )
    assert b.formato_parametros == "POSITIONAL"
    assert [c["type"] for c in b.componentes] == ["BODY", "FOOTER"]
    assert {t.estado for t in r.items} == {"APPROVED", "REJECTED", "PAUSED"}


async def test_consulta_solo_lectura_con_los_campos_y_el_token_en_el_encabezado(sim, registro):
    sim.cargar_catalogo_ejemplo()
    await cliente_para(registro).listar()
    (p,) = registro.peticiones
    assert p.method == "GET" and p.url.path == f"/v22.0/{WABA_ID}/message_templates"
    assert p.url.params["limit"] == "100" and "after" not in p.url.params
    assert p.url.params["fields"] == "id,name,language,category,status,components,parameter_format"
    assert p.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert ACCESS_TOKEN not in str(p.url)
    assert p.content == b""


async def test_pagina_con_el_cursor_hasta_traer_todo(sim, registro):
    llenar(sim, 250)
    r = await cliente_para(registro).listar()
    assert len(r.items) == 250 and not r.truncado
    assert len({t.id for t in r.items}) == 250
    assert [p.get("after") for p in sim.listados] == [None, "100", "200"]


async def test_con_exactamente_el_tope_no_se_marca_truncado(sim, registro):
    llenar(sim, MAX_PLANTILLAS_LISTADO)
    r = await cliente_para(registro).listar()
    assert len(r.items) == MAX_PLANTILLAS_LISTADO and not r.truncado
    assert len(sim.listados) == 5


async def test_el_tope_recorta_y_marca_truncado(sim, registro):
    llenar(sim, 650)
    r = await cliente_para(registro).listar()
    assert len(r.items) == MAX_PLANTILLAS_LISTADO and r.truncado
    assert len(sim.listados) <= 6  # nunca un recorrido sin fin


async def test_un_maximo_menor_tambien_trunca(sim, registro):
    llenar(sim, 30)
    r = await cliente_para(registro).listar(maximo=10)
    assert len(r.items) == 10 and r.truncado


async def test_nunca_sigue_la_url_next_de_meta(sim, registro):
    """``paging.next`` apunta a graph.facebook.com (a veces con el token): se usa solo el cursor
    contra el servidor configurado."""
    llenar(sim, 120)
    await cliente_para(registro).listar()
    assert {p.url.host for p in registro.peticiones} == {"graph.prueba.invalid"}
    assert all("access_token" not in str(p.url) for p in registro.peticiones)


async def test_un_cursor_repetido_corta_el_ciclo():
    paginas = []

    def responder(peticion):
        paginas.append(1)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": f"{len(paginas)}",
                        "name": "a",
                        "language": "es_MX",
                        "status": "APPROVED",
                    }
                ],
                "paging": {"cursors": {"after": "X"}, "next": "https://graph/next"},
            },
        )

    r = await cliente_para(httpx.MockTransport(responder)).listar()
    assert len(paginas) == 2 and len(r.items) == 2  # el segundo "after" era el mismo: se detuvo


async def test_descarta_entradas_raras_y_ids_repetidos():
    def responder(peticion):
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "1", "name": "a", "language": "es_MX", "status": "APPROVED"},
                    {"id": "1", "name": "a", "language": "es_MX", "status": "APPROVED"},
                    {"name": "sin_id", "language": "es_MX"},
                    "basura",
                    {"id": "2", "name": "b", "language": "es_MX", "components": 5},
                ]
            },
        )

    r = await cliente_para(httpx.MockTransport(responder)).listar()
    assert [t.id for t in r.items] == ["1", "2"]


async def test_obtener_busca_por_nombre_e_idioma_exactos(sim, registro):
    sim.cargar_catalogo_ejemplo()
    sim.agregar_catalogo("bienvenida_colaborador", id_="800000000000099", idioma="en_US")
    c = cliente_para(registro)
    es = await c.obtener(nombre="bienvenida_colaborador", idioma="es_MX")
    en = await c.obtener(nombre="bienvenida_colaborador", idioma="en_US")
    assert es.id == "800000000000001" and en.id == "800000000000099"
    assert await c.obtener(nombre="no_existe", idioma="es_MX") is None
    assert await c.obtener(nombre="bienvenida_colaborador", idioma="pt_BR") is None


async def test_la_consulta_de_sincronizacion_sigue_igual(sim, registro):
    """Agregar el listado no cambia ``consultar`` (NOT-13): sigue sin ``components``."""
    sim.cargar_catalogo_ejemplo()
    c = cliente_para(registro)
    creada = await c.crear(
        nombre="aviso_nuevo",
        categoria="UTILITY",
        idioma="es_MX",
        texto="Hola {{1}}",
        ejemplos=["a"],
    )
    sim.aprobar("aviso_nuevo")
    consultada = await c.consultar(nombre="aviso_nuevo", idioma="es_MX")
    assert consultada.id == creada.id and consultada.estado == "APPROVED"
    # y lo creado por la API aparece en el listado, igual que lo haría en Meta
    assert "aviso_nuevo" in {t.nombre for t in (await c.listar()).items}


# ------------------------------------------------------------------ errores


@pytest.mark.parametrize(
    ("error", "codigo", "fragmento"),
    [
        ((400, 190), "190", "rechazó el token"),
        ((403, 10), "10", "permisos"),
        ((400, 100), "100", "WABA ID"),
        ((429, 130429), "130429", "limitó"),
        ((503, 131000), "131000", "no pudo responder"),
    ],
)
async def test_errores_de_meta_se_traducen_a_un_502_en_espanol(
    sim, registro, caplog, error, codigo, fragmento
):
    sim.siguientes.append(error)
    with pytest.raises(ErrorMeta) as info:
        await cliente_para(registro).listar()
    assert info.value.codigo == codigo
    traducido = traducir_error_meta(info.value)
    assert isinstance(traducido, ErrorProveedor) and traducido.http == 502
    assert traducido.codigo == "ERROR_PROVEEDOR_META"
    assert fragmento in traducido.mensaje_publico
    assert ACCESS_TOKEN not in traducido.mensaje_publico and ACCESS_TOKEN not in caplog.text
    assert "sim" not in traducido.mensaje_publico.split()  # no copia el texto de Meta


async def test_token_incorrecto_es_un_error_de_acceso(sim):
    async def mal_token():
        return CredencialesMeta("otro-token-que-meta-rechaza", WABA_ID)

    c = cliente_para(sim.transporte(), credenciales=mal_token)
    with pytest.raises(ErrorMeta) as info:
        await c.listar()
    assert info.value.codigo == "190" and "token" in traducir_error_meta(info.value).mensaje_publico


async def test_tiempo_agotado_y_red_caida_son_errores_de_meta_no_500(caplog):
    def tiempo(peticion):
        raise httpx.ReadTimeout("tardó", request=peticion)

    def red(peticion):
        raise httpx.ConnectError("sin ruta", request=peticion)

    for responder, fragmento in ((tiempo, "no respondió a tiempo"), (red, "No se pudo contactar")):
        with pytest.raises(ErrorMeta) as info:
            await cliente_para(httpx.MockTransport(responder)).listar()
        traducido = traducir_error_meta(info.value)
        assert isinstance(traducido, ErrorProveedor) and fragmento in traducido.mensaje_publico
    assert ACCESS_TOKEN not in caplog.text


async def test_sin_credenciales_es_422_meta_no_configurada(caplog):
    async def sin():
        raise ErrorMeta("META_SIN_CREDENCIALES")

    with pytest.raises(ErrorMeta) as info:
        await cliente_para(
            httpx.MockTransport(lambda p: httpx.Response(500)), credenciales=sin
        ).listar()
    traducido = traducir_error_meta(info.value)
    assert isinstance(traducido, ErrorValidacion) and traducido.http == 422
    assert traducido.codigo == "META_NO_CONFIGURADA"
    assert "Conexión con Meta" in traducido.mensaje_publico


async def test_una_respuesta_que_no_es_json_no_rompe():
    r = cliente_para(httpx.MockTransport(lambda p: httpx.Response(200, text="<html>")))
    with pytest.raises(ErrorMeta) as info:
        await r.listar()
    assert isinstance(traducir_error_meta(info.value), ErrorProveedor)


async def test_el_sustituto_sin_red_devuelve_datos_de_ejemplo_coherentes():
    s = StubPlantillasMeta()
    r = await s.listar()
    assert len(r.items) == 13 and not r.truncado
    assert sum(t.estado == "APPROVED" for t in r.items) == 11
    # las siete plantillas reales de la cuenta compartida
    nombres = {t.nombre: t for t in r.items}
    for real in (
        "hello_world",
        "vida_aviso_checkout",
        "vida_bienvenida_llegada",
        "vida_recordatorio_prellegada",
        "vida_checkout_notice",
        "vida_prearrival_reminder",
        "vida_welcome_greeting",
    ):
        assert real in nombres, real
    assert nombres["hello_world"].idioma == "en_US"
    assert nombres["vida_aviso_checkout"].formato_parametros == "NAMED"
    assert {nombres[n].idioma for n in ("vida_checkout_notice", "vida_welcome_greeting")} == {"en"}
    assert (await s.obtener(nombre="bienvenida_colaborador", idioma="es_MX")).id
    assert await s.obtener(nombre="bienvenida_colaborador", idioma="en_US") is None
    s.error = ErrorMeta("META_TRANSITORIO")
    with pytest.raises(ErrorMeta):
        await s.listar()
