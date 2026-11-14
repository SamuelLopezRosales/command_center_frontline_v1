"""Fixtures del servicio dashboard: app con base real (rol svc_dashboard) y tokens firmados."""

import httpx
import psycopg
import pytest
from ayudantes_dashboard import CLIENTE, EMISOR, LLAVE, CognitoFalso
from cc_common.auth import VerificadorToken
from cc_common.db import crear_motor
from cc_dashboard.config import ConfigDashboard
from cc_dashboard.main import crear_app


@pytest.fixture
def datos(bd_migrada):
    """Empresa A con un usuario RH activo y uno inactivo; empresa B con un usuario."""
    with psycopg.connect(bd_migrada.url_admin, autocommit=True) as c:
        a = c.execute(
            "INSERT INTO identidad.empresa (razon_social) VALUES ('A') RETURNING id"
        ).fetchone()[0]
        b = c.execute(
            "INSERT INTO identidad.empresa (razon_social) VALUES ('B') RETURNING id"
        ).fetchone()[0]
        ua = c.execute(
            "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
            "VALUES (%s, 'Ana RH', 'ana@a.com', 'sub-a') RETURNING id",
            (a,),
        ).fetchone()[0]
        ui = c.execute(
            "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub, activo) "
            "VALUES (%s, 'Inactivo', 'ina@a.com', 'sub-inactivo', false) RETURNING id",
            (a,),
        ).fetchone()[0]
        ub = c.execute(
            "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
            "VALUES (%s, 'Beto RH', 'beto@b.com', 'sub-b') RETURNING id",
            (b,),
        ).fetchone()[0]
    return {"a": a, "b": b, "ua": ua, "ui": ui, "ub": ub, "bd": bd_migrada}


@pytest.fixture
def cognito():
    return CognitoFalso()


@pytest.fixture
async def cliente(datos, cognito):
    motor = crear_motor(datos["bd"].url_rol("svc_dashboard"))
    verificador = VerificadorToken(EMISOR, CLIENTE, resolver_llave=lambda _t: LLAVE.public_key())
    app = crear_app(
        ConfigDashboard(cognito_emisor=EMISOR, cognito_client_id=CLIENTE),
        motor=motor,
        verificador=verificador,
        cognito=cognito,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await motor.dispose()
