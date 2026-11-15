"""Aplicación FastAPI del servicio whatsapp (design.md §3.7).

En esta etapa expone ``/salud`` y ejecuta el ``relay-outbox`` que publica los eventos de las
Lambdas (``wa.mensaje_estado``, ``wa.plantilla_estado``, ``wa.numero_invalido``). Las rutas de chat
(WAP-01 a 05) y el ``worker-whatsapp-entrada`` se agregan en sus tareas.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from cc_common.auth import VerificadorToken
from cc_common.errores import instalar_manejadores
from cc_common.logging import configurar_logging
from fastapi import FastAPI

from cc_whatsapp.config import ConfigWhatsapp

VERSION = "0.1.0"


def crear_app(
    config: ConfigWhatsapp | None = None,
    *,
    motor: Any | None = None,
    verificador: Any | None = None,
) -> FastAPI:
    cfg = config or ConfigWhatsapp()

    @asynccontextmanager
    async def ciclo(app: FastAPI) -> AsyncIterator[None]:
        configurar_logging(cfg.servicio, cfg.ambiente, cfg.log_nivel)
        creado = None
        if app.state.motor is None:
            from cc_common.recursos import motor_desde_config

            creado = app.state.motor = motor_desde_config(cfg)
        parar = asyncio.Event()
        tareas = []
        if cfg.eventos_activos:
            tareas.append(asyncio.create_task(_relay(app, parar)))
        yield
        parar.set()
        if tareas:
            _, pendientes = await asyncio.wait(tareas, timeout=5)
            for t in pendientes:
                t.cancel()
        if creado is not None:
            await creado.dispose()

    app = FastAPI(
        title="Command Center - whatsapp",
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
    instalar_manejadores(app)

    @app.get("/salud", include_in_schema=False)
    def salud() -> dict[str, str]:
        return {"estado": "ok", "servicio": cfg.servicio, "version": VERSION}

    return app


async def _relay(app: FastAPI, parar: asyncio.Event) -> None:
    """relay-outbox: publica los eventos de whatsapp en EventBridge (design.md §4.7)."""
    import boto3
    from cc_common.outbox import publicador_aws
    from cc_common.tareas import relay_outbox

    cfg = app.state.config
    opciones = {"region_name": cfg.region, "endpoint_url": cfg.aws_endpoint or None}
    publicador = publicador_aws(
        boto3.client("sqs", **opciones), boto3.client("events", **opciones), fuente="cc.whatsapp"
    )
    await relay_outbox(app.state.motor, "whatsapp", publicador, parar)
