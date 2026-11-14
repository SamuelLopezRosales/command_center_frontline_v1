"""Creación de recursos a partir de la configuración (motor de base de datos, secretos).

En AWS las credenciales de la base vienen de Secrets Manager (``db_secreto_id``, formato del
secreto de RDS: ``{"username": ..., "password": ...}``). En desarrollo local se usan
``CC_DB_USUARIO`` y ``CC_DB_CONTRASENA``. Ningún valor se registra.
"""

from __future__ import annotations

import json
import os
from typing import Any

from cc_common.config import Configuracion
from cc_common.db import crear_motor, url_postgres


def leer_secreto(secreto_id: str, region: str, cliente: Any | None = None) -> str:
    if cliente is None:  # pragma: no cover - requiere AWS
        import boto3

        cliente = boto3.client("secretsmanager", region_name=region)
    return cliente.get_secret_value(SecretId=secreto_id)["SecretString"]


def credenciales_db(cfg: Configuracion, cliente: Any | None = None) -> tuple[str, str]:
    if cfg.db_secreto_id:
        datos = json.loads(leer_secreto(cfg.db_secreto_id, cfg.region, cliente))
        return datos["username"], datos["password"]
    if not cfg.es_local:
        raise RuntimeError("Fuera de local, las credenciales de la base vienen de Secrets Manager")
    usuario = cfg.db_usuario or os.environ.get("CC_DB_USUARIO", "")
    return usuario, os.environ.get("CC_DB_CONTRASENA", "")


def motor_desde_config(cfg: Configuracion, cliente_secretos: Any | None = None):
    usuario, contrasena = credenciales_db(cfg, cliente_secretos)
    return crear_motor(
        url_postgres(cfg, usuario, contrasena),
        tamano=cfg.db_pool_tamano,
        desborde=cfg.db_pool_desborde,
        ssl=cfg.db_ssl,
    )
