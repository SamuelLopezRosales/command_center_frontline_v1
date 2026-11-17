"""Simulador de Meta (design.md §7.5, DS-16): webhook firmado y API de mensajes.

Sustituye a Meta mientras no hay cuenta vinculada:

- **Webhook:** arma cuerpos como los de Meta (mensaje entrante, estados ``sent``, ``delivered``,
  ``read`` y ``failed``, cambio de plantilla) y los firma con HMAC-SHA256 como ``X-Hub-Signature-256``,
  dentro de un evento de API Gateway.
- **API de mensajes:** un ``httpx.MockTransport`` que responde como Graph API: acepta envíos con
  identificador ``wamid``, valida el token y simula errores (número no válido, ventana cerrada,
  límite de tasa, fallo 5xx). Guarda lo recibido en ``enviados``.
- **API de plantillas (T-216):** ``POST /{waba}/message_templates`` (crea en ``PENDING``),
  ``POST /{id}`` (edita), ``GET /{waba}/message_templates?name=`` (consulta). ``aprobar`` y
  ``rechazar`` cambian el estado en el simulador, como lo haría la revisión de Meta; el aviso por
  webhook se arma con ``cambio_de_plantilla``. Los errores de ``siguientes`` también aplican.
- **Consultas de conexión (integraciones/Meta):** ``GET /{v}/{phone_number_id}`` (nombre verificado,
  número y calidad), ``GET /{v}/{waba_id}`` (nombre) y ``GET /{v}/{waba_id}/subscribed_apps``
  (``apps_suscritas``). Un id desconocido responde el error 100 de Graph; ``fallos_consulta``
  fuerza un error por consulta (``"numero"``, ``"waba"``, ``"webhook"``): ``(estado, código)`` o
  ``"tiempo"`` para un tiempo agotado.

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
        waba_id: str = "WABA-PRUEBA",
    ) -> None:
        self.app_secret = app_secret
        self.verify_token = verify_token
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.waba_id = waba_id
        self.plantillas: dict[str, dict[str, Any]] = {}  # nombre -> plantilla
        self.enviados: list[dict[str, Any]] = []
        self.por_destino: dict[str, tuple[int, int]] = {}  # destino -> error permanente
        self.siguientes: list[tuple[int, int]] = []  # errores de los próximos envíos
        # Consultas de conexión (probar integración): datos del número y de la cuenta.
        self.nombre_verificado = "Empresa de Prueba"
        self.numero_mostrado = "+52 1 55 0000 0000"
        self.calidad = "GREEN"
        self.nombre_waba = "Cuenta de Prueba"
        self.apps_suscritas: list[dict[str, Any]] = [
            {"whatsapp_business_api_data": {"id": "APP-1", "name": "Command Center"}}
        ]
        self.fallos_consulta: dict[str, tuple[int, int] | str] = {}
        self.consultas: list[str] = []  # rutas consultadas, en orden
        self._n = 0

    # ------------------------------------------------------------------ secretos y eventos

    @property
    def secretos(self) -> dict[str, str]:
        return {
            "app_secret": self.app_secret,
            "verify_token": self.verify_token,
            "phone_number_id": self.phone_number_id,
            "access_token": self.access_token,
            "waba_id": self.waba_id,
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

    def aprobar(self, nombre: str) -> None:
        self.plantillas[nombre]["status"] = "APPROVED"
        self.plantillas[nombre]["rejected_reason"] = "NONE"

    def rechazar(self, nombre: str, motivo: str = "INVALID_FORMAT") -> None:
        self.plantillas[nombre]["status"] = "REJECTED"
        self.plantillas[nombre]["rejected_reason"] = motivo

    def _responder_plantillas(self, peticion: httpx.Request) -> httpx.Response:
        ruta = peticion.url.path
        if ruta.endswith(f"/{self.waba_id}/message_templates"):
            if peticion.method == "GET":
                nombre = peticion.url.params.get("name")
                datos = [p for p in self.plantillas.values() if nombre in (None, p["name"])]
                return httpx.Response(200, json={"data": datos})
            cuerpo = json.loads(peticion.content)
            if cuerpo.get("name") in self.plantillas:
                return httpx.Response(
                    400, json={"error": {"code": 100, "error_subcode": 2388024, "message": "dup"}}
                )
            cuerpo_texto = next(c for c in cuerpo["components"] if c["type"] == "BODY")
            self._n += 1
            self.plantillas[cuerpo["name"]] = {
                "id": f"TPL{self._n}",
                "name": cuerpo["name"],
                "language": cuerpo["language"],
                "category": cuerpo["category"],
                "status": "PENDING",
                "rejected_reason": "NONE",
                "texto": cuerpo_texto["text"],
                "ejemplo": cuerpo_texto.get("example"),
            }
            return httpx.Response(
                200,
                json={"id": f"TPL{self._n}", "status": "PENDING", "category": cuerpo["category"]},
            )
        existente = next(
            (p for p in self.plantillas.values() if ruta.endswith(f"/{p['id']}")), None
        )
        if existente is None:
            return httpx.Response(404, json={"error": {"code": 100, "message": "ruta"}})
        cuerpo = json.loads(peticion.content)
        existente["texto"] = next(c for c in cuerpo["components"] if c["type"] == "BODY")["text"]
        existente["status"] = "PENDING"  # la edición vuelve a revisión
        existente["rejected_reason"] = "NONE"
        return httpx.Response(200, json={"success": True})

    def _responder(self, peticion: httpx.Request) -> httpx.Response:
        if peticion.headers.get("authorization") != f"Bearer {self.access_token}":
            return httpx.Response(401, json={"error": {"code": 190, "message": "token"}})
        if "/message_templates" in peticion.url.path or (
            peticion.method == "POST" and "/messages" not in peticion.url.path
        ):
            if self.siguientes:
                error = self.siguientes.pop(0)
                return httpx.Response(
                    error[0], json={"error": {"code": error[1], "message": "sim"}}
                )
            return self._responder_plantillas(peticion)
        if peticion.method == "GET":
            return self._responder_consultas(peticion)
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

    def _responder_consultas(self, peticion: httpx.Request) -> httpx.Response:
        ruta = peticion.url.path.rstrip("/")
        self.consultas.append(ruta)
        partes = ruta.split("/")[2:]  # sin "" ni la versión
        if len(partes) == 1 and partes[0] == self.phone_number_id:
            clave = "numero"
        elif len(partes) == 1 and partes[0] == self.waba_id:
            clave = "waba"
        elif len(partes) == 2 and partes[0] == self.waba_id and partes[1] == "subscribed_apps":
            clave = "webhook"
        else:
            return httpx.Response(
                400, json={"error": {"code": 100, "message": "Unsupported get request"}}
            )
        fallo = self.fallos_consulta.get(clave)
        if fallo == "tiempo":
            raise httpx.ReadTimeout("simulado", request=peticion)
        if fallo:
            return httpx.Response(
                fallo[0], json={"error": {"code": fallo[1], "message": "simulado"}}
            )
        if clave == "numero":
            return httpx.Response(
                200,
                json={
                    "id": self.phone_number_id,
                    "display_phone_number": self.numero_mostrado,
                    "verified_name": self.nombre_verificado,
                    "quality_rating": self.calidad,
                },
            )
        if clave == "waba":
            return httpx.Response(200, json={"id": self.waba_id, "name": self.nombre_waba})
        return httpx.Response(200, json={"data": self.apps_suscritas})

    def cliente_http(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._responder))

    def transporte(self) -> httpx.MockTransport:
        """Para ``httpx.AsyncClient(transport=...)`` (cliente de plantillas de `notificaciones`)."""
        return httpx.MockTransport(self._responder)
