"""Borrador de una plantilla (CON-07 y CON-08)."""

from __future__ import annotations

from datetime import datetime

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel

from cc_constancias.contenido import ContenidoPlantilla
from cc_constancias.dependencias import almacen, ip_cliente, motor, usuario_actual
from cc_constancias.errores import contenido_demasiado_grande
from cc_constancias.servicios import borrador as servicio

router = APIRouter(tags=["borrador"])

Editar = Permiso.PLANTILLAS_EDITAR


class BorradorLeido(BaseModel):
    contenido: ContenidoPlantilla
    hash: str
    fecha_modificacion: datetime


class BorradorGuardado(BaseModel):
    hash: str
    fecha_modificacion: datetime


async def _cuerpo(request: Request, maximo: int) -> bytes:
    """Lee el cuerpo sin pasar de ``maximo``: un cuerpo enorme se corta con 413 sin cargarlo."""
    declarado = request.headers.get("content-length", "")
    if declarado.isdigit() and int(declarado) > maximo:
        raise contenido_demasiado_grande(maximo)
    trozos: list[bytes] = []
    total = 0
    async for trozo in request.stream():
        total += len(trozo)
        if total > maximo:
            raise contenido_demasiado_grande(maximo)
        trozos.append(trozo)
    return b"".join(trozos)


@router.get(
    "/plantillas/{plantilla_id}/borrador",
    response_model=BorradorLeido,
    response_model_exclude_none=True,  # el contenido se entrega en su forma canónica
    summary="Borrador (CON-07)",
)
async def obtener(
    plantilla_id: int,
    response: Response,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen),
) -> BorradorLeido:
    b = await servicio.obtener(m, a, u, plantilla_id)
    response.headers["ETag"] = b.etag
    return BorradorLeido(
        contenido=ContenidoPlantilla.model_validate(b.contenido),
        hash=b.hash,
        fecha_modificacion=b.fecha_modificacion,
    )


@router.put(
    "/plantillas/{plantilla_id}/borrador",
    response_model=BorradorGuardado,
    summary="Guarda el borrador (CON-08)",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/ContenidoPlantilla"}}
            },
        }
    },
)
async def guardar(
    plantilla_id: int,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None),
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen),
) -> BorradorGuardado:
    maximo = request.app.state.config.contenido_max_bytes
    cuerpo = await _cuerpo(request, maximo)
    b = await servicio.guardar(m, a, u, plantilla_id, cuerpo, if_match, maximo, ip_cliente(request))
    response.headers["ETag"] = b.etag
    return BorradorGuardado(hash=b.hash, fecha_modificacion=b.fecha_modificacion)
