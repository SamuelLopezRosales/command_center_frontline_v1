"""Routers del servicio notificaciones."""

from __future__ import annotations

from fastapi import FastAPI


def registrar_rutas(app: FastAPI) -> None:
    from cc_notificaciones.api import audiencias, internas, notificaciones, plantillas_mensaje

    app.include_router(audiencias.router, prefix="/api/v1")
    app.include_router(plantillas_mensaje.router, prefix="/api/v1")
    app.include_router(notificaciones.router, prefix="/api/v1")
    app.include_router(internas.router)
