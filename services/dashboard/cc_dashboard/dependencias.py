"""Dependencias de FastAPI del servicio dashboard.

Los recursos (motor de base de datos, verificador de tokens, cliente de Cognito) se guardan en
``app.state`` al crear la aplicación, lo que permite sustituirlos en las pruebas.
"""

from __future__ import annotations

from typing import Any

from cc_common.auth import UsuarioActual, extraer_bearer
from fastapi import Header, Request


def usuario_actual(
    request: Request, authorization: str | None = Header(default=None)
) -> UsuarioActual:
    verificador = request.app.state.verificador
    return verificador.verificar(extraer_bearer(authorization))


def motor(request: Request) -> Any:
    return request.app.state.motor


def ip_cliente(request: Request) -> str | None:
    """IP real del visitante: CloudFront la envía en ``CloudFront-Viewer-Address`` (ip:puerto)."""
    visor = request.headers.get("cloudfront-viewer-address")
    if visor:
        return visor.rsplit(":", 1)[0].strip("[]")
    return request.client.host if request.client else None
