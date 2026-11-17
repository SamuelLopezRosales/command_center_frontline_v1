"""Cliente de la API de mensajes de Meta (design.md §4.3, §7.5).

Clasifica los errores en **permanentes** (no se reintentan: número no válido, plantilla inexistente,
ventana cerrada) y **transitorios** (límite de tasa, 5xx, tiempo agotado). Los códigos concretos se
confirman contra la documentación al vincular la cuenta (PQ-07); aquí viven en una tabla para
corregirlos en un solo lugar.
"""

from __future__ import annotations

from typing import Any

import httpx

# Código de Meta -> motivo propio (lo que se guarda en ``error_codigo`` y viaja en el evento).
PERMANENTES: dict[str, str] = {
    "131026": "NUMERO_INVALIDO",
    "131021": "NUMERO_INVALIDO",
    "131030": "NUMERO_NO_PERMITIDO",
    "131047": "VENTANA_CERRADA",
    "132001": "PLANTILLA_INEXISTENTE",
    "132000": "PLANTILLA_PARAMETROS",
    "132012": "PLANTILLA_PARAMETROS",
    "132015": "PLANTILLA_PAUSADA",
    "132016": "PLANTILLA_DESHABILITADA",
    "100": "PARAMETRO_INVALIDO",
}
TRANSITORIOS = {"130429", "131056", "131000", "131016", "80007", "4", "17", "32", "613"}
NUMERO_INVALIDO = {"131026", "131021"}


class ErrorMeta(Exception):  # noqa: N818
    def __init__(self, motivo: str, *, permanente: bool, codigo: str | None = None):
        super().__init__(motivo)
        self.motivo = motivo
        self.permanente = permanente
        self.codigo = codigo

    @property
    def numero_invalido(self) -> bool:
        return self.codigo in NUMERO_INVALIDO


def clasificar(status: int, cuerpo: Any) -> ErrorMeta:
    error = cuerpo.get("error", {}) if isinstance(cuerpo, dict) else {}
    codigo = str(error.get("code")) if error.get("code") is not None else None
    if codigo in PERMANENTES:
        return ErrorMeta(PERMANENTES[codigo], permanente=True, codigo=codigo)
    if status == 429 or status >= 500 or codigo in TRANSITORIOS:
        return ErrorMeta("META_TRANSITORIO", permanente=False, codigo=codigo)
    return ErrorMeta(f"META_{codigo or status}", permanente=True, codigo=codigo)


class ClienteMeta:
    def __init__(
        self,
        *,
        base: str,
        version: str,
        phone_number_id: str,
        token: str,
        timeout_s: float = 10.0,
        cliente: httpx.Client | None = None,
    ) -> None:
        self._url = f"{base.rstrip('/')}/{version}/{phone_number_id}/messages"
        self._token = token
        self._http = cliente or httpx.Client(timeout=timeout_s)

    def _enviar(self, cuerpo: dict[str, Any]) -> str:
        try:
            r = self._http.post(
                self._url,
                json={"messaging_product": "whatsapp", **cuerpo},
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.HTTPError as exc:  # tiempo agotado, conexión
            raise ErrorMeta("META_TRANSITORIO", permanente=False) from exc
        try:
            datos = r.json()
        except ValueError:
            datos = {}
        if r.status_code != 200:
            raise clasificar(r.status_code, datos)
        try:
            return str(datos["messages"][0]["id"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ErrorMeta("META_RESPUESTA_INVALIDA", permanente=False) from exc

    def enviar_texto(self, destino: str, texto: str) -> str:
        return self._enviar(
            {"to": destino, "type": "text", "text": {"body": texto, "preview_url": False}}
        )

    def enviar_interactivo(self, destino: str, interactivo: dict[str, Any]) -> str:
        """Lista o botones (``interactive``); solo dentro de la ventana de 24 horas."""
        return self._enviar({"to": destino, "type": "interactive", "interactive": interactivo})

    def enviar_plantilla(
        self,
        destino: str,
        nombre: str,
        idioma: str,
        variables: list[str] | None = None,
        variables_nombres: list[str] | None = None,
    ) -> str:
        """Envía una plantilla. Posicional: ``parameters`` solo con ``text``. Con nombre
        (``variables_nombres``, paralela a ``variables``): cada parámetro lleva ``parameter_name``
        (Meta exige enviarlos **todos** y rechaza mezclar formatos, 132000 o 132012)."""
        plantilla: dict[str, Any] = {"name": nombre, "language": {"code": idioma}}
        if variables:
            if variables_nombres is not None:
                if len(variables_nombres) != len(variables):
                    raise ErrorMeta("PLANTILLA_PARAMETROS", permanente=True, codigo="132000")
                parametros = [
                    {"type": "text", "parameter_name": n, "text": v}
                    for n, v in zip(variables_nombres, variables, strict=True)
                ]
            else:
                parametros = [{"type": "text", "text": v} for v in variables]
            plantilla["components"] = [{"type": "body", "parameters": parametros}]
        return self._enviar({"to": destino, "type": "template", "template": plantilla})
