import copy
import json

import pytest

from infra.config import esquema
from infra.config.esquema import ConfiguracionInvalida, parsear


def _base() -> dict:
    return json.loads(esquema.RUTA_POR_DEFECTO.read_text(encoding="utf-8"))


def _texto(datos: dict) -> str:
    return json.dumps(datos)


def test_archivo_real_es_valido():
    amb = esquema.obtener_ambiente("test")
    assert amb.cuentas_permitidas == ("034362033822",)
    assert amb.region == "us-east-1"
    assert amb.perfil == "cc-test"
    assert amb.presupuesto.monto_usd == 50
    assert amb.presupuesto.correo == "samuel.lopez@honne.com"
    assert [(a.tipo, a.umbral_pct) for a in amb.presupuesto.alertas] == [
        ("ACTUAL", 80),
        ("ACTUAL", 100),
        ("PRONOSTICADO", 100),
    ]
    assert amb.etiquetas == {
        "proyecto": "command-center",
        "ambiente": "test",
        "responsable": "Samuel Lopez",
    }


def test_configuracion_economica_de_test():
    eco = esquema.obtener_ambiente("test").economia
    assert eco.nat == "instancia"
    assert eco.rds_clase == "db.t4g.micro"
    assert eco.rds_proxy is False
    assert eco.waf_habilitado is False
    assert eco.workers_min_tareas == 0
    assert eco.permite_borrado is True


def test_rechaza_ambiente_sin_cuenta():
    datos = _base()
    datos["ambientes"]["test"]["cuentas_permitidas"] = []
    with pytest.raises(ConfiguracionInvalida, match="cuentas_permitidas"):
        parsear(_texto(datos))


def test_rechaza_cuenta_mal_formada():
    datos = _base()
    datos["ambientes"]["test"]["cuentas_permitidas"] = ["12345"]
    with pytest.raises(ConfiguracionInvalida, match="12 dígitos"):
        parsear(_texto(datos))


@pytest.mark.parametrize("perfil", ["default", "cc-prod", "otro", ""])
def test_rechaza_perfil_distinto_de_cc_test(perfil):
    datos = _base()
    datos["ambientes"]["test"]["perfil"] = perfil
    with pytest.raises(ConfiguracionInvalida):
        parsear(_texto(datos))


def test_rechaza_etiqueta_faltante():
    datos = _base()
    del datos["ambientes"]["test"]["etiquetas"]["responsable"]
    with pytest.raises(ConfiguracionInvalida, match="responsable"):
        parsear(_texto(datos))


def test_rechaza_etiqueta_ambiente_incoherente():
    datos = _base()
    datos["ambientes"]["test"]["etiquetas"]["ambiente"] = "prod"
    with pytest.raises(ConfiguracionInvalida, match="ambiente"):
        parsear(_texto(datos))


def test_rechaza_presupuesto_invalido():
    datos = _base()
    datos["ambientes"]["test"]["presupuesto"]["monto_usd"] = 0
    with pytest.raises(ConfiguracionInvalida, match="presupuesto"):
        parsear(_texto(datos))
    datos = copy.deepcopy(_base())
    datos["ambientes"]["test"]["presupuesto"]["correo"] = "no-es-correo"
    with pytest.raises(ConfiguracionInvalida, match="correo"):
        parsear(_texto(datos))


def test_ambiente_desconocido():
    with pytest.raises(ConfiguracionInvalida, match="desconocido"):
        esquema.obtener_ambiente("produccion")


def test_rechaza_llave_de_acceso_en_el_archivo():
    texto = _texto(_base()).replace("Samuel Lopez", "AKIAZZZZZZZZZZZZZZZZ")
    with pytest.raises(ConfiguracionInvalida, match="llave de acceso"):
        parsear(texto)


def test_rechaza_claves_de_credenciales():
    datos = _base()
    datos["ambientes"]["test"]["aws_secret_access_key"] = "x"
    with pytest.raises(ConfiguracionInvalida, match="prohibida"):
        parsear(_texto(datos))


def test_el_archivo_real_no_contiene_credenciales():
    contenido = esquema.RUTA_POR_DEFECTO.read_text(encoding="utf-8")
    assert not esquema._LLAVE_AWS.search(contenido)
    for clave in esquema._CLAVES_PROHIBIDAS:
        assert clave not in contenido.lower()
