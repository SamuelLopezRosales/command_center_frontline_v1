"""Routers del servicio campos."""

from __future__ import annotations

from fastapi import FastAPI


def registrar_rutas(app: FastAPI) -> None:
    from cc_campos.api import campos, internas, opciones

    app.include_router(internas.router)  # /internal: sin prefijo /api/v1 ni API Gateway
    app.include_router(campos.router, prefix="/api/v1")
    app.include_router(opciones.router, prefix="/api/v1")
