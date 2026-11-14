"""Alembic del servicio constancias: esquema `constancias`."""

from alembic import context
from cc_common.migraciones import ejecutar_env

ejecutar_env(context, esquema_versiones="constancias", esquemas=("constancias",))
