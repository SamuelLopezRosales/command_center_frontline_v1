"""Dependencias de FastAPI del servicio whatsapp (chat de RH)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cc_common.auth import UsuarioActual, extraer_bearer
from cc_common.errores import ErrorInterno
from fastapi import Header, Request

from cc_whatsapp.servicios.ventana_service import VentanaService


def usuario_actual(
    request: Request, authorization: str | None = Header(default=None)
) -> UsuarioActual:
    return request.app.state.verificador.verificar(extraer_bearer(authorization))


def motor(request: Request) -> Any:
    return request.app.state.motor


def ip_cliente(request: Request) -> str | None:
    """IP del cliente para la bitácora (``X-Forwarded-For`` lo pone el balanceador)."""
    adelante = request.headers.get("x-forwarded-for")
    if adelante:
        return adelante.split(",")[0].strip() or None
    return request.client.host if request.client else None


def reloj(request: Request) -> datetime:
    return request.app.state.reloj()


def ventana(request: Request) -> VentanaService:
    return VentanaService(request.app.state.config.ventana_horas)


def _cliente_interno(estado, url: str):
    from cc_common.internal_client import ClienteInterno

    return ClienteInterno(url, servicio="whatsapp", secreto=estado.secreto_interno)


def cifrador(request: Request) -> Any:
    estado = request.app.state
    if estado.cifrador is None:
        cfg = estado.config
        if cfg.kms_llave_datos:
            from cc_whatsapp.cifrado import cifrador_desde_config

            estado.cifrador = cifrador_desde_config(cfg)
        else:
            raise ErrorInterno("SERVICIO_NO_CONFIGURADO", "Servicio no configurado.")
    return estado.cifrador


def colaboradores(request: Request) -> Any:
    estado = request.app.state
    if estado.colaboradores is None:
        cfg = estado.config
        if cfg.colaboradores_url:
            from cc_whatsapp.clientes import ColaboradoresHttp

            estado.colaboradores = ColaboradoresHttp(
                _cliente_interno(estado, cfg.colaboradores_url)
            )
        elif cfg.es_local:
            from cc_whatsapp.clientes import StubColaboradoresChat

            estado.colaboradores = StubColaboradoresChat()
        else:
            raise ErrorInterno("SERVICIO_NO_CONFIGURADO", "Servicio no configurado.")
    return estado.colaboradores


def notificaciones(request: Request) -> Any:
    estado = request.app.state
    if estado.notificaciones is None:
        cfg = estado.config
        if cfg.notificaciones_url:
            from cc_whatsapp.clientes import NotificacionesHttp

            estado.notificaciones = NotificacionesHttp(
                _cliente_interno(estado, cfg.notificaciones_url)
            )
        elif cfg.es_local:
            from cc_whatsapp.clientes import StubNotificaciones

            estado.notificaciones = StubNotificaciones()
        else:
            raise ErrorInterno("SERVICIO_NO_CONFIGURADO", "Servicio no configurado.")
    return estado.notificaciones
