"""Acceso a PostgreSQL desde las Lambdas ``enviador`` y ``estados-entrega`` (design.md §4.8).

Se conectan como ``svc_whatsapp`` por RDS Proxy. Las credenciales se leen de Secrets Manager
(``CC_DB_SECRETO_ID``) y fijan ``app.empresa_id`` antes de leer o escribir, como los servicios.
Las pruebas sustituyen ``abrir_conexion``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

_secreto: dict[str, Any] | None = None


def _credenciales(cfg) -> dict[str, Any]:
    global _secreto  # noqa: PLW0603 - caché por contenedor de Lambda
    if _secreto is None:
        import boto3

        r = boto3.client("secretsmanager").get_secret_value(SecretId=cfg.db_secreto_id)
        _secreto = json.loads(r["SecretString"])
    return _secreto


def abrir_conexion(cfg) -> psycopg.Connection:
    s = _credenciales(cfg)
    return psycopg.connect(
        host=cfg.db_host if cfg.db_host != "localhost" else s["host"],
        port=int(s.get("port", cfg.db_puerto)),
        dbname=s.get("dbname", cfg.db_nombre),
        user=s["username"],
        password=s["password"],
        sslmode="require",
        connect_timeout=5,
    )


def fijar_empresa(conn: psycopg.Connection, empresa_id: int) -> None:
    conn.execute("SELECT set_config('app.empresa_id', %s, true)", (str(empresa_id),))


def escribir_evento(
    conn: psycopg.Connection, cfg, tipo: str, payload: dict[str, Any], empresa_id: int | None
) -> None:
    """Escribe un evento de dominio en el ``outbox`` (lo publica el ``relay-outbox`` del servicio,
    en la misma transacción del cambio)."""
    conn.execute(
        "INSERT INTO whatsapp.outbox (evento_id, empresa_id, destino_tipo, destino, tipo, payload) "
        "VALUES (%s, %s, 'EVENTBRIDGE', %s, %s, %s)",
        (uuid.uuid4(), empresa_id, cfg.bus_eventos, tipo, Jsonb(payload)),
    )
