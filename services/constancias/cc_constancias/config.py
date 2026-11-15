"""Configuración del servicio constancias (variables ``CC_*``)."""

from __future__ import annotations

from functools import lru_cache

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
    # Servicios a los que `constancias` consulta (INT-CAM-01 e INT-COL-04). Sin URL, solo en
    # local se usan sustitutos vacíos.
    campos_url: str | None = None
    colaboradores_url: str | None = None


@lru_cache(maxsize=1)
def obtener() -> ConfigConstancias:
    return ConfigConstancias()
