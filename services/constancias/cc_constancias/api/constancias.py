"""Constancias emitidas: detalle, descarga y reenvío (CON-16 a CON-18)."""

from __future__ import annotations

from datetime import datetime

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from cc_constancias.dependencias import firmador, ip_cliente, motor, usuario_actual
from cc_constancias.servicios import constancias as servicio

router = APIRouter(tags=["constancias"])


class ConstanciaDetalle(BaseModel):
    id: int
    folio: str
    solicitud_id: int
    colaborador_id: int
    colaborador_nombre: str
    numero_empleado: str
    plantilla_id: int
    plantilla_nombre: str
    version: int
    fecha_generacion: datetime
    estado_entrega: str
    fecha_entrega: datetime | None = None
    estado_vigencia: str


class UrlDescarga(BaseModel):
    url: str
    expira: datetime


@router.get(
    "/constancias/{constancia_id}",
    response_model=ConstanciaDetalle,
    summary="Detalle de una constancia emitida (CON-16)",
)
async def detalle(
    constancia_id: int,
    u: UsuarioActual = requiere_permiso(Permiso.CONSTANCIAS_VER, usuario_actual),
    m=Depends(motor),
) -> ConstanciaDetalle:
    return ConstanciaDetalle(**await servicio.detalle(m, u, constancia_id))


@router.post(
    "/constancias/{constancia_id}/descarga",
    response_model=UrlDescarga,
    summary="URL firmada de 24 horas para RH (CON-17)",
)
async def descarga(
    constancia_id: int,
    request: Request,
    u: UsuarioActual = requiere_permiso(Permiso.CONSTANCIAS_VER, usuario_actual),
    m=Depends(motor),
    f=Depends(firmador),
) -> UrlDescarga:
    r = await servicio.descarga(m, f, u, constancia_id, ip_cliente(request))
    return UrlDescarga(url=r.url, expira=r.expira)


@router.post(
    "/constancias/{constancia_id}/reenviar",
    status_code=202,
    summary="Reenvía una constancia cuya entrega falló (CON-18)",
)
async def reenviar(
    constancia_id: int,
    request: Request,
    u: UsuarioActual = requiere_permiso(Permiso.CONSTANCIAS_REENVIAR, usuario_actual),
    m=Depends(motor),
) -> Response:
    await servicio.reenviar(m, request.app.state.config, u, constancia_id, ip_cliente(request))
    return Response(status_code=202)
