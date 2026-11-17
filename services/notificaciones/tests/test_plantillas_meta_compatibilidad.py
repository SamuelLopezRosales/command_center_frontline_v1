"""Importar plantillas de Meta: reglas de compatibilidad (``servicios/plantillas_meta.evaluar``).

Sin Docker ni red: cada motivo de "no compatible" y los casos que sí se importan.
"""

import pytest
from cc_notificaciones.meta import PlantillaListada, interpretar_plantilla
from cc_notificaciones.servicios.plantillas_meta import MOTIVOS, evaluar

ES = "es_MX"


def plantilla(
    *componentes,
    nombre="bienvenida_colaborador",
    idioma=ES,
    categoria="UTILITY",
    estado="APPROVED",
    formato="POSITIONAL",
    cuerpo="Hola {{1}}, bienvenido a {{2}}.",
    ejemplo=None,
):
    comp = []
    if cuerpo is not None:
        c = {"type": "BODY", "text": cuerpo}
        if ejemplo is not None:
            c["example"] = {"body_text": [ejemplo]}
        comp.append(c)
    comp.extend(componentes)
    return PlantillaListada("1001", nombre, idioma, categoria, estado, tuple(comp), formato)


def ev(p, idioma_envio=ES):
    return evaluar(p, idioma_envio=idioma_envio)


def test_bienvenida_de_solo_texto_es_compatible():
    r = ev(plantilla(ejemplo=["Ana", "Apodaca"]))
    assert r.compatible and r.codigo_incompatible is None and r.motivo_incompatible is None
    assert r.texto == "Hola {{1}}, bienvenido a {{2}}." and r.num_variables == 2
    assert r.ejemplos == ("Ana", "Apodaca") and r.advertencias == ()


def test_sin_variables_y_formato_ausente_son_compatibles():
    r = ev(plantilla(cuerpo="Bienvenido a la empresa.", formato=None))
    assert r.compatible and r.num_variables == 0 and r.ejemplos == ()


def test_una_variable_repetida_cuenta_una_vez():
    r = ev(plantilla(cuerpo="{{1}}, {{1}} y {{2}}"))
    assert r.compatible and r.num_variables == 2


def test_las_categorias_de_utilidad_marketing_y_autenticacion_se_aceptan():
    for categoria in ("UTILITY", "MARKETING", "AUTHENTICATION"):
        assert ev(plantilla(categoria=categoria)).compatible


def test_un_pie_de_pagina_de_texto_se_tolera_y_se_reporta():
    r = ev(plantilla({"type": "FOOTER", "text": "Recursos Humanos"}))
    assert r.compatible
    assert len(r.advertencias) == 1 and "pie de página" in r.advertencias[0]


def test_ejemplos_que_no_calzan_con_las_variables_se_descartan():
    assert ev(plantilla(ejemplo=["solo uno"])).ejemplos == ()
    assert ev(plantilla(ejemplo=["Ana", ""])).ejemplos == ()


@pytest.mark.parametrize(
    ("estado", "texto"),
    [
        ("PENDING", "en revisión"),
        ("REJECTED", "rechazada"),
        ("PAUSED", "pausada"),
        ("DISABLED", "deshabilitada"),
        ("RARO", "raro"),
    ],
)
def test_un_estado_distinto_de_aprobada_no_se_importa(estado, texto):
    r = ev(plantilla(estado=estado))
    assert not r.compatible and r.codigo_incompatible == "ESTADO_NO_APROBADO"
    assert texto in r.motivo_incompatible and "aprobadas" in r.motivo_incompatible
    assert r.texto  # el texto se informa aunque no sea importable


@pytest.mark.parametrize("formato", ["IMAGE", "VIDEO", "DOCUMENT", "TEXT", "LOCATION"])
def test_cualquier_encabezado_no_es_compatible(formato):
    r = ev(plantilla({"type": "HEADER", "format": formato}))
    assert not r.compatible and r.codigo_incompatible == "TIENE_ENCABEZADO"
    assert r.motivo_incompatible == MOTIVOS["TIENE_ENCABEZADO"]


def test_botones_no_son_compatibles():
    r = ev(plantilla({"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Sí"}]}))
    assert not r.compatible and r.codigo_incompatible == "TIENE_BOTONES"


def test_un_carrusel_no_es_compatible():
    r = ev(plantilla({"type": "CAROUSEL", "cards": []}))
    assert not r.compatible and r.codigo_incompatible == "TIENE_CARRUSEL"


def test_un_componente_desconocido_no_es_compatible():
    r = ev(plantilla({"type": "LIMITED_TIME_OFFER"}))
    assert not r.compatible and r.codigo_incompatible == "COMPONENTE_NO_SOPORTADO"


def test_el_encabezado_gana_sobre_el_pie_que_se_tolera():
    r = ev(plantilla({"type": "HEADER", "format": "IMAGE"}, {"type": "FOOTER", "text": "x"}))
    assert r.codigo_incompatible == "TIENE_ENCABEZADO"


