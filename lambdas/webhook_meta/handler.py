"""``webhook-meta`` (LAM-01; design.md §4.2; CC-REQ-158, 162).

``GET`` verifica la suscripción con ``hub.verify_token``. ``POST`` valida ``X-Hub-Signature-256``
(HMAC-SHA256 del cuerpo crudo, en tiempo constante) y encola cada mensaje en ``wa-entrada.fifo`` y
cada estado en ``wa-estados``. Responde rápido y sin acceso a la base. **Nunca** registra el cuerpo
ni números.

Códigos: 200 firma válida (también si el ``phone_number_id`` no es el nuestro: se ignora), 403 firma
inválida (no encola), 500 si falla SQS (Meta reintenta; la deduplicación por ``wamid`` evita
duplicados).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any

from cc_whatsapp.metricas import metrica
from cc_whatsapp.normalizacion import grupo_de

log = logging.getLogger("webhook_meta")

_CACHE_SEGUNDOS = 300
_cache: dict[str, Any] = {"valor": None, "hasta": 0.0}


def secretos_meta(cfg) -> dict[str, str]:
    """Secreto ``cc/{env}/meta`` con caché de 5 minutos (tolera la rotación)."""
    if _cache["valor"] is None or time.monotonic() > _cache["hasta"]:
        import boto3

        r = boto3.client("secretsmanager").get_secret_value(SecretId=cfg.meta_secreto_id)
        _cache["valor"] = json.loads(r["SecretString"])
        _cache["hasta"] = time.monotonic() + _CACHE_SEGUNDOS
    return _cache["valor"]


def _respuesta(status: int, cuerpo: str = "") -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "text/plain"},
        "body": cuerpo,
    }


def _firma_valida(cuerpo: bytes, cabecera: str | None, app_secret: str) -> bool:
    if not cabecera or not cabecera.startswith("sha256="):
        return False
    esperada = hmac.new(app_secret.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, cabecera.removeprefix("sha256="))


def _cabecera(evento: dict[str, Any], nombre: str) -> str | None:
    for k, v in (evento.get("headers") or {}).items():
        if k.lower() == nombre:
            return v
    return None


def _mensaje_entrante(m: dict[str, Any], phone_number_id: str) -> dict[str, Any]:
    tipo = m.get("type", "desconocido")
    texto = (m.get("text") or {}).get("body") if tipo == "text" else None
    interactivo = None
    if tipo == "interactive":
        i = m.get("interactive") or {}
        interactivo = (i.get("button_reply") or i.get("list_reply") or {}).get("id")
    elif tipo == "button":
        interactivo = (m.get("button") or {}).get("payload")
    return {
        "wamid": m["id"],
        "wa_id": m["from"],
        "tipo": tipo,
        "texto": texto,
        "interactivo_id": interactivo,
        "timestamp": m.get("timestamp"),
        "phone_number_id": phone_number_id,
    }


def _estado_mensaje(s: dict[str, Any]) -> dict[str, Any]:
    errores = s.get("errors") or [{}]
    codigo = errores[0].get("code")
    return {
        "clase": "mensaje",
        "id": s["id"],
        "estado": s.get("status"),
        "timestamp": s.get("timestamp"),
        "error_codigo": str(codigo) if codigo is not None else None,
    }


def _estado_plantilla(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "clase": "plantilla",
        "nombre": v.get("message_template_name"),
        "idioma": v.get("message_template_language"),
        "evento": v.get("event"),
        "motivo": v.get("reason"),
    }


def extraer(cuerpo: dict[str, Any], phone_number_id: str) -> tuple[list[dict], list[dict], int]:
    """``(entrantes, estados, ignorados)`` del cuerpo de Meta."""
    entrantes: list[dict] = []
    estados: list[dict] = []
    ignorados = 0
    for entrada in cuerpo.get("entry", []):
        for cambio in entrada.get("changes", []):
            valor = cambio.get("value") or {}
            if cambio.get("field") == "message_template_status_update":
                estados.append(_estado_plantilla(valor))
                continue
            if (valor.get("metadata") or {}).get("phone_number_id") != phone_number_id:
                ignorados += 1
                continue
            entrantes += [_mensaje_entrante(m, phone_number_id) for m in valor.get("messages", [])]
            estados += [_estado_mensaje(s) for s in valor.get("statuses", [])]
    return entrantes, estados, ignorados


def manejar(evento: dict[str, Any], *, sqs, secretos: dict[str, str], cfg) -> dict[str, Any]:
    http = evento.get("requestContext", {}).get("http", {})
    metodo = (http.get("method") or evento.get("httpMethod") or "").upper()
    if metodo == "GET":
        q = evento.get("queryStringParameters") or {}
        if q.get("hub.mode") == "subscribe" and hmac.compare_digest(
            q.get("hub.verify_token", ""), secretos["verify_token"]
        ):
            return _respuesta(200, q.get("hub.challenge", ""))
        return _respuesta(403)
    if metodo != "POST":
        return _respuesta(405)

    crudo = evento.get("body") or ""
    cuerpo_bytes = base64.b64decode(crudo) if evento.get("isBase64Encoded") else crudo.encode()
    if not _firma_valida(
        cuerpo_bytes, _cabecera(evento, "x-hub-signature-256"), secretos["app_secret"]
    ):
        metrica("webhook_firma_invalida")
        return _respuesta(403)
    try:
        cuerpo = json.loads(cuerpo_bytes)
    except ValueError:
        return _respuesta(400)

    phone_number_id = cfg.meta_phone_number_id or secretos.get("phone_number_id", "")
    entrantes, estados, ignorados = extraer(cuerpo, phone_number_id)
    if ignorados:
        metrica("webhook_phone_number_id_ignorado", ignorados)
    try:
        for m in entrantes:
            sqs.send_message(
                QueueUrl=cfg.cola_entrada_url,
                MessageBody=json.dumps(m),
                MessageGroupId=grupo_de(m["wa_id"]),
                MessageDeduplicationId=m["wamid"],
            )
        for s in estados:
            sqs.send_message(QueueUrl=cfg.cola_estados_url, MessageBody=json.dumps(s))
    except Exception:
        metrica("webhook_error_sqs")
        log.error("falló el encolado")  # sin cuerpo ni números
        return _respuesta(500)
    if entrantes or estados:
        metrica("webhook_mensajes_encolados", len(entrantes) + len(estados))
    return _respuesta(200)


def lambda_handler(evento, _contexto):  # pragma: no cover - requiere AWS
    import boto3
    from cc_whatsapp.config import ConfigWhatsapp

    cfg = ConfigWhatsapp()
    sqs = boto3.client("sqs", region_name=cfg.region, endpoint_url=cfg.aws_endpoint or None)
    return manejar(evento, sqs=sqs, secretos=secretos_meta(cfg), cfg=cfg)
