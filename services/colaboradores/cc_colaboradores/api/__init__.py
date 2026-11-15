"""Routers del servicio colaboradores. Cada tarea agrega su router aquí."""

from __future__ import annotations

from fastapi import FastAPI


def registrar_rutas(app: FastAPI) -> None:
    from cc_colaboradores.api import colaboradores, internas, organizaciones, plantas

    app.include_router(internas.router)  # /internal: sin prefijo /api/v1 ni API Gateway
    app.include_router(colaboradores.router, prefix="/api/v1")
    app.include_router(organizaciones.router, prefix="/api/v1")
    app.include_router(plantas.router, prefix="/api/v1")
