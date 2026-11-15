"""Opciones de los campos de lista (CAM-07 a CAM-09)."""

from __future__ import annotations

from typing import Annotated

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from cc_campos import catalogo
from cc_campos.api.campos import OpcionDto
from cc_campos.dependencias import ip_cliente, motor, usuario_actual
from cc_campos.servicios import opciones as servicio

router = APIRouter(tags=["opciones"])

Etiqueta = Annotated[str, Field(min_length=1, max_length=100)]
Descripcion = Annotated[str, Field(max_length=300)]
Administrar = Permiso.CAMPOS_ADMINISTRAR


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OpcionCrear(_Base):
    etiqueta: Etiqueta
    valor: str = Field(pattern=catalogo.VALOR_OPCION.pattern)
    descripcion: Descripcion | None = None
    orden: int | None = Field(default=None, ge=0, le=100000)

    @field_validator("valor", mode="before")
    @classmethod
    def _mayusculas(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class OpcionActualizar(_Base):
    """El ``valor`` no está: no cambia (enviarlo da 422 ``CAMPO_NO_PERMITIDO``)."""

    etiqueta: Etiqueta | None = None
    descripcion: Descripcion | None = None
    orden: int | None = Field(default=None, ge=0, le=100000)
    activo: bool | None = None

    @field_validator("etiqueta", "orden", "activo")
    @classmethod
    def _no_nulos(cls, v):
        if v is None:
            raise ValueError("No puede quedar vacío.")
        return v


class OpcionesSalida(BaseModel):
    items: list[OpcionDto]


@router.get(
    "/campos/{campo_id}/opciones", response_model=OpcionesSalida, summary="Opciones (CAM-07)"
)
async def listar(
    campo_id: int,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
) -> OpcionesSalida:
    return OpcionesSalida(items=[OpcionDto(**o) for o in await servicio.listar(m, u, campo_id)])


@router.post(
    "/campos/{campo_id}/opciones",
    status_code=201,
    response_model=OpcionDto,
    summary="Alta de opción (CAM-08)",
)
async def crear(
    campo_id: int,
    entrada: OpcionCrear,
    request: Request,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
) -> OpcionDto:
    o = await servicio.crear(
        m, request.app.state.config, u, campo_id, entrada.model_dump(), ip_cliente(request)
    )
    return OpcionDto(**o)


@router.patch(
    "/campos/{campo_id}/opciones/{opcion_id}",
    response_model=OpcionDto,
    summary="Edición o desactivación de una opción (CAM-09)",
)
async def actualizar(
    campo_id: int,
    opcion_id: int,
    entrada: OpcionActualizar,
    request: Request,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
) -> OpcionDto:
    o = await servicio.actualizar(
        m,
        request.app.state.config,
        u,
        campo_id,
        opcion_id,
        entrada.model_dump(exclude_unset=True),
        ip_cliente(request),
    )
    return OpcionDto(**o)
