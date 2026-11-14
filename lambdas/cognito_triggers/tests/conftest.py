"""Fixtures de los triggers de Cognito: base migrada y conexión como ``svc_dashboard``."""

import psycopg
import pytest
from cognito_triggers import comun


@pytest.fixture
def bd(bd_migrada, monkeypatch):
    """Empresa A con un usuario RH; las Lambdas se conectan como ``svc_dashboard``."""
    url = bd_migrada.url_rol("svc_dashboard", asincrona=False)
    monkeypatch.setattr(comun, "abrir_conexion", lambda: psycopg.connect(url))
    with psycopg.connect(bd_migrada.url_admin, autocommit=True) as c:
        a = c.execute(
            "INSERT INTO identidad.empresa (razon_social) VALUES ('A') RETURNING id"
        ).fetchone()[0]
        ua = c.execute(
            "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
            "VALUES (%s, 'Ana RH', 'ana@a.com', 'sub-ana') RETURNING id",
            (a,),
        ).fetchone()[0]
    return {"url": bd_migrada.url_admin, "empresa": a, "usuario": ua}
