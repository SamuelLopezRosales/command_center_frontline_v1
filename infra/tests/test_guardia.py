import pytest

from infra.app import crear_app
from infra.config import esquema
from infra.guardia import CuentaNoPermitida, verificar_cuenta

PERMITIDA = "034362033822"


@pytest.fixture
def ambiente():
    return esquema.obtener_ambiente("test")


def test_cuenta_permitida_pasa(ambiente):
    destino = verificar_cuenta(
        ambiente, {"CDK_DEFAULT_ACCOUNT": PERMITIDA, "CDK_DEFAULT_REGION": "us-east-1"}
    )
    assert destino.cuenta == PERMITIDA
    assert destino.region == "us-east-1"


def test_region_por_defecto_del_ambiente(ambiente):
    destino = verificar_cuenta(ambiente, {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    assert destino.region == "us-east-1"


@pytest.mark.parametrize("cuenta", ["111111111111", "999999999999", "03436203382", " "])
def test_cuenta_distinta_falla(ambiente, cuenta):
    with pytest.raises(CuentaNoPermitida):
        verificar_cuenta(ambiente, {"CDK_DEFAULT_ACCOUNT": cuenta})


def test_cuenta_ausente_falla_con_indicacion_de_login(ambiente):
    with pytest.raises(CuentaNoPermitida, match="aws sso login --profile cc-test"):
        verificar_cuenta(ambiente, {})


def test_cuenta_vacia_falla(ambiente):
    with pytest.raises(CuentaNoPermitida):
        verificar_cuenta(ambiente, {"CDK_DEFAULT_ACCOUNT": ""})


def test_region_distinta_falla(ambiente):
    with pytest.raises(CuentaNoPermitida, match="región"):
        verificar_cuenta(
            ambiente, {"CDK_DEFAULT_ACCOUNT": PERMITIDA, "CDK_DEFAULT_REGION": "us-west-2"}
        )


def test_el_mensaje_no_revela_secretos(ambiente):
    with pytest.raises(CuentaNoPermitida) as exc:
        verificar_cuenta(ambiente, {"CDK_DEFAULT_ACCOUNT": "111111111111"})
    assert "AKIA" not in str(exc.value)


def test_crear_app_aplica_la_guardia_antes_de_crear_stacks():
    with pytest.raises(CuentaNoPermitida):
        crear_app("test", {"CDK_DEFAULT_ACCOUNT": "111111111111"})


def test_crear_app_ambiente_desconocido():
    with pytest.raises(esquema.ConfiguracionInvalida, match="desconocido"):
        crear_app("prod-falso", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})


def test_crear_app_sin_ambiente():
    with pytest.raises(esquema.ConfiguracionInvalida, match="falta el ambiente"):
        crear_app(None, {"CDK_DEFAULT_ACCOUNT": PERMITIDA})


def test_crear_app_correcta():
    _app, amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    assert amb.nombre == "test"
    assert destino.cuenta == PERMITIDA
