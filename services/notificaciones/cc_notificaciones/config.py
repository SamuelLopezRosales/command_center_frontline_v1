"""Configuración del servicio notificaciones (variables ``CC_*``)."""

from __future__ import annotations

from datetime import time
from functools import lru_cache

from cc_common.config import Configuracion


class ConfigNotificaciones(Configuracion):
    servicio: str = "notificaciones"
    cognito_emisor: str = "https://cognito-idp.us-east-1.amazonaws.com/local"
    cognito_client_id: str = "local"
    # Servicios a los que `notificaciones` consulta: INT-CAM-01 (catálogo para validar criterios)
    # e INT-COL-06 (evaluación de audiencias). Sin URL, solo en local se usan sustitutos vacíos.
    campos_url: str | None = None
    colaboradores_url: str | None = None
    # Tamaño de página al pedir a `colaboradores` los seleccionados de una audiencia.
    audiencia_pagina: int = 1000
    # Tope de seguridad de colaboradores por revisión (evita una revisión descontrolada).
    audiencia_maximo: int = 50_000

    # Horario permitido de envío en la zona de la notificación (design.md §6.3; PQ-06). El valor
    # por empresa vive en `identidad` y no es legible desde este servicio: se configura aquí.
    horario_inicio: time = time(8, 0)
    horario_fin: time = time(20, 0)  # inclusivo

    # Meta (design.md §7.5). El secreto ``cc/{env}/meta`` es un JSON con ``access_token`` y
    # ``waba_id`` (cuenta de WhatsApp Business) además de las claves que usa `whatsapp`. Nunca se
    # lee de variables de entorno; sin ``meta_secreto_id`` solo en local se usa un sustituto.
    meta_secreto_id: str | None = None
    # ``meta_api_base`` es el servidor al que se envía el token: es configuración del despliegue y
    # NO se puede cambiar desde la API ni la pantalla de integraciones (eso mandaría el token a
    # cualquier servidor). ``meta_api_version`` es el respaldo si el secreto no trae
    # ``api_version``.
    meta_api_base: str = "https://graph.facebook.com"
    meta_api_version: str = "v21.0"
    meta_timeout_s: float = 10.0
    meta_sonda_timeout_s: float = 5.0  # "Probar conexión": tres consultas, cada una con este tope
    # Solo local: con ``CC_META_SECRETO_ID`` fijo (para guardar credenciales en LocalStack), las
    # plantillas siguen usando el sustituto sin red en lugar de llamar a Meta.
    meta_plantillas_stub: bool = False

    # Programación (EventBridge Scheduler) y despacho (design.md §4.5, §6.3). El destino del
    # schedule único es la cola ``notif-despacho``; el rol lo asume Scheduler para publicar en ella.
    aws_endpoint: str | None = None  # LocalStack en local; vacío en AWS
    scheduler_destino_arn: str | None = None
    scheduler_rol_arn: str | None = None
    scheduler_grupo: str = "default"
    cola_despacho_url: str = "notif-despacho"

    # Eventos: el relay del outbox arranca con la API si ``eventos_activos``; el consumidor de
    # ``ev-notificaciones`` solo si además ``consumidor_activo`` (los demás consumidores, T-217).
    cola_eventos_url: str = "ev-notificaciones"
    bus_eventos: str = "cc-local-eventos"
    eventos_activos: bool = False
    consumidor_activo: bool = False


@lru_cache(maxsize=1)
def obtener() -> ConfigNotificaciones:
    return ConfigNotificaciones()
