"""Plantillas con variables con nombre (``{{guest_name}}``), idioma por plantilla y botones estáticos.

Base real con RLS; Meta es el simulador de `whatsapp` con las siete plantillas reales de la cuenta
compartida. Cubre importar (fila local, ejemplos por nombre, idioma, motivos exactos), crear y enviar
a revisión una plantilla nombrada, y las notificaciones con ``variables_json`` por nombre (NOT-14/15,
detalle y duplicar).
"""

import pytest
from ayudantes_notificaciones import insertar_plantilla, sql

pytestmark = pytest.mark.docker

PM = "/api/v1/plantillas-mensaje"
LISTA = f"{PM}/meta"
IMPORTAR = f"{PM}/importar"
NOT = "/api/v1/notificaciones"
CRITERIOS = {"op": "Y", "items": [{"campo": "planta_id", "operador": "es", "valor": 3}]}

REALES = {
    ("hello_world", "en_US"),
    ("vida_aviso_checkout", "es_MX"),
    ("vida_bienvenida_llegada", "es_MX"),
    ("vida_recordatorio_prellegada", "es_MX"),
    ("vida_checkout_notice", "en"),
    ("vida_prearrival_reminder", "en"),
    ("vida_welcome_greeting", "en"),
}


@pytest.fixture
def catalogo(sim):
    sim.cargar_catalogo_ejemplo()
    return sim


def pedir(*pares):
    return {"plantillas": [{"nombre": n, "idioma": i} for n, i in pares]}


def por_nombre(r):
    return {i["nombre"]: i for i in r.json()["items"]}


def _codigos(r):
    return {(e["campo"], e["codigo"]) for e in r.json()["errores"]}


def locales(datos):
    return sql(
        datos,
        "SELECT nombre, idioma, texto_con_variables, ejemplos_json, estado_meta "
        "FROM notificaciones.plantilla_mensaje ORDER BY id",
    )


# ------------------------------------------------------------------ listado de las siete reales


async def test_de_las_siete_plantillas_reales_quedan_importables_seis(http, h, catalogo):
    r = await http.get(LISTA, headers=h)
    assert r.status_code == 200, r.text
    items = por_nombre(r)
    reales = {n: items[n] for n, _ in REALES}
    assert {(n, i["idioma"]) for n, i in reales.items()} == REALES
    compatibles = {n for n, i in reales.items() if i["compatible"]}
    assert compatibles == {n for n, _ in REALES} - {"vida_recordatorio_prellegada"}
    pre = reales["vida_recordatorio_prellegada"]
    assert pre["codigo_incompatible"] == "ENCABEZADO_IMAGEN"
    assert [m["codigo"] for m in pre["motivos_incompatibles"]] == ["ENCABEZADO_IMAGEN"]
    assert "Encabezado de imagen" in pre["motivo_incompatible"]
    assert pre["encabezado"] == {"tipo": "MEDIA", "formato": "IMAGE", "texto": None}
    assert pre["formato_variables"] == "NOMBRADO"
    assert pre["variables"] == ["guest_name", "arrival_date", "checkin_time"]


async def test_el_listado_expone_variables_botones_y_advertencias(http, h, catalogo):
    items = por_nombre(await http.get(LISTA, headers=h))
    v = items["vida_aviso_checkout"]
    assert v["compatible"] and v["codigo_incompatible"] is None and v["motivos_incompatibles"] == []
    assert v["formato_variables"] == "NOMBRADO" and v["num_variables"] == 2
    assert v["variables"] == ["guest_name", "checkout_time"]
    assert v["texto"].startswith("Hola {{guest_name}}")  # el texto con {{nombre}} tal cual
    assert v["botones"] == [
        {"tipo": "QUICK_REPLY", "texto": "Sí"},
        {"tipo": "QUICK_REPLY", "texto": "No"},
    ]
    assert v["encabezado"] is None
    assert any("webhook" in a for a in v["advertencias"])  # respuestas rápidas: otro webhook
    hello = items["hello_world"]
    assert hello["compatible"] and hello["idioma"] == "en_US"
    assert hello["formato_variables"] == "POSICIONAL" and hello["variables"] == []
    assert items["vida_checkout_notice"]["idioma"] == "en"
    # una plantilla que mezcla formatos o tiene un botón con variable dice exactamente por qué
    assert items["bienvenida_mezclada"]["codigo_incompatible"] == "VARIABLES_MEZCLADAS"
    assert items["bienvenida_con_boton"]["codigo_incompatible"] == "BOTON_URL_CON_VARIABLE"


