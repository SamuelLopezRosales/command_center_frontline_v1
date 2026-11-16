"""Aplicación FastAPI del servicio notificaciones (design.md §3.1, §3.6).

``crear_app`` no se conecta a nada al importarse: el motor se crea en el arranque salvo que se
inyecte, y los clientes de `campos`, `colaboradores`, Meta (plantillas) y EventBridge Scheduler se
crean al primer uso. Con ``CC_EVENTOS_ACTIVOS`` arranca el relay del ``outbox`` (publica el mensaje
de ``notif-despacho`` al confirmar un envío inmediato); el consumidor de ``ev-notificaciones``
(``wa.plantilla_estado``; el resto, T-217) arranca con ``CC_CONSUMIDOR_ACTIVO``. ``reloj`` es
inyectable para probar el horario.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from cc_common.auth import VerificadorToken
from cc_common.errores import instalar_manejadores
from cc_common.logging import configurar_logging
from fastapi import FastAPI

import cc_notificaciones.errores  # noqa: F401 - registra las restricciones del servicio
from cc_notificaciones.config import ConfigNotificaciones

VERSION = "0.1.0"


def crear_app(
    config: ConfigNotificaciones | None = None,
    *,
    motor: Any | None = None,
    verificador: Any | None = None,
    campos: Any | None = None,
    colaboradores: Any | None = None,
    meta: Any | None = None,
    scheduler: Any | None = None,
    reloj: Callable[[], datetime] | None = None,
    secreto_interno: Callable[[], str] | None = None,
) -> FastAPI:
    cfg = config or ConfigNotificaciones()

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
            if cfg.consumidor_activo:
                from cc_notificaciones import consumidores

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
        title="Command Center - notificaciones",
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
    app.state.campos = campos
    app.state.colaboradores = colaboradores
    app.state.meta = meta
    app.state.scheduler = scheduler
    app.state.reloj = reloj or (lambda: datetime.now(UTC))
    app.state.secreto_interno = secreto_interno or _secreto_interno_de(cfg)
    instalar_manejadores(app)

    @app.get("/salud", include_in_schema=False)
    def salud() -> dict[str, str]:
        return {"estado": "ok", "servicio": cfg.servicio, "version": VERSION}

    from cc_notificaciones.api import registrar_rutas

    registrar_rutas(app)
    return app


def _secreto_interno_de(cfg: ConfigNotificaciones) -> Callable[[], str]:
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


async def _relay(app: FastAPI, parar: asyncio.Event) -> None:
    """relay-outbox: publica en ``notif-despacho`` el inicio del envío inmediato (§4.7)."""
    import boto3
    from cc_common.outbox import publicador_aws
    from cc_common.tareas import relay_outbox

    cfg = app.state.config
    opciones = {"region_name": cfg.region, "endpoint_url": cfg.aws_endpoint or None}
    publicador = publicador_aws(
        boto3.client("sqs", **opciones),
        boto3.client("events", **opciones),
        fuente="cc.notificaciones",
    )
    await relay_outbox(app.state.motor, "notificaciones", publicador, parar)
