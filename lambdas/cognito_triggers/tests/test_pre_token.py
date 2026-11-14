"""T-037: ``cognito-pre-token`` con eventos simulados."""

import psycopg
import pytest
from cognito_triggers import pre_token

pytestmark = pytest.mark.docker


def evento(sub="sub-ana", origen="TokenGeneration_Authentication"):
    return {
        "version": "2",
        "triggerSource": origen,
        "request": {"userAttributes": {"sub": sub}},
        "response": {},
    }


def _fijar(bd, sql, params=()):
    with psycopg.connect(bd["url"], autocommit=True) as c:
        c.execute(sql, params)


def _claims(r):
    return r["response"]["claimsAndScopeOverrideDetails"]["accessTokenGeneration"][
        "claimsToAddOrOverride"
    ]


def test_agrega_empresa_id_y_rol_al_token_de_acceso(bd):
    r = pre_token.handler(evento())
    assert _claims(r) == {"empresa_id": str(bd["empresa"]), "rol": "RH"}


def test_conserva_otras_modificaciones_de_la_respuesta(bd):
    ev = evento()
    ev["response"] = {"claimsAndScopeOverrideDetails": {"idTokenGeneration": {"x": 1}}}
    r = pre_token.handler(ev)
    assert r["response"]["claimsAndScopeOverrideDetails"]["idTokenGeneration"] == {"x": 1}
    assert _claims(r)["rol"] == "RH"


def test_usuario_inexistente_no_agrega_nada(bd):
    r = pre_token.handler(evento(sub="sub-fantasma"))
    assert r["response"] == {}


def test_usuario_inactivo_se_rechaza_en_cualquier_origen(bd):
    _fijar(bd, "UPDATE identidad.usuario SET activo = false WHERE cognito_sub = 'sub-ana'")
    for origen in ("TokenGeneration_Authentication", "TokenGeneration_RefreshTokens"):
        with pytest.raises(pre_token.SesionNoPermitida):
            pre_token.handler(evento(origen=origen))


def test_renovar_con_mas_de_30_minutos_de_inactividad_se_rechaza(bd):
    _fijar(
        bd,
        "UPDATE identidad.usuario SET ultima_actividad = now() - interval '31 minutes' "
        "WHERE cognito_sub = 'sub-ana'",
    )
    with pytest.raises(pre_token.SesionNoPermitida):
        pre_token.handler(evento(origen="TokenGeneration_RefreshTokens"))


def test_renovar_con_menos_de_30_minutos_se_permite(bd):
    _fijar(
        bd,
        "UPDATE identidad.usuario SET ultima_actividad = now() - interval '29 minutes' "
        "WHERE cognito_sub = 'sub-ana'",
    )
    r = pre_token.handler(evento(origen="TokenGeneration_RefreshTokens"))
    assert _claims(r)["rol"] == "RH"


def test_inicio_de_sesion_interactivo_no_se_bloquea_por_inactividad(bd):
    """Quien vuelve tras horas sin entrar debe poder autenticarse de nuevo."""
    _fijar(
        bd,
        "UPDATE identidad.usuario SET ultima_actividad = now() - interval '3 days' "
        "WHERE cognito_sub = 'sub-ana'",
    )
    assert _claims(pre_token.handler(evento()))["empresa_id"] == str(bd["empresa"])


def test_primer_inicio_sin_actividad_previa_se_permite(bd):
    r = pre_token.handler(evento(origen="TokenGeneration_RefreshTokens"))
    assert _claims(r)["rol"] == "RH"


def test_evento_sin_sub_no_agrega_nada(bd):
    ev = {"triggerSource": "TokenGeneration_Authentication", "request": {}, "response": {}}
    assert pre_token.handler(ev)["response"] == {}
