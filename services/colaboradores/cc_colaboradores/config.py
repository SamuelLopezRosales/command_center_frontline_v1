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
    # Bucket ``cargas``: archivos de Excel de la carga masiva, con ciclo de vida de 7 días.
    bucket_cargas: str = "cc-local-cargas"
    s3_endpoint: str | None = None  # LocalStack en local; vacío en AWS
    sqs_endpoint: str | None = None
    hmac_celular_secreto_id: str | None = None  # cc/{env}/hmac-celular
    logotipo_max_bytes: int = 1_048_576
    url_subida_segundos: int = 900
    # Carga masiva (CC-REQ-035, 038): URL de la cola ``cola-cargas`` donde el relay publica.
    cola_cargas_url: str = "cola-cargas"
    carga_max_bytes: int = 5 * 1024 * 1024
    carga_max_filas: int = 2000
    carga_lote: int = 200
    carga_sin_confirmar_segundos: int = 3600
    # Integración con campos (T-206): INT-CAM-01 y el evento campo.actualizado.
    campos_url: str | None = None
    cola_eventos_url: str = "ev-colaboradores"
    eventos_activos: bool = False  # inicia el consumidor de eventos con la API


@lru_cache(maxsize=1)
def obtener() -> ConfigColaboradores:
    return ConfigColaboradores()
