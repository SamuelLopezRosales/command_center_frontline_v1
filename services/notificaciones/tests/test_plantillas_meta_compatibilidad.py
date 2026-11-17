"""Importar plantillas de Meta: reglas de compatibilidad (``servicios/plantillas_meta.evaluar``).

Sin Docker ni red: cada motivo de "no compatible" y los casos que sí se importan (variables
numeradas y con nombre, cualquier idioma, botones estáticos y encabezado de texto fijo).
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
    ejemplo_nombrado=None,
):
    comp = []
    if cuerpo is not None:
        c = {"type": "BODY", "text": cuerpo}
        if ejemplo is not None:
            c["example"] = {"body_text": [ejemplo]}
        if ejemplo_nombrado is not None:
            c["example"] = {
                "body_text_named_params": [
                    {"param_name": n, "example": e} for n, e in ejemplo_nombrado.items()
                ]
            }
        comp.append(c)
    comp.extend(componentes)
    return PlantillaListada("1001", nombre, idioma, categoria, estado, tuple(comp), formato)


def botones(*tipos, **extra):
    return {"type": "BUTTONS", "buttons": [{"type": t, "text": f"b-{t}", **extra} for t in tipos]}


ev = evaluar


def codigos(r):
    return [c for c, _ in r.motivos]


def test_bienvenida_de_solo_texto_es_compatible():
    r = ev(plantilla(ejemplo=["Ana", "Apodaca"]))
    assert r.compatible and r.codigo_incompatible is None and r.motivo_incompatible is None
    assert r.motivos == () and r.texto == "Hola {{1}}, bienvenido a {{2}}."
    assert r.num_variables == 2 and r.formato == "POSICIONAL" and r.variables == ("1", "2")
    assert r.ejemplos == ("Ana", "Apodaca") and r.advertencias == ()
    assert r.botones == () and r.encabezado is None


def test_sin_variables_y_formato_ausente_son_compatibles():
    r = ev(plantilla(cuerpo="Bienvenido a la empresa.", formato=None))
    assert r.compatible and r.num_variables == 0 and r.ejemplos == () and r.variables == ()


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


# ------------------------------------------------------------------ variables con nombre


def test_una_plantilla_nombrada_es_compatible_con_sus_variables_y_ejemplos():
    r = ev(
        plantilla(
            cuerpo="Hola {{guest_name}}, tu salida es a las {{checkout_time}}.",
            formato="NAMED",
            ejemplo_nombrado={"checkout_time": "12:00", "guest_name": "Juan"},  # otro orden
        )
    )
    assert r.compatible and r.num_variables == 2 and r.formato == "NOMBRADO"
    assert r.variables == ("guest_name", "checkout_time")
    assert r.ejemplos == ("Juan", "12:00")  # en el orden de aparición, no en el de Meta


def test_un_nombre_repetido_cuenta_una_variable():
    r = ev(plantilla(cuerpo="{{guest_name}}, hola {{guest_name}}.", formato="NAMED"))
    assert r.compatible and r.num_variables == 1 and r.variables == ("guest_name",)


def test_los_ejemplos_nombrados_incompletos_se_descartan():
    r = ev(plantilla(cuerpo="Hola {{a}} y {{b}}.", formato="NAMED", ejemplo_nombrado={"a": "x"}))
    assert r.compatible and r.ejemplos == ()


def test_formato_ausente_con_nombres_se_infiere_del_texto():
    r = ev(plantilla(cuerpo="Hola {{nombre}}, bienvenido.", formato=None))
    assert r.compatible and r.formato == "NOMBRADO" and r.variables == ("nombre",)


@pytest.mark.parametrize(
    ("cuerpo", "formato"),
    [
        ("Hola {{nombre}}, bienvenido.", "POSITIONAL"),  # Meta declara otro formato que el texto
        ("Hola {{1}}.", "NAMED"),
    ],
)
def test_formato_declarado_que_no_coincide_con_el_texto_no_es_compatible(cuerpo, formato):
    r = ev(plantilla(cuerpo=cuerpo, formato=formato))
    assert not r.compatible and r.codigo_incompatible == "VARIABLES_FORMATO_INCONSISTENTE"


@pytest.mark.parametrize(
    ("cuerpo", "codigo"),
    [
        ("Hola {{1}} y {{nombre}}.", "VARIABLES_MEZCLADAS"),
        ("Hola {{Nombre}}.", "NOMBRE_VARIABLE_INVALIDO"),
        ("Hola {{guestName}}.", "NOMBRE_VARIABLE_INVALIDO"),
        ("Hola {{ nombre_completo }}.", "VARIABLES_INVALIDAS"),
        ("Hola {{2}}.", "VARIABLES_NO_CONSECUTIVAS"),
        ("Hola {{1}} y {{3}}.", "VARIABLES_NO_CONSECUTIVAS"),
        ("Hola {{0}}.", "VARIABLES_INVALIDAS"),
        ("Hola {{1}", "VARIABLES_INVALIDAS"),
        ("Hola {{1}} }}", "VARIABLES_INVALIDAS"),
        ("Hola {{1}} " + " ".join(f"{{{{{i}}}}}" for i in range(2, 23)), "DEMASIADAS_VARIABLES"),
        (" ".join(f"{{{{v{i}}}}}" for i in range(1, 22)), "DEMASIADAS_VARIABLES"),
    ],
)
def test_variables_mal_formadas_o_mezcladas(cuerpo, codigo):
    r = ev(plantilla(cuerpo=cuerpo, formato=None))
    assert not r.compatible and r.codigo_incompatible == codigo


# ------------------------------------------------------------------ idioma


@pytest.mark.parametrize("idioma", ["es_MX", "en", "en_US", "pt_BR", "fil", "zh_CN"])
def test_cualquier_idioma_con_formato_de_meta_es_compatible(idioma):
    r = ev(plantilla(idioma=idioma))
    assert r.compatible, idioma


@pytest.mark.parametrize("idioma", ["", "ES", "es-MX", "es_mx", "español", "e", "en_USA"])
def test_un_idioma_fuera_de_formato_no_es_compatible(idioma):
    r = ev(plantilla(idioma=idioma))
    assert not r.compatible and r.codigo_incompatible == "IDIOMA_INVALIDO"


# ------------------------------------------------------------------ encabezados


def test_un_encabezado_de_texto_fijo_es_compatible_y_se_informa():
    r = ev(plantilla({"type": "HEADER", "format": "TEXT", "text": "Aviso importante"}))
    assert r.compatible
    assert r.encabezado == {"tipo": "TEXTO", "formato": "TEXT", "texto": "Aviso importante"}
    assert any("encabezado de texto fijo" in a for a in r.advertencias)


def test_un_encabezado_de_texto_con_variable_no_es_compatible():
    r = ev(
        plantilla({"type": "HEADER", "format": "TEXT", "text": "Hola {{1}}"}, cuerpo="Texto {{1}}")
    )
    assert not r.compatible and r.codigo_incompatible == "ENCABEZADO_TEXTO_CON_VARIABLE"


@pytest.mark.parametrize(
    ("formato", "codigo", "tipo", "frase"),
    [
        ("IMAGE", "ENCABEZADO_IMAGEN", "MEDIA", "Encabezado de imagen"),
        ("VIDEO", "ENCABEZADO_VIDEO", "MEDIA", "Encabezado de video"),
        ("DOCUMENT", "ENCABEZADO_DOCUMENTO", "MEDIA", "Encabezado de documento"),
        ("LOCATION", "ENCABEZADO_UBICACION", "UBICACION", "Encabezado de ubicación"),
    ],
)
def test_un_encabezado_de_medios_no_es_compatible_y_dice_cual_es(formato, codigo, tipo, frase):
    r = ev(plantilla({"type": "HEADER", "format": formato}))
    assert not r.compatible and r.codigo_incompatible == codigo
    assert r.motivo_incompatible == MOTIVOS[codigo] and frase in r.motivo_incompatible
    assert r.encabezado == {"tipo": tipo, "formato": formato, "texto": None}


def test_un_encabezado_de_otro_tipo_no_es_compatible():
    r = ev(plantilla({"type": "HEADER", "format": "RARO"}))
    assert codigos(r) == ["ENCABEZADO_NO_SOPORTADO"]


# ------------------------------------------------------------------ botones


def test_botones_estaticos_son_compatibles_y_se_informan():
    r = ev(
        plantilla(
            {
                "type": "BUTTONS",
                "buttons": [
                    {"type": "QUICK_REPLY", "text": "Sí"},
                    {"type": "QUICK_REPLY", "text": "No"},
                    {"type": "PHONE_NUMBER", "text": "Llamar", "phone_number": "+5218100000000"},
                    {"type": "URL", "text": "Ver", "url": "https://empresa.mx/guia"},
                ],
            }
        )
    )
    assert r.compatible
    assert r.botones == (
        {"tipo": "QUICK_REPLY", "texto": "Sí"},
        {"tipo": "QUICK_REPLY", "texto": "No"},
        {"tipo": "PHONE_NUMBER", "texto": "Llamar"},
        {"tipo": "URL", "texto": "Ver"},
    )
    assert any("botones fijos" in a for a in r.advertencias)
    # Las respuestas rápidas llegan al webhook de la cuenta en Meta (puede ser de otro proyecto).
    assert any("webhook" in a for a in r.advertencias)


def test_solo_las_respuestas_rapidas_avisan_del_webhook():
    r = ev(
        plantilla(
            {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "V", "url": "https://x.mx"}]}
        )
    )
    assert r.compatible and not any("webhook" in a for a in r.advertencias)


def test_un_boton_url_con_variable_no_es_compatible():
    r = ev(
        plantilla(
            {
                "type": "BUTTONS",
                "buttons": [{"type": "URL", "text": "V", "url": "https://x.mx/{{1}}"}],
            }
        )
    )
    assert not r.compatible and r.codigo_incompatible == "BOTON_URL_CON_VARIABLE"


@pytest.mark.parametrize(
    ("tipo", "codigo"),
    [
        ("COPY_CODE", "BOTON_COPIAR_CODIGO"),
        ("OTP", "BOTON_OTP"),
        ("FLOW", "BOTON_FLOW"),
        ("CATALOG", "BOTON_CATALOGO"),
        ("MPM", "BOTON_MPM"),
        ("SPM", "BOTON_SPM"),
        ("VOICE_CALL", "BOTON_NO_SOPORTADO"),
    ],
)
def test_botones_con_parametros_o_desconocidos_no_son_compatibles(tipo, codigo):
    r = ev(plantilla(botones(tipo)))
    assert not r.compatible and codigos(r) == [codigo]
    assert r.motivo_incompatible == MOTIVOS[codigo]


def test_una_plantilla_de_autenticacion_con_otp_no_es_compatible():
    r = ev(plantilla(botones("OTP"), categoria="AUTHENTICATION", cuerpo="{{1}} es tu código."))
    assert not r.compatible and codigos(r) == ["BOTON_OTP"]


# ------------------------------------------------------------------ otros componentes


def test_un_carrusel_no_es_compatible():
    r = ev(plantilla({"type": "CAROUSEL", "cards": []}))
    assert not r.compatible and r.codigo_incompatible == "TIENE_CARRUSEL"


def test_un_componente_desconocido_no_es_compatible():
    r = ev(plantilla({"type": "LIMITED_TIME_OFFER"}))
    assert not r.compatible and r.codigo_incompatible == "COMPONENTE_NO_SOPORTADO"


def test_un_pie_con_variables_no_es_compatible():
    r = ev(plantilla({"type": "FOOTER", "text": "Folio {{1}}"}))
    assert not r.compatible and r.codigo_incompatible == "FOOTER_NO_SOPORTADO"


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


# ------------------------------------------------------------------ todos los motivos


def test_se_evaluan_todos_los_motivos_y_el_primero_es_el_de_siempre():
    r = ev(
        plantilla(
            {"type": "HEADER", "format": "IMAGE"},
            botones("OTP", "FLOW"),
            estado="PAUSED",
            idioma="en",
            cuerpo="Hello {{1}} and {{name}}",
            formato=None,
        )
    )
    assert not r.compatible
    assert codigos(r) == [
        "ESTADO_NO_APROBADO",
        "ENCABEZADO_IMAGEN",
        "BOTON_OTP",
        "BOTON_FLOW",
        "VARIABLES_MEZCLADAS",
    ]
    assert r.codigo_incompatible == "ESTADO_NO_APROBADO"
    assert r.motivo_incompatible == r.motivos[0][1]


def test_un_motivo_repetido_se_informa_una_sola_vez():
    r = ev(plantilla(botones("OTP", "OTP", "OTP")))
    assert codigos(r) == ["BOTON_OTP"]


def test_una_plantilla_incompatible_informa_igual_su_formato_botones_y_encabezado():
    r = ev(
        plantilla(
            {"type": "HEADER", "format": "IMAGE"},
            botones("QUICK_REPLY"),
            cuerpo="Hola {{guest_name}}",
            formato="NAMED",
        )
    )
    assert not r.compatible
    assert r.formato == "NOMBRADO" and r.variables == ("guest_name",) and r.num_variables == 1
    assert r.botones == ({"tipo": "QUICK_REPLY", "texto": "b-QUICK_REPLY"},)
    assert r.encabezado is not None and r.encabezado["formato"] == "IMAGE"


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
