"""Consistencia del JSON que escribe la pantalla con los demás lectores del secreto ``cc/{env}/meta``.

Se escribe con el módulo de integraciones (``servicios.integraciones.guardar``) y el JSON real
resultante lo leen, sin cambios: la Lambda ``webhook-meta`` (``secretos_meta``: firma y token de
verificación), la Lambda ``enviador`` (precedencia de ``phone_number_id`` y ``api_version``), el
cliente de plantillas de `notificaciones` y el cliente de mensajes de `whatsapp`.
"""

import hashlib
import hmac
import json
import time

import boto3
import pytest
from ayudantes_integraciones_meta import (
    ACCESS_TOKEN,
    APP_SECRET,
    COMPLETO,
    PHONE_NUMBER_ID,
    VERIFY_TOKEN,
    WABA_ID,
    ClienteSecretosFalso,
    MotorFalso,
)
from cc_common.auth import UsuarioActual
from cc_notificaciones.integracion_meta import AlmacenSecretsManager
from cc_notificaciones.meta import cargador_credenciales
from cc_notificaciones.servicios import integraciones
from cc_whatsapp.config import ConfigWhatsapp
from cc_whatsapp.meta import ClienteMeta
from webhook_meta import handler as webhook
from webhook_meta.handler import api_version_efectiva, manejar, phone_number_id_efectivo

USUARIO = UsuarioActual(sub="sub-a", empresa_id=1, rol="RH", usuario_id=5)


async def escribir(secretos: ClienteSecretosFalso, cambios: dict[str, str]) -> None:
    almacen = AlmacenSecretsManager("cc/test/meta", "us-east-1", cliente=secretos)
    await integraciones.guardar(MotorFalso(), almacen, USUARIO, cambios, version_defecto="v21.0")


@pytest.fixture
def cfg():
    return ConfigWhatsapp(
        meta_secreto_id="cc/test/meta",
        cola_entrada_url="wa-entrada.fifo",
        cola_estados_url="wa-estados",
    )


@pytest.fixture(autouse=True)
def _cache_limpio():
    webhook._cache.update({"valor": None, "hasta": 0.0})
    yield
    webhook._cache.update({"valor": None, "hasta": 0.0})


class SqsFalso:
    def __init__(self):
        self.enviados = []

    def send_message(self, **kw):
        self.enviados.append(kw)


def evento_post(cuerpo: dict, app_secret: str) -> dict:
    crudo = json.dumps(cuerpo).encode()
    firma = "sha256=" + hmac.new(app_secret.encode(), crudo, hashlib.sha256).hexdigest()
    return {
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"X-Hub-Signature-256": firma},
        "body": crudo.decode(),
    }


def evento_get(token: str) -> dict:
    return {
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": {
            "hub.mode": "subscribe",
            "hub.verify_token": token,
            "hub.challenge": "4321",
        },
    }


def mensaje(phone_number_id: str) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "messages": [
                                {
                                    "id": "wamid.X1",
                                    "from": "5218112345678",
                                    "type": "text",
                                    "text": {"body": "Hola"},
                                    "timestamp": "1",
                                }
                            ],
                        },
                    }
                ]
            }
        ]
    }


@pytest.fixture
def sm_falso(monkeypatch):
    """``boto3.client`` devuelve el cliente en memoria (la Lambda importa boto3 al leer)."""
    cliente = ClienteSecretosFalso()
    monkeypatch.setattr(boto3, "client", lambda *_a, **_k: cliente)
    return cliente


async def test_el_json_escrito_lo_lee_el_webhook_para_firma_y_verificacion(sm_falso, cfg):
    await escribir(sm_falso, COMPLETO)
    secretos = webhook.secretos_meta(cfg)
    assert secretos["app_secret"] == APP_SECRET and secretos["phone_number_id"] == PHONE_NUMBER_ID

    sqs = SqsFalso()
    r = manejar(evento_get(VERIFY_TOKEN), sqs=sqs, secretos=secretos, cfg=cfg)
    assert (r["statusCode"], r["body"]) == (200, "4321")
    assert manejar(evento_get("otro"), sqs=sqs, secretos=secretos, cfg=cfg)["statusCode"] == 403

    ok = manejar(
        evento_post(mensaje(PHONE_NUMBER_ID), APP_SECRET), sqs=sqs, secretos=secretos, cfg=cfg
    )
    assert ok["statusCode"] == 200 and len(sqs.enviados) == 1
    mala = manejar(
        evento_post(mensaje(PHONE_NUMBER_ID), "f" * 32), sqs=sqs, secretos=secretos, cfg=cfg
    )
    assert mala["statusCode"] == 403 and len(sqs.enviados) == 1


async def test_los_lectores_de_plantillas_y_mensajes_leen_el_mismo_json(sm_falso, cfg):
    await escribir(sm_falso, {**COMPLETO, "api_version": "v22.0"})
    cred = await cargador_credenciales("cc/test/meta", "us-east-1", cliente=sm_falso)()
    assert (cred.access_token, cred.waba_id, cred.api_version) == (ACCESS_TOKEN, WABA_ID, "v22.0")

    secretos = webhook.secretos_meta(cfg)
    cliente = ClienteMeta(
        base=cfg.meta_api_base,
        version=api_version_efectiva(secretos, cfg),
        phone_number_id=phone_number_id_efectivo(secretos, cfg),
        token=secretos["access_token"],
    )
    assert cliente._url == f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    assert cliente._token == ACCESS_TOKEN


