"""Flujo de punta a punta con plantillas importadas de Meta: variables con nombre, botones estáticos
e idioma por plantilla (las plantillas reales de la cuenta compartida, en el simulador de Meta).

Recorrido: importar desde Meta -> notificación individual -> revisar -> enviar -> despachador ->
enviador -> la API simulada de Meta recibe ``parameter_name`` y el idioma de la plantilla -> estados.
Comparte el mundo de ``test_flujo_notificacion.py`` (``mundo_notif``).

Comando: ``uv run pytest tests/e2e/test_flujo_plantillas_nombradas.py -q``
"""

import pytest
from ayudantes_e2e_notif import BASE_NOT, BASE_PLANTILLAS, CELULARES, wa_id

pytestmark = pytest.mark.docker


async def importar(w, nombre: str, idioma: str) -> int:
    r = await w.http_not.post(
        f"{BASE_PLANTILLAS}/importar",
        json={"plantillas": [{"nombre": nombre, "idioma": idioma}]},
        headers=w.rh_a,
    )
    assert r.status_code == 200, r.text
    (item,) = r.json()["items"]
    assert item["resultado"] == "IMPORTADA", item
    return item["plantilla_id"]


async def notificacion_individual(w, plantilla_id: int, variables: dict, quien="ana") -> int:
    r = await w.http_not.post(
        BASE_NOT,
        json={
            "titulo": "Aviso individual",
            "modo": "INDIVIDUAL",
            "colaborador_id": w.colaboradores[quien],
            "plantilla_mensaje_id": plantilla_id,
            "variables": variables,
        },
        headers=w.rh_a,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def enviar_ahora(w, nid: int):
    rev = await w.revisar(nid)
    assert rev["total_seleccionados"] == 1 and rev["total_excluidos"] == 0, rev
    r = await w.confirmar(nid, modo_envio="AHORA")
    assert r.status_code == 202, r.text
    await w.bombear("despacho inmediato")


async def test_plantilla_nombrada_con_botones_se_envia_con_parameter_name_y_su_idioma(mundo_notif):
    w = mundo_notif
    w.sim.cargar_catalogo_ejemplo()
    pid = await importar(w, "vida_aviso_checkout", "es_MX")
    d = (await w.http_not.get(f"{BASE_PLANTILLAS}/{pid}", headers=w.rh_a)).json()
    assert d["estado_meta"] == "APROBADA" and d["formato_variables"] == "NOMBRADO"
    assert d["variables"] == ["guest_name", "checkout_time"] and d["idioma"] == "es_MX"
    w.paso(
        "Importar desde Meta", "`vida_aviso_checkout` (es_MX): variables guest_name y checkout_time"
    )

    nid = await notificacion_individual(
        w,
        pid,
        {
            "guest_name": {"origen": "COLABORADOR", "campo": "nombre_completo"},
            "checkout_time": {"origen": "FIJO", "valor": "12:00"},
        },
    )
    n = await w.notificacion(nid)
    assert n["vista_previa"].startswith("Hola {{nombre_completo}}, tu salida es hoy a las 12:00")
    await enviar_ahora(w, nid)

    assert w.estado_notificacion(nid) == "COMPLETADA"
    [envio] = w.meta_a("ana")
    assert envio["type"] == "template" and envio["template"]["name"] == "vida_aviso_checkout"
    assert envio["template"]["language"] == {"code": "es_MX"}
    # La API simulada recibió `parameter_name` en cada parámetro (si no, la habría rechazado: 132012).
    assert envio["template"]["components"] == [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "parameter_name": "guest_name", "text": "Ana Notif Luna"},
                {"type": "text", "parameter_name": "checkout_time", "text": "12:00"},
            ],
        }
    ]  # y ningún componente `button`: los botones estáticos los agrega Meta
    assert w.sim.rechazados == []
    d = w.destinatarios(nid)
    assert d["ana"][0] == "ENVIADO" and d["ana"][3] == "WHATSAPP"
    await w.estado_meta(
        envio["wamid"], "delivered", destinatario=wa_id(CELULARES["ana"])
    )  # el estado de entrega llega por el webhook como siempre
    assert w.destinatarios(nid)["ana"][0] == "ENTREGADO"
    w.paso("Envío", "el simulador de Meta recibió `parameter_name` y el texto del colaborador")