async def test_se_informan_todos_los_motivos_de_una_plantilla_en_ingles_con_dos_problemas(
    http, h, sim
):
    sim.agregar_catalogo(
        "otra_en_ingles", id_="800000000000050", idioma="en", estado="PAUSED",
        cuerpo="Hello {{1}} and {{name}}", formato=None,
        componentes=[
            {"type": "HEADER", "format": "VIDEO"},
            {"type": "BUTTONS", "buttons": [{"type": "OTP", "text": "Copy"}]},
        ],
    )  # fmt: skip
    (p,) = (
        i
        for i in (await http.get(LISTA, headers=h)).json()["items"]
        if i["nombre"] == "otra_en_ingles"
    )
    assert [m["codigo"] for m in p["motivos_incompatibles"]] == [
        "ESTADO_NO_APROBADO",
        "ENCABEZADO_VIDEO",
        "BOTON_OTP",
        "VARIABLES_MEZCLADAS",
    ]
    assert p["codigo_incompatible"] == "ESTADO_NO_APROBADO"
    assert all(m["motivo"] for m in p["motivos_incompatibles"])


# ------------------------------------------------------------------ importar


async def test_importa_una_nombrada_con_botones_y_sus_ejemplos_por_nombre(http, h, datos, catalogo):
    r = await http.post(IMPORTAR, json=pedir(("vida_aviso_checkout", "es_MX")), headers=h)
    assert r.status_code == 200, r.text
    (item,) = r.json()["items"]
    assert item["resultado"] == "IMPORTADA"
    ((nombre, idioma, texto, ejemplos, estado),) = locales(datos)
    assert (nombre, idioma, estado) == ("vida_aviso_checkout", "es_MX", "APROBADA")
    assert texto == (
        "Hola {{guest_name}}, tu salida es hoy a las {{checkout_time}}. Gracias por tu estancia."
    )
    assert ejemplos == ["Juan", "12:00"]  # en el orden de aparición, de body_text_named_params
    d = (await http.get(f"{PM}/{item['plantilla_id']}", headers=h)).json()
    assert d["cantidad_variables"] == 2 and d["formato_variables"] == "NOMBRADO"
    assert d["variables"] == ["guest_name", "checkout_time"] and d["estado_meta"] == "APROBADA"


async def test_importa_en_su_idioma_y_omite_la_del_encabezado_de_imagen(http, h, datos, catalogo):
    r = await http.post(IMPORTAR, json=pedir(*sorted(REALES)), headers=h)
    assert r.status_code == 200, r.text
    por = {i["nombre"]: i for i in r.json()["items"]}
    importadas = {n for n, i in por.items() if i["resultado"] == "IMPORTADA"}
    assert importadas == {n for n, _ in REALES} - {"vida_recordatorio_prellegada"}
    pre = por["vida_recordatorio_prellegada"]
    assert pre["resultado"] == "OMITIDA" and pre["codigo"] == "ENCABEZADO_IMAGEN"
    assert "adjuntar la imagen" in pre["motivo"] and pre["plantilla_id"] is None
    idiomas = {f[0]: f[1] for f in locales(datos)}
    assert idiomas["hello_world"] == "en_US" and idiomas["vida_welcome_greeting"] == "en"
    assert idiomas["vida_aviso_checkout"] == "es_MX"
    assert len(idiomas) == 6


async def test_hello_world_sin_variables_ni_ejemplos(http, h, datos, catalogo):
    r = await http.post(IMPORTAR, json=pedir(("hello_world", "en_US")), headers=h)
    assert r.json()["items"][0]["resultado"] == "IMPORTADA"
    ((nombre, idioma, _texto, ejemplos, _),) = locales(datos)
    assert (nombre, idioma, ejemplos) == ("hello_world", "en_US", [])


async def test_importar_solo_lo_que_se_pide_y_por_el_idioma_exacto(http, h, datos, catalogo):
    # `hello_world` existe en en_US; pedirla en es_MX no la encuentra.
    r = await http.post(IMPORTAR, json=pedir(("hello_world", "es_MX")), headers=h)
    (item,) = r.json()["items"]
    assert item["resultado"] == "OMITIDA" and item["codigo"] == "NO_ENCONTRADA_EN_META"
    assert locales(datos) == []


