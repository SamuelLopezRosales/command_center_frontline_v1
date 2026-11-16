"""T-143 (CC-REQ-158, 162; design.md §4.2, §11.3): el webhook de Meta sin firma o con firma inválida
da 403 y no encola nada; la verificación de la suscripción no se deja adivinar; el handler no
registra el cuerpo ni los números.

Handler real (``lambdas/webhook_meta/handler.py``) con el simulador de Meta; la cola es un doble que
registra cada ``send_message``. Corre sin Docker.
"""

import base64
import hashlib
import hmac
import json
import logging

import pytest
from ayudantes_whatsapp import ColaFalsa
from cc_whatsapp.config import ConfigWhatsapp
from simulador_meta import SimuladorMeta
from webhook_meta.handler import manejar

WA_ID = "5218112345678"
TEXTO_SECRETO = "mi NSS es 12345678901 y mi CURP es XAXX010101HNEXXXA4"  # pragma: allowlist secret


@pytest.fixture
def sim():
    return SimuladorMeta()


@pytest.fixture
def cfg():
    return ConfigWhatsapp(
        meta_phone_number_id="PN-PRUEBA", cola_entrada_url="wa-entrada.fifo",
        cola_estados_url="wa-estados", cola_salida_url="wa-salida.fifo", bus_eventos="cc-prueba",
    )  # fmt: skip


def _evento(sim, payload, *, cabecera=None, cuerpo: bytes | None = None, base64_=False):
    """Evento de API Gateway/Lambda con la cabecera de firma dada (``None``: sin cabecera)."""
    crudo = cuerpo if cuerpo is not None else json.dumps(payload).encode()
    headers = {"content-type": "application/json"}
    if cabecera is not None:
        headers["X-Hub-Signature-256"] = cabecera
    return {
        "requestContext": {"http": {"method": "POST"}},
        "headers": headers,
        "body": base64.b64encode(crudo).decode() if base64_ else crudo.decode(),
        "isBase64Encoded": base64_,
    }


def _firma(secreto: str, cuerpo: bytes) -> str:
    return "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


def _llamar(sim, cfg, evento):
    cola = ColaFalsa()
    return manejar(evento, sqs=cola, secretos=sim.secretos, cfg=cfg), cola


def test_sin_firma_o_con_firma_invalida_da_403_y_no_encola_nada(sim, cfg):
    payload = sim.mensaje_entrante(WA_ID, TEXTO_SECRETO, wamid="wamid.X1")
    cuerpo = json.dumps(payload).encode()
    valida = _firma(sim.app_secret, cuerpo)
    otra_empresa = _firma("secreto-de-otra-app", cuerpo)
    casos = {
        "sin_cabecera": None,
        "cabecera_vacia": "",
        "solo_el_prefijo": "sha256=",
        "sin_prefijo": valida.removeprefix("sha256="),
        "prefijo_sha1": "sha1=" + valida.removeprefix("sha256="),
        "firma_con_otro_secreto": otra_empresa,
        "firma_truncada": valida[:-2],
        "firma_con_un_caracter_distinto": valida[:-1] + ("0" if valida[-1] != "0" else "1"),
        "hex_en_mayusculas": "sha256=" + valida.removeprefix("sha256=").upper(),
        "firma_de_otro_cuerpo": _firma(sim.app_secret, cuerpo + b" "),
        "firma_de_cuerpo_vacio": _firma(sim.app_secret, b""),
        "espacios": "sha256= " + valida.removeprefix("sha256="),
    }
    for nombre, cabecera in casos.items():
        r, cola = _llamar(sim, cfg, _evento(sim, payload, cabecera=cabecera, cuerpo=cuerpo))
        assert r["statusCode"] == 403, nombre
        assert cola.enviados == [], f"{nombre}: encoló un mensaje sin firma válida"
        assert r["body"] == ""  # no explica por qué


def test_la_firma_se_calcula_sobre_el_cuerpo_crudo_no_sobre_el_json_reformateado(sim, cfg):
    payload = sim.mensaje_entrante(WA_ID, "Hola", wamid="wamid.X2")
    crudo = json.dumps(payload, indent=2).encode()  # otros espacios y saltos de línea
    firma_del_compacto = _firma(sim.app_secret, json.dumps(payload).encode())
    r, cola = _llamar(sim, cfg, _evento(sim, payload, cabecera=firma_del_compacto, cuerpo=crudo))
    assert r["statusCode"] == 403 and cola.enviados == []
    r, cola = _llamar(
        sim, cfg, _evento(sim, payload, cabecera=_firma(sim.app_secret, crudo), cuerpo=crudo)
    )
    assert r["statusCode"] == 200 and len(cola.enviados) == 1


def test_cuerpo_en_base64_se_firma_decodificado(sim, cfg):
    payload = sim.mensaje_entrante(WA_ID, "Hola", wamid="wamid.X3")
    crudo = json.dumps(payload).encode()
    evento = _evento(
        sim, payload, cabecera=_firma(sim.app_secret, crudo), cuerpo=crudo, base64_=True
    )
    r, cola = _llamar(sim, cfg, evento)
    assert r["statusCode"] == 200 and len(cola.enviados) == 1
    # la firma del texto en base64 (lo que NO se firmó) no vale
    evento = _evento(
        sim, payload, cuerpo=crudo, base64_=True,
        cabecera=_firma(sim.app_secret, base64.b64encode(crudo)),
    )  # fmt: skip
    r, cola = _llamar(sim, cfg, evento)
    assert r["statusCode"] == 403 and cola.enviados == []


