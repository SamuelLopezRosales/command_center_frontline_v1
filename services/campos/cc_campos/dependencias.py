"""Dependencias de FastAPI del servicio campos."""

from __future__ import annotations

from typing import Any

from cc_common.auth import UsuarioActual, extraer_bearer
from cc_common.errores import ErrorInterno
from fastapi import Header, Request


def usuario_actual(
    request: Request, authorization: str | None = Header(default=None)
) -> UsuarioActual:
    return request.app.state.verificador.verificar(extraer_bearer(authorization))


def motor(request: Request) -> Any:
    return request.app.state.motor


def _cliente_interno(estado, url: str):
    from cc_common.internal_client import ClienteInterno

    return ClienteInterno(url, servicio="campos", secreto=estado.secreto_interno)


def colaboradores(request: Request) -> Any:
    estado = request.app.state
    if estado.colaboradores is None:
        cfg = estado.config
        if cfg.colaboradores_url:
            from cc_campos.clientes import ColaboradoresHttp

            estado.colaboradores = ColaboradoresHttp(
                _cliente_interno(estado, cfg.colaboradores_url)
            )
        elif cfg.es_local:
            from cc_campos.clientes import StubColaboradores

            estado.colaboradores = StubColaboradores()
        else:
            raise ErrorInterno("SERVICIO_NO_CONFIGURADO", "Servicio no configurado.")
    return estado.colaboradores


def constancias(request: Request) -> Any:
    estado = request.app.state
    if estado.constancias is None:
        cfg = estado.config
        if cfg.constancias_url:
            from cc_campos.clientes import ConstanciasHttp

            estado.constancias = ConstanciasHttp(_cliente_interno(estado, cfg.constancias_url))
        elif cfg.es_local:
            from cc_campos.clientes import StubConstancias

            estado.constancias = StubConstancias()
        else:
            raise ErrorInterno("SERVICIO_NO_CONFIGURADO", "Servicio no configurado.")
    return estado.constancias


def ip_cliente(request: Request) -> str | None:
    """IP real del visitante: CloudFront la envía en ``CloudFront-Viewer-Address`` (ip:puerto)."""
    visor = request.headers.get("cloudfront-viewer-address")
    if visor:
        return visor.rsplit(":", 1)[0].strip("[]")
    return request.client.host if request.client else None