async def test_plantilla_en_ingles_sin_variables_se_envia_en_en_us(mundo_notif):
    w = mundo_notif
    w.sim.cargar_catalogo_ejemplo()
    pid = await importar(w, "hello_world", "en_US")
    d = (await w.http_not.get(f"{BASE_PLANTILLAS}/{pid}", headers=w.rh_a)).json()
    assert d["idioma"] == "en_US" and d["cantidad_variables"] == 0 and d["variables"] == []
    nid = await notificacion_individual(w, pid, {})
    await enviar_ahora(w, nid)

    assert w.estado_notificacion(nid) == "COMPLETADA"
    [envio] = w.meta_a("ana")
    # el idioma es el de la plantilla (antes se mandaba siempre es_MX y Meta respondía 132001)
    assert envio["template"] == {"name": "hello_world", "language": {"code": "en_US"}}
    assert w.destinatarios(nid)["ana"][0] == "ENVIADO"
    # sin variables, las posicionales siguen sin `parameter_name`
    assert "parameter_name" not in str(envio)


async def test_plantilla_en_ingles_con_nombres_usa_su_idioma_y_los_nombres(mundo_notif):
    w = mundo_notif
    w.sim.cargar_catalogo_ejemplo()
    pid = await importar(w, "vida_welcome_greeting", "en")
    nid = await notificacion_individual(
        w,
        pid,
        {
            "guest_name": {"origen": "COLABORADOR", "campo": "nombre_completo"},
            "tower": {"origen": "FIJO", "valor": "B"},
        },
    )
    await enviar_ahora(w, nid)
    [envio] = w.meta_a("ana")
    assert envio["template"]["language"] == {"code": "en"}
    assert [p["parameter_name"] for p in envio["template"]["components"][0]["parameters"]] == [
        "guest_name",
        "tower",
    ]
    assert w.destinatarios(nid)["ana"][0] == "ENVIADO"


async def test_si_meta_rechaza_el_formato_el_destinatario_queda_fallido_con_motivo_y_sin_reintento(
    mundo_notif,
):
    w = mundo_notif
    w.sim.cargar_catalogo_ejemplo()
    pid = await importar(w, "vida_aviso_checkout", "es_MX")
    # Meta cambia la plantilla a posicional después de importarla: el envío con nombres ya no vale.
    p = next(x for x in w.sim.catalogo_meta if x["name"] == "vida_aviso_checkout")
    p["components"][0]["text"] = "Hola {{1}}, tu salida es a las {{2}}."
    p["parameter_format"] = "POSITIONAL"
    nid = await notificacion_individual(
        w,
        pid,
        {
            "guest_name": {"origen": "COLABORADOR", "campo": "nombre_completo"},
            "checkout_time": {"origen": "FIJO", "valor": "12:00"},
        },
    )
    await enviar_ahora(w, nid)

    d = w.destinatarios(nid)
    assert d["ana"][0] == "FALLIDO" and d["ana"][2] == "PLANTILLA_PARAMETROS"
    assert w.meta_a("ana") == [] and len(w.sim.rechazados) == 1  # un solo intento: error permanente
    assert w.reintentos_pedidos == []
    assert w.estado_notificacion(nid) == "CON_FALLAS"


async def test_una_plantilla_con_encabezado_de_imagen_no_se_importa_y_dice_por_que(mundo_notif):
    w = mundo_notif
    w.sim.cargar_catalogo_ejemplo()
    r = await w.http_not.post(
        f"{BASE_PLANTILLAS}/importar",
        json={"plantillas": [{"nombre": "vida_recordatorio_prellegada", "idioma": "es_MX"}]},
        headers=w.rh_a,
    )
    (item,) = r.json()["items"]
    assert item["resultado"] == "OMITIDA" and item["codigo"] == "ENCABEZADO_IMAGEN"
    assert "imagen" in item["motivo"]
    assert wa_id(CELULARES["ana"]) not in r.text  # sin datos personales
