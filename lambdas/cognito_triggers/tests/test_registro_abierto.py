"""Registro abierto (``CC_REGISTRO=ABIERTO``, solo ambientes de prueba): sin código de invitación,
con dominios de correo permitidos y la única empresa activa."""

import psycopg
import pytest
from ayudantes_cognito import consulta
from cognito_triggers import comun, post_confirmation, pre_signup

pytestmark = pytest.mark.docker


@pytest.fixture(autouse=True)
def abierto(monkeypatch):
    monkeypatch.setenv("CC_REGISTRO", "ABIERTO")
    monkeypatch.setenv("CC_REGISTRO_DOMINIOS", "honne.com, Otra.mx")
    monkeypatch.setattr(comun, "cliente_cognito", lambda: pytest.fail("no debe tocar Cognito"))


def pre(correo, **atributos):
    return {
        "triggerSource": "PreSignUp_SignUp",
        "userName": correo,
        "request": {"userAttributes": {"email": correo, "name": "Nueva", **atributos}},
        "response": {},
    }


def post(sub="sub-abierto", correo="ana@honne.com"):
    return {
        "triggerSource": "PostConfirmation_ConfirmSignUp",
        "userPoolId": "us-east-1_PRUEBA",
        "userName": correo,
        "request": {"userAttributes": {"sub": sub, "email": correo, "name": "Ana Abierta"}},
        "response": {},
    }


def test_un_correo_de_un_dominio_permitido_se_registra_sin_codigo_ni_autoconfirmar():
    for correo in ("ana@honne.com", "BETO@Honne.COM", "x@otra.mx"):
        r = pre_signup.handler(pre(correo))
        assert (
            r["response"]
            == {
                "autoConfirmUser": False,  # Cognito sigue verificando que el correo sea de quien se registra
                "autoVerifyEmail": False,
                "autoVerifyPhone": False,
            }
        )


@pytest.mark.parametrize(
    "correo", ["intruso@gmail.com", "ana@honne.com.evil.com", "ana@sub.honne.com", "sin-arroba", ""]
)
def test_otro_dominio_o_sin_correo_se_rechaza(correo):
    with pytest.raises(comun.RegistroNoAutorizado):
        pre_signup.handler(pre(correo))


def test_sin_dominios_configurados_no_se_admite_a_nadie(monkeypatch):
    monkeypatch.setenv("CC_REGISTRO_DOMINIOS", "")
    with pytest.raises(comun.RegistroNoAutorizado):
        pre_signup.handler(pre("ana@honne.com"))


def test_solo_el_registro_desde_la_aplicacion_pasa_por_el_trigger():
    e = pre("ana@honne.com")
    e["triggerSource"] = "PreSignUp_AdminCreateUser"
    with pytest.raises(comun.RegistroNoAutorizado):
        pre_signup.handler(e)


def test_el_codigo_de_invitacion_se_ignora_en_registro_abierto():
    r = pre_signup.handler(pre("ana@honne.com", **{comun.ATRIBUTO_CODIGO: "cualquier-cosa"}))
    assert r["response"]["autoConfirmUser"] is False


def test_al_confirmar_crea_el_usuario_rh_de_la_unica_empresa_con_bitacora(bd):
    post_confirmation.handler(post())
    usuarios = consulta(bd, "SELECT empresa_id, rol, correo, nombre FROM identidad.usuario "
                        "WHERE cognito_sub = 'sub-abierto'")  # fmt: skip
    assert usuarios == [(bd["empresa"], "RH", "ana@honne.com", "Ana Abierta")]
    bit = consulta(
        bd, "SELECT accion, origen FROM auditoria.bitacora WHERE accion = 'USUARIO_REGISTRADO'"
    )
    assert bit == [("USUARIO_REGISTRADO", "USUARIO")]


def test_confirmar_dos_veces_no_duplica_al_usuario(bd):
    post_confirmation.handler(post())
    post_confirmation.handler(post())  # Cognito puede reintentar el trigger
    assert consulta(
        bd, "SELECT count(*) FROM identidad.usuario WHERE cognito_sub = 'sub-abierto'"
    ) == [(1,)]


def test_con_dos_empresas_activas_no_se_adivina_y_se_rechaza(bd):
    with psycopg.connect(bd["url"], autocommit=True) as c:
        c.execute("INSERT INTO identidad.empresa (razon_social) VALUES ('Otra')")
    with pytest.raises(comun.RegistroNoAutorizado):
        post_confirmation.handler(post())
    assert consulta(
        bd, "SELECT count(*) FROM identidad.usuario WHERE cognito_sub = 'sub-abierto'"
    ) == [(0,)]


def test_sin_empresa_activa_se_rechaza(bd):
    with psycopg.connect(bd["url"], autocommit=True) as c:
        c.execute("UPDATE identidad.empresa SET activa = false")
    with pytest.raises(comun.RegistroNoAutorizado):
        post_confirmation.handler(post())


def test_el_dominio_se_vuelve_a_comprobar_al_confirmar(bd):
    with pytest.raises(comun.RegistroNoAutorizado):
        post_confirmation.handler(post(correo="intruso@gmail.com"))
