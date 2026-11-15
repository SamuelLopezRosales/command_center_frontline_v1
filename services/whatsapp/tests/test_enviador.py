"""T-211 (T-096): Lambda ``enviador`` con base real, ventana de 24 horas y simulador de Meta."""

import uuid

import pytest
from ayudantes_whatsapp import (
    ColaFalsa,
    ContactosFalso,
    crear_conversacion,
    eventos,
    mensaje,
    registro_sqs,
)
from cc_whatsapp.meta import ClienteMeta
from cc_whatsapp.metricas import CONTADORES
from enviador.handler import manejar
from simulador_meta import ERROR_NUMERO_INVALIDO, ERROR_SERVIDOR, ERROR_VENTANA

pytestmark = pytest.mark.docker

CELULAR = "8112345678"
DESTINO = "528112345678"


@pytest.fixture
def mundo(datos, simulador, cfg):
    contactos = ContactosFalso({datos["colaborador"]: {"elegible": True, "celular": CELULAR}})
    meta = ClienteMeta(
        base=cfg.meta_api_base,
        version=cfg.meta_api_version,
        phone_number_id=simulador.phone_number_id,
        token=simulador.access_token,
        cliente=simulador.cliente_http(),
    )
    cola = ColaFalsa()

    def enviar(*mensajes, receptor=1, grupo=None):
        registros = [registro_sqs(m, n, receptor, grupo) for n, m in enumerate(mensajes, 1)]
        return manejar(
            {"Records": registros}, abrir=datos["abrir"], cfg=cfg, meta=meta, contactos=contactos,
            sqs=cola,
        )  # fmt: skip

    return {"enviar": enviar, "contactos": contactos, "cola": cola, "sim": simulador, "d": datos}


def salida(d, **extra):
    """``MensajeSalida`` de notificación o chat; ``constancia()`` arma el de constancias."""
    return {
        "mensaje_uuid": str(uuid.uuid4()), "origen_tipo": "CHAT", "origen_id": 1,
        "colaborador_id": d["colaborador"], "empresa_id": d["empresa"], "tipo": "TEXTO",
        "texto": "Hola", "max_intentos": 3, "proposito": "CHAT", **extra,
    }  # fmt: skip


def constancia(d, **extra):
    return {
        "tipo": "CONSTANCIA_ENLACE", "mensaje_uuid": str(uuid.uuid4()), "empresa_id": d["empresa"],
        "colaborador_id": d["colaborador"], "conversacion_id": None, "solicitud_id": 5,
        "constancia_id": 7, "folio": "CG-2026-0001", "enlace": "https://cc.test/d/" + "T" * 43,
        **extra,
    }  # fmt: skip


def test_constancia_dentro_de_la_ventana_sale_como_texto_con_el_enlace(mundo):
    d = mundo["d"]
    crear_conversacion(d, d["colaborador"], hace="2 hours")
    m = constancia(d)
    assert mundo["enviar"](m) == {"batchItemFailures": []}
    [e] = mundo["sim"].enviados
    assert e["to"] == DESTINO and e["type"] == "text"
    assert "https://cc.test/d/" in e["text"]["body"] and e["text"]["preview_url"] is False
    estado, error, wamid, intentos, tipo, _ = mensaje(d, m["mensaje_uuid"])
    assert (estado, error, wamid, intentos, tipo) == ("ENVIADO", None, e["wamid"], 1, "TEXTO")
    [ev] = eventos(d, "wa.mensaje_estado")
    assert ev["estado"] == "ENVIADO" and ev["origen_tipo"] == "CONSTANCIA" and ev["origen_id"] == 7
    assert CONTADORES["envios_ok"] == 1
    assert mundo["contactos"].llamadas == [(d["empresa"], d["colaborador"], "CONSTANCIA")]


def test_constancia_fuera_de_la_ventana_usa_la_plantilla_de_constancia_lista(mundo):
    d = mundo["d"]
    crear_conversacion(d, d["colaborador"], hace="30 hours")
    m = constancia(d)
    mundo["enviar"](m)
    [e] = mundo["sim"].enviados
    assert e["type"] == "template" and e["template"]["name"] == "constancia_lista"
    textos = [p["text"] for p in e["template"]["components"][0]["parameters"]]
    assert textos[0] == "CG-2026-0001" and mensaje(d, m["mensaje_uuid"])[4:] == (
        "PLANTILLA",
        "constancia_lista",
    )


def test_constancia_fuera_de_la_ventana_sin_plantilla_queda_fallida(mundo, cfg, datos):
    crear_conversacion(datos, datos["colaborador"], hace=None)  # nunca escribió
    cfg2 = cfg.model_copy(update={"plantilla_constancia_lista": None})
    m = constancia(datos)
    from enviador import handler

    r = handler.manejar(
        {"Records": [registro_sqs(m)]}, abrir=datos["abrir"], cfg=cfg2,
        meta=None, contactos=mundo["contactos"], sqs=mundo["cola"],
    )  # fmt: skip
    assert r == {"batchItemFailures": []} and mundo["sim"].enviados == []
    assert mensaje(datos, m["mensaje_uuid"])[:2] == ("FALLIDO", "VENTANA_CERRADA")
    assert CONTADORES["ventana_cerrada"] == 1


