"""Routers del servicio notificaciones."""

from __future__ import annotations

from fastapi import FastAPI


def registrar_rutas(app: FastAPI) -> None:
    from cc_notificaciones.api import (
        audiencias,
        integraciones,
        internas,
        notificaciones,
        plantillas_mensaje,
        plantillas_meta,
    )

    app.include_router(audiencias.router, prefix="/api/v1")
    # Antes que `plantillas_mensaje`: la ruta fija ``/meta`` no debe caer en ``/{plantilla_id}``.
    app.include_router(plantillas_meta.router, prefix="/api/v1")
    app.include_router(plantillas_mensaje.router, prefix="/api/v1")
    app.include_router(notificaciones.router, prefix="/api/v1")
    app.include_router(integraciones.router, prefix="/api/v1")
    app.include_router(internas.router)
