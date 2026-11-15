"""Aplicación FastAPI del servicio colaboradores (design.md §3.1, §3.3).

``crear_app`` no se conecta a nada al importarse: el motor se crea en el arranque salvo que se
inyecte; el cifrador (KMS y llave HMAC) y el almacén S3 se crean al primer uso. Así se exporta el
OpenAPI y se prueba sin infraestructura.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from cc_common.auth import VerificadorToken
from cc_common.errores import instalar_manejadores
from cc_common.logging import configurar_logging
from fastapi import FastAPI

import cc_colaboradores.errores  # noqa: F401 - registra las restricciones del servicio
from cc_colaboradores.campos_cliente import CacheCampos, StubCampos
from cc_colaboradores.config import ConfigColaboradores

VERSION = "0.1.0"


def crear_app(
    config: ConfigColaboradores | None = None,
    *,
    motor: Any | None = None,
    verificador: Any | None = None,
    cifrador: Any | None = None,
    almacen: Any | None = None,
    campos: Any | None = None,
) -> FastAPI:
    cfg = config or ConfigColaboradores()

    @asynccontextmanager
    async def ciclo(app: FastAPI) -> AsyncIterator[None]:
        configurar_logging(cfg.servicio, cfg.ambiente, cfg.log_nivel)
        creado = None
        if app.state.motor is None:
            from cc_common.recursos import motor_desde_config

            creado = app.state.motor = motor_desde_config(cfg)
        yield
        if creado is not None:
            await creado.dispose()

    app = FastAPI(
        title="Command Center - colaboradores",
        version=VERSION,
        lifespan=ciclo,
        docs_url="/docs" if cfg.es_local else None,
        redoc_url=None,
    )
    app.state.config = cfg
    app.state.motor = motor
    app.state.verificador = verificador or VerificadorToken(
        cfg.cognito_emisor, cfg.cognito_client_id
    )
    app.state.cifrador = cifrador
    app.state.almacen = almacen
    # Temporal: StubCampos se reemplaza por el cliente de INT-CAM-01 en T-206.
    app.state.campos = campos or CacheCampos(StubCampos())
    instalar_manejadores(app)

    @app.get("/salud", include_in_schema=False)
    def salud() -> dict[str, str]:
        return {"estado": "ok", "servicio": cfg.servicio, "version": VERSION}

    from cc_colaboradores.api import registrar_rutas

    registrar_rutas(app)
    return app
