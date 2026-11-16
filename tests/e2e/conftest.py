"""Fixtures de la prueba E2E de la constancia por WhatsApp (T-214).

Usa lo ya existente de ``tests/fixtures/plugin.py``: ``bd_migrada`` (PostgreSQL 16 migrado, con RLS
y roles de servicio), ``localstack`` (SQS, EventBridge, SNS y S3) y el marcador ``docker``.
"""

import logging

import pytest
from ayudantes_e2e import FalsoPdf, cerrar_mundo, construir_mundo
from ayudantes_e2e_notif import cerrar_mundo_notificaciones, construir_mundo_notificaciones


def _registro(caplog) -> None:
    """INFO para todo; ``httpx`` en WARNING: registraría las URL que la propia prueba visita
    (con el token del enlace) y botocore en DEBUG imprimiría cuerpos de SQS de la prueba."""
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.WARNING, logger="httpx")


@pytest.fixture
async def mundo(bd_migrada, localstack, caplog):
    """Empresa A con su colaborador y una plantilla activa; renderizador de PDF inyectado."""
    _registro(caplog)
    w = await construir_mundo(bd_migrada, localstack)
    yield w
    await cerrar_mundo(w)


@pytest.fixture
async def mundo_dos_empresas(bd_migrada, localstack, caplog):
    _registro(caplog)
    w = await construir_mundo(bd_migrada, localstack, con_empresa_b=True)
    yield w
    await cerrar_mundo(w)


@pytest.fixture
async def mundo_varias_plantillas(bd_migrada, localstack, caplog):
    _registro(caplog)
    w = await construir_mundo(bd_migrada, localstack, plantillas=2)
    yield w
    await cerrar_mundo(w)


@pytest.fixture
async def mundo_pdf_falla(bd_migrada, localstack, caplog):
    """El renderizador falla siempre: tras ``max_intentos_pdf`` la solicitud queda FALLIDA."""
    _registro(caplog)
    w = await construir_mundo(bd_migrada, localstack, pdf=FalsoPdf(fallos=None))
    yield w
    await cerrar_mundo(w)


@pytest.fixture
async def mundo_notif(bd_migrada, localstack, caplog):
    """Empresas A y B con `notificaciones`, el chat de RH, las Lambdas despachador y respaldo-correo,
    y los colaboradores de la prueba (T-218)."""
    _registro(caplog)
    w = await construir_mundo_notificaciones(bd_migrada, localstack)
    yield w
    await cerrar_mundo_notificaciones(w)