def test_un_pie_con_variables_no_es_compatible():
    r = ev(plantilla({"type": "FOOTER", "text": "Folio {{1}}"}))
    assert not r.compatible and r.codigo_incompatible == "FOOTER_NO_SOPORTADO"


@pytest.mark.parametrize(
    ("cuerpo", "formato"),
    [
        ("Hola {{nombre}}, bienvenido.", "NAMED"),
        ("Hola {{nombre}}, bienvenido.", "POSITIONAL"),  # Meta a veces omite el formato
        ("Hola {{1}}.", "NAMED"),
        ("Hola {{ nombre_completo }}.", None),
    ],
)
def test_variables_con_nombre_no_son_compatibles(cuerpo, formato):
    r = ev(plantilla(cuerpo=cuerpo, formato=formato))
    assert not r.compatible and r.codigo_incompatible == "VARIABLES_CON_NOMBRE"


@pytest.mark.parametrize(
    ("cuerpo", "codigo"),
    [
        ("Hola {{2}}.", "VARIABLES_NO_CONSECUTIVAS"),
        ("Hola {{1}} y {{3}}.", "VARIABLES_NO_CONSECUTIVAS"),
        ("Hola {{0}}.", "VARIABLES_INVALIDAS"),
        ("Hola {{1}", "VARIABLES_INVALIDAS"),
        ("Hola {{1}} }}", "VARIABLES_INVALIDAS"),
        ("Hola {{1}} " + " ".join(f"{{{{{i}}}}}" for i in range(2, 23)), "DEMASIADAS_VARIABLES"),
    ],
)
def test_variables_mal_formadas(cuerpo, codigo):
    r = ev(plantilla(cuerpo=cuerpo))
    assert not r.compatible and r.codigo_incompatible == codigo


def test_sin_cuerpo_o_con_cuerpo_vacio_no_es_compatible():
    assert ev(plantilla(cuerpo=None)).codigo_incompatible == "SIN_CUERPO_TEXTO"
    assert ev(plantilla(cuerpo="   ")).codigo_incompatible == "SIN_CUERPO_TEXTO"
    dos = plantilla({"type": "BODY", "text": "otro"})
    assert ev(dos).codigo_incompatible == "SIN_CUERPO_TEXTO"


def test_un_cuerpo_demasiado_largo_no_es_compatible():
    r = ev(plantilla(cuerpo="a" * 1025))
    assert not r.compatible and r.codigo_incompatible == "TEXTO_DEMASIADO_LARGO"


@pytest.mark.parametrize(
    "nombre", ["Bienvenida", "bienvenida-1", "bienvenida colaborador", "ñandú"]
)
def test_un_nombre_fuera_de_formato_no_es_compatible(nombre):
    r = ev(plantilla(nombre=nombre))
    assert not r.compatible and r.codigo_incompatible == "NOMBRE_INVALIDO"


def test_un_nombre_con_salto_de_linea_al_final_no_pasa():
    # ``$`` en una expresión de Python aceptaría "abc\n"; la regla usa coincidencia completa.
    assert ev(plantilla(nombre="bienvenida\n")).codigo_incompatible == "NOMBRE_INVALIDO"


def test_una_categoria_desconocida_no_es_compatible():
    r = ev(plantilla(categoria="SERVICE"))
    assert not r.compatible and r.codigo_incompatible == "CATEGORIA_NO_SOPORTADA"


def test_un_idioma_distinto_del_de_envio_no_es_compatible():
    r = ev(plantilla(idioma="en_US"))
    assert not r.compatible and r.codigo_incompatible == "IDIOMA_NO_ENVIABLE"
    assert "en_US" in r.motivo_incompatible and ES in r.motivo_incompatible
    # Con otro idioma de envío configurado, ese sí es el enviable.
    assert ev(plantilla(idioma="en_US"), idioma_envio="en_US").compatible
    assert not ev(plantilla(idioma=ES), idioma_envio="en_US").compatible


def test_el_estado_se_evalua_antes_que_la_estructura():
    r = ev(plantilla({"type": "BUTTONS", "buttons": []}, estado="PAUSED"))
    assert r.codigo_incompatible == "ESTADO_NO_APROBADO"


def test_todo_codigo_de_motivo_tiene_texto_en_espanol():
    for texto in MOTIVOS.values():
        assert texto and texto[0].isupper() and texto.endswith(".")


# ------------------------------------------------------------------ lectura de la respuesta de Meta


def test_interpretar_descarta_entradas_sin_id_nombre_o_idioma():
    base = {
        "id": "1",
        "name": "a",
        "language": "es_MX",
        "category": "utility",
        "status": "approved",
    }
    p = interpretar_plantilla(base)
    assert p and p.categoria == "UTILITY" and p.estado == "APPROVED" and p.componentes == ()
    assert interpretar_plantilla({**base, "id": None}) is None
    assert interpretar_plantilla({**base, "name": ""}) is None
    assert interpretar_plantilla({**base, "language": None}) is None
    assert interpretar_plantilla("texto") is None
    assert interpretar_plantilla({**base, "id": 77}).id == "77"
    raro = interpretar_plantilla({**base, "components": "no es lista"})
    assert raro and raro.componentes == ()
