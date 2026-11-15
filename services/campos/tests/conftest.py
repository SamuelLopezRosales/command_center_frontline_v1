"""Fixtures del servicio campos: base real con el rol ``svc_campos``."""

import httpx
import psycopg
import pytest
from ayudantes_campos import cab, construir_app, emitir
from cc_campos.clientes import StubColaboradores, StubConstancias
from cc_common.db import crear_motor


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
    m = crear_motor(datos["bd"].url_rol("svc_campos"))
    yield m
    await m.dispose()


@pytest.fixture
def colaboradores():
    return StubColaboradores()


@pytest.fixture
def constancias():
    return StubConstancias()


@pytest.fixture
async def http(motor, colaboradores, constancias):
    app = construir_app(motor, colaboradores, constancias)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture
def h(datos):
    """Encabezados de la usuaria de la empresa A."""
    return cab(emitir("sub-a", datos["a"], datos["ua"]))


@pytest.fixture
def hb(datos):
    return cab(emitir("sub-b", datos["b"], datos["ub"]))
