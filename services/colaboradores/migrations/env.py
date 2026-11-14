"""Alembic del servicio colaboradores: esquema ``colaboradores``."""

from alembic import context
from cc_common.migraciones import ejecutar_env

ejecutar_env(context, esquema_versiones="colaboradores", esquemas=("colaboradores",))
