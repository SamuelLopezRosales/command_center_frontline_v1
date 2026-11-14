"""Ejecuta las migraciones de Alembic de un servicio contra una base de prueba."""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config

RAIZ = Path(__file__).resolve().parents[2]


# Orden fijo por las llaves foráneas entre esquemas (design.md §2.8).
ORDEN = ("dashboard", "campos", "colaboradores", "whatsapp", "constancias", "notificaciones")


def subir_todo(url_sync: str) -> None:
    for servicio in ORDEN:
        subir(servicio, url_sync)


def config_servicio(servicio: str) -> Config:
    return Config(str(RAIZ / "services" / servicio / "alembic.ini"))


def subir(servicio: str, url_sync: str, revision: str = "head") -> None:
    anterior = os.environ.get("CC_MIGRAR_URL")
    os.environ["CC_MIGRAR_URL"] = url_sync
    try:
        command.upgrade(config_servicio(servicio), revision)
    finally:
        if anterior is None:
            os.environ.pop("CC_MIGRAR_URL", None)
        else:
            os.environ["CC_MIGRAR_URL"] = anterior


def bajar(servicio: str, url_sync: str, revision: str = "base") -> None:
    os.environ["CC_MIGRAR_URL"] = url_sync
    try:
        command.downgrade(config_servicio(servicio), revision)
    finally:
        os.environ.pop("CC_MIGRAR_URL", None)
