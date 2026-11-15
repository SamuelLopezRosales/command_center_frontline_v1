"""Routers del servicio colaboradores. Cada tarea agrega su router aquí."""

from __future__ import annotations

from fastapi import FastAPI


def registrar_rutas(app: FastAPI) -> None:
    from cc_colaboradores.api import organizaciones, plantas

    app.include_router(organizaciones.router, prefix="/api/v1")
    app.include_router(plantas.router, prefix="/api/v1")
