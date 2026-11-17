"""Plantillas de mensaje (NOT-07 a NOT-13; design.md §3.6; CC-REQ-117)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cc_notificaciones.dependencias import meta, motor, usuario_actual
from cc_notificaciones.servicios import plantillas as servicio

router = APIRouter(prefix="/plantillas-mensaje", tags=["plantillas-mensaje"])

Editar = Permiso.NOTIFICACIONES_EDITAR
Categoria = Literal["UTILITY", "MARKETING", "AUTHENTICATION"]
Estado = Literal["BORRADOR", "EN_REVISION", "APROBADA", "RECHAZADA"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PlantillaCrear(_Base):
    nombre: Annotated[str, Field(min_length=1, max_length=512)]
    categoria: Categoria
    idioma: Annotated[str, Field(min_length=2, max_length=10)] = "es_MX"
    texto_con_variables: Annotated[str, Field(min_length=1, max_length=1024)]
    ejemplos: Annotated[list[str], Field(max_length=20)] = []


class PlantillaActualizar(_Base):
    nombre: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    categoria: Categoria | None = None
    idioma: Annotated[str, Field(min_length=2, max_length=10)] | None = None
    texto_con_variables: Annotated[str, Field(min_length=1, max_length=1024)] | None = None
    ejemplos: Annotated[list[str], Field(max_length=20)] | None = None

    @model_validator(mode="after")
    def _no_nulos(self):
        for c in self.model_fields_set:
            if getattr(self, c) is None:
                raise ValueError(f"{c} no puede quedar vacío.")
        return self


class PlantillaDto(BaseModel):
    id: int
    nombre: str
    categoria: Categoria
    idioma: str
    texto_con_variables: str
    ejemplos: list[str]
    cantidad_variables: int
    formato_variables: Literal["POSICIONAL", "NOMBRADO"]
    variables: list[str]
    estado_meta: Estado
    id_plantilla_meta: str | None
    motivo_rechazo: str | None
    creada_por_usuario_id: int
    fecha_creacion: datetime

    @classmethod
    def de_fila(cls, f: dict[str, Any]) -> PlantillaDto:
        v = servicio.variables_de(f["texto_con_variables"])
        return cls(
            id=f["id"],
            nombre=f["nombre"],
            categoria=f["categoria"],
            idioma=f["idioma"],
            texto_con_variables=f["texto_con_variables"],
            ejemplos=f["ejemplos_json"] or [],
            cantidad_variables=v.cantidad,
            formato_variables=v.formato,  # type: ignore[arg-type]
            variables=list(v.nombres),
            estado_meta=f["estado_meta"],
            id_plantilla_meta=f["id_plantilla_meta"],
            motivo_rechazo=f["motivo_rechazo"],
            creada_por_usuario_id=f["creada_por_usuario_id"],
            fecha_creacion=f["fecha_creacion"],
        )


class PaginaPlantillas(BaseModel):
    items: list[PlantillaDto]
    siguiente: str | None = None


@router.get("", response_model=PaginaPlantillas, summary="Listado de plantillas (NOT-07)")
async def listar(
    estado: Estado | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=200),
    limite: int | None = Query(default=None, ge=1, le=200),
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> PaginaPlantillas:
    p = await servicio.listar(m, u, estado, cursor, limite)
    return PaginaPlantillas(items=[PlantillaDto.de_fila(f) for f in p.items], siguiente=p.siguiente)


@router.post("", status_code=201, response_model=PlantillaDto, summary="Alta (NOT-08)")
async def crear(
    entrada: PlantillaCrear,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> PlantillaDto:
    f = await servicio.crear(
        m,
        u,
        nombre=entrada.nombre,
        categoria=entrada.categoria,
        idioma=entrada.idioma,
        texto=entrada.texto_con_variables,
        ejemplos=entrada.ejemplos,
    )
    return PlantillaDto.de_fila(f)


@router.get("/{plantilla_id}", response_model=PlantillaDto, summary="Detalle (NOT-09)")
async def detalle(
    plantilla_id: int,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> PlantillaDto:
    return PlantillaDto.de_fila(await servicio.detalle(m, u, plantilla_id))


@router.patch("/{plantilla_id}", response_model=PlantillaDto, summary="Edición (NOT-10)")
async def actualizar(
    plantilla_id: int,
    entrada: PlantillaActualizar,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> PlantillaDto:
    cambios = entrada.model_dump(exclude_unset=True)
    return PlantillaDto.de_fila(await servicio.actualizar(m, u, plantilla_id, cambios))


@router.post(
    "/{plantilla_id}/enviar-revision",
    status_code=202,
    response_model=PlantillaDto,
    summary="Envío a revisión de Meta (NOT-11)",
)
async def enviar_revision(
    plantilla_id: int,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    cliente=Depends(meta),
) -> PlantillaDto:
    return PlantillaDto.de_fila(await servicio.enviar_a_revision(m, cliente, u, plantilla_id))


@router.post(
    "/{plantilla_id}/duplicar",
    status_code=201,
    response_model=PlantillaDto,
    summary="Duplicar como borrador (NOT-12)",
)
async def duplicar(
    plantilla_id: int,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> PlantillaDto:
    return PlantillaDto.de_fila(await servicio.duplicar(m, u, plantilla_id))


@router.post(
    "/{plantilla_id}/sincronizar",
    status_code=202,
    response_model=PlantillaDto,
    summary="Sincronizar el estado con Meta (NOT-13)",
)
async def sincronizar(
    plantilla_id: int,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    cliente=Depends(meta),
) -> PlantillaDto:
    return PlantillaDto.de_fila(await servicio.sincronizar(m, cliente, u, plantilla_id))
