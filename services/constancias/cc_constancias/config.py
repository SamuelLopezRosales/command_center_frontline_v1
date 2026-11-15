"""Configuración del servicio constancias (variables ``CC_*``)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from cc_common.config import Configuracion


class ConfigConstancias(Configuracion):
    servicio: str = "constancias"
    cognito_emisor: str = "https://cognito-idp.us-east-1.amazonaws.com/local"
    cognito_client_id: str = "local"
    # Bucket ``plantillas``: borradores y versiones bajo ``plantillas/{empresa}/{plantilla}/``.
    bucket_plantillas: str = "cc-local-plantillas"
    s3_endpoint: str | None = None  # LocalStack en local; vacío en AWS
    contenido_max_bytes: int = 512 * 1024  # CC-REQ-060: máximo del JSON de una plantilla
    # Dominio público: el QR de una constancia apunta a https://{dominio}/v/{código} (CC-REQ-080).
    dominio: str = "localhost"
    logotipo_cache_segundos: int = 600
    logotipo_max_bytes: int = 1_048_576
    # Emisión de constancias (T-209)
    bucket_constancias: str = "cc-local-constancias"  # con Object Lock desde su creación
    retencion_constancias_dias: int | None = None  # None: la retención por defecto del bucket
    cola_pdf_url: str = "cola-pdf"
    cola_wa_salida_url: str = "wa-salida.fifo"
    cola_eventos_url: str = "ev-constancias"
    bus_eventos: str = "cc-local-eventos"
    aws_endpoint: str | None = None  # LocalStack en local; vacío en AWS
    eventos_activos: bool = False  # inicia el relay y el consumidor con la API
    max_intentos_pdf: int = 3  # recepciones de cola-pdf antes de marcar la solicitud FALLIDA
    modo_entrega: Literal["enlace", "adjunto"] = "enlace"  # D-10
    # Descarga por CloudFront con URL firmada (design.md §11.3)
    cloudfront_dominio: str | None = None
    cloudfront_key_pair_id: str | None = None
    cloudfront_clave_secreto_id: str | None = None  # cc/{env}/cf-signing-key
    # Servicios a los que `constancias` consulta (INT-CAM-01 e INT-COL-04). Sin URL, solo en
    # local se usan sustitutos vacíos.
    campos_url: str | None = None
    colaboradores_url: str | None = None


@lru_cache(maxsize=1)
def obtener() -> ConfigConstancias:
    return ConfigConstancias()
