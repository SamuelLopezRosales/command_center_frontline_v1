"""Plantillas de constancia (CON-01 a CON-06)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cc_constancias.dependencias import almacen, ip_cliente, motor, usuario_actual
from cc_constancias.servicios import plantillas as servicio

router = APIRouter(tags=["plantillas"])

Editar = Permiso.PLANTILLAS_EDITAR
Nombre = Annotated[str, Field(min_length=1, max_length=120)]
Descripcion = Annotated[str, Field(max_length=500)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PlantillaCrear(_Base):
    nombre: Nombre
    descripcion: Descripcion | None = None


class PlantillaActualizar(_Base):
    nombre: Nombre | None = None
    descripcion: Descripcion | None = None
    activa: bool | None = None

    @model_validator(mode="after")
    def _no_nulos(self):
        for c in self.model_fields_set - {"descripcion"}:
            if getattr(self, c) is None:
                raise ValueError(f"{c} no puede quedar vacío.")
        return self


class Plantilla(BaseModel):
    id: int
    nombre: str
    descripcion: str | None
    estado: Literal["ACTIVA", "INACTIVA", "BORRADOR"]
    activa: bool
    version: int | None  # última versión publicada
    tiene_borrador: bool
    emitidas: int
    fecha_creacion: datetime
    fecha_modificacion: datetime

    @classmethod
    def de_fila(cls, f: dict) -> Plantilla:
        return cls(**{k: f[k] for k in cls.model_fields})


class PlantillasSalida(BaseModel):
    items: list[Plantilla]


@router.get("/plantillas", response_model=PlantillasSalida, summary="Listado (CON-01)")
async def listar(
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual), m=Depends(motor)
) -> PlantillasSalida:
    return PlantillasSalida(items=[Plantilla.de_fila(f) for f in await servicio.listar(m, u)])


@router.post("/plantillas", status_code=201, response_model=Plantilla, summary="Alta (CON-02)")
async def crear(
    entrada: PlantillaCrear,
    request: Request,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> Plantilla:
    f = await servicio.crear(m, u, entrada.nombre, entrada.descripcion, ip_cliente(request))
    return Plantilla.de_fila(f)


@router.get("/plantillas/{plantilla_id}", response_model=Plantilla, summary="Detalle (CON-03)")
async def detalle(
    plantilla_id: int,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> Plantilla:
    return Plantilla.de_fila(await servicio.detalle(m, u, plantilla_id))


@router.patch("/plantillas/{plantilla_id}", response_model=Plantilla, summary="Edición (CON-04)")
async def actualizar(
    plantilla_id: int,
    entrada: PlantillaActualizar,
    request: Request,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> Plantilla:
    f = await servicio.actualizar(
        m, u, plantilla_id, entrada.model_dump(exclude_unset=True), ip_cliente(request)
    )
    return Plantilla.de_fila(f)


@router.post(
    "/plantillas/{plantilla_id}/duplicar",
    status_code=201,
    response_model=Plantilla,
    summary="Duplicado (CON-05)",
)
async def duplicar(
    plantilla_id: int,
    request: Request,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen),
) -> Plantilla:
    f = await servicio.duplicar(m, a, u, plantilla_id, ip_cliente(request))
    return Plantilla.de_fila(f)


@router.delete("/plantillas/{plantilla_id}", status_code=204, summary="Eliminación lógica (CON-06)")
async def eliminar(
    plantilla_id: int,
    request: Request,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> Response:
    await servicio.eliminar(m, u, plantilla_id, ip_cliente(request))
    return Response(status_code=204)
