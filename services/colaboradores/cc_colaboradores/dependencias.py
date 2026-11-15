"""Dependencias de FastAPI del servicio colaboradores.

Los recursos (motor, verificador de tokens, cifrador, almacén S3 y cliente de campos) viven en
``app.state`` para poder sustituirlos en las pruebas. El cifrador y el almacén de AWS se crean al
primer uso: así el servicio arranca y expone su OpenAPI sin credenciales.
"""

from __future__ import annotations

from typing import Any

from cc_common.auth import UsuarioActual, extraer_bearer
from fastapi import Header, Request


def usuario_actual(
    request: Request, authorization: str | None = Header(default=None)
) -> UsuarioActual:
    return request.app.state.verificador.verificar(extraer_bearer(authorization))


def motor(request: Request) -> Any:
    return request.app.state.motor


def almacen(request: Request) -> Any:
    estado = request.app.state
    if estado.almacen is None:
        from cc_colaboradores.almacenamiento import almacen_desde_config

        estado.almacen = almacen_desde_config(estado.config)
    return estado.almacen


def cifrador(request: Request) -> Any:
    estado = request.app.state
    if estado.cifrador is None:
        from cc_colaboradores.cifrado import cifrador_desde_config

        estado.cifrador = cifrador_desde_config(estado.config)
    return estado.cifrador


def campos(request: Request) -> Any:
    return request.app.state.campos


def ip_cliente(request: Request) -> str | None:
    """IP real del visitante: CloudFront la envía en ``CloudFront-Viewer-Address`` (ip:puerto)."""
    visor = request.headers.get("cloudfront-viewer-address")
    if visor:
        return visor.rsplit(":", 1)[0].strip("[]")
    return request.client.host if request.client else None
