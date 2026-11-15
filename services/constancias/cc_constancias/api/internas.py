"""Rutas ``/internal`` de constancias (INT-CON-01 a INT-CON-06).

No están en API Gateway: solo se alcanzan desde las tareas por grupo de seguridad, con el token
interno (design.md §11.1). La empresa llega en ``X-Empresa-Id``.
"""

from __future__ import annotations

from datetime import datetime

from cc_common.internal_client import LlamadaInterna, requiere_servicio
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from cc_constancias.dependencias import almacen, campos, colaboradores, motor
from cc_constancias.servicios import solicitudes as servicio

router = APIRouter(prefix="/internal", tags=["internas"])

WHATSAPP = requiere_servicio("whatsapp")
CAMPOS = requiere_servicio("campos")


class PlantillaDisponible(BaseModel):
    id: int
    nombre: str
    descripcion: str | None = None
    version: int


class PlantillasDisponibles(BaseModel):
    plantillas: list[PlantillaDisponible]


class SolicitudEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    colaborador_id: int = Field(ge=1)
    conversacion_id: int | None = Field(default=None, ge=1)
    colaborador_nombre: str = Field(min_length=1, max_length=200)


class SolicitudSalida(BaseModel):
    id: int
    estado: str
    version_plantilla_id: int | None = None
    fecha_solicitud: datetime


class PlantillaElegida(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plantilla_id: int = Field(ge=1)


class Usos(BaseModel):
    class Plantilla(BaseModel):
        id: int
        nombre: str

    usos: dict[str, list[Plantilla]]


def _salida(s: dict) -> SolicitudSalida:
    return SolicitudSalida(
        id=s["id"],
        estado=s["estado"],
        version_plantilla_id=s["version_plantilla_id"],
        fecha_solicitud=s["fecha_solicitud"],
    )


@router.get(
    "/plantillas/activas",
    response_model=PlantillasDisponibles,
    summary="Plantillas activas con versión publicada (INT-CON-01)",
)
async def disponibles(ll: LlamadaInterna = WHATSAPP, m=Depends(motor)) -> PlantillasDisponibles:
    filas = await servicio.plantillas(m, ll.empresa_id)
    return PlantillasDisponibles(plantillas=[PlantillaDisponible(**f) for f in filas])


@router.post(
    "/solicitudes",
    status_code=201,
    response_model=SolicitudSalida,
    summary="Crea una solicitud de constancia (INT-CON-02)",
)
async def crear(
    e: SolicitudEntrada, ll: LlamadaInterna = WHATSAPP, m=Depends(motor)
) -> SolicitudSalida:
    s = await servicio.crear(
        m,
        ll.empresa_id,
        colaborador_id=e.colaborador_id,
        conversacion_id=e.conversacion_id,
        nombre=e.colaborador_nombre,
    )
    return _salida(s)


@router.post(
    "/solicitudes/{solicitud_id}/plantilla",
    response_model=SolicitudSalida,
    summary="Fija la plantilla elegida (INT-CON-03)",
)
async def elegir(
    solicitud_id: int, e: PlantillaElegida, ll: LlamadaInterna = WHATSAPP, m=Depends(motor)
) -> SolicitudSalida:
    return _salida(await servicio.fijar_plantilla(m, ll.empresa_id, solicitud_id, e.plantilla_id))


@router.post(
    "/solicitudes/{solicitud_id}/generar",
    status_code=202,
    summary="Valida los datos y encola el PDF (INT-CON-04)",
)
async def generar(
    solicitud_id: int,
    request: Request,
    ll: LlamadaInterna = WHATSAPP,
    m=Depends(motor),
    a=Depends(almacen),
    c=Depends(campos),
    col=Depends(colaboradores),
) -> Response:
    await servicio.generar(m, a, c, col, request.app.state.config, ll.empresa_id, solicitud_id)
    return Response(status_code=202)


@router.post(
    "/solicitudes/{solicitud_id}/cancelar",
    response_model=SolicitudSalida,
    summary="Cancela una solicitud recibida (INT-CON-05)",
)
async def cancelar(
    solicitud_id: int, ll: LlamadaInterna = WHATSAPP, m=Depends(motor)
) -> SolicitudSalida:
    return _salida(await servicio.cancelar(m, ll.empresa_id, solicitud_id))


@router.get(
    "/plantillas/uso-de-variable",
    response_model=Usos,
    summary="Plantillas que usan cada variable (INT-CON-06)",
)
async def uso_de_variable(
    variable: list[str] = Query(min_length=1, max_length=50),
    ll: LlamadaInterna = CAMPOS,
    m=Depends(motor),
    a=Depends(almacen),
) -> Usos:
    return Usos(usos=await servicio.uso_de_variables(m, a, ll.empresa_id, variable))
