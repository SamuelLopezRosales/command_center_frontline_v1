"""Fixtures de whatsapp: base migrada, conexión de las Lambdas como ``svc_whatsapp`` y simulador."""

import psycopg
import pytest
from ayudantes_whatsapp import crear_colaborador
from cc_whatsapp.config import ConfigWhatsapp
from cc_whatsapp.metricas import CONTADORES
from simulador_meta import SimuladorMeta


@pytest.fixture
def simulador():
    return SimuladorMeta()


@pytest.fixture
def cfg():
    return ConfigWhatsapp(
        meta_phone_number_id="PN-PRUEBA",
        cola_entrada_url="wa-entrada.fifo",
        cola_estados_url="wa-estados",
        cola_salida_url="wa-salida.fifo",
        bus_eventos="cc-prueba",
        plantilla_constancia_lista="constancia_lista",
    )


@pytest.fixture(autouse=True)
def _metricas_limpias():
    CONTADORES.clear()


@pytest.fixture
def datos(bd_migrada):
    """Empresa A con un colaborador; ``abrir`` conecta como ``svc_whatsapp`` (RLS vigente)."""
    with psycopg.connect(bd_migrada.url_admin, autocommit=True) as c:
        empresa = c.execute(
            "INSERT INTO identidad.empresa (razon_social) VALUES ('A') RETURNING id"
        ).fetchone()[0]
    d = {"url_admin": bd_migrada.url_admin, "empresa": empresa}
    d["colaborador"] = crear_colaborador(d)
    url = bd_migrada.url_rol("svc_whatsapp", asincrona=False)
    d["abrir"] = lambda: psycopg.connect(url)
    return d
