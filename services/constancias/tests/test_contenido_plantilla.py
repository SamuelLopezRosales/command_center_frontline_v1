"""T-207 (T-077): esquema JSON del contenido de las plantillas (sin base de datos)."""

import json

import pytest
from cc_common.errores import ErrorValidacion
from cc_constancias import contenido as c

from scripts.exportar_esquemas import main as exportar_esquemas

VALIDO = {
    "esquema": 1,
    "pagina": {"tamano": "CARTA", "margenes_cm": {"sup": 2.5, "inf": 2.5, "izq": 2.5, "der": 2.5}},
    "bloques": [
        {"tipo": "logotipo", "alineacion": "izquierda"},
        {
            "tipo": "parrafo",
            "alineacion": "derecha",
            "contenido": [{"var": "lugar"}, {"texto": ", "}, {"var": "fecha_emision"}],
        },
        {
            "tipo": "parrafo",
            "contenido": [
                {"texto": "hace constar que "},
                {"var": "nombre_completo", "negrita": True},
                {"salto": True},
                {
                    "texto": "texto con todo",
                    "negrita": True,
                    "cursiva": True,
                    "subrayado": True,
                    "tamano_pt": 48,
                    "color": "#1f3A5F",
                },
            ],
        },
        {"tipo": "parrafo", "contenido": []},  # párrafo vacío = espacio
    ],
}


def _con_nodo(nodo):
    return {"esquema": 1, "bloques": [{"tipo": "parrafo", "contenido": [nodo]}]}


def _codigos(contenido) -> list[tuple[str, str]]:
    with pytest.raises(ErrorValidacion) as exc:
        c.leer(contenido)
    assert exc.value.http == 422 and exc.value.codigo == "CONTENIDO_INVALIDO"
    return [(e.campo, e.codigo) for e in exc.value.errores]


def test_un_contenido_valido_se_lee_con_sus_valores_por_defecto():
    m = c.leer(json.dumps(VALIDO))
    assert m.pagina.tamano == "CARTA" and len(m.bloques) == 4
    minimo = c.leer({"esquema": 1})
    assert minimo.bloques == [] and minimo.pagina.margenes_cm.sup == 2.5
    assert c.leer(json.dumps(VALIDO).encode()) == m  # también acepta bytes


def test_variables_usadas_sin_repetir_y_en_orden():
    doc = _con_nodo({"var": "area"})
    doc["bloques"].append(
        {
            "tipo": "parrafo",
            "contenido": [{"var": "nss"}, {"var": "area"}, {"var": "organizacion.rfc"}],
        }
    )
    assert c.variables_usadas(c.leer(doc)) == ["area", "nss", "organizacion.rfc"]
    assert c.variables_usadas(c.leer({"esquema": 1})) == []
    assert c.usa_logotipo(c.leer(VALIDO)) and not c.usa_logotipo(c.leer(doc))


@pytest.mark.parametrize(
    ("documento", "esperado"),
    [
        # HTML libre: un tipo de bloque, una clave, una etiqueta en el texto
        (
            {"esquema": 1, "bloques": [{"tipo": "html", "contenido": "<b>x</b>"}]},
            ("bloques.0", "HTML_NO_PERMITIDO"),
        ),
        (
            _con_nodo({"texto": "x", "html": "<b>x</b>"}),
            ("bloques.0.contenido.0.html", "HTML_NO_PERMITIDO"),
        ),
        (
            _con_nodo({"texto": "x", "style": "color:red"}),
            ("bloques.0.contenido.0.style", "HTML_NO_PERMITIDO"),
        ),
        (
            _con_nodo({"texto": "<script>alert(1)</script>"}),
            ("bloques.0.contenido.0.texto", "HTML_NO_PERMITIDO"),
        ),
        (
            _con_nodo({"texto": "uno </p> dos"}),
            ("bloques.0.contenido.0.texto", "HTML_NO_PERMITIDO"),
        ),
        (_con_nodo({"texto": "<!-- x -->"}), ("bloques.0.contenido.0.texto", "HTML_NO_PERMITIDO")),
        # color
        (
            _con_nodo({"texto": "x", "color": "rojo"}),
            ("bloques.0.contenido.0.color", "COLOR_INVALIDO"),
        ),
        (
            _con_nodo({"texto": "x", "color": "#12345"}),
            ("bloques.0.contenido.0.color", "COLOR_INVALIDO"),
        ),
        (
            _con_nodo({"texto": "x", "color": "#GGGGGG"}),
            ("bloques.0.contenido.0.color", "COLOR_INVALIDO"),
        ),
        (
            _con_nodo({"texto": "x", "color": "red; background:url(x)"}),
            ("bloques.0.contenido.0.color", "COLOR_INVALIDO"),
        ),
        # tamaño fuera de 8 a 48 pt
        (
            _con_nodo({"texto": "x", "tamano_pt": 7}),
            ("bloques.0.contenido.0.tamano_pt", "TAMANO_FUERA_DE_RANGO"),
        ),
        (
            _con_nodo({"texto": "x", "tamano_pt": 49}),
            ("bloques.0.contenido.0.tamano_pt", "TAMANO_FUERA_DE_RANGO"),
        ),
        (
            _con_nodo({"var": "a", "tamano_pt": 0}),
            ("bloques.0.contenido.0.tamano_pt", "TAMANO_FUERA_DE_RANGO"),
        ),
        # variable, nodo y bloque
        (_con_nodo({"var": "Nombre Completo"}), ("bloques.0.contenido.0.var", "VARIABLE_INVALIDA")),
        (_con_nodo({"var": "{{x}}"}), ("bloques.0.contenido.0.var", "VARIABLE_INVALIDA")),
        (_con_nodo({"otra": 1}), ("bloques.0.contenido.0", "ESTRUCTURA_INVALIDA")),
        (_con_nodo("texto suelto"), ("bloques.0.contenido.0", "ESTRUCTURA_INVALIDA")),
        (_con_nodo({"texto": ""}), ("bloques.0.contenido.0.texto", "DEMASIADO_CORTO")),
        (_con_nodo({"texto": "x" * 5001}), ("bloques.0.contenido.0.texto", "DEMASIADO_LARGO")),
        (_con_nodo({"salto": False}), ("bloques.0.contenido.0.salto", "VALOR_NO_PERMITIDO")),
        (
            {"esquema": 1, "bloques": [{"tipo": "imagen"}]},
            ("bloques.0", "TIPO_NO_PERMITIDO"),
        ),
        (
            {"esquema": 1, "bloques": [{"tipo": "parrafo", "alineacion": "arriba"}]},
            ("bloques.0.alineacion", "VALOR_NO_PERMITIDO"),
        ),
        # página y esquema
        (
            {"esquema": 1, "pagina": {"margenes_cm": {"sup": 9}}},
            ("pagina.margenes_cm.sup", "MARGEN_FUERA_DE_RANGO"),
        ),
        ({"esquema": 1, "pagina": {"tamano": "OFICIO"}}, ("pagina.tamano", "VALOR_NO_PERMITIDO")),
        ({"esquema": 2}, ("esquema", "VALOR_NO_PERMITIDO")),
        ({}, ("esquema", "REQUERIDO")),
        ({"esquema": 1, "extra": 1}, ("extra", "CAMPO_NO_PERMITIDO")),
    ],
)
def test_rechaza_lo_que_el_esquema_no_permite(documento, esperado):
    assert esperado in _codigos(documento)


