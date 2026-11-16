"""Utilidades compartidas por los triggers de Cognito (design.md §4.6, §4.8, §11.2).

Los triggers se conectan a PostgreSQL como ``svc_dashboard`` por RDS Proxy. Las credenciales se
leen de Secrets Manager (``CC_DB_SECRET_ARN``) y el host del proxy de ``CC_DB_HOST``. Los
triggers aún no conocen la empresa del usuario, así que leen con las funciones
``identidad.validar_invitacion`` y ``identidad.usuario_por_sub`` (SECURITY DEFINER) y fijan
``app.empresa_id`` antes de escribir, igual que los servicios.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

import psycopg

log = logging.getLogger("cognito_triggers")

# Mensaje único para cualquier rechazo del registro: no revela si el código existe, venció,
# ya se usó o pertenece a otro correo (CC-REQ-008).
MENSAJE_GENERICO = "No fue posible completar el registro."
ATRIBUTO_CODIGO = "custom:codigo_invitacion"
CODIGO_LONGITUD_MAX = 128


class RegistroNoAutorizado(Exception):  # noqa: N818
    """Se lanza hacia Cognito; el texto que ve el usuario es siempre el mismo."""

    def __init__(self, motivo: str):
        super().__init__(MENSAJE_GENERICO)
        self.motivo = motivo  # solo para el registro interno, nunca para el usuario


def registro_abierto() -> bool:
    """``CC_REGISTRO=ABIERTO``: registro sin código de invitación (solo ambientes de prueba)."""
    return os.environ.get("CC_REGISTRO", "INVITACION").strip().upper() == "ABIERTO"


def dominio_permitido(correo: str) -> bool:
    """El correo pertenece a uno de ``CC_REGISTRO_DOMINIOS`` (separados por comas). Sin
    dominios configurados no se permite ninguno."""
    permitidos = {d.strip().lower() for d in os.environ.get("CC_REGISTRO_DOMINIOS", "").split(",")}
    permitidos.discard("")
    return "@" in correo and correo.rsplit("@", 1)[1].strip().lower() in permitidos


def hash_codigo(codigo: str) -> bytes:
    return hashlib.sha256(codigo.encode()).digest()


def rechazar(motivo: str) -> RegistroNoAutorizado:
    """Registra el motivo (sin datos personales) y devuelve la excepción genérica."""
    log.warning("registro rechazado", extra={"motivo": motivo})
    return RegistroNoAutorizado(motivo)


_secreto: dict[str, Any] | None = None


def _credenciales() -> dict[str, Any]:
    global _secreto  # noqa: PLW0603 - caché por contenedor de Lambda
    if _secreto is None:
        import boto3

        r = boto3.client("secretsmanager").get_secret_value(SecretId=os.environ["CC_DB_SECRET_ARN"])
        _secreto = json.loads(r["SecretString"])
    return _secreto


def abrir_conexion() -> psycopg.Connection:
    """Conexión como ``svc_dashboard``. Las pruebas la sustituyen."""
    s = _credenciales()
    return psycopg.connect(
        host=os.environ.get("CC_DB_HOST") or s["host"],
        port=int(s.get("port", 5432)),
        dbname=s.get("dbname", "command_center"),
        user=s["username"],
        password=s["password"],
        sslmode="require",
        connect_timeout=5,
    )


def fijar_empresa(conn: psycopg.Connection, empresa_id: int) -> None:
    conn.execute("SELECT set_config('app.empresa_id', %s, true)", (str(empresa_id),))


def cliente_cognito() -> Any:
    import boto3

    return boto3.client("cognito-idp")
