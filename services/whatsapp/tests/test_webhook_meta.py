"""T-211 (T-093, T-094): simulador de Meta y Lambda ``webhook-meta``."""

import hashlib
import json

import pytest
from ayudantes_whatsapp import ColaFalsa
from cc_whatsapp.metricas import CONTADORES
from webhook_meta.handler import manejar

WA_ID = "5218112345678"


def llamar(sim, cfg, evento, cola=None):
    cola = cola or ColaFalsa()
    return manejar(evento, sqs=cola, secretos=sim.secretos, cfg=cfg), cola


def test_get_de_verificacion_valido_e_invalido(simulador, cfg):
    r, _ = llamar(simulador, cfg, simulador.evento_get(desafio="987"))
    assert (r["statusCode"], r["body"]) == (200, "987")
    for malo in (
        simulador.evento_get(token="otro"),
        simulador.evento_get(modo="unsubscribe"),
    ):
        assert llamar(simulador, cfg, malo)[0]["statusCode"] == 403


def test_mensaje_firmado_se_encola_con_grupo_y_deduplicacion(simulador, cfg):
    evento = simulador.evento_post(simulador.mensaje_entrante(WA_ID, "Hola", wamid="wamid.A1"))
    r, cola = llamar(simulador, cfg, evento)
    assert r["statusCode"] == 200
    [e] = cola.enviados
    assert e["QueueUrl"] == "wa-entrada.fifo"
    assert e["MessageGroupId"] == hashlib.sha256(WA_ID.encode()).hexdigest()
    assert e["MessageDeduplicationId"] == "wamid.A1"
    cuerpo = json.loads(e["MessageBody"])
    assert cuerpo["texto"] == "Hola" and cuerpo["wa_id"] == WA_ID and cuerpo["tipo"] == "text"
    assert CONTADORES["webhook_mensajes_encolados"] == 1


def test_respuesta_interactiva_y_cuerpo_en_base64(simulador, cfg):
    evento = simulador.evento_post(
        simulador.respuesta_interactiva(WA_ID, "plantilla:3"), base64=True
    )
    r, cola = llamar(simulador, cfg, evento)
    assert r["statusCode"] == 200
    assert json.loads(cola.enviados[0]["MessageBody"])["interactivo_id"] == "plantilla:3"


def test_estados_y_plantillas_van_a_wa_estados(simulador, cfg):
    cola = ColaFalsa()
    for p in (
        simulador.estado("wamid.OUT1", "delivered"),
        simulador.estado("wamid.OUT2", "failed", error=131026),
        simulador.cambio_de_plantilla("aviso", "REJECTED", "ABUSIVE_CONTENT"),
    ):
        assert llamar(simulador, cfg, simulador.evento_post(p), cola)[0]["statusCode"] == 200
    cuerpos = cola.cuerpos("wa-estados")
    assert [c["clase"] for c in cuerpos] == ["mensaje", "mensaje", "plantilla"]
    assert cuerpos[1]["error_codigo"] == "131026" and cuerpos[0]["estado"] == "delivered"
    assert cuerpos[2]["evento"] == "REJECTED" and cuerpos[2]["motivo"] == "ABUSIVE_CONTENT"
    assert all("MessageGroupId" not in e for e in cola.enviados)  # cola estándar


def test_firma_invalida_da_403_sin_encolar_y_cuenta_la_metrica(simulador, cfg):
    evento = simulador.evento_post(simulador.mensaje_entrante(WA_ID, "x"), firma_valida=False)
    r, cola = llamar(simulador, cfg, evento)
    assert r["statusCode"] == 403 and cola.enviados == []
    assert CONTADORES["webhook_firma_invalida"] == 1
    sin_firma = simulador.evento_post(simulador.mensaje_entrante(WA_ID, "x"))
    sin_firma["headers"] = {}
    assert llamar(simulador, cfg, sin_firma)[0]["statusCode"] == 403


def test_phone_number_id_desconocido_se_ignora_con_200(simulador, cfg):
    payload = simulador.mensaje_entrante(WA_ID, "x", phone_number_id="OTRO-NUMERO")
    r, cola = llamar(simulador, cfg, simulador.evento_post(payload))
    assert r["statusCode"] == 200 and cola.enviados == []
    assert CONTADORES["webhook_phone_number_id_ignorado"] == 1


def test_un_fallo_de_sqs_da_500(simulador, cfg):
    evento = simulador.evento_post(simulador.mensaje_entrante(WA_ID, "x"))
    r, _ = llamar(simulador, cfg, evento, ColaFalsa(fallar=True))
    assert r["statusCode"] == 500 and CONTADORES["webhook_error_sqs"] == 1


def test_el_cuerpo_y_los_numeros_no_se_registran(simulador, cfg, caplog, capsys):
    caplog.set_level("DEBUG")
    ok = simulador.evento_post(simulador.mensaje_entrante(WA_ID, "texto-secreto-123"))
    llamar(simulador, cfg, ok)
    llamar(simulador, cfg, ok, ColaFalsa(fallar=True))
    llamar(
        simulador,
        cfg,
        simulador.evento_post(simulador.mensaje_entrante(WA_ID, "x"), firma_valida=False),
    )
    salida = caplog.text + capsys.readouterr().out
    assert WA_ID not in salida and "texto-secreto-123" not in salida


def test_metodo_no_permitido(simulador, cfg):
    r, _ = llamar(simulador, cfg, {"requestContext": {"http": {"method": "DELETE"}}})
    assert r["statusCode"] == 405


def test_el_simulador_responde_como_graph_api(simulador):
    http = simulador.cliente_http()
    url = f"https://graph.facebook.com/v21.0/{simulador.phone_number_id}/messages"
    cuerpo = {"messaging_product": "whatsapp", "to": "525512345678", "type": "text",
              "text": {"body": "hola"}}  # fmt: skip
    assert http.post(url, json=cuerpo, headers={"Authorization": "Bearer malo"}).status_code == 401
    r = http.post(url, json=cuerpo, headers={"Authorization": f"Bearer {simulador.access_token}"})
    assert r.status_code == 200 and r.json()["messages"][0]["id"] == "wamid.OUT1"
    simulador.por_destino["525512345678"] = (400, 131026)
    r = http.post(url, json=cuerpo, headers={"Authorization": f"Bearer {simulador.access_token}"})
    assert r.status_code == 400 and r.json()["error"]["code"] == 131026
    assert simulador.secuencia_de_estados("wamid.OUT1")[2]["entry"]
    with pytest.raises(KeyError):
        simulador.por_destino["otro"]
