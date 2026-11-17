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

- **Listado de plantillas (importar aprobadas):** ``GET /{waba}/message_templates`` con ``fields``
  que incluya ``components`` responde como Graph (``id``, ``name``, ``language``, ``category``,
  ``status``, ``components``, ``parameter_format``), filtra por ``name`` y ``language``, y **pagina**
  con ``limit`` y ``after`` (``paging.cursors.after`` y ``paging.next`` solo si hay más). El catálogo
  es ``catalogo_meta`` (``cargar_catalogo_ejemplo`` lo llena con una plantilla de bienvenida
  compatible y otras con botones, encabezado, variables mezcladas, rechazada y pausada, más las siete
  plantillas reales de la cuenta compartida: ``hello_world`` en ``en_US``, ``vida_*`` con variables
  con nombre, botones de respuesta rápida, un encabezado de imagen y tres en inglés) más las
  creadas por ``POST``. ``listados`` guarda los parámetros de cada consulta. La consulta de
  sincronización (con ``name`` y sin ``components``) no cambia.

- **Variables con nombre (``parameter_format`` ``NAMED``):** el catálogo de ejemplo trae plantillas
  nombradas (``vida_*``) y una que mezcla formatos (incompatible). Los **envíos** de una plantilla que el simulador conoce se
  validan como Meta: una plantilla nombrada exige ``parameter_name`` en **todos** los parámetros y
  con los nombres exactos; una posicional no admite ``parameter_name``; si el formato no coincide
  responde 400 con el código ``132012`` y si el número de parámetros no coincide, ``132000``. Una
  plantilla que el simulador no conoce se acepta como siempre. Si el nombre existe pero no en el
  idioma recibido (``language.code``), responde 400 con el código ``132001`` (la plantilla no
  existe en esa traducción). ``rechazados`` guarda los cuerpos
  rechazados por esa validación.

