"""Configuración del servicio colaboradores (variables ``CC_*``)."""

from __future__ import annotations

from functools import lru_cache

from cc_common.config import Configuracion


class ConfigColaboradores(Configuracion):
    servicio: str = "colaboradores"
    cognito_emisor: str = "https://cognito-idp.us-east-1.amazonaws.com/local"
    cognito_client_id: str = "local"
    # Bucket ``plantillas``: los logotipos van bajo ``logotipos/{empresa_id}/`` (design.md §13.4).
    bucket_plantillas: str = "cc-local-plantillas"
    s3_endpoint: str | None = None  # LocalStack en local; vacío en AWS
    hmac_celular_secreto_id: str | None = None  # cc/{env}/hmac-celular
    logotipo_max_bytes: int = 1_048_576
    url_subida_segundos: int = 900


@lru_cache(maxsize=1)
def obtener() -> ConfigColaboradores:
    return ConfigColaboradores()