# ------------------------------------------------------------------ crear y enviar a revisión


async def test_crear_y_enviar_a_revision_una_plantilla_nombrada(http, h, datos, sim):
    cuerpo = {
        "nombre": "aviso_llegada",
        "categoria": "UTILITY",
        "idioma": "es_MX",
        "texto_con_variables": "Hola {{guest_name}}, te esperamos en {{lugar}}. {{guest_name}}, ¡hasta pronto!",
        "ejemplos": ["Juan", "Recepción"],
    }
    r = await http.post(PM, json=cuerpo, headers=h)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["cantidad_variables"] == 2 and d["formato_variables"] == "NOMBRADO"
    assert d["variables"] == ["guest_name", "lugar"]
    r = await http.post(f"{PM}/{d['id']}/enviar-revision", headers=h)
    assert r.status_code == 202, r.text
    creada = sim.plantillas["aviso_llegada"]
    assert creada["parameter_format"] == "NAMED"
    assert creada["ejemplo"] == {
        "body_text_named_params": [
            {"param_name": "guest_name", "example": "Juan"},
            {"param_name": "lugar", "example": "Recepción"},
        ]
    }


async def test_una_plantilla_posicional_se_crea_en_meta_como_siempre(http, h, sim):
    cuerpo = {
        "nombre": "aviso_pos",
        "categoria": "UTILITY",
        "texto_con_variables": "Hola {{1}}, es el {{2}}.",
        "ejemplos": ["Ana", "lunes"],
    }
    d = (await http.post(PM, json=cuerpo, headers=h)).json()
    assert d["formato_variables"] == "POSICIONAL" and d["variables"] == ["1", "2"]
    await http.post(f"{PM}/{d['id']}/enviar-revision", headers=h)
    assert sim.plantillas["aviso_pos"]["parameter_format"] == "POSITIONAL"
    assert sim.plantillas["aviso_pos"]["ejemplo"] == {"body_text": [["Ana", "lunes"]]}


@pytest.mark.parametrize(
    ("texto", "codigo"),
    [
        ("Hola {{1}} y {{nombre}}", "VARIABLES_MEZCLADAS"),
        ("Hola {{Nombre}}", "NOMBRE_VARIABLE_INVALIDO"),
    ],
)
async def test_crear_rechaza_mezclas_y_nombres_invalidos(http, h, texto, codigo):
    cuerpo = {
        "nombre": "aviso_malo",
        "categoria": "UTILITY",
        "texto_con_variables": texto,
        "ejemplos": ["a", "b"],
    }
    r = await http.post(PM, json=cuerpo, headers=h)
    assert r.status_code == 422 and ("texto_con_variables", codigo) in _codigos(r)


# ------------------------------------------------------------------ notificaciones (NOT-14/15)

NOMBRADAS = {
    "guest_name": {"origen": "COLABORADOR", "campo": "nombre_completo"},
    "checkout_time": {"origen": "FIJO", "valor": "12:00"},
}


@pytest.fixture
def nombrada(datos):
    return insertar_plantilla(
        datos,
        nombre="vida_aviso_checkout",
        texto="Hola {{guest_name}}, tu salida es a las {{checkout_time}}.",
    )


def _cuerpo(plantilla, **cambios):
    base = {
        "titulo": "Aviso de salida",
        "modo": "CRITERIOS",
        "criterios": CRITERIOS,
        "plantilla_mensaje_id": plantilla,
        "variables": NOMBRADAS,
    }
    base.update(cambios)
    return base


async def test_notificacion_con_variables_por_nombre_se_guarda_y_se_ve_en_el_detalle(
    http, h, datos, nombrada
):
    r = await http.post(NOT, json=_cuerpo(nombrada), headers=h)
    assert r.status_code == 201, r.text
    n = r.json()
    assert n["variables"] == NOMBRADAS
    assert n["vista_previa"] == "Hola {{nombre_completo}}, tu salida es a las 12:00."
    (guardado,) = sql(
        datos, "SELECT variables_json FROM notificaciones.notificacion WHERE id = %s", (n["id"],)
    )
    assert guardado[0] == NOMBRADAS
    d = (await http.get(f"{NOT}/{n['id']}", headers=h)).json()
    assert d["variables"] == NOMBRADAS and d["vista_previa"] == n["vista_previa"]


