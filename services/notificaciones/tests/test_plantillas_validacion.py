"""T-108: validación del nombre, las variables y los ejemplos de una plantilla. Sin base."""

import pytest
from cc_common.errores import ErrorValidacion
from cc_notificaciones.clientes import DefinicionCampo
from cc_notificaciones.servicios import plantillas as p
from cc_notificaciones.servicios import variables as v


def _ok(**kw):
    datos = {
        "nombre": "aviso_nomina_v1",
        "categoria": "UTILITY",
        "idioma": "es_MX",
        "texto": "Hola {{1}}, tu nómina cierra el {{2}}.",
        "ejemplos": ["Ana", "13 de noviembre"],
    }
    datos.update(kw)
    return p.validar(**datos)


def _codigos(**kw):
    with pytest.raises(ErrorValidacion) as e:
        _ok(**kw)
    return {(x.campo, x.codigo) for x in e.value.errores}


def test_plantilla_valida_cuenta_sus_variables():
    assert _ok() == 2
    assert _ok(texto="Sin variables.", ejemplos=[]) == 0
    assert _ok(texto="{{1}} y otra vez {{1}}.", ejemplos=["x"]) == 1  # una variable repetida


@pytest.mark.parametrize("nombre", ["Aviso", "aviso nomina", "aviso-nomina", "avisó", "", "a.b"])
def test_nombre_solo_minusculas_numeros_y_guion_bajo(nombre):
    assert ("nombre", "NOMBRE_INVALIDO") in _codigos(nombre=nombre)


def test_nombre_hasta_512_caracteres():
    assert _ok(nombre="a" * 512) == 2
    assert ("nombre", "NOMBRE_INVALIDO") in _codigos(nombre="a" * 513)


def test_variables_deben_ser_consecutivas_desde_uno():
    assert ("texto_con_variables", "VARIABLES_NO_CONSECUTIVAS") in _codigos(
        texto="Hola {{2}} y {{3}}", ejemplos=["a", "b"]
    )
    assert ("texto_con_variables", "VARIABLES_NO_CONSECUTIVAS") in _codigos(
        texto="Hola {{1}} y {{3}}", ejemplos=["a", "b"]
    )


@pytest.mark.parametrize(
    "texto", ["Hola {{0}}", "Hola {{ 1 }}", "Hola {{1}", "Hola {1}}", "Hola {{a b}}", "Hola {{}}"]
)
def test_variables_mal_formadas(texto):
    assert ("texto_con_variables", "VARIABLE_INVALIDA") in _codigos(texto=texto, ejemplos=["x"])


def test_variables_con_nombre_validas_en_orden_de_aparicion():
    assert _ok(texto="Hola {{guest_name}}, sales a las {{hora}}.", ejemplos=["Ana", "12:00"]) == 2
    assert _ok(texto="{{guest_name}} y otra vez {{guest_name}}.", ejemplos=["x"]) == 1


@pytest.mark.parametrize(
    ("texto", "codigo"),
    [
        ("Hola {{1}} y {{nombre}}", "VARIABLES_MEZCLADAS"),
        ("Hola {{Nombre}}", "NOMBRE_VARIABLE_INVALIDO"),
        ("Hola {{_nombre}}", "NOMBRE_VARIABLE_INVALIDO"),
        ("Hola {{ñandú}}", "VARIABLE_INVALIDA"),
    ],
)
def test_variables_con_nombre_invalidas_o_mezcladas(texto, codigo):
    assert ("texto_con_variables", codigo) in _codigos(texto=texto, ejemplos=["x", "y"])


def test_un_ejemplo_por_variable():
    assert ("ejemplos", "EJEMPLOS_NO_COINCIDEN") in _codigos(ejemplos=["solo uno"])
    assert ("ejemplos", "EJEMPLOS_NO_COINCIDEN") in _codigos(texto="Sin variables", ejemplos=["x"])
    assert ("ejemplos", "EJEMPLO_INVALIDO") in _codigos(ejemplos=["Ana", "  "])
    assert ("ejemplos", "EJEMPLO_INVALIDO") in _codigos(ejemplos=["Ana", "a\nb"])


