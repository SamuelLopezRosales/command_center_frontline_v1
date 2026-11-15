"""Simulador de Meta (design.md §7.5, DS-16): webhook firmado y API de mensajes.

Sustituye a Meta mientras no hay cuenta vinculada:

- **Webhook:** arma cuerpos como los de Meta (mensaje entrante, estados ``sent``, ``delivered``,
  ``read`` y ``failed``, cambio de plantilla) y los firma con HMAC-SHA256 como ``X-Hub-Signature-256``,
  dentro de un evento de API Gateway.
- **API de mensajes:** un ``httpx.MockTransport`` que responde como Graph API: acepta envíos con
  identificador ``wamid``, valida el token y simula errores (número no válido, ventana cerrada,
  límite de tasa, fallo 5xx). Guarda lo recibido en ``enviados``.

Corre dentro del proceso de prueba: no necesita puertos ni red.
"""

# ruff: noqa: S107
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx

ERROR_NUMERO_INVALIDO = (400, 131026)
ERROR_VENTANA = (400, 131047)
ERROR_TASA = (429, 130429)
ERROR_SERVIDOR = (503, 131000)


class SimuladorMeta:
    def __init__(
        self,
        *,
        app_secret: str = "secreto-de-la-app",
        verify_token: str = "token-de-verificacion",
        phone_number_id: str = "PN-PRUEBA",
        access_token: str = "token-de-acceso",
    ) -> None:
        self.app_secret = app_secret
        self.verify_token = verify_token
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.enviados: list[dict[str, Any]] = []
        self.por_destino: dict[str, tuple[int, int]] = {}  # destino -> error permanente
        self.siguientes: list[tuple[int, int]] = []  # errores de los próximos envíos
        self._n = 0

    # ------------------------------------------------------------------ secretos y eventos

    @property
    def secretos(self) -> dict[str, str]:
        return {
            "app_secret": self.app_secret,
            "verify_token": self.verify_token,
            "phone_number_id": self.phone_number_id,
            "access_token": self.access_token,
        }

    def firma(self, cuerpo: bytes, secreto: str | None = None) -> str:
        mac = hmac.new((secreto or self.app_secret).encode(), cuerpo, hashlib.sha256)
        return "sha256=" + mac.hexdigest()

    def evento_post(
        self, payload: dict[str, Any], *, firma_valida: bool = True, base64: bool = False
    ) -> dict[str, Any]:
        import base64 as b64

        cuerpo = json.dumps(payload).encode()
        firma = self.firma(cuerpo, None if firma_valida else "otro-secreto")
        return {
            "requestContext": {"http": {"method": "POST"}},
            "headers": {"X-Hub-Signature-256": firma, "content-type": "application/json"},
            "body": b64.b64encode(cuerpo).decode() if base64 else cuerpo.decode(),
            "isBase64Encoded": base64,
        }

    def evento_get(self, *, modo="subscribe", token=None, desafio="12345") -> dict[str, Any]:
        return {
            "requestContext": {"http": {"method": "GET"}},
            "queryStringParameters": {
                "hub.mode": modo,
                "hub.verify_token": token if token is not None else self.verify_token,
                "hub.challenge": desafio,
            },
        }

    # ------------------------------------------------------------------ cuerpos de Meta

    def _cambio(self, valor: dict[str, Any], phone_number_id: str | None) -> dict[str, Any]:
        valor = {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": phone_number_id or self.phone_number_id},
            **valor,
        }
        return {"entry": [{"id": "CUENTA", "changes": [{"field": "messages", "value": valor}]}]}

    def mensaje_entrante(
        self, wa_id: str, texto: str, *, wamid: str = "wamid.IN1", phone_number_id=None
    ) -> dict[str, Any]:
        mensaje = {
            "from": wa_id, "id": wamid, "timestamp": "1760000000", "type": "text",
            "text": {"body": texto},
        }  # fmt: skip
        return self._cambio({"messages": [mensaje]}, phone_number_id)

    def respuesta_interactiva(self, wa_id: str, opcion_id: str, *, wamid="wamid.IN2") -> dict:
        mensaje = {
            "from": wa_id, "id": wamid, "timestamp": "1760000001", "type": "interactive",
            "interactive": {"type": "list_reply", "list_reply": {"id": opcion_id, "title": "x"}},
        }  # fmt: skip
        return self._cambio({"messages": [mensaje]}, None)

    def estado(
        self,
        wamid: str,
        estado: str,
        destinatario: str = "5218112345678",
        *,
        error: int | None = None,
    ) -> dict[str, Any]:
        s: dict[str, Any] = {
            "id": wamid, "status": estado, "timestamp": "1760000002", "recipient_id": destinatario
        }  # fmt: skip
        if error is not None:
            s["errors"] = [{"code": error, "title": "error"}]
        return self._cambio({"statuses": [s]}, None)

    def cambio_de_plantilla(self, nombre: str, evento: str, motivo: str | None = None) -> dict:
        valor = {
            "event": evento,
            "message_template_name": nombre,
            "message_template_language": "es_MX",
        }
        if motivo:
            valor["reason"] = motivo
        return {
            "entry": [
                {"id": "CUENTA",
                 "changes": [{"field": "message_template_status_update", "value": valor}]}
            ]
        }  # fmt: skip

    def secuencia_de_estados(self, wamid: str, destinatario="5218112345678") -> list[dict]:
        return [self.estado(wamid, e, destinatario) for e in ("sent", "delivered", "read")]

    # ------------------------------------------------------------------ API de mensajes

    def _responder(self, peticion: httpx.Request) -> httpx.Response:
        if peticion.headers.get("authorization") != f"Bearer {self.access_token}":
            return httpx.Response(401, json={"error": {"code": 190, "message": "token"}})
        cuerpo = json.loads(peticion.content)
        if f"/{self.phone_number_id}/messages" not in peticion.url.path:
            return httpx.Response(404, json={"error": {"code": 100, "message": "ruta"}})
        error = self.siguientes.pop(0) if self.siguientes else self.por_destino.get(cuerpo["to"])
        if error:
            return httpx.Response(error[0], json={"error": {"code": error[1], "message": "sim"}})
        self._n += 1
        wamid = f"wamid.OUT{self._n}"
        self.enviados.append({**cuerpo, "wamid": wamid})
        return httpx.Response(200, json={"messages": [{"id": wamid}]})

    def cliente_http(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._responder))
