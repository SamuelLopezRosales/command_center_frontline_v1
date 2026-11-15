"""Configuración del servicio campos (variables ``CC_*``)."""

from __future__ import annotations

from functools import lru_cache

from cc_common.config import Configuracion


class ConfigCampos(Configuracion):
    servicio: str = "campos"
    cognito_emisor: str = "https://cognito-idp.us-east-1.amazonaws.com/local"
    cognito_client_id: str = "local"
    # Servicios a los que `campos` consulta (INT-COL-10 e INT-CON-06). Sin URL, solo en local se
    # usan sustitutos que dicen "sin valores" y "sin plantillas".
    colaboradores_url: str | None = None
    constancias_url: str | None = None
    # Bus de EventBridge donde el relay publica ``campo.actualizado``.
    bus_eventos: str = "cc-local-eventos"


@lru_cache(maxsize=1)
def obtener() -> ConfigCampos:
    return ConfigCampos()
