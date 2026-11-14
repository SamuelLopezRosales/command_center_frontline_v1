"""Configuración del servicio dashboard (variables ``CC_*``)."""

from __future__ import annotations

from functools import lru_cache

from cc_common.config import Configuracion


class ConfigDashboard(Configuracion):
    servicio: str = "dashboard"
    cognito_emisor: str = "https://cognito-idp.us-east-1.amazonaws.com/local"
    cognito_client_id: str = "local"
    cognito_user_pool_id: str | None = None
    invitacion_horas: int = 72


@lru_cache(maxsize=1)
def obtener() -> ConfigDashboard:
    return ConfigDashboard()
