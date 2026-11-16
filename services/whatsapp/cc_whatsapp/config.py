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
    notificaciones_url: str | None = None  # INT-NOT-01: plantillas de mensaje (chat de RH)
    ventana_horas: int = 24
    # Bot (design.md §7). Una cuenta de WhatsApp atiende a una empresa: el worker de entrada usa la
    # empresa configurada (la asociación número-empresa llega con la vinculación, PQ-07).
    empresa_id: int | None = None
    constancias_url: str | None = None
    codigo_hmac_secreto_id: str | None = None  # cc/{env}/whatsapp-hmac
    alertas_topic_arn: str | None = None  # SNS alertas-rh
    aviso_privacidad_url: str | None = None  # texto y enlace por confirmar (PQ-12)
    inactividad_minutos: int = 30  # DS-14, PQ-20
    bloqueo_horas: int = 24  # PQ-23
    intentos_verificacion: int = 3
    codigo_minutos: int = 10
    limite_mensajes_minuto: int = 20  # DS-17
    limite_solicitudes_dia: int = 5  # PQ-20
    plantillas_por_pagina: int = 9  # una lista interactiva admite 10 filas: 9 más "Ver más"


@lru_cache(maxsize=1)
def obtener() -> ConfigWhatsapp:
    return ConfigWhatsapp()
