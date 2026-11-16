"""Envío del correo de respaldo por SES (design.md §6.4; DS-10).

``CorreoSes`` usa la API v1 de SES (``send_email``) con texto plano, la dirección de origen
verificada y, si se configura, el conjunto de configuración cuyos eventos de rebote y queja van al
tema de SNS. Cada correo lleva las etiquetas ``notificacion_id``, ``destinatario_id`` y
``empresa_id`` (identificadores, nunca datos personales) para poder asociar un rebote con su
destinatario.

Errores: ``CorreoRechazado`` es permanente para ese destinatario (dirección rechazada o no válida;
queda FALLIDO). Cualquier otro (límite de envío, servicio caído, identidad de origen sin verificar
-- un ``MessageRejected`` que nombra al origen --, conjunto de configuración inexistente)
es ``CorreoTransitorio``: el mensaje se reintenta y, si persiste, llega a la DLQ con alarma,
sin marcar destinatarios como fallidos por un problema
nuestro.
"""

from __future__ import annotations

from typing import Any, Protocol

PERMANENTES = frozenset({"MessageRejected", "InvalidParameterValue"})


class CorreoRechazado(Exception):  # noqa: N818
    """SES rechazó este correo de forma permanente."""


class CorreoTransitorio(Exception):  # noqa: N818
    """Error reintentable (o del lado de la configuración): no se marca al destinatario."""


class EnviarCorreo(Protocol):
    def enviar(
        self, *, destino: str, asunto: str, texto: str, etiquetas: dict[str, str]
    ) -> str: ...


class CorreoSes:
    def __init__(self, cliente: Any, origen: str, config_set: str | None = None) -> None:
        self._c = cliente
        self._origen = origen
        self._config_set = config_set

    def enviar(self, *, destino: str, asunto: str, texto: str, etiquetas: dict[str, str]) -> str:
        params: dict[str, Any] = {
            "Source": self._origen,
            "Destination": {"ToAddresses": [destino]},
            "Message": {
                "Subject": {"Data": asunto, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": texto, "Charset": "UTF-8"}},
            },
            "Tags": [{"Name": k, "Value": str(v)} for k, v in etiquetas.items()],
        }
        if self._config_set:
            params["ConfigurationSetName"] = self._config_set
        try:
            return self._c.send_email(**params)["MessageId"]
        except Exception as exc:
            error = getattr(exc, "response", {}).get("Error", {})
            codigo = error.get("Code")
            # "Email address (is) not verified <identidades>": si nombra nuestro origen, el
            # problema es de configuración (transitorio), no del destinatario.
            if codigo == "MessageRejected" and self._origen in (error.get("Message") or ""):
                raise CorreoTransitorio("ORIGEN_NO_VERIFICADO") from exc
            if codigo in PERMANENTES:
                raise CorreoRechazado(codigo) from exc
            raise CorreoTransitorio(codigo or type(exc).__name__) from exc
