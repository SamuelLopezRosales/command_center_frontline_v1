"""T-201: ``ValidadorCampos``, el stub de INT-CAM-01 y su caché (sin base de datos)."""

from datetime import date
from decimal import Decimal

import pytest
from cc_colaboradores.campos_cliente import CacheCampos, DefinicionCampo, OpcionCampo, StubCampos
from cc_colaboradores.validador_campos import ValidadorCampos


def d(i, clave, tipo, **kw):
    return DefinicionCampo(
        id=i, nombre_campo=clave, clave=clave, codigo_interno=f"CAMP-{i:04d}", tipo_dato=tipo, **kw
    )


DEFS = [
    d(1, "nss", "TEXTO", es_sensible=True, formato_validacion=r"\d{11}"),
    d(
        2,
        "area",
        "LISTA",
        opciones=(
            OpcionCampo(10, "Ventas", "VENTAS"),
            OpcionCampo(11, "Vieja", "VIEJA", activo=False),
        ),
    ),
    d(3, "sueldo", "NUMERO", es_sensible=True),
    d(4, "periodicidad_sueldo", "LISTA", opciones=(OpcionCampo(20, "Mensual", "MENSUAL"),)),
    d(5, "ingreso_planta", "FECHA"),
    d(6, "usa_transporte", "SI_NO"),
    d(7, "correo", "TEXTO", obligatorio=True),
    d(8, "ruta_transporte", "TEXTO", activo=False),
]
V = ValidadorCampos(DEFS)


def _ok(valores, **kw):
    r, e = V.validar({"CAMP-0007": "x@a.com", **valores}, **kw)
    assert e == [], e
    return {x.codigo_interno: x for x in r}


def test_tipos_se_normalizan():
    r = _ok(
        {
            "CAMP-0001": "12345678901",
            "CAMP-0002": "VENTAS",
            "CAMP-0003": "9,500.5",
            "CAMP-0004": "MENSUAL",
            "CAMP-0005": "15/03/2021",
            "CAMP-0006": "Sí",
        }
    )
    assert r["CAMP-0001"].valor == "12345678901" and r["CAMP-0001"].es_sensible
    assert r["CAMP-0002"].valor == 10  # id de la opción
    assert r["CAMP-0003"].valor == Decimal("9500.5000")
    assert r["CAMP-0005"].valor == date(2021, 3, 15)
    assert r["CAMP-0006"].valor is True


@pytest.mark.parametrize(
    ("valores", "campo", "codigo"),
    [
        ({"CAMP-0001": "123"}, "campos.CAMP-0001", "FORMATO_INVALIDO"),
        ({"CAMP-0001": "1234567890123"}, "campos.CAMP-0001", "FORMATO_INVALIDO"),
        ({"CAMP-0002": "VIEJA"}, "campos.CAMP-0002", "VALOR_LISTA_INVALIDO"),
        ({"CAMP-0002": "OTRA"}, "campos.CAMP-0002", "VALOR_LISTA_INVALIDO"),
        ({"CAMP-0003": "mucho", "CAMP-0004": "MENSUAL"}, "campos.CAMP-0003", "FORMATO_INVALIDO"),
        ({"CAMP-0005": "31/02/2021"}, "campos.CAMP-0005", "FECHA_INVALIDA"),
        ({"CAMP-0006": "tal vez"}, "campos.CAMP-0006", "VALOR_NO_PERMITIDO"),
        ({"CAMP-9999": "dato-secreto"}, "campos.CAMP-9999", "CAMPO_DESCONOCIDO"),
        ({"CAMP-0008": "dato-secreto"}, "campos.CAMP-0008", "CAMPO_INACTIVO"),
        ({"CAMP-0003": "100"}, "campos.CAMP-0003", "SUELDO_SIN_PERIODICIDAD"),
    ],
)
def test_errores_por_campo_sin_eco_del_valor(valores, campo, codigo):
    _, errores = V.validar({"CAMP-0007": "x@a.com", **valores})
    assert [(e.campo, e.codigo) for e in errores] == [(campo, codigo)]
    for e in errores:
        for v in valores.values():
            assert str(v) not in e.mensaje


def test_obligatorio_en_alta_y_no_en_edicion():
    _, errores = V.validar({})
    assert [(e.campo, e.codigo) for e in errores] == [("campos.CAMP-0007", "REQUERIDO")]
    _, errores = V.validar({}, parcial=True)
    assert errores == []
    _, errores = V.validar({"CAMP-0007": "  "}, parcial=True)
    assert [e.codigo for e in errores] == ["REQUERIDO"]


def test_vacio_en_opcional_borra_el_valor():
    r = _ok({"CAMP-0005": ""})
    assert r["CAMP-0005"].valor is None


def test_texto_largo_y_formato_con_re2():
    _, errores = V.validar({"CAMP-0007": "x" * 501})
    assert [e.codigo for e in errores] == ["DEMASIADO_LARGO"]
    # Un patrón con retroceso catastrófico en motores clásicos responde al instante con re2.
    malo = ValidadorCampos([d(1, "t", "TEXTO", formato_validacion=r"(a+)+$")])
    _, errores = malo.validar({"CAMP-0001": "a" * 450 + "!"})
    assert [e.codigo for e in errores] == ["FORMATO_INVALIDO"]


async def test_stub_y_cache_de_60_segundos():
    reloj = {"t": 0.0}
    stub = StubCampos({1: DEFS})
    cache = CacheCampos(stub, reloj=lambda: reloj["t"])
    assert len(await cache.definiciones(1)) == len(DEFS)
    await cache.definiciones(1)
    assert stub.llamadas == 1
    reloj["t"] = 61
    await cache.definiciones(1)
    assert stub.llamadas == 2
    cache.invalidar(1)  # evento campo.actualizado (T-206)
    await cache.definiciones(1)
    assert stub.llamadas == 3
    assert await cache.definiciones(2) == []