def test_limites_de_cantidad():
    assert ("bloques", "DEMASIADO_LARGO") in _codigos(
        {"esquema": 1, "bloques": [{"tipo": "parrafo"}] * (c.MAX_BLOQUES + 1)}
    )
    assert c.leer({"esquema": 1, "bloques": [{"tipo": "parrafo"}] * c.MAX_BLOQUES})
    assert ("bloques.0.contenido", "DEMASIADO_LARGO") in _codigos(
        _con_nodo({"salto": True})
        | {"bloques": [{"tipo": "parrafo", "contenido": [{"salto": True}] * (c.MAX_NODOS + 1)}]}
    )


def test_json_mal_formado_o_de_otro_tipo():
    assert _codigos(b"{no es json") == [("contenido", "ESTRUCTURA_INVALIDA")]
    assert _codigos(b"[1, 2]") == [("contenido", "ESTRUCTURA_INVALIDA")]
    assert _codigos(b"") == [("contenido", "ESTRUCTURA_INVALIDA")]


def test_los_errores_no_repiten_el_valor_recibido():
    secreto = "TOKEN-SECRETO-12345"
    with pytest.raises(ErrorValidacion) as exc:
        c.leer(_con_nodo({"texto": f"<b>{secreto}</b>", "color": secreto, "tamano_pt": 999}))
    texto = repr(exc.value.errores) + exc.value.mensaje_publico
    assert secreto not in texto and "999" not in texto


def test_un_documento_con_muchos_errores_los_lista_todos_pero_acotados():
    documento = {
        "esquema": 1,
        "bloques": [{"tipo": "parrafo", "contenido": [{"texto": "x", "color": "m"}] * 100}],
    }
    errores = _codigos(documento)
    assert 1 < len(errores) <= 50


def test_la_forma_canonica_es_estable_y_la_misma_con_cualquier_orden_de_claves():
    a = c.serializar(c.leer(VALIDO))
    invertido = json.loads(json.dumps(VALIDO))
    invertido = dict(reversed(list(invertido.items())))
    assert c.serializar(c.leer(json.dumps(invertido))) == a
    assert c.hash_de(a) == c.hash_de(c.serializar(c.leer(a)))  # idempotente
    assert len(c.hash_de(a)) == 64
    assert b" " not in a.replace(b"hace constar que ", b"").replace(b"texto con todo", b"").replace(
        b", ", b""
    )
    cambiado = json.loads(json.dumps(VALIDO))
    cambiado["bloques"][2]["contenido"][1]["negrita"] = False
    assert c.hash_de(c.serializar(c.leer(cambiado))) != c.hash_de(a)


def test_valores_por_defecto_se_completan_en_la_forma_canonica():
    canonico = json.loads(c.serializar(c.leer({"esquema": 1, "bloques": [{"tipo": "logotipo"}]})))
    assert canonico["bloques"][0] == {
        "tipo": "logotipo",
        "alineacion": "izquierda",
        "ancho_cm": 5.0,
    }
    assert canonico["pagina"]["tamano"] == "CARTA"


def test_el_contrato_json_schema_esta_al_dia_y_describe_la_estructura():
    assert exportar_esquemas(["exportar_esquemas.py", "--verificar"]) == 0
    from scripts.exportar_esquemas import DESTINO

    esquema = json.loads((DESTINO / "contenido_plantilla.schema.json").read_text(encoding="utf-8"))
    assert esquema["additionalProperties"] is False and "bloques" in esquema["properties"]
    definiciones = set(esquema["$defs"])
    assert {
        "BloqueLogotipo",
        "BloqueParrafo",
        "NodoTexto",
        "NodoVariable",
        "NodoSalto",
    } <= definiciones
    assert (
        esquema["$defs"]["NodoTexto"]["properties"]["color"]["anyOf"][0]["pattern"]
        == c.PATRON_COLOR
    )