async def test_las_plantillas_sin_credenciales_guardadas_dan_sin_credenciales(sm_falso):
    from cc_notificaciones.meta import ErrorMeta

    cargador = cargador_credenciales("cc/test/meta", "us-east-1", cliente=sm_falso)
    for valor in (
        sm_falso.valor,
        "",
        "texto",
        "[]",
        json.dumps({"access_token": "", "waba_id": ""}),
    ):
        sm_falso.valor = valor
        with pytest.raises(ErrorMeta) as e:
            await cargador()
        assert e.value.motivo == "META_SIN_CREDENCIALES"


def test_cache_del_webhook_vence_a_los_5_minutos(sm_falso, cfg, monkeypatch):
    reloj = {"t": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: reloj["t"])
    sm_falso.valor = json.dumps({"app_secret": "a" * 32, "verify_token": "v" * 20})
    assert webhook.secretos_meta(cfg)["app_secret"] == "a" * 32
    lecturas = sm_falso.lecturas

    sm_falso.valor = json.dumps({"app_secret": "b" * 32, "verify_token": "v" * 20})  # rotación
    reloj["t"] += 299
    assert webhook.secretos_meta(cfg)["app_secret"] == "a" * 32  # aún en caché
    assert sm_falso.lecturas == lecturas
    reloj["t"] += 2  # 301 s
    assert webhook.secretos_meta(cfg)["app_secret"] == "b" * 32  # tomó el cambio
    assert sm_falso.lecturas == lecturas + 1


@pytest.mark.parametrize("valor", ["", "no es json", "[1]", "null"])
def test_el_webhook_tolera_un_secreto_que_no_es_un_objeto_json(sm_falso, cfg, valor):
    sm_falso.valor = valor
    assert webhook.secretos_meta(cfg) == {}


def test_precedencia_el_secreto_gana_y_la_variable_es_respaldo():
    cfg = ConfigWhatsapp(meta_phone_number_id="PN-ENV", meta_api_version="v20.0")
    assert phone_number_id_efectivo({"phone_number_id": "PN-SECRETO"}, cfg) == "PN-SECRETO"
    assert phone_number_id_efectivo({"phone_number_id": ""}, cfg) == "PN-ENV"  # valor inicial CDK
    assert phone_number_id_efectivo({}, cfg) == "PN-ENV"
    assert api_version_efectiva({"api_version": "v22.0"}, cfg) == "v22.0"
    assert api_version_efectiva({}, cfg) == "v20.0"
    assert phone_number_id_efectivo({}, ConfigWhatsapp()) == ""
    assert api_version_efectiva({}, ConfigWhatsapp()) == "v21.0"


def test_el_webhook_usa_el_phone_number_id_del_secreto_sobre_la_variable():
    cfg = ConfigWhatsapp(
        meta_phone_number_id="PN-ENV", cola_entrada_url="wa-entrada.fifo", cola_estados_url="e"
    )
    secretos = {"app_secret": APP_SECRET, "phone_number_id": "PN-SECRETO"}
    sqs = SqsFalso()
    manejar(evento_post(mensaje("PN-ENV"), APP_SECRET), sqs=sqs, secretos=secretos, cfg=cfg)
    assert sqs.enviados == []  # el número de la variable ya no es el nuestro
    manejar(evento_post(mensaje("PN-SECRETO"), APP_SECRET), sqs=sqs, secretos=secretos, cfg=cfg)
    assert len(sqs.enviados) == 1
    # Sin ``phone_number_id`` en el secreto (valor inicial de CDK) manda la variable de respaldo.
    sqs2 = SqsFalso()
    manejar(
        evento_post(mensaje("PN-ENV"), APP_SECRET),
        sqs=sqs2,
        secretos={"app_secret": APP_SECRET, "phone_number_id": ""},
        cfg=cfg,
    )
    assert len(sqs2.enviados) == 1


@pytest.mark.parametrize("secretos", [{}, {"app_secret": ""}, {"app_secret": None}])
def test_sin_app_secret_el_webhook_no_acepta_ni_una_firma_con_llave_vacia(secretos, cfg):
    sqs = SqsFalso()
    for llave in ("", "cualquiera"):
        r = manejar(evento_post(mensaje("PN"), llave), sqs=sqs, secretos=secretos, cfg=cfg)
        assert r["statusCode"] == 403
    assert sqs.enviados == []


@pytest.mark.parametrize("secretos", [{}, {"verify_token": ""}])
def test_sin_verify_token_nadie_se_suscribe(secretos, cfg):
    evento = {
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": {"hub.mode": "subscribe", "hub.challenge": "1"},
    }
    assert manejar(evento, sqs=SqsFalso(), secretos=secretos, cfg=cfg)["statusCode"] == 403
    evento["queryStringParameters"]["hub.verify_token"] = ""
    assert manejar(evento, sqs=SqsFalso(), secretos=secretos, cfg=cfg)["statusCode"] == 403


def test_un_token_no_ascii_en_la_verificacion_es_403_no_error(cfg):
    secretos = {"verify_token": VERIFY_TOKEN}
    r = manejar(evento_get("tókén-ñ"), sqs=SqsFalso(), secretos=secretos, cfg=cfg)
    assert r["statusCode"] == 403
