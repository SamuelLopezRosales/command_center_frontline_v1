"""Aplicación FastAPI del servicio constancias (design.md §3.1, §3.5).

``crear_app`` no se conecta a nada al importarse: el motor se crea en el arranque salvo que se
inyecte, y el almacén S3 y los clientes de campos y colaboradores se crean al primer uso. Así se
exporta el OpenAPI y se prueba sin infraestructura.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from cc_common.auth import VerificadorToken
from cc_common.errores import instalar_manejadores
from cc_common.logging import configurar_logging
from fastapi import FastAPI

import cc_constancias.errores  # noqa: F401 - registra las restricciones del servicio
from cc_constancias.config import ConfigConstancias

VERSION = "0.1.0"


def crear_app(
    config: ConfigConstancias | None = None,
    *,
    motor: Any | None = None,
    verificador: Any | None = None,
    almacen: Any | None = None,
    campos: Any | None = None,
    colaboradores: Any | None = None,
    logotipos: Any | None = None,
    almacen_constancias: Any | None = None,
    firmador: Any | None = None,
    secreto_interno: Callable[[], str] | None = None,
) -> FastAPI:
    cfg = config or ConfigConstancias()

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
            from cc_constancias import consumidores

            tareas.append(asyncio.create_task(_relay(app, parar)))
            tareas.append(asyncio.create_task(consumidores.ejecutar(app, parar)))
        yield
        parar.set()
        if tareas:
            _, pendientes = await asyncio.wait(tareas, timeout=5)
            for t in pendientes:
                t.cancel()
        if creado is not None:
            await creado.dispose()

    app = FastAPI(
        title="Command Center - constancias",
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
    app.state.almacen = almacen
    app.state.campos = campos
    app.state.colaboradores = colaboradores
    app.state.logotipos = logotipos
    app.state.almacen_constancias = almacen_constancias
    app.state.firmador = firmador
    app.state.secreto_interno = secreto_interno or _secreto_interno_de(cfg)
    instalar_manejadores(app)

    @app.get("/salud", include_in_schema=False)
    def salud() -> dict[str, str]:
        return {"estado": "ok", "servicio": cfg.servicio, "version": VERSION}

    from cc_constancias.api import registrar_rutas
    from cc_constancias.api.publico import CABECERAS, es_ruta_publica

    @app.middleware("http")
    async def cabeceras_publicas(request, call_next):
        # También en los errores (404, 410): nada de lo público se guarda ni se indexa.
        respuesta = await call_next(request)
        if es_ruta_publica(request.url.path):
            respuesta.headers.update(CABECERAS)
        return respuesta

    registrar_rutas(app)
    return app


async def _relay(app: FastAPI, parar: asyncio.Event) -> None:
    """relay-outbox: publica el mensaje de entrega y los eventos de falla (design.md §4.7)."""
    import boto3
    from cc_common.outbox import publicador_aws
    from cc_common.tareas import relay_outbox

    cfg = app.state.config
    opciones = {"region_name": cfg.region, "endpoint_url": cfg.aws_endpoint or None}
    publicador = publicador_aws(
        boto3.client("sqs", **opciones), boto3.client("events", **opciones), fuente="cc.constancias"
    )
    await relay_outbox(app.state.motor, "constancias", publicador, parar)


def _secreto_interno_de(cfg: ConfigConstancias) -> Callable[[], str]:
    """Lee ``cc/{env}/internal-auth`` al primer uso y lo guarda 5 minutos (tolera la rotación)."""
    estado: dict[str, Any] = {"valor": None, "hasta": 0.0}

    def leer() -> str:
        if estado["valor"] is None or time.monotonic() > estado["hasta"]:
            if not cfg.internal_auth_secreto_id:
                from cc_common.errores import ErrorInterno

                raise ErrorInterno("SECRETO_INTERNO_NO_CONFIGURADO", "Servicio no configurado.")
            from cc_common.recursos import leer_secreto

            estado["valor"] = leer_secreto(cfg.internal_auth_secreto_id, cfg.region)
            estado["hasta"] = time.monotonic() + 300
        return estado["valor"]

    return leer
