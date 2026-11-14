"""T-036: ``cognito-post-confirmation`` con eventos simulados."""

import pytest
from ayudantes_cognito import consulta, invitar
from cognito_triggers import comun, post_confirmation

pytestmark = pytest.mark.docker


class CognitoFalso:
    def __init__(self, falla=False):
        self.llamadas = []
        self.falla = falla

    def admin_update_user_attributes(self, **kw):
        if self.falla:
            raise RuntimeError("cognito caído")
        self.llamadas.append(kw)


@pytest.fixture
def cognito(monkeypatch):
    falso = CognitoFalso()
    monkeypatch.setattr(comun, "cliente_cognito", lambda: falso)
    return falso


def evento(sub="sub-nuevo", correo="nuevo@a.com", codigo="CODIGO-OK", origen=None):
    return {
        "triggerSource": origen or "PostConfirmation_ConfirmSignUp",
        "userPoolId": "us-east-1_PRUEBA",
        "userName": correo,
        "request": {
            "userAttributes": {
                "sub": sub,
                "email": correo,
                "name": "Nuevo Usuario",
                comun.ATRIBUTO_CODIGO: codigo,
            }
        },
        "response": {},
    }


def test_crea_usuario_rh_marca_invitacion_y_registra_bitacora(bd, cognito):
    inv = invitar(bd, "CODIGO-OK")
    post_confirmation.handler(evento())
    u = consulta(
        bd,
        "SELECT empresa_id, nombre, correo, rol, activo FROM identidad.usuario WHERE cognito_sub = 'sub-nuevo'",
    )
    assert u == [(bd["empresa"], "Nuevo Usuario", "nuevo@a.com", "RH", True)]
    nuevo = consulta(bd, "SELECT id FROM identidad.usuario WHERE cognito_sub = 'sub-nuevo'")[0][0]
    assert consulta(
        bd,
        "SELECT usada_por_usuario_id, fecha_uso IS NOT NULL FROM identidad.invitacion_registro WHERE id = %s",
        (inv,),
    ) == [(nuevo, True)]
    assert consulta(
        bd,
        "SELECT empresa_id, usuario_id, entidad_id, origen, detalle FROM auditoria.bitacora "
        "WHERE accion = 'USUARIO_REGISTRADO'",
    ) == [(bd["empresa"], nuevo, nuevo, "USUARIO", {})]


def test_invalida_el_atributo_del_codigo_en_cognito(bd, cognito):
    invitar(bd, "CODIGO-OK")
    post_confirmation.handler(evento())
    assert len(cognito.llamadas) == 1
    atributos = cognito.llamadas[0]["UserAttributes"]
    assert atributos == [{"Name": comun.ATRIBUTO_CODIGO, "Value": "usado"}]
    assert "CODIGO-OK" not in str(cognito.llamadas)


def test_fallo_al_invalidar_el_atributo_no_deshace_el_registro(bd, monkeypatch):
    monkeypatch.setattr(comun, "cliente_cognito", lambda: CognitoFalso(falla=True))
    invitar(bd, "CODIGO-OK")
    post_confirmation.handler(evento())
    assert consulta(
        bd, "SELECT count(*) FROM identidad.usuario WHERE cognito_sub = 'sub-nuevo'"
    ) == [(1,)]


def test_reintento_de_cognito_es_idempotente(bd, cognito):
    invitar(bd, "CODIGO-OK")
    post_confirmation.handler(evento())
    post_confirmation.handler(evento())
    assert consulta(
        bd, "SELECT count(*) FROM identidad.usuario WHERE cognito_sub = 'sub-nuevo'"
    ) == [(1,)]
    assert consulta(
        bd, "SELECT count(*) FROM auditoria.bitacora WHERE accion = 'USUARIO_REGISTRADO'"
    ) == [(1,)]
    assert len(cognito.llamadas) == 1


def test_codigo_usado_dos_veces_el_segundo_se_rechaza_sin_dejar_nada(bd, cognito):
    invitar(bd, "CODIGO-OK")
    post_confirmation.handler(evento())
    with pytest.raises(comun.RegistroNoAutorizado):
        post_confirmation.handler(evento(sub="sub-otro", correo="otro@a.com"))
    assert consulta(
        bd, "SELECT count(*) FROM identidad.usuario WHERE cognito_sub = 'sub-otro'"
    ) == [(0,)]


def test_todo_o_nada_si_falla_a_medias(bd, cognito):
    """Un correo ya registrado viola la unicidad al crear el usuario: la invitación no se marca."""
    inv = invitar(bd, "CODIGO-OK")
    with pytest.raises(Exception):  # noqa: B017, PT011 - violación de unicidad de PostgreSQL
        post_confirmation.handler(evento(sub="sub-dup", correo="ANA@a.com"))
    assert consulta(
        bd, "SELECT usada_por_usuario_id FROM identidad.invitacion_registro WHERE id = %s", (inv,)
    ) == [(None,)]
    assert consulta(
        bd, "SELECT count(*) FROM auditoria.bitacora WHERE accion = 'USUARIO_REGISTRADO'"
    ) == [(0,)]
    assert cognito.llamadas == []


@pytest.mark.parametrize("caso", ["sin_codigo", "correo_distinto", "vencida"])
def test_rechazos_no_crean_usuario(bd, cognito, caso):
    from datetime import UTC, datetime, timedelta

    if caso == "correo_distinto":
        invitar(bd, "CODIGO-OK", correo="otro@a.com")
    elif caso == "vencida":
        invitar(bd, "CODIGO-OK", expira=datetime.now(UTC) - timedelta(minutes=1))
    else:
        invitar(bd, "CODIGO-OK")
    ev = evento(codigo="" if caso == "sin_codigo" else "CODIGO-OK")
    with pytest.raises(comun.RegistroNoAutorizado):
        post_confirmation.handler(ev)
    assert consulta(
        bd, "SELECT count(*) FROM identidad.usuario WHERE cognito_sub = 'sub-nuevo'"
    ) == [(0,)]


def test_confirmar_cambio_de_contrasena_no_hace_nada(bd, cognito):
    invitar(bd, "CODIGO-OK")
    ev = evento(origen="PostConfirmation_ConfirmForgotPassword")
    assert post_confirmation.handler(ev) is ev
    assert consulta(bd, "SELECT count(*) FROM identidad.usuario") == [(1,)]
