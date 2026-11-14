"""Alembic del servicio whatsapp: esquema `whatsapp`."""

from alembic import context
from cc_common.migraciones import ejecutar_env

ejecutar_env(context, esquema_versiones="whatsapp", esquemas=("whatsapp",))
