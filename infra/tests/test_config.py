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


def test_mfa_obligatorio_por_defecto_y_apagado_solo_en_samuel():
    assert esquema.obtener_ambiente("test").economia.mfa == "ON"
    assert esquema.obtener_ambiente("samuel").economia.mfa == "OFF"


def test_el_mfa_solo_admite_on_optional_u_off_y_prod_exige_on():
    datos = _base()
    datos["ambientes"]["test"]["economia"]["mfa"] = "MAYBE"
    with pytest.raises(ConfiguracionInvalida, match="mfa"):
        parsear(_texto(datos))
    datos = _base()
    datos["ambientes"]["test"]["economia"]["mfa"] = "OPTIONAL"
    assert parsear(_texto(datos))["test"].economia.mfa == "OPTIONAL"
    datos["ambientes"]["test"]["economia"]["permite_borrado"] = False  # tipo prod
    with pytest.raises(ConfiguracionInvalida, match="MFA obligatorio"):
        parsear(_texto(datos))


def test_todo_ambiente_de_ambientes_json_es_un_valor_valido_de_cc_ambiente(monkeypatch):
    """Los servicios reciben ``CC_AMBIENTE=<nombre>``: un nombre que ``cc_common`` rechace tumba
    todas las tareas al arrancar (falla vista al desplegar `samuel` por primera vez)."""
    from cc_common.config import Configuracion

    monkeypatch.setenv("CC_SERVICIO", "prueba")
    for nombre in esquema.cargar():
        monkeypatch.setenv("CC_AMBIENTE", nombre)
        assert Configuracion().ambiente == nombre


def test_registro_por_invitacion_por_defecto_y_abierto_solo_en_samuel():
    assert esquema.obtener_ambiente("test").economia.registro == "INVITACION"
    samuel = esquema.obtener_ambiente("samuel").economia
    assert samuel.registro == "ABIERTO" and samuel.registro_dominios == ("honne.com",)


def test_el_registro_abierto_exige_dominios_y_no_se_admite_en_prod():
    datos = _base()
    eco = datos["ambientes"]["test"]["economia"]
    eco["registro"] = "ABIERTO"
    with pytest.raises(ConfiguracionInvalida, match="registro_dominios"):
        parsear(_texto(datos))
    eco["registro_dominios"] = ["no es un dominio"]
    with pytest.raises(ConfiguracionInvalida, match="registro_dominios"):
        parsear(_texto(datos))
    eco["registro_dominios"] = ["Honne.com"]
    assert parsear(_texto(datos))["test"].economia.registro_dominios == ("honne.com",)
    eco["permite_borrado"] = False  # tipo prod
    eco["mfa"] = "ON"
    with pytest.raises(ConfiguracionInvalida, match="invitación"):
        parsear(_texto(datos))
    eco["registro"] = "OTRO"
    with pytest.raises(ConfiguracionInvalida, match="registro"):
        parsear(_texto(datos))