def test_texto_e_idioma():
    assert ("texto_con_variables", "TEXTO_INVALIDO") in _codigos(texto="  ", ejemplos=[])
    assert ("texto_con_variables", "TEXTO_INVALIDO") in _codigos(texto="x" * 1025, ejemplos=[])
    assert ("idioma", "IDIOMA_INVALIDO") in _codigos(idioma="español")


def test_el_error_no_repite_el_texto_recibido():
    with pytest.raises(ErrorValidacion) as e:
        _ok(texto="Dato secreto {{X}}", ejemplos=["a"])
    assert "secreto" not in repr(e.value.errores)


# ------------------------------------------------------------------ variables de una notificación

TEXTO = "Hola {{1}}, te esperamos el {{2}}."
FIJO = {"origen": "FIJO", "valor": "x"}


def _vcodigos(vars_, defs=None):
    with pytest.raises(ErrorValidacion) as e:
        v.validar(vars_, TEXTO, defs)
    return {(x.campo, x.codigo) for x in e.value.errores}


def test_variables_validas():
    v.validar(
        {
            "1": {"origen": "COLABORADOR", "campo": "nombre_completo"},
            "2": {"origen": "FIJO", "valor": "13 de noviembre"},
        },
        TEXTO,
    )


def test_variables_faltantes_sobrantes_y_estructura():
    assert _vcodigos({"1": FIJO}) == {("variables.2", "VARIABLE_FALTANTE")}
    assert ("variables.3", "VARIABLE_NO_EXISTE") in _vcodigos({"1": FIJO, "2": FIJO, "3": FIJO})
    assert ("variables", "ESTRUCTURA_INVALIDA") in _vcodigos([])
    assert ("variables.1", "ESTRUCTURA_INVALIDA") in _vcodigos({"1": {"origen": "X"}, "2": FIJO})
    assert ("variables.1.valor", "VALOR_INVALIDO") in _vcodigos(
        {"1": {"origen": "FIJO", "valor": "a\nb"}, "2": FIJO}
    )
    assert ("variables.1.valor", "VALOR_INVALIDO") in _vcodigos(
        {"1": {"origen": "FIJO", "valor": "a     b"}, "2": FIJO}
    )


def test_campos_dinamicos_solo_activos_y_no_sensibles():
    defs = [
        DefinicionCampo(1, "CAMP-0001", "NSS", "TEXTO", es_sensible=True),
        DefinicionCampo(2, "CAMP-0002", "Área", "TEXTO"),
        DefinicionCampo(3, "CAMP-0003", "Viejo", "TEXTO", activo=False),
    ]

    def con(campo):
        return {"1": {"origen": "COLABORADOR", "campo": campo}, "2": FIJO}

    v.validar(con("CAMP-0002"), TEXTO, defs)
    assert ("variables.1.campo", "CAMPO_SENSIBLE_NO_PERMITIDO") in _vcodigos(con("CAMP-0001"), defs)
    assert ("variables.1.campo", "CAMPO_DESCONOCIDO") in _vcodigos(con("CAMP-0003"), defs)
    assert ("variables.1.campo", "CAMPO_DESCONOCIDO") in _vcodigos(con("CAMP-9999"), defs)
    assert ("variables.1.campo", "CAMPO_DESCONOCIDO") in _vcodigos(con("CAMP-0002"))  # sin catálogo


def test_vista_previa_sustituye_fijas_y_deja_las_de_colaborador():
    vars_ = {
        "1": {"origen": "COLABORADOR", "campo": "nombre_completo"},
        "2": {"origen": "FIJO", "valor": "13 nov"},
    }
    assert v.vista_previa(TEXTO, vars_) == "Hola {{nombre_completo}}, te esperamos el 13 nov."
