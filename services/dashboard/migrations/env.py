"""Alembic del servicio dashboard: esquemas ``identidad`` y ``auditoria``."""

from alembic import context
from cc_common.migraciones import ejecutar_env

ejecutar_env(context, esquema_versiones="identidad", esquemas=("identidad", "auditoria"))
