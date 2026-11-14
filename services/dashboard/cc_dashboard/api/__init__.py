"""Routers del servicio dashboard. Cada tarea agrega su router aquí."""

from __future__ import annotations

from fastapi import FastAPI


def registrar_rutas(app: FastAPI) -> None:
    from cc_dashboard.api import usuarios

    app.include_router(usuarios.router, prefix="/api/v1")
