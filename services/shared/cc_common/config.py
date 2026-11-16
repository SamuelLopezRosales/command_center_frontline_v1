"""Configuración de cada servicio a partir de variables de entorno (prefijo ``CC_``).

Los secretos nunca viven en variables de entorno: se leen de Secrets Manager por su
identificador (``*_secreto_id``). Los valores que cambian sin redesplegar se leen de SSM
(design.md §13.8).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CC_", extra="ignore", frozen=True)

    servicio: str = Field(min_length=1)
    # Nombre de un ambiente de `infra/config/ambientes.json` (test, prod, samuel...): el servicio no
    # conoce la lista, solo exige un nombre bien formado. `local` es el equipo de desarrollo.
    ambiente: str = Field(default="local", pattern=r"^[a-z][a-z0-9-]{1,19}$")
    region: str = "us-east-1"
    zona_horaria: str = "America/Mexico_City"
    log_nivel: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Base de datos: host directo o RDS Proxy (cambio B, configurable por ambiente).
    db_host: str = "localhost"
    db_puerto: int = 5432
    db_nombre: str = "command_center"
    db_usuario: str | None = None
    db_secreto_id: str | None = None
    db_ssl: bool = True
    db_pool_tamano: int = Field(default=5, ge=1, le=50)
    db_pool_desborde: int = Field(default=5, ge=0, le=50)

    internal_auth_secreto_id: str | None = None
    kms_llave_datos: str | None = None

    @property
    def es_local(self) -> bool:
        return self.ambiente == "local"


@lru_cache(maxsize=1)
def obtener_configuracion() -> Configuracion:
    return Configuracion()  # type: ignore[call-arg]
