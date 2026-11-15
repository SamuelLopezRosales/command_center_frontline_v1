"""Plantas (COL-13 a COL-15). Sin endpoint de borrado: solo se desactivan (CC-REQ-044)."""

from __future__ import annotations

from typing import Annotated

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cc_colaboradores.dependencias import ip_cliente, motor, usuario_actual
from cc_colaboradores.servicios import catalogos as servicio

router = APIRouter(tags=["plantas"])

Nombre = Annotated[str, Field(min_length=1, max_length=120)]


class PlantaCrear(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    nombre: Nombre


class PlantaActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    nombre: Nombre | None = None
    activa: bool | None = None

    @model_validator(mode="after")
    def _no_nulos(self):
        for campo in ("nombre", "activa"):
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"{campo} no puede quedar vacío.")
        return self


class Planta(BaseModel):
    id: int
    nombre: str
    activa: bool


class PlantasSalida(BaseModel):
    items: list[Planta]


@router.get("/plantas", response_model=PlantasSalida, summary="Plantas (COL-13)")
async def listar(
    solo_activas: bool = Query(default=False),
    u: UsuarioActual = requiere_permiso(Permiso.COLABORADORES_VER, usuario_actual),
    m=Depends(motor),
) -> PlantasSalida:
    return PlantasSalida(
        items=[Planta(**f) for f in await servicio.listar_plantas(m, u, solo_activas)]
    )


@router.post("/plantas", status_code=201, response_model=Planta, summary="Crea una planta (COL-14)")
async def crear(
    entrada: PlantaCrear,
    request: Request,
    u: UsuarioActual = requiere_permiso(Permiso.CATALOGOS_ADMINISTRAR, usuario_actual),
    m=Depends(motor),
) -> Planta:
    return Planta(**await servicio.crear_planta(m, u, entrada.nombre, ip_cliente(request)))


@router.patch(
    "/plantas/{planta_id}",
    response_model=Planta,
    summary="Actualiza o desactiva una planta (COL-15)",
)
async def actualizar(
    planta_id: int,
    entrada: PlantaActualizar,
    request: Request,
    u: UsuarioActual = requiere_permiso(Permiso.CATALOGOS_ADMINISTRAR, usuario_actual),
    m=Depends(motor),
) -> Planta:
    fila = await servicio.actualizar_planta(
        m, u, planta_id, entrada.model_dump(exclude_unset=True), ip_cliente(request)
    )
    return Planta(**fila)