@pytest.mark.parametrize("motivo", ["BAJA", "SIN_CONSENTIMIENTO"])
def test_un_colaborador_no_elegible_no_recibe_nada(mundo, motivo):
    d = mundo["d"]
    mundo["contactos"].contactos[d["colaborador"]] = {"elegible": False, "motivo": motivo}
    crear_conversacion(d, d["colaborador"])
    m = constancia(d)
    mundo["enviar"](m)
    assert mundo["sim"].enviados == []
    assert mensaje(d, m["mensaje_uuid"])[:2] == ("FALLIDO", motivo)
    assert eventos(d, "wa.mensaje_estado")[0]["error_codigo"] == motivo
    assert CONTADORES["envios_bloqueados_elegibilidad"] == 1


def test_el_rechazo_del_bot_es_una_respuesta_fija_dentro_de_la_ventana(mundo):
    d = mundo["d"]
    conv = crear_conversacion(d, d["colaborador"], hace="1 minute")
    # a quien escribió no se le resuelve contacto: no es elegible, pero se le responde
    m = salida(d, origen_tipo="BOT", proposito="RECHAZO_BOT", wa_id="5218199999999",
               conversacion_id=conv, texto="No encontramos tu número.")  # fmt: skip
    m["colaborador_id"] = None
    mundo["enviar"](m)
    [e] = mundo["sim"].enviados
    assert e["to"] == "528199999999" and e["text"]["body"] == "No encontramos tu número."
    assert mundo["contactos"].llamadas == []
    fuera = crear_conversacion(d, d["colaborador"], hace="48 hours")
    m2 = salida(d, origen_tipo="BOT", proposito="RECHAZO_BOT", wa_id="5218199999999",
                conversacion_id=fuera)  # fmt: skip
    m2["colaborador_id"] = None
    mundo["enviar"](m2)
    assert len(mundo["sim"].enviados) == 1
    assert mensaje(d, m2["mensaje_uuid"])[:2] == ("FALLIDO", "VENTANA_CERRADA")


def test_una_notificacion_siempre_es_plantilla_y_el_texto_libre_fuera_de_ventana_no_sale(mundo):
    d = mundo["d"]
    crear_conversacion(d, d["colaborador"], hace="1 hour")
    con = salida(d, origen_tipo="NOTIFICACION", tipo="PLANTILLA", plantilla="aviso_rh",
                 variables=["Ana"], proposito="NOTIFICACION")  # fmt: skip
    mundo["enviar"](con)
    assert mundo["sim"].enviados[0]["type"] == "template"  # aunque la ventana está abierta

    libre = salida(d, origen_tipo="NOTIFICACION", proposito="NOTIFICACION")
    mundo["enviar"](libre)
    assert len(mundo["sim"].enviados) == 1
    assert mensaje(d, libre["mensaje_uuid"])[:2] == ("FALLIDO", "PLANTILLA_REQUERIDA")

    chat = salida(d, origen_tipo="CHAT")  # texto libre del chat, fuera de ventana
    crear_conversacion(d, d["colaborador"], hace="40 hours")
    # la conversación más reciente es la de hace 1 hora: se fija la vieja de forma explícita
    chat["conversacion_id"] = crear_conversacion(d, d["colaborador"], hace="40 hours")
    mundo["enviar"](chat)
    assert mensaje(d, chat["mensaje_uuid"])[:2] == ("FALLIDO", "VENTANA_24H_CERRADA")


def test_error_permanente_no_reintenta_y_el_numero_invalido_publica_su_evento(mundo):
    d = mundo["d"]
    crear_conversacion(d, d["colaborador"])
    mundo["sim"].por_destino[DESTINO] = ERROR_NUMERO_INVALIDO
    m = constancia(d)
    assert mundo["enviar"](m) == {"batchItemFailures": []}  # se consume: no hay reintento
    assert mensaje(d, m["mensaje_uuid"])[:2] == ("FALLIDO", "NUMERO_INVALIDO")
    assert eventos(d, "wa.numero_invalido") == [
        {"colaborador_id": d["colaborador"], "empresa_id": d["empresa"]}
    ]
    mundo["sim"].por_destino[DESTINO] = ERROR_VENTANA
    m2 = constancia(d)
    mundo["enviar"](m2)
    assert mensaje(d, m2["mensaje_uuid"])[:2] == ("FALLIDO", "VENTANA_CERRADA")
    assert mundo["cola"].visibilidad == []


