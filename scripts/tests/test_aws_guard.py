import json

import pytest

from scripts.aws_guard import verificar

ENTORNO_OK = {"AWS_PROFILE": "cc-test"}


def ejecutor(codigo=0, cuenta="034362033822", error=""):
    llamadas = []

    def _ej(cmd):
        llamadas.append(cmd)
        salida = json.dumps(
            {"Account": cuenta, "Arn": "arn:aws:sts::x:assumed-role/r/s", "UserId": "u"}
        )
        return codigo, salida if codigo == 0 else "", error

    _ej.llamadas = llamadas
    return _ej


def test_cuenta_correcta_devuelve_exito():
    ej = ejecutor()
    r = verificar("test", ENTORNO_OK, ej)
    assert r.ok and r.codigo == "OK" and r.cuenta == "034362033822"
    assert ej.llamadas == [
        [
            "aws",
            "sts",
            "get-caller-identity",
            "--profile",
            "cc-test",
            "--region",
            "us-east-1",
            "--output",
            "json",
        ]
    ]


@pytest.mark.parametrize(
    "error",
    [
        "Error when retrieving token from sso: Token has expired and refresh failed",
        "The SSO session associated with this profile has expired or is otherwise invalid.",
        "Error loading SSO Token: Token for cc-test does not exist",
    ],
)
def test_sesion_vencida_indica_login(error):
    r = verificar("test", ENTORNO_OK, ejecutor(codigo=255, error=error))
    assert not r.ok and r.codigo == "SESION_VENCIDA"
    assert "aws sso login --profile cc-test" in r.mensaje


def test_otro_fallo_de_sts_tambien_indica_login():
    r = verificar("test", ENTORNO_OK, ejecutor(codigo=254, error="Could not connect"))
    assert not r.ok and r.codigo == "STS_FALLO"
    assert "aws sso login --profile cc-test" in r.mensaje


@pytest.mark.parametrize("cuenta", ["686699774254", "111111111111"])
def test_cuenta_distinta_aborta(cuenta):
    r = verificar("test", ENTORNO_OK, ejecutor(cuenta=cuenta))
    assert not r.ok and r.codigo == "CUENTA_INCORRECTA"


@pytest.mark.parametrize("perfil", ["", "default", "cc-prod"])
def test_perfil_distinto_aborta_sin_llamar_a_aws(perfil):
    ej = ejecutor()
    entorno = {"AWS_PROFILE": perfil} if perfil else {}
    r = verificar("test", entorno, ej)
    assert not r.ok and r.codigo == "PERFIL_INCORRECTO"
    assert ej.llamadas == []


def test_llaves_en_el_entorno_abortan():
    ej = ejecutor()
    r = verificar("test", {"AWS_PROFILE": "cc-test", "AWS_ACCESS_KEY_ID": "x"}, ej)
    assert not r.ok and r.codigo == "LLAVES_EN_ENTORNO"
    assert ej.llamadas == []


def test_region_distinta_aborta():
    r = verificar("test", {"AWS_PROFILE": "cc-test", "AWS_REGION": "us-west-2"}, ejecutor())
    assert not r.ok and r.codigo == "REGION_INCORRECTA"


def test_respuesta_invalida():
    def ej(_cmd):
        return 0, "no es json", ""

    r = verificar("test", ENTORNO_OK, ej)
    assert not r.ok and r.codigo == "RESPUESTA_INVALIDA"
