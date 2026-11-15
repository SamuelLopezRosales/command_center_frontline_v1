"""Routers del servicio constancias. Cada tarea agrega su router aquí."""

from __future__ import annotations

from fastapi import FastAPI


def registrar_rutas(app: FastAPI) -> None:
    from cc_constancias.api import borrador, plantillas, variables

    app.include_router(plantillas.router, prefix="/api/v1")
    app.include_router(borrador.router, prefix="/api/v1")
    app.include_router(variables.router, prefix="/api/v1")  # antes de /constancias/{id} (CON-16)
