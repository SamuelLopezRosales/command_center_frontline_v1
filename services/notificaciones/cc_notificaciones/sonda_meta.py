"""Prueba de conexión con la Graph API de Meta (``POST /api/v1/integraciones/meta/probar``).

Hace tres consultas de solo lectura con las credenciales guardadas:

1. ``GET /{version}/{phone_number_id}?fields=display_phone_number,verified_name,quality_rating``:
   valida el token y el número.
2. ``GET /{version}/{waba_id}?fields=id,name``: valida el WABA ID.
3. ``GET /{version}/{waba_id}/subscribed_apps``: ¿hay una app suscrita a los eventos de la cuenta
   (el webhook)? Meta no dice si la app suscrita es *esta* (haría falta el id de la app); basta con
   que haya alguna.

Reglas de seguridad:

- El token viaja en el encabezado ``Authorization`` (jamás en la URL) y **no** se registra ni se
  devuelve. Los mensajes al usuario son fijos: nunca se copia el texto de error de Meta (podría
  repetir identificadores) ni la excepción de ``httpx``.
- El servidor es ``meta_api_base`` (configuración del despliegue); no lo elige quien llama.
- Un fallo de Meta (token, permisos, recurso inexistente, tasa, red) nunca es un 500: es un
  resultado con ``ok: false`` y un mensaje en español.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

CODIGOS_TOKEN = frozenset({190, 102, 463, 467})
CODIGOS_PERMISOS = frozenset({10, *range(200, 300)})
CODIGOS_NO_EXISTE = frozenset({100, 803})
CODIGOS_TASA = frozenset({4, 17, 32, 613, 80007, 130429})

CAT_ACCESO = "ACCESO"
PERMISOS = "PERMISOS"
NO_EXISTE = "NO_EXISTE"
TASA = "TASA"
TRANSITORIO = "TRANSITORIO"
TIEMPO = "TIEMPO"
RED = "RED"
OTRO = "OTRO"
# Con estos fallos no tiene sentido seguir consultando.
DETIENEN = frozenset({TASA, TRANSITORIO, TIEMPO, RED, OTRO})

MENSAJES = {
    CAT_ACCESO: (
        "Meta rechazó el token de acceso: no es válido o ya venció. Genere uno nuevo y guárdelo."
    ),
    PERMISOS: (
        "El token no tiene permisos suficientes. Debe incluir whatsapp_business_messaging y "
        "whatsapp_business_management, y el usuario del sistema debe tener asignada la cuenta "
        "de WhatsApp."
    ),
    TASA: "Meta limitó temporalmente las consultas. Espere unos minutos e intente de nuevo.",
    TRANSITORIO: "Meta no pudo responder en este momento. Intente de nuevo en unos minutos.",
    TIEMPO: "Meta no respondió a tiempo. Intente de nuevo en unos minutos.",
    RED: "No se pudo contactar a Meta desde el servidor. Intente de nuevo en unos minutos.",
}
NO_EXISTE_NUMERO = (
    "No se encontró el Phone Number ID, o el token no tiene acceso a ese número. Revise que sea el "
    "«Phone number ID» del panel de Meta y no el número de teléfono."
)
NO_EXISTE_WABA = (
    "No se encontró el WABA ID, o el token no tiene acceso a esa cuenta de WhatsApp Business."
)
NO_COMPROBADO_ACCESO = "No se pudo comprobar porque Meta rechazó el token."
NO_COMPROBADO_WABA = "No se pudo comprobar porque el WABA ID no es válido."


@dataclass(frozen=True)
class Resultado:
    clave: str  # token | numero | waba | webhook
    ok: bool
    detalle: str


@dataclass
class ResultadoPrueba:
    resultados: list[Resultado] = field(default_factory=list)
    numero: dict[str, str | None] | None = None
    webhook_suscrito: bool | None = None

    def ok_de(self, clave: str) -> bool:
        return any(r.clave == clave and r.ok for r in self.resultados)

    @property
    def ok(self) -> bool:
        """La conexión funciona: token, número y WABA. El webhook se informa aparte."""
        return all(self.ok_de(c) for c in ("token", "numero", "waba"))

    @property
    def fallidas(self) -> list[str]:
        return [r.clave for r in self.resultados if not r.ok]


def _cuerpo(r: httpx.Response) -> dict[str, Any]:
    try:
        datos = r.json()
    except ValueError:
        return {}
    return datos if isinstance(datos, dict) else {}


def clasificar(status: int, cuerpo: dict[str, Any]) -> str:
    """Categoría de un fallo de Meta por su código de error (primero) y por el estado HTTP."""
    error = cuerpo.get("error") if isinstance(cuerpo.get("error"), dict) else {}
    codigo = error.get("code")
    if isinstance(codigo, int):
        if codigo in CODIGOS_TOKEN:
            return CAT_ACCESO
        if codigo in CODIGOS_PERMISOS:
            return PERMISOS
        if codigo in CODIGOS_NO_EXISTE:
            return NO_EXISTE
        if codigo in CODIGOS_TASA:
            return TASA
    if status == 401:
        return CAT_ACCESO
    if status == 403:
        return PERMISOS
    if status == 404:
        return NO_EXISTE
    if status == 429:
        return TASA
    if status >= 500:
        return TRANSITORIO
    return OTRO


def _mensaje(categoria: str, status: int, recurso: str) -> str:
    if categoria == NO_EXISTE:
        return NO_EXISTE_NUMERO if recurso == "numero" else NO_EXISTE_WABA
    if categoria == OTRO:
        return f"Meta devolvió una respuesta inesperada (HTTP {status})."
    return MENSAJES[categoria]


class _Fallo(Exception):  # noqa: N818
    def __init__(self, categoria: str, status: int = 0) -> None:
        super().__init__(categoria)
        self.categoria = categoria
        self.status = status


async def _consultar(
    http: httpx.AsyncClient, url: str, token: str, params: dict[str, str] | None = None
) -> dict[str, Any]:
    try:
        r = await http.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
    except httpx.TimeoutException:
        raise _Fallo(TIEMPO) from None
    except httpx.HTTPError:
        raise _Fallo(RED) from None
    cuerpo = _cuerpo(r)
    if r.status_code != 200:
        raise _Fallo(clasificar(r.status_code, cuerpo), r.status_code)
    return cuerpo


def _texto(valor: Any) -> str | None:
    return valor.strip()[:200] if isinstance(valor, str) and valor.strip() else None


async def probar(
    *,
    base: str,
    version: str,
    phone_number_id: str,
    waba_id: str,
    access_token: str,
    timeout_s: float = 5.0,
    transporte: httpx.AsyncBaseTransport | None = None,
) -> ResultadoPrueba:
    raiz = f"{base.rstrip('/')}/{version}"
    salida = ResultadoPrueba()

    def agregar(clave: str, ok: bool, detalle: str) -> None:
        salida.resultados.append(Resultado(clave, ok, detalle))

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=min(timeout_s, 4.0)),
        transport=transporte,
        follow_redirects=False,
    ) as http:
        # (a) token y número
        try:
            d = await _consultar(
                http,
                f"{raiz}/{phone_number_id}",
                access_token,
                {"fields": "display_phone_number,verified_name,quality_rating"},
            )
            salida.numero = {
                "nombre_verificado": _texto(d.get("verified_name")),
                "numero_mostrado": _texto(d.get("display_phone_number")),
                "calidad": _texto(d.get("quality_rating")),
            }
            agregar("token", True, "Meta aceptó el token de acceso.")
            visible = salida.numero["numero_mostrado"] or "sin número visible"
            agregar("numero", True, f"Número encontrado: {visible}.")
        except _Fallo as f:
            if f.categoria == CAT_ACCESO:
                agregar("token", False, _mensaje(CAT_ACCESO, f.status, "token"))
                for clave in ("numero", "waba", "webhook"):
                    agregar(clave, False, NO_COMPROBADO_ACCESO)
                return salida
            if f.categoria in DETIENEN:
                for clave in ("token", "numero", "waba", "webhook"):
                    agregar(clave, False, _mensaje(f.categoria, f.status, ""))
                return salida
            if f.categoria == PERMISOS:
                agregar("token", False, _mensaje(PERMISOS, f.status, "token"))
                agregar("numero", False, "No se pudo comprobar el número: faltan permisos.")
            else:  # NO_EXISTE: Meta aceptó el token pero no encuentra el número
                agregar("token", True, "Meta aceptó el token de acceso.")
                agregar("numero", False, _mensaje(NO_EXISTE, f.status, "numero"))

        # (b) WABA
        try:
            d = await _consultar(http, f"{raiz}/{waba_id}", access_token, {"fields": "id,name"})
            nombre = _texto(d.get("name"))
            agregar(
                "waba",
                True,
                f"Cuenta de WhatsApp Business encontrada: {nombre}."
                if nombre
                else "Cuenta de WhatsApp Business encontrada.",
            )
        except _Fallo as f:
            detalle = _mensaje(f.categoria, f.status, "waba")
            agregar("waba", False, detalle)
            agregar(
                "webhook",
                False,
                detalle if f.categoria in DETIENEN else NO_COMPROBADO_WABA,
            )
            return salida

        # (c) suscripción de la app al webhook de la cuenta
        try:
            d = await _consultar(http, f"{raiz}/{waba_id}/subscribed_apps", access_token)
        except _Fallo as f:
            agregar("webhook", False, _mensaje(f.categoria, f.status, "waba"))
            return salida
        apps = d.get("data")
        salida.webhook_suscrito = isinstance(apps, list) and len(apps) > 0
        if salida.webhook_suscrito:
            agregar("webhook", True, "La app está suscrita a los eventos de la cuenta.")
        else:
            agregar(
                "webhook",
                False,
                "Ninguna app está suscrita a la cuenta todavía. Registre el webhook y suscriba la "
                "app en el panel de Meta (consulte la guía) y vuelva a probar.",
            )
    return salida
