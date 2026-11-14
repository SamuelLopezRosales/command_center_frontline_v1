"""Aplicación FastAPI del servicio dashboard (design.md §3.1, §3.2).

``crear_app`` no se conecta a nada al importarse: el motor de base de datos se crea en el
arranque (``lifespan``) salvo que se inyecte uno, lo que permite exportar el OpenAPI y probar
sin infraestructura.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from cc_common.auth import VerificadorToken
from cc_common.errores import instalar_manejadores
from cc_common.logging import configurar_logging
from fastapi import FastAPI

from cc_dashboard.config import ConfigDashboard

VERSION = "0.1.0"


def crear_app(
    config: ConfigDashboard | None = None,
    *,
    motor: Any | None = None,
    verificador: Any | None = None,
    cognito: Any | None = None,
) -> FastAPI:
    cfg = config or ConfigDashboard()

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
        title="Command Center - dashboard",
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
    app.state.cognito = cognito
    instalar_manejadores(app)

    @app.get("/salud", include_in_schema=False)
    def salud() -> dict[str, str]:
        return {"estado": "ok", "servicio": cfg.servicio, "version": VERSION}

    from cc_dashboard.api import registrar_rutas

    registrar_rutas(app)
    return app
