"""Ayudante común para los ``env.py`` de Alembic de cada servicio (design.md §2.8).

Cada servicio tiene su carpeta ``migrations/`` y su propia tabla de versiones dentro de su
esquema principal (``{esquema}.alembic_version``). Las migraciones usan el rol ``migrador``.
La URL se lee de ``CC_MIGRAR_URL`` (``postgresql+psycopg://...``) o de la configuración de
Alembic; nunca se escribe en archivos del repositorio.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

from sqlalchemy import create_engine, pool, text

_ESQUEMA = re.compile(r"^[a-z_]{1,40}$")


def ejecutar_env(context, esquema_versiones: str, esquemas: Sequence[str]) -> None:
    for e in (esquema_versiones, *esquemas):
        if not _ESQUEMA.match(e):
            raise ValueError("esquema inválido")
    url = os.environ.get("CC_MIGRAR_URL") or context.config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("Falta CC_MIGRAR_URL para ejecutar las migraciones")
    motor = create_engine(url, poolclass=pool.NullPool)
    with motor.connect() as conn:
        for e in dict.fromkeys((esquema_versiones, *esquemas)):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {e}"))
        conn.commit()
        context.configure(
            connection=conn,
            target_metadata=None,
            version_table="alembic_version",
            version_table_schema=esquema_versiones,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    motor.dispose()