def test_cabecera_en_cualquier_combinacion_de_mayusculas_se_acepta_y_la_ausente_no(sim, cfg):
    payload = sim.mensaje_entrante(WA_ID, "Hola", wamid="wamid.X4")
    crudo = json.dumps(payload).encode()
    evento = _evento(sim, payload, cuerpo=crudo)
    evento["headers"]["x-hub-signature-256"] = _firma(sim.app_secret, crudo)
    assert _llamar(sim, cfg, evento)[0]["statusCode"] == 200
    # una cabecera parecida pero distinta no cuenta
    evento = _evento(sim, payload, cuerpo=crudo)
    evento["headers"]["X-Hub-Signature"] = _firma(sim.app_secret, crudo)
    r, cola = _llamar(sim, cfg, evento)
    assert r["statusCode"] == 403 and cola.enviados == []


def test_estados_y_plantillas_sin_firma_tampoco_se_encolan(sim, cfg):
    for payload in (
        sim.estado("wamid.OUT1", "delivered"),
        sim.cambio_de_plantilla("aviso", "APPROVED"),
    ):
        r, cola = _llamar(sim, cfg, sim.evento_post(payload, firma_valida=False))
        assert r["statusCode"] == 403 and cola.enviados == []


def test_cuerpo_firmado_pero_malformado_da_400_y_no_encola(sim, cfg):
    crudo = b'{"entry": [ esto no es json'
    r, cola = _llamar(
        sim, cfg, _evento(sim, None, cabecera=_firma(sim.app_secret, crudo), cuerpo=crudo)
    )
    assert r["statusCode"] == 400 and cola.enviados == []


def test_la_verificacion_de_la_suscripcion_no_se_adivina(sim, cfg):
    candidatos = [
        {"token": ""},
        {"token": "token-de-verificacion "},  # con un espacio
        {"token": sim.verify_token.upper()},
        {"token": sim.app_secret},  # el otro secreto no sirve
        {"modo": "unsubscribe"},
        {"modo": ""},
    ]
    for c in candidatos:
        evento = sim.evento_get(
            modo=c.get("modo", "subscribe"), token=c.get("token"), desafio="reto"
        )
        r, cola = _llamar(sim, cfg, evento)
        assert r["statusCode"] == 403 and "reto" not in r["body"] and cola.enviados == []
    # sin parámetros
    r, _ = _llamar(sim, cfg, {"requestContext": {"http": {"method": "GET"}}})
    assert r["statusCode"] == 403
    # contraprueba: el token correcto sí devuelve el reto
    r, _ = _llamar(sim, cfg, sim.evento_get(desafio="reto"))
    assert (r["statusCode"], r["body"]) == (200, "reto")


def test_otros_metodos_no_se_atienden(sim, cfg):
    for metodo in ("PUT", "DELETE", "PATCH", "OPTIONS"):
        evento = {"requestContext": {"http": {"method": metodo}}, "headers": {}, "body": ""}
        r, cola = _llamar(sim, cfg, evento)
        assert r["statusCode"] == 405 and cola.enviados == []


def test_el_handler_no_registra_cuerpo_ni_numeros_en_ningun_camino(sim, cfg, caplog, capsys):
    """Logs y salida estándar (las métricas EMF van a stdout) de todos los caminos."""
    caplog.set_level(logging.DEBUG)
    payload = sim.mensaje_entrante(WA_ID, TEXTO_SECRETO, wamid="wamid.X5")
    _llamar(sim, cfg, sim.evento_post(payload))  # firma válida
    _llamar(sim, cfg, sim.evento_post(payload, firma_valida=False))  # inválida
    _llamar(sim, cfg, _evento(sim, payload))  # sin firma
    crudo = b"{no es json"
    _llamar(sim, cfg, _evento(sim, None, cabecera=_firma(sim.app_secret, crudo), cuerpo=crudo))
    # SQS caído: el único camino con log propio
    cola_rota = ColaFalsa(fallar=True)
    manejar(sim.evento_post(payload), sqs=cola_rota, secretos=sim.secretos, cfg=cfg)
    visto = caplog.text + capsys.readouterr().out
    for secreto in (TEXTO_SECRETO, "12345678901", "XAXX010101HNEXXXA4", WA_ID, "8112345678",
                    sim.app_secret, sim.access_token, "wamid.X5"):  # fmt: skip
        assert secreto not in visto, f"el handler registró {secreto!r}"


def test_un_phone_number_id_ajeno_se_ignora_aunque_la_firma_sea_valida(sim, cfg):
    """El número de otra cuenta no se encola (no es de esta empresa)."""
    payload = sim._cambio(
        {"messages": [{"id": "wamid.AJ", "from": WA_ID, "type": "text", "text": {"body": "hola"},
                       "timestamp": "1"}]}, "PN-OTRO"
    )  # fmt: skip
    r, cola = _llamar(sim, cfg, sim.evento_post(payload))
    assert r["statusCode"] == 200 and cola.enviados == []
