"""Ayudantes de prueba de los triggers de Cognito."""

import hashlib
from datetime import UTC, datetime, timedelta

import psycopg


def hash_(codigo: str) -> bytes:
    return hashlib.sha256(codigo.encode()).digest()


def invitar(bd, codigo, *, correo=None, expira=None, usada=False):
    expira = expira or datetime.now(UTC) + timedelta(hours=72)
    with psycopg.connect(bd["url"], autocommit=True) as c:
        inv = c.execute(
            "INSERT INTO identidad.invitacion_registro "
            "(empresa_id, codigo_hash, correo_destino, creada_por_usuario_id, fecha_creacion, "
            "fecha_expira) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (
                bd["empresa"],
                hash_(codigo),
                correo,
                bd["usuario"],
                expira - timedelta(hours=72),
                expira,
            ),
        ).fetchone()[0]
        if usada:
            c.execute(
                "UPDATE identidad.invitacion_registro SET usada_por_usuario_id = %s, "
                "fecha_uso = now() WHERE id = %s",
                (bd["usuario"], inv),
            )
    return inv


def consulta(bd, sql, params=()):
    with psycopg.connect(bd["url"]) as c:
        return c.execute(sql, params).fetchall()