def test_constancias_hacen_dos_intentos_con_espera_creciente(mundo):
    d = mundo["d"]
    crear_conversacion(d, d["colaborador"])
    mundo["sim"].siguientes = [ERROR_SERVIDOR, ERROR_SERVIDOR]
    m = constancia(d)
    r1 = mundo["enviar"](m, receptor=1)
    assert r1 == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert mundo["cola"].visibilidad == [("rh1", 30)]
    assert mensaje(d, m["mensaje_uuid"])[0] == "ENCOLADO"
    r2 = mundo["enviar"](m, receptor=2)  # segunda y última recepción
    assert r2 == {"batchItemFailures": []}
    assert mensaje(d, m["mensaje_uuid"])[:2] == ("FALLIDO", "INTENTOS_AGOTADOS")
    assert mensaje(d, m["mensaje_uuid"])[3] == 2  # intentos guardados antes de cada llamada


def test_notificaciones_hacen_tres_intentos_y_el_exito_borra_el_reintento(mundo):
    d = mundo["d"]
    crear_conversacion(d, d["colaborador"])
    mundo["sim"].siguientes = [ERROR_SERVIDOR, ERROR_SERVIDOR]
    m = salida(d, origen_tipo="NOTIFICACION", tipo="PLANTILLA", plantilla="aviso_rh",
               proposito="NOTIFICACION")  # fmt: skip
    assert mundo["enviar"](m, receptor=1)["batchItemFailures"]
    assert mundo["enviar"](m, receptor=2)["batchItemFailures"]  # sigue reintentando
    assert [v for _, v in mundo["cola"].visibilidad] == [30, 120]
    assert mundo["enviar"](m, receptor=3) == {"batchItemFailures": []}  # Meta ya responde
    assert mensaje(d, m["mensaje_uuid"])[0] == "ENVIADO"


def test_la_clave_de_idempotencia_evita_enviar_dos_veces(mundo):
    d = mundo["d"]
    crear_conversacion(d, d["colaborador"])
    m = constancia(d)
    mundo["enviar"](m)
    mundo["enviar"](m)
    mundo["enviar"](m, receptor=2)
    assert len(mundo["sim"].enviados) == 1
    assert len(eventos(d, "wa.mensaje_estado")) == 1


def test_en_fifo_un_fallo_detiene_los_siguientes_del_mismo_grupo(mundo):
    d = mundo["d"]
    crear_conversacion(d, d["colaborador"])
    mundo["sim"].siguientes = [ERROR_SERVIDOR]
    a, b = constancia(d), constancia(d)
    r = mundo["enviar"](a, b, grupo=str(d["colaborador"]))
    assert [f["itemIdentifier"] for f in r["batchItemFailures"]] == ["m1", "m2"]
    assert mundo["sim"].enviados == []  # el segundo no se adelantó


def test_el_bot_responde_a_un_numero_sin_conversacion_con_la_ventana_del_mensaje_que_contesta(
    mundo,
):
    from datetime import UTC, datetime

    d = mundo["d"]  # sin conversación ni colaborador: solo cuenta `entrante_at`
    ahora = datetime.now(UTC).isoformat()
    m = salida(d, origen_tipo="BOT", proposito="RECHAZO_BOT", wa_id="5219999999999",
               texto="Este número no tiene acceso al servicio.", entrante_at=ahora)  # fmt: skip
    m["colaborador_id"] = None
    mundo["enviar"](m)
    assert mundo["sim"].enviados[0]["to"] == "529999999999"
    sin = salida(d, origen_tipo="BOT", proposito="RECHAZO_BOT", wa_id="5219999999999")
    sin["colaborador_id"] = None
    mundo["enviar"](sin)  # sin `entrante_at` ni conversación la ventana está cerrada
    assert mensaje(d, sin["mensaje_uuid"])[:2] == ("FALLIDO", "VENTANA_CERRADA")


def test_la_lista_interactiva_del_menu_se_envia_dentro_de_la_ventana(mundo):
    from datetime import UTC, datetime

    d = mundo["d"]
    lista = {"type": "list", "body": {"text": "Elige"},
             "action": {"button": "Ver", "sections": [{"rows": [{"id": "plantilla:1", "title": "A"}]}]}}  # fmt: skip
    m = salida(d, origen_tipo="BOT", proposito="BOT", wa_id="5218112345678", tipo="INTERACTIVO",
               interactivo=lista, texto=None, entrante_at=datetime.now(UTC).isoformat())  # fmt: skip
    mundo["enviar"](m)
    [e] = mundo["sim"].enviados
    assert e["type"] == "interactive" and e["interactive"]["action"]["button"] == "Ver"
    assert (
        mensaje(d, m["mensaje_uuid"])[0] == "ENVIADO"
        and mensaje(d, m["mensaje_uuid"])[4] == "INTERACTIVO"
    )
