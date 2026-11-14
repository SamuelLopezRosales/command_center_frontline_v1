"""T-036: ``cognito-pre-signup`` con eventos simulados."""

from datetime import UTC, datetime, timedelta

import pytest
from ayudantes_cognito import invitar
from cognito_triggers import comun, pre_signup

pytestmark = pytest.mark.docker


def evento(codigo="CODIGO-OK", correo="nuevo@a.com", origen="PreSignUp_SignUp"):
    atributos = {"email": correo, "name": "Nuevo"}
    if codigo is not None:
        atributos[comun.ATRIBUTO_CODIGO] = codigo
    return {
        "triggerSource": origen,
        "userName": correo,
        "request": {"userAttributes": atributos},
        "response": {},
    }


def test_codigo_valido_permite_sin_autoconfirmar(bd):
    invitar(bd, "CODIGO-OK")
    r = pre_signup.handler(evento())
    assert r["response"] == {
        "autoConfirmUser": False,
        "autoVerifyEmail": False,
        "autoVerifyPhone": False,
    }


def test_correo_se_compara_sin_importar_mayusculas(bd):
    invitar(bd, "CODIGO-OK", correo="Nuevo@A.com")
    assert pre_signup.handler(evento(correo="NUEVO@a.COM"))["response"]["autoConfirmUser"] is False


def _casos(bd):
    invitar(bd, "VENCIDO", expira=datetime.now(UTC) - timedelta(minutes=1))
    invitar(bd, "USADO", usada=True)
    invitar(bd, "OTRO-CORREO", correo="esperado@a.com")
    return [
        evento(codigo=None),
        evento(codigo=""),
        evento(codigo="NO-EXISTE"),
        evento(codigo="VENCIDO"),
        evento(codigo="USADO"),
        evento(codigo="OTRO-CORREO", correo="intruso@a.com"),
        evento(codigo="x" * 500),
        evento(origen="PreSignUp_AdminCreateUser"),
        evento(origen="PreSignUp_ExternalProvider"),
    ]


def test_todo_rechazo_usa_el_mismo_mensaje_generico(bd):
    mensajes = set()
    for caso in _casos(bd):
        with pytest.raises(comun.RegistroNoAutorizado) as exc:
            pre_signup.handler(caso)
        mensajes.add(str(exc.value))
    assert mensajes == {comun.MENSAJE_GENERICO}


def test_el_mensaje_no_revela_el_motivo(bd):
    invitar(bd, "USADO", usada=True)
    with pytest.raises(comun.RegistroNoAutorizado) as exc:
        pre_signup.handler(evento(codigo="USADO"))
    assert "usad" not in str(exc.value).lower() and "USADO" not in str(exc.value)
    assert exc.value.motivo == "codigo_no_valido"  # solo para el registro interno


def test_pre_signup_no_escribe_nada(bd):
    from ayudantes_cognito import consulta

    invitar(bd, "CODIGO-OK")
    antes = consulta(bd, "SELECT count(*) FROM identidad.usuario")
    pre_signup.handler(evento())
    assert consulta(bd, "SELECT count(*) FROM identidad.usuario") == antes
    assert consulta(
        bd, "SELECT count(*) FROM identidad.invitacion_registro WHERE fecha_uso IS NOT NULL"
    ) == [(0,)]
