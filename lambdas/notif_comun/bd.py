"""Acceso a PostgreSQL de las Lambdas de notificaciones (design.md §4.8).

Se conectan como ``svc_notificaciones`` por RDS Proxy; las credenciales vienen de Secrets Manager
(``CC_DB_SECRETO_ID``). Cada transacción fija ``app.empresa_id`` con ``set_config(..., true)``: es
local a la transacción, así que hay que fijarla de nuevo después de cada ``commit``. Las pruebas
sustituyen ``abrir_conexion``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import psycopg

_secreto: dict[str, Any] | None = None


def leer_secreto(secreto_id: str, region: str) -> str:  # pragma: no cover - requiere AWS
    """Lee un secreto con boto3 (el runtime de Lambda lo trae; ``cc_common.recursos`` arrastra
    SQLAlchemy, que no se empaqueta)."""
    import boto3

    return boto3.client("secretsmanager", region_name=region).get_secret_value(SecretId=secreto_id)[
        "SecretString"
    ]


def secreto_interno(cfg) -> Callable[[], str]:  # pragma: no cover - requiere AWS
    """Secreto de las llamadas internas (``cc/{env}/internal-auth``), con caché de 5 minutos."""
    estado: dict[str, Any] = {"valor": None, "hasta": 0.0}

    def leer() -> str:
        if estado["valor"] is None or time.monotonic() > estado["hasta"]:
            estado["valor"] = leer_secreto(cfg.internal_auth_secreto_id, cfg.region)
            estado["hasta"] = time.monotonic() + 300
        return estado["valor"]

    return leer


def _credenciales(cfg) -> dict[str, Any]:
    global _secreto  # noqa: PLW0603 - caché por contenedor de Lambda
    if _secreto is None:
        _secreto = json.loads(leer_secreto(cfg.db_secreto_id, cfg.region))
    return _secreto


def abrir_conexion(cfg) -> psycopg.Connection:
    s = _credenciales(cfg)
    return psycopg.connect(
        host=cfg.db_host if cfg.db_host != "localhost" else s.get("host", cfg.db_host),
        port=int(s.get("port", cfg.db_puerto)),
        dbname=s.get("dbname", cfg.db_nombre),
        user=s["username"],
        password=s["password"],
        sslmode="require" if cfg.db_ssl else "prefer",
        connect_timeout=5,
    )


def fijar_empresa(conn: psycopg.Connection, empresa_id: int) -> None:
    conn.execute("SELECT set_config('app.empresa_id', %s, true)", (str(empresa_id),))
