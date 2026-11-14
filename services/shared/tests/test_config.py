import pytest
from cc_common.config import Configuracion
from pydantic import ValidationError


def test_valores_por_defecto(monkeypatch):
    monkeypatch.setenv("CC_SERVICIO", "colaboradores")
    c = Configuracion()
    assert c.servicio == "colaboradores"
    assert c.ambiente == "local" and c.es_local
    assert c.zona_horaria == "America/Mexico_City"
    assert c.db_ssl is True


def test_lee_variables_con_prefijo(monkeypatch):
    monkeypatch.setenv("CC_SERVICIO", "campos")
    monkeypatch.setenv("CC_AMBIENTE", "test")
    monkeypatch.setenv("CC_DB_HOST", "proxy.local")
    c = Configuracion()
    assert c.ambiente == "test" and c.db_host == "proxy.local" and not c.es_local


def test_ambiente_invalido(monkeypatch):
    monkeypatch.setenv("CC_SERVICIO", "x")
    monkeypatch.setenv("CC_AMBIENTE", "produccion")
    with pytest.raises(ValidationError):
        Configuracion()


def test_servicio_obligatorio(monkeypatch):
    monkeypatch.delenv("CC_SERVICIO", raising=False)
    with pytest.raises(ValidationError):
        Configuracion()
