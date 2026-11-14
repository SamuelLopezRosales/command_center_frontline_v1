from datetime import date

import pytest
from cc_common.tipos import (
    Celular10,
    Correo,
    Curp,
    FechaIngreso,
    Nss,
    NumeroEmpleado,
    RegistroPatronal,
    Rfc13,
    RfcOrg,
)
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError


class M(BaseModel):
    celular: Celular10 | None = None
    rfc: Rfc13 | None = None
    rfc_org: RfcOrg | None = None
    curp: Curp | None = None
    nss: Nss | None = None
    reg: RegistroPatronal | None = None
    num: NumeroEmpleado | None = None
    fecha: FechaIngreso | None = None
    correo: Correo | None = None


def _error(**kw) -> str:
    with pytest.raises(ValidationError) as exc:
        M(**kw)
    (e,) = exc.value.errors()
    return e["msg"]


@pytest.mark.parametrize("valor", ["8112345678", "81 1234 5678", "81-1234-5678"])
def test_celular_valido_se_normaliza(valor):
    assert M(celular=valor).celular == "8112345678"


@pytest.mark.parametrize(
    "valor", ["+528112345678", "528112345678", "811234567", "81123456789", "abc"]
)
def test_celular_invalido(valor):
    assert "10 dígitos" in _error(celular=valor)


@given(st.from_regex(r"\A\d{10}\Z", fullmatch=True))
def test_celular_propiedad(valor):
    assert M(celular=valor).celular == valor


def test_rfc_persona_13_y_mayusculas():
    assert M(rfc="xaxx010101000").rfc == "XAXX010101000"
    assert "13" in _error(rfc="EEJ010101AAA")


@pytest.mark.parametrize("valor", ["EEJ010101AAA", "XAXX010101000"])
def test_rfc_org_12_o_13(valor):
    assert M(rfc_org=valor).rfc_org == valor


def test_curp():
    assert M(curp="xexx010101hnexxxa4").curp == "XEXX010101HNEXXXA4"
    assert "18" in _error(curp="AAAA000000BBBB11")


def test_nss_y_registro_patronal():
    assert M(nss="00000000000").nss == "00000000000"
    assert "11" in _error(nss="111111111")
    assert M(reg="a0000000000").reg == "A0000000000"
    assert "11" in _error(reg="A000000")


def test_numero_empleado_normalizado():
    assert M(num="  emp-0009 ").num == "EMP-0009"
    assert "vacío" in _error(num="   ")
    assert "30" in _error(num="X" * 31)


@pytest.mark.parametrize("valor", ["15/03/2021", "2021-03-15", date(2021, 3, 15)])
def test_fecha_formatos(valor):
    assert M(fecha=valor).fecha == date(2021, 3, 15)


@pytest.mark.parametrize("valor", ["31/02/2021", "2021/03/15", "ayer"])
def test_fecha_invalida(valor):
    assert "Fecha inválida" in _error(fecha=valor)


def test_correo():
    assert M(correo="Maria.Ramirez@Ejemplo.com").correo == "maria.ramirez@ejemplo.com"
    assert "Correo" in _error(correo="sin-arroba")


@pytest.mark.parametrize(
    "campo,valor",
    [("celular", "5512349876X"), ("rfc", "ZZZZ999999ZZ"), ("curp", "BADCURP123"), ("nss", "98765")],
)
def test_mensajes_no_contienen_el_valor(campo, valor):
    assert valor not in _error(**{campo: valor})
