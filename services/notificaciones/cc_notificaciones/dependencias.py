"""Dependencias de FastAPI del servicio notificaciones."""

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

    return ClienteInterno(url, servicio="notificaciones", secreto=estado.secreto_interno)


def campos(request: Request) -> Any:
    estado = request.app.state
    if estado.campos is None:
        cfg = estado.config
        if cfg.campos_url:
            from cc_notificaciones.clientes import CamposHttp

            estado.campos = CamposHttp(_cliente_interno(estado, cfg.campos_url))
        elif cfg.es_local:
            from cc_notificaciones.clientes import StubCampos

            estado.campos = StubCampos()
        else:
            raise ErrorInterno("SERVICIO_NO_CONFIGURADO", "Servicio no configurado.")
    return estado.campos


def colaboradores(request: Request) -> Any:
    estado = request.app.state
    if estado.colaboradores is None:
        cfg = estado.config
        if cfg.colaboradores_url:
            from cc_notificaciones.clientes import ColaboradoresHttp

            estado.colaboradores = ColaboradoresHttp(
                _cliente_interno(estado, cfg.colaboradores_url)
            )
        elif cfg.es_local:
            from cc_notificaciones.clientes import StubColaboradores

            estado.colaboradores = StubColaboradores()
        else:
            raise ErrorInterno("SERVICIO_NO_CONFIGURADO", "Servicio no configurado.")
    return estado.colaboradores


def meta(request: Request) -> Any:
    """Cliente de plantillas de Meta. Las credenciales se leen de Secrets Manager por id
    (``CC_META_SECRETO_ID``); sin él, solo en local hay un sustituto sin red."""
    estado = request.app.state
    if estado.meta is None:
        cfg = estado.config
        if cfg.meta_secreto_id and not (cfg.es_local and cfg.meta_plantillas_stub):
            from cc_notificaciones.meta import MetaPlantillasHttp, cargador_credenciales

            estado.meta = MetaPlantillasHttp(
                cargador_credenciales(cfg.meta_secreto_id, cfg.region),
                base=cfg.meta_api_base,
                version=cfg.meta_api_version,
                timeout_s=cfg.meta_timeout_s,
            )
        elif cfg.es_local:
            from cc_notificaciones.meta import StubPlantillasMeta

            estado.meta = StubPlantillasMeta()
        else:
            raise ErrorInterno("SERVICIO_NO_CONFIGURADO", "Servicio no configurado.")
    return estado.meta


def almacen_meta(request: Request) -> Any:
    """Almacén de las credenciales de Meta: el secreto ``cc/{env}/meta`` (``CC_META_SECRETO_ID``).
    Sin él, solo en local se usa un sustituto en memoria."""
    estado = request.app.state
    if estado.almacen_meta is None:
        cfg = estado.config
        if cfg.meta_secreto_id:
            from cc_notificaciones.integracion_meta import AlmacenSecretsManager

            estado.almacen_meta = AlmacenSecretsManager(
                cfg.meta_secreto_id, cfg.region, endpoint=cfg.aws_endpoint
            )
        elif cfg.es_local:
            from cc_notificaciones.integracion_meta import AlmacenMemoria

            estado.almacen_meta = AlmacenMemoria()
        else:
            raise ErrorInterno("SERVICIO_NO_CONFIGURADO", "Servicio no configurado.")
    return estado.almacen_meta


def programador(request: Request) -> Any:
    """Cliente de EventBridge Scheduler. Sin destino configurado, solo en local se usa un
    sustituto en memoria (el conciliador de T-217 reencola las PROGRAMADA atrasadas)."""
    estado = request.app.state
    if estado.scheduler is None:
        cfg = estado.config
        if cfg.scheduler_destino_arn and cfg.scheduler_rol_arn:
            from cc_notificaciones.scheduler import SchedulerBoto

            estado.scheduler = SchedulerBoto(
                destino_arn=cfg.scheduler_destino_arn,
                rol_arn=cfg.scheduler_rol_arn,
                grupo=cfg.scheduler_grupo,
                region=cfg.region,
                endpoint=cfg.aws_endpoint,
            )
        elif cfg.es_local:
            from cc_notificaciones.scheduler import StubScheduler

            estado.scheduler = StubScheduler()
        else:
            raise ErrorInterno("SERVICIO_NO_CONFIGURADO", "Servicio no configurado.")
    return estado.scheduler