Corre dentro del proceso de prueba: no necesita puertos ni red.
"""

# ruff: noqa: S107
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx
from cc_common import plantillas_meta as pm

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
        # Plantillas "ya existentes" en la cuenta, en el formato de Graph (listado de plantillas).
        self.catalogo_meta: list[dict[str, Any]] = []
        self.listados: list[dict[str, str]] = []  # parámetros de cada listado, en orden
        self.rechazados: list[dict[str, Any]] = []  # envíos de plantilla rechazados por formato
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

    def agregar_catalogo(
        self,
        nombre: str,
        *,
        id_: str | None = None,
        idioma: str = "es_MX",
        categoria: str = "UTILITY",
        estado: str = "APPROVED",
        cuerpo: str | None = "Hola {{1}}, bienvenido a {{2}}.",
        ejemplo: list[str] | None = None,
        componentes: list[dict[str, Any]] | None = None,
        formato: str | None = "POSITIONAL",
        ejemplo_nombrado: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Agrega al catálogo una plantilla como la devuelve Graph. ``componentes`` se suma al
        ``BODY`` (``cuerpo`` en ``None`` lo omite)."""
        self._n += 1
        todos: list[dict[str, Any]] = []
        if cuerpo is not None:
            c: dict[str, Any] = {"type": "BODY", "text": cuerpo}
            if ejemplo:
                c["example"] = {"body_text": [ejemplo]}
            if ejemplo_nombrado:
                c["example"] = {
                    "body_text_named_params": [
                        {"param_name": n, "example": e} for n, e in ejemplo_nombrado.items()
                    ]
                }
            todos.append(c)
        todos.extend(componentes or [])
        p: dict[str, Any] = {
            "id": id_ or f"CAT{self._n}", "name": nombre, "language": idioma,
            "category": categoria, "status": estado, "components": todos,
        }  # fmt: skip
        if formato:
            p["parameter_format"] = formato
        self.catalogo_meta.append(p)
        return p

    def cargar_catalogo_ejemplo(self) -> None:
        """Una compatible (con pie de página), una por cada motivo típico de no compatibilidad y las
        siete plantillas reales de la cuenta compartida (``hello_world``, ``vida_*``)."""
        self.agregar_catalogo(
            "bienvenida_colaborador", id_="800000000000001",
            cuerpo="Hola {{1}}, te damos la bienvenida a {{2}}. Tu primer día es el {{3}}.",
            ejemplo=["Ana", "Planta Apodaca", "lunes"],
            componentes=[{"type": "FOOTER", "text": "Recursos Humanos"}],
        )  # fmt: skip
        self.agregar_catalogo(
            "bienvenida_con_boton", id_="800000000000002", cuerpo="Bienvenido {{1}}.",
            ejemplo=["Ana"],
            componentes=[{"type": "BUTTONS", "buttons": [
                {"type": "URL", "text": "Guía", "url": "https://empresa.mx/guia/{{1}}",
                 "example": ["https://empresa.mx/guia/x"]},
            ]}],
        )  # fmt: skip
        self.agregar_catalogo(
            "bienvenida_con_imagen", id_="800000000000003", categoria="MARKETING",
            cuerpo="Bienvenido a la familia.",
            componentes=[{"type": "HEADER", "format": "IMAGE"}],
        )  # fmt: skip
        self.agregar_catalogo(
            "bienvenida_mezclada", id_="800000000000004", cuerpo="Hola {{1}}, {{nombre}}.",
            formato="NAMED",
        )  # fmt: skip
        self.agregar_catalogo(
            "bienvenida_rechazada", id_="800000000000005", categoria="MARKETING",
            estado="REJECTED", cuerpo="Hola {{1}}.", ejemplo=["Ana"],
        )  # fmt: skip
        self.agregar_catalogo(
            "bienvenida_pausada", id_="800000000000006", estado="PAUSED",
            cuerpo="Hola {{1}}.", ejemplo=["Ana"],
        )  # fmt: skip
        # Las plantillas reales de la cuenta compartida (con variables con nombre).
        self.agregar_catalogo(
            "hello_world", id_="800000000000007", idioma="en_US", formato=None,
            cuerpo="Welcome and congratulations!! This message demonstrates your ability to send "
            "a WhatsApp message notification from the Cloud API.",
            componentes=[{"type": "FOOTER", "text": "WhatsApp Business Platform sample message"}],
        )  # fmt: skip
        self.agregar_catalogo(
            "vida_aviso_checkout", id_="800000000000008", formato="NAMED",
            cuerpo="Hola {{guest_name}}, tu salida es hoy a las {{checkout_time}}. Gracias por "
            "tu estancia.",
            ejemplo_nombrado={"guest_name": "Juan", "checkout_time": "12:00"},
            componentes=[
                {"type": "BUTTONS", "buttons": [
                    {"type": "QUICK_REPLY", "text": "Sí"},
                    {"type": "QUICK_REPLY", "text": "No"},
                ]},
            ],
        )  # fmt: skip
        self.agregar_catalogo(
            "vida_bienvenida_llegada", id_="800000000000009", formato="NAMED",
            cuerpo="Bienvenido {{guest_name}}. Tu habitación está en la torre {{tower}}.",
            ejemplo_nombrado={"guest_name": "Juan", "tower": "A"},
            componentes=[
                {"type": "BUTTONS", "buttons": [
                    {"type": "QUICK_REPLY", "text": "Gracias"},
                    {"type": "QUICK_REPLY", "text": "Necesito ayuda"},
                ]},
            ],
        )  # fmt: skip
        self.agregar_catalogo(
            "vida_recordatorio_prellegada", id_="800000000000010", formato="NAMED",
            cuerpo="Hola {{guest_name}}, te esperamos el {{arrival_date}}. El registro es a las "
            "{{checkin_time}}.",
            ejemplo_nombrado={
                "guest_name": "Juan", "arrival_date": "lunes", "checkin_time": "15:00",
            },
            componentes=[
                {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["h"]}},
            ],
        )  # fmt: skip
        self.agregar_catalogo(
            "vida_checkout_notice", id_="800000000000011", idioma="en", formato="NAMED",
            cuerpo="Hello {{guest_name}}, your checkout is today at {{checkout_time}}.",
            ejemplo_nombrado={"guest_name": "John", "checkout_time": "12:00"},
        )  # fmt: skip
        self.agregar_catalogo(
            "vida_prearrival_reminder", id_="800000000000012", idioma="en", formato="NAMED",
            cuerpo="Hello {{guest_name}}, we look forward to seeing you on {{arrival_date}}.",
            ejemplo_nombrado={"guest_name": "John", "arrival_date": "Monday"},
        )  # fmt: skip
        self.agregar_catalogo(
            "vida_welcome_greeting", id_="800000000000013", idioma="en", formato="NAMED",
            cuerpo="Welcome {{guest_name}}! Your room is in tower {{tower}}.",
            ejemplo_nombrado={"guest_name": "John", "tower": "A"},
        )  # fmt: skip

    def _catalogo_completo(self) -> list[dict[str, Any]]:
        """El catálogo más lo creado por ``POST`` (en formato de Graph)."""
        creadas = []
        for p in self.plantillas.values():
            cuerpo: dict[str, Any] = {"type": "BODY", "text": p["texto"]}
            if p.get("ejemplo"):
                cuerpo["example"] = p["ejemplo"]
            creadas.append(
                {
                    "id": p["id"],
                    "name": p["name"],
                    "language": p["language"],
                    "category": p["category"],
                    "status": p["status"],
                    "components": [cuerpo],
                    "parameter_format": p.get("parameter_format", "POSITIONAL"),
                }  # fmt: skip
            )
        return [*self.catalogo_meta, *creadas]

    def _listar_catalogo(self, peticion: httpx.Request) -> httpx.Response:
        params = dict(peticion.url.params)
        self.listados.append(params)
        datos = [
            p
            for p in self._catalogo_completo()
            if params.get("name") in (None, p["name"])
            and params.get("language") in (None, p["language"])
        ]
        limite = max(1, int(params.get("limit", "25")))
        inicio = int(params.get("after", "0"))
        pagina = datos[inicio : inicio + limite]
        cuerpo: dict[str, Any] = {"data": pagina}
        if pagina:
            cursores = {"before": str(inicio), "after": str(inicio + len(pagina))}
            cuerpo["paging"] = {"cursors": cursores}
            if inicio + limite < len(datos):  # como Graph: ``next`` solo si hay más
                cuerpo["paging"]["next"] = (
                    f"https://graph.facebook.com/v21.0/{self.waba_id}/message_templates"
                    f"?limit={limite}&after={cursores['after']}"
                )
        return httpx.Response(200, json=cuerpo)

    def rechazar(self, nombre: str, motivo: str = "INVALID_FORMAT") -> None:
        self.plantillas[nombre]["status"] = "REJECTED"
        self.plantillas[nombre]["rejected_reason"] = motivo

    def _responder_plantillas(self, peticion: httpx.Request) -> httpx.Response:
        ruta = peticion.url.path
        if ruta.endswith(f"/{self.waba_id}/message_templates"):
            if peticion.method == "GET":
                if "components" in peticion.url.params.get("fields", ""):
                    return self._listar_catalogo(peticion)
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
                "parameter_format": cuerpo.get("parameter_format", "POSITIONAL"),
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
        rechazo = self._validar_plantilla(cuerpo)
        if rechazo:
            self.rechazados.append(cuerpo)
            return rechazo
        self._n += 1
        wamid = f"wamid.OUT{self._n}"
        self.enviados.append({**cuerpo, "wamid": wamid})
        return httpx.Response(200, json={"messages": [{"id": wamid}]})

    def _plantilla_conocida(self, nombre: str, idioma: str) -> tuple[bool, list[str]] | None:
        """``(nombrada, variables)`` de una plantilla que el simulador conoce (catálogo o creada
        por ``POST``); ``None`` si no la conoce."""
        for p in self._catalogo_completo():
            if p["name"] == nombre and p["language"] == idioma:
                texto = next((c.get("text") for c in p["components"] if c["type"] == "BODY"), "")
                try:
                    v = pm.analizar(texto or "", maximo=10_000)
                except pm.ErrorVariables:
                    return None
                nombrada = p.get("parameter_format") == "NAMED" and v.nombrado
                return nombrada, list(v.nombres)
        return None

    @staticmethod
    def _error_plantilla(codigo: int, detalle: str) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": f"(#{codigo}) {detalle}",
                    "type": "OAuthException",
                    "code": codigo,
                    "error_data": {"messaging_product": "whatsapp", "details": detalle},
                }
            },
        )

    def _validar_plantilla(self, cuerpo: dict[str, Any]) -> httpx.Response | None:
        """Como Meta: el formato de los parámetros debe ser el de la plantilla (132012) y el
        número de parámetros, el de sus variables (132000)."""
        if cuerpo.get("type") != "template":
            return None
        t = cuerpo["template"]
        todas = self._catalogo_completo()
        if any(p["name"] == t["name"] for p in todas) and not any(
            p["name"] == t["name"] and p["language"] == t["language"]["code"] for p in todas
        ):
            return self._error_plantilla(132001, "Template name does not exist in the translation")
        conocida = self._plantilla_conocida(t["name"], t["language"]["code"])
        if conocida is None:
            return None
        nombrada, variables = conocida
        parametros: list[dict[str, Any]] = []
        for c in t.get("components") or []:
            if c.get("type") == "body":
                parametros = list(c.get("parameters") or [])
        con_nombre = [p for p in parametros if "parameter_name" in p]
        if parametros and (
            len(con_nombre) not in (0, len(parametros)) or bool(con_nombre) != nombrada
        ):
            esperado = "NAMED" if nombrada else "POSITIONAL"
            return self._error_plantilla(
                132012,
                "Parameter format does not match format in the created template "
                f"(expected {esperado})",
            )
        cantidad = "Number of parameters does not match the expected number of params"
        if len(parametros) != len(variables):
            return self._error_plantilla(132000, cantidad)
        if nombrada and {p["parameter_name"] for p in parametros} != set(variables):
            return self._error_plantilla(
                132012, "Parameter name does not match the names in the created template"
            )
        if any(not str(p.get("text", "")).strip() for p in parametros):
            return self._error_plantilla(132000, cantidad)
        return None

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
