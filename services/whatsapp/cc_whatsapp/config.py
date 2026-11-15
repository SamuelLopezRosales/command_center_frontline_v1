"""Configuración del servicio whatsapp y de sus Lambdas (variables ``CC_*``)."""

from __future__ import annotations

from functools import lru_cache

from cc_common.config import Configuracion


class ConfigWhatsapp(Configuracion):
    servicio: str = "whatsapp"
    cognito_emisor: str = "https://cognito-idp.us-east-1.amazonaws.com/local"
    cognito_client_id: str = "local"
    # Meta (design.md §7.5). El secreto ``cc/{env}/meta`` trae app_secret, verify_token, token de
    # acceso y phone_number_id; el identificador del número también puede fijarse por variable.
    meta_secreto_id: str | None = None
    meta_api_base: str = "https://graph.facebook.com"
    meta_api_version: str = "v21.0"  # se fija al vincular la cuenta (PQ-07)
    meta_phone_number_id: str | None = None
    meta_timeout_s: float = 10.0
    plantilla_constancia_lista: str | None = "constancia_lista"  # PQ-11
    plantilla_idioma: str = "es_MX"
    # Colas y eventos
    cola_entrada_url: str = "wa-entrada.fifo"
    cola_estados_url: str = "wa-estados"
    cola_salida_url: str = "wa-salida.fifo"
    bus_eventos: str = "cc-local-eventos"
    aws_endpoint: str | None = None  # LocalStack en local; vacío en AWS
    eventos_activos: bool = False  # inicia el relay del outbox con la API
    colaboradores_url: str | None = None
    ventana_horas: int = 24


@lru_cache(maxsize=1)
def obtener() -> ConfigWhatsapp:
    return ConfigWhatsapp()
