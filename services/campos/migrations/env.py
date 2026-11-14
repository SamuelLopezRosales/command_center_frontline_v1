"""Alembic del servicio campos: esquema ``campos``."""

from alembic import context
from cc_common.migraciones import ejecutar_env

ejecutar_env(context, esquema_versiones="campos", esquemas=("campos",))