async def test_faltantes_y_sobrantes_dan_422_por_campo_sin_repetir_valores(http, h, nombrada):
    r = await http.post(
        NOT, json=_cuerpo(nombrada, variables={"guest_name": NOMBRADAS["guest_name"]}), headers=h
    )
    assert r.status_code == 422 and _codigos(r) == {
        ("variables.checkout_time", "VARIABLE_FALTANTE")
    }
    extra = {**NOMBRADAS, "otra": {"origen": "FIJO", "valor": "valor-secreto-123"}}
    r = await http.post(NOT, json=_cuerpo(nombrada, variables=extra), headers=h)
    assert _codigos(r) == {("variables.otra", "VARIABLE_NO_EXISTE")}
    assert "valor-secreto-123" not in r.text
    # las posiciones no sirven para una plantilla con nombre (ni al revés)
    posicionales = {"1": NOMBRADAS["guest_name"], "2": NOMBRADAS["checkout_time"]}
    r = await http.post(NOT, json=_cuerpo(nombrada, variables=posicionales), headers=h)
    assert _codigos(r) == {
        ("variables.guest_name", "VARIABLE_FALTANTE"),
        ("variables.checkout_time", "VARIABLE_FALTANTE"),
        ("variables.1", "VARIABLE_NO_EXISTE"),
        ("variables.2", "VARIABLE_NO_EXISTE"),
    }


async def test_los_valores_de_cada_variable_nombrada_se_validan_igual_que_las_posicionales(
    http, h, nombrada
):
    sensible = {**NOMBRADAS, "guest_name": {"origen": "COLABORADOR", "campo": "CAMP-0001"}}
    r = await http.post(NOT, json=_cuerpo(nombrada, variables=sensible), headers=h)
    assert ("variables.guest_name.campo", "CAMPO_SENSIBLE_NO_PERMITIDO") in _codigos(r)
    largo = {**NOMBRADAS, "checkout_time": {"origen": "FIJO", "valor": "dos\nlineas"}}
    r = await http.post(NOT, json=_cuerpo(nombrada, variables=largo), headers=h)
    assert ("variables.checkout_time.valor", "VALOR_INVALIDO") in _codigos(r)
    dinamico = {**NOMBRADAS, "guest_name": {"origen": "COLABORADOR", "campo": "CAMP-0003"}}
    assert (
        await http.post(NOT, json=_cuerpo(nombrada, variables=dinamico), headers=h)
    ).status_code == 201


async def test_un_nombre_repetido_en_el_texto_pide_una_sola_variable(http, h, datos):
    p = insertar_plantilla(datos, nombre="repetida", texto="{{guest_name}}, hola {{guest_name}}.")
    solo = {"guest_name": NOMBRADAS["guest_name"]}
    r = await http.post(NOT, json=_cuerpo(p, variables=solo), headers=h)
    assert (
        r.status_code == 201
        and r.json()["vista_previa"] == "{{nombre_completo}}, hola {{nombre_completo}}."
    )


async def test_editar_y_duplicar_conservan_las_variables_por_nombre(http, h, datos, nombrada):
    n = (await http.post(NOT, json=_cuerpo(nombrada), headers=h)).json()
    nuevas = {**NOMBRADAS, "checkout_time": {"origen": "FIJO", "valor": "13:30"}}
    r = await http.patch(f"{NOT}/{n['id']}", json={"variables": nuevas}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["variables"] == nuevas and "13:30" in r.json()["vista_previa"]
    r = await http.patch(
        f"{NOT}/{n['id']}", json={"variables": {"guest_name": NOMBRADAS["guest_name"]}}, headers=h
    )
    assert r.status_code == 422 and ("variables.checkout_time", "VARIABLE_FALTANTE") in _codigos(r)
    r = await http.post(f"{NOT}/{n['id']}/duplicar", headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["variables"] == nuevas and r.json()["plantilla"]["id"] == nombrada


async def test_las_posicionales_siguen_pidiendo_posiciones(http, h, datos):
    p = insertar_plantilla(datos)  # "Hola {{1}}, te esperamos el {{2}}."
    r = await http.post(
        NOT, json=_cuerpo(p, variables={"guest_name": NOMBRADAS["guest_name"]}), headers=h
    )
    assert _codigos(r) == {
        ("variables.1", "VARIABLE_FALTANTE"),
        ("variables.2", "VARIABLE_FALTANTE"),
        ("variables.guest_name", "VARIABLE_NO_EXISTE"),
    }
