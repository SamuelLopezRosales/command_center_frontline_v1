"""Routers del servicio whatsapp."""

from __future__ import annotations

from fastapi import FastAPI


def registrar_rutas(app: FastAPI) -> None:
    from cc_whatsapp.api import conversaciones

    app.include_router(conversaciones.router, prefix="/api/v1")
