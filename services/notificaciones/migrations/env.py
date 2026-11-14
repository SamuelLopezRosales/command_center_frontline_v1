"""Alembic del servicio notificaciones: esquema `notificaciones`."""

from alembic import context
from cc_common.migraciones import ejecutar_env

ejecutar_env(context, esquema_versiones="notificaciones", esquemas=("notificaciones",))
