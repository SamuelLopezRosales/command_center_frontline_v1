"""Fixtures del servicio notificaciones: base real con el rol ``svc_notificaciones``."""

import httpx
import psycopg
import pytest
from ayudantes_notificaciones import Reloj, cab, construir_app, emitir, simulador_meta
from cc_common.db import crear_motor
from cc_notificaciones.clientes import (
    DefinicionCampo,
    OpcionCampo,
    StubCampos,
    StubColaboradores,
)
from cc_notificaciones.meta import CredencialesMeta, MetaPlantillasHttp
from cc_notificaciones.scheduler import StubScheduler


@pytest.fixture
def datos(bd_migrada):
    """Empresas A y B con un usuario RH cada una."""
    with psycopg.connect(bd_migrada.url_admin, autocommit=True) as c:

        def uno(sql, params=()):
            return c.execute(sql, params).fetchone()[0]

        a = uno("INSERT INTO identidad.empresa (razon_social) VALUES ('A') RETURNING id")
        b = uno("INSERT INTO identidad.empresa (razon_social) VALUES ('B') RETURNING id")
        ua = uno(
            "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
            "VALUES (%s, 'Ana RH', 'ana@a.com', 'sub-a') RETURNING id",
            (a,),
        )
        ub = uno(
            "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
            "VALUES (%s, 'Beto RH', 'beto@b.com', 'sub-b') RETURNING id",
            (b,),
        )
    return {"a": a, "b": b, "ua": ua, "ub": ub, "bd": bd_migrada}


@pytest.fixture
async def motor(datos):
    m = crear_motor(datos["bd"].url_rol("svc_notificaciones"))
    yield m
    await m.dispose()


def definiciones_base() -> list[DefinicionCampo]:
    """Catálogo de prueba (INT-CAM-01): una lista, un texto, un sensible y uno inactivo."""
    return [
        DefinicionCampo(1, "CAMP-0001", "NSS", "TEXTO", es_sensible=True),
        DefinicionCampo(
            2,
            "CAMP-0002",
            "Área",
            "LISTA",
            opciones=(OpcionCampo(10, "VENTAS", "Ventas"), OpcionCampo(11, "OLD", "Viejo", False)),
        ),
        DefinicionCampo(3, "CAMP-0003", "Puntos", "NUMERO"),
        DefinicionCampo(4, "CAMP-0004", "Notas", "TEXTO", activo=False),
    ]


@pytest.fixture
def campos(datos):
    return StubCampos({datos["a"]: definiciones_base(), datos["b"]: []})


@pytest.fixture
def colaboradores():
    return StubColaboradores()


@pytest.fixture
def sim():
    """Simulador de Meta (webhook y API de mensajes y plantillas)."""
    return simulador_meta().SimuladorMeta()


@pytest.fixture
def meta(sim):
    async def credenciales():
        return CredencialesMeta(sim.access_token, sim.waba_id)

    return MetaPlantillasHttp(credenciales, transporte=sim.transporte())


@pytest.fixture
def scheduler():
    return StubScheduler()


@pytest.fixture
def reloj():
    return Reloj()


@pytest.fixture
async def http(motor, campos, colaboradores, meta, scheduler, reloj):
    app = construir_app(motor, campos, colaboradores, meta=meta, scheduler=scheduler, reloj=reloj)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture
def h(datos):
    """Encabezados de la usuaria de la empresa A."""
    return cab(emitir("sub-a", datos["a"], datos["ua"]))


@pytest.fixture
def hb(datos):
    return cab(emitir("sub-b", datos["b"], datos["ub"]))
