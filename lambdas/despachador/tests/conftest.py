"""Fixtures: base migrada con las empresas A y B (ver ``notif_comun.pruebas``)."""

import pytest
from notif_comun.metricas import CONTADORES
from notif_comun.pruebas import Mundo


@pytest.fixture
def mundo(bd_migrada):
    return Mundo(bd_migrada)


@pytest.fixture(autouse=True)
def _metricas_limpias():
    CONTADORES.clear()
