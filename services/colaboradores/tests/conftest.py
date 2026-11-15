"""Fixtures del servicio colaboradores: base real con el rol ``svc_colaboradores``."""

import httpx
import psycopg
import pytest
from ayudantes_colaboradores import LLAVE_HMAC, LLAVE_KMS, KmsFalso, construir_app
from cc_colaboradores.cifrado import Cifrador
from cc_common.db import crear_motor


@pytest.fixture
def datos(bd_migrada):
    """Empresas A y B con un usuario RH cada una, más dos campos de A (uno sensible)."""
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
        campos = {}
        for clave, codigo, tipo, sensible in (
            ("nss", "CAMP-0001", "TEXTO", True),
            ("area", "CAMP-0002", "LISTA", False),
            ("sueldo", "CAMP-0003", "NUMERO", True),
            ("antiguedad_fecha", "CAMP-0004", "FECHA", False),
        ):
            campos[clave] = uno(
                "INSERT INTO campos.campo_colaborador (empresa_id, nombre_campo, clave, "
                "codigo_interno, tipo_dato, orden, es_sensible) VALUES (%s, %s, %s, %s, %s, 1, %s) "
                "RETURNING id",
                (a, clave.upper(), clave, codigo, tipo, sensible),
            )
        opcion = uno(
            "INSERT INTO campos.opcion_campo (empresa_id, campo_id, etiqueta, valor) "
            "VALUES (%s, %s, 'Ventas', 'VENTAS') RETURNING id",
            (a, campos["area"]),
        )
    return {
        "a": a,
        "b": b,
        "ua": ua,
        "ub": ub,
        "campos": campos,
        "opcion": opcion,
        "bd": bd_migrada,
    }


@pytest.fixture
def kms():
    return KmsFalso()


@pytest.fixture
def cifrador(kms):
    return Cifrador(kms, LLAVE_KMS, LLAVE_HMAC)


@pytest.fixture
async def motor(datos):
    m = crear_motor(datos["bd"].url_rol("svc_colaboradores"))
    yield m
    await m.dispose()


@pytest.fixture
async def cliente(motor, cifrador):
    app = construir_app(motor, cifrador)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
