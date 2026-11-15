"""Dependencias de FastAPI del servicio constancias.

Los recursos (motor, verificador de tokens, almacén S3 y clientes de campos y colaboradores) viven
en ``app.state`` para poder sustituirlos en las pruebas. Los de AWS y los clientes HTTP se crean al
primer uso: así el servicio arranca y expone su OpenAPI sin credenciales.
"""

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


def almacen(request: Request) -> Any:
    estado = request.app.state
    if estado.almacen is None:
        from cc_constancias.almacenamiento import almacen_desde_config

        estado.almacen = almacen_desde_config(estado.config)
    return estado.almacen


def _cliente_interno(estado: Any, url: str) -> Any:
    from cc_common.internal_client import ClienteInterno

    return ClienteInterno(url, servicio="constancias", secreto=estado.secreto_interno)


def campos(request: Request) -> Any:
    estado = request.app.state
    if estado.campos is None:
        cfg = estado.config
        if cfg.campos_url:
            from cc_constancias.clientes import CamposHttp

            estado.campos = CamposHttp(_cliente_interno(estado, cfg.campos_url))
        elif cfg.es_local:
            from cc_constancias.clientes import StubCampos

            estado.campos = StubCampos()
        else:
            raise ErrorInterno("SERVICIO_NO_CONFIGURADO", "Servicio no configurado.")
    return estado.campos


def colaboradores(request: Request) -> Any:
    estado = request.app.state
    if estado.colaboradores is None:
        cfg = estado.config
        if cfg.colaboradores_url:
            from cc_constancias.clientes import ColaboradoresHttp

            estado.colaboradores = ColaboradoresHttp(
                _cliente_interno(estado, cfg.colaboradores_url)
            )
        elif cfg.es_local:
            from cc_constancias.clientes import StubColaboradores

            estado.colaboradores = StubColaboradores()
        else:
            raise ErrorInterno("SERVICIO_NO_CONFIGURADO", "Servicio no configurado.")
    return estado.colaboradores


def cargador_logotipo(request: Request) -> Any:
    estado = request.app.state
    if estado.logotipos is None:
        from cc_constancias.render.logotipo import CargadorLogotipo

        cfg = estado.config
        estado.logotipos = CargadorLogotipo(
            almacen(request),
            ttl_s=cfg.logotipo_cache_segundos,
            maximo=cfg.logotipo_max_bytes,
        )
    return estado.logotipos


def ip_cliente(request: Request) -> str | None:
    """IP real del visitante: CloudFront la envía en ``CloudFront-Viewer-Address`` (ip:puerto)."""
    visor = request.headers.get("cloudfront-viewer-address")
    if visor:
        return visor.rsplit(":", 1)[0].strip("[]")
    return request.client.host if request.client else None
