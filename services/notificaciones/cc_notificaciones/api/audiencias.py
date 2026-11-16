"""Audiencias guardadas (NOT-01 a NOT-06)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cc_notificaciones.dependencias import campos, colaboradores, motor, usuario_actual
from cc_notificaciones.servicios import audiencias as servicio

router = APIRouter(prefix="/audiencias", tags=["audiencias"])

Nombre = Annotated[str, Field(min_length=1, max_length=100)]
Editar = Permiso.NOTIFICACIONES_EDITAR


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AudienciaCrear(_Base):
    nombre: Nombre
    criterios: dict[str, Any]


class AudienciaActualizar(_Base):
    nombre: Nombre | None = None
    criterios: dict[str, Any] | None = None
    activa: bool | None = None

    @model_validator(mode="after")
    def _no_nulos(self):
        for c in self.model_fields_set:
            if getattr(self, c) is None:
                raise ValueError(f"{c} no puede quedar vacío.")
        return self


class AudienciaDto(BaseModel):
    id: int
    nombre: str
    activa: bool
    criterios: dict[str, Any]
    creada_por_usuario_id: int
    fecha_creacion: datetime

    @classmethod
    def de_fila(cls, f: dict[str, Any]) -> AudienciaDto:
        return cls(
            id=f["id"],
            nombre=f["nombre"],
            activa=f["activa"],
            criterios=f["criterios_json"],
            creada_por_usuario_id=f["creada_por_usuario_id"],
            fecha_creacion=f["fecha_creacion"],
        )


class PaginaAudiencias(BaseModel):
    items: list[AudienciaDto]
    siguiente: str | None = None


class Previsualizar(_Base):
    criterios: dict[str, Any]


class Total(BaseModel):
    total: int


@router.get("", response_model=PaginaAudiencias, summary="Listado de audiencias (NOT-01)")
async def listar(
    estado: Literal["activas", "inactivas", "todas"] = Query(default="activas"),
    cursor: str | None = Query(default=None, max_length=200),
    limite: int | None = Query(default=None, ge=1, le=200),
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> PaginaAudiencias:
    p = await servicio.listar(m, u, estado, cursor, limite)
    return PaginaAudiencias(items=[AudienciaDto.de_fila(f) for f in p.items], siguiente=p.siguiente)


@router.post("", status_code=201, response_model=AudienciaDto, summary="Alta (NOT-02)")
async def crear(
    entrada: AudienciaCrear,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    c=Depends(campos),
) -> AudienciaDto:
    return AudienciaDto.de_fila(await servicio.crear(m, c, u, entrada.nombre, entrada.criterios))


@router.post(
    "/previsualizar",
    response_model=Total,
    summary="Conteo de la audiencia sin guardarla (NOT-06)",
)
async def previsualizar(
    entrada: Previsualizar,
    request: Request,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    c=Depends(campos),
    col=Depends(colaboradores),
) -> Total:
    zona = request.app.state.config.zona_horaria
    return Total(total=await servicio.previsualizar(c, col, u, entrada.criterios, zona))


@router.get("/{audiencia_id}", response_model=AudienciaDto, summary="Detalle (NOT-03)")
async def detalle(
    audiencia_id: int,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> AudienciaDto:
    return AudienciaDto.de_fila(await servicio.detalle(m, u, audiencia_id))


@router.patch("/{audiencia_id}", response_model=AudienciaDto, summary="Edición (NOT-04)")
async def actualizar(
    audiencia_id: int,
    entrada: AudienciaActualizar,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    c=Depends(campos),
) -> AudienciaDto:
    cambios = entrada.model_dump(exclude_unset=True)
    return AudienciaDto.de_fila(await servicio.actualizar(m, c, u, audiencia_id, cambios))


@router.delete("/{audiencia_id}", status_code=204, summary="Desactivación (NOT-05)")
async def desactivar(
    audiencia_id: int,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> Response:
    await servicio.desactivar(m, u, audiencia_id)
    return Response(status_code=204)
