"""Variables de plantillas de Meta: formato posicional o con nombre (``cc_common.plantillas_meta``)."""

from __future__ import annotations

import pytest
from cc_common import plantillas_meta as pm


def test_sin_variables_es_posicional_con_cero():
    v = pm.analizar("Hola, bienvenido.")
    assert v.formato == pm.POSICIONAL and v.nombres == () and v.cantidad == 0 and not v.nombrado


def test_posicional_consecutiva_con_repetidas():
    v = pm.analizar("Hola {{1}}, {{2}} y otra vez {{1}}.")
    assert v.formato == pm.POSICIONAL and v.nombres == ("1", "2") and v.cantidad == 2


def test_posicional_ordena_por_numero_aunque_aparezcan_desordenadas():
    assert pm.analizar("{{2}} y {{1}}").nombres == ("1", "2")


def test_nombrado_en_orden_de_aparicion_y_un_nombre_repetido_cuenta_una():
    v = pm.analizar("Hola {{guest_name}}, tu salida es {{checkout_time}}. Adiós {{guest_name}}.")
    assert v.formato == pm.NOMBRADO and v.nombrado
    assert v.nombres == ("guest_name", "checkout_time") and v.cantidad == 2


@pytest.mark.parametrize(
    ("texto", "codigo"),
    [
        ("Hola {{1}} y {{nombre}}", "VARIABLES_MEZCLADAS"),
        ("Hola {{nombre}} y {{2}}", "VARIABLES_MEZCLADAS"),
        ("Hola {{2}}", "VARIABLES_NO_CONSECUTIVAS"),
        ("Hola {{1}} y {{3}}", "VARIABLES_NO_CONSECUTIVAS"),
        ("Hola {{0}}", "VARIABLE_INVALIDA"),
        ("Hola {{100}}", "VARIABLE_INVALIDA"),
        ("Hola {{01}}", "VARIABLE_INVALIDA"),
        ("Hola {{Nombre}}", "NOMBRE_VARIABLE_INVALIDO"),
        ("Hola {{guestName}}", "NOMBRE_VARIABLE_INVALIDO"),
        ("Hola {{_guest}}", "NOMBRE_VARIABLE_INVALIDO"),
        ("Hola {{" + "a" * 51 + "}}", "NOMBRE_VARIABLE_INVALIDO"),
        ("Hola {{ nombre }}", "VARIABLE_INVALIDA"),
        ("Hola {{}}", "VARIABLE_INVALIDA"),
        ("Hola {{a-b}}", "VARIABLE_INVALIDA"),
        ("Hola {{1}", "VARIABLE_INVALIDA"),
        ("Hola {{1}} }}", "VARIABLE_INVALIDA"),
    ],
)
def test_textos_invalidos_con_su_codigo(texto, codigo):
    with pytest.raises(pm.ErrorVariables) as e:
        pm.analizar(texto)
    assert e.value.codigo == codigo and e.value.mensaje


def test_demasiadas_variables_en_los_dos_formatos():
    posicional = " ".join(f"{{{{{i}}}}}" for i in range(1, 22))
    nombrado = " ".join(f"{{{{v{i}}}}}" for i in range(1, 22))
    for texto in (posicional, nombrado):
        with pytest.raises(pm.ErrorVariables) as e:
            pm.analizar(texto)
        assert e.value.codigo == "DEMASIADAS_VARIABLES"
    assert pm.analizar(nombrado, maximo=21).cantidad == 21


def test_nombres_para_envio_solo_si_es_nombrada_y_nunca_lanza():
    assert pm.nombres_para_envio("Hola {{guest_name}} {{otra}}") == ["guest_name", "otra"]
    assert pm.nombres_para_envio("Hola {{1}}") is None
    assert pm.nombres_para_envio("Sin variables") is None
    assert pm.nombres_para_envio("Hola {{1}} {{x}}") is None  # mezcla: no se puede interpretar
    assert pm.nombres_para_envio("{{") is None


def test_sustituir_por_nombre_y_posicion_sin_reinterpretar_los_valores():
    assert pm.sustituir("Hola {{guest_name}}", {"guest_name": "Juan"}) == "Hola Juan"
    assert pm.sustituir("{{1}}-{{2}}", {"1": "a", "2": "b"}) == "a-b"
    assert pm.sustituir("Hola {{x}}", {}) == "Hola {{x}}"  # sin valor: se deja el marcador
    # un valor con forma de marcador no se vuelve a sustituir
    assert pm.sustituir("{{a}} {{b}}", {"a": "{{b}}", "b": "ok"}) == "{{b}} ok"


def test_valores_por_nombre_empareja_en_orden_de_aparicion():
    texto = "{{lugar}} {{guest_name}} {{lugar}}"
    assert pm.valores_por_nombre(texto, ["Recepción", "Juan"]) == {
        "lugar": "Recepción",
        "guest_name": "Juan",
    }
    assert pm.valores_por_nombre("{{1}} {{2}}", ["a", "b"]) == {"1": "a", "2": "b"}
    assert pm.valores_por_nombre("{{a}} {{b}}", ["x"], nombres=["a", "b"]) == {"a": "x"}


def test_el_modulo_solo_usa_la_biblioteca_estandar():
    """Se empaqueta en las Lambdas sin dependencias: no debe importar nada de terceros."""
    import ast
    from pathlib import Path

    fuente = Path(pm.__file__).read_text(encoding="utf-8")
    modulos = {
        n.module.split(".")[0]
        if isinstance(n, ast.ImportFrom) and n.module
        else a.name.split(".")[0]
        for n in ast.walk(ast.parse(fuente))
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert modulos <= {"__future__", "re", "collections", "dataclasses"}
