"""Campos dinámicos (CAM-01 a CAM-06)."""

from __future__ import annotations

from typing import Annotated, Literal

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cc_campos import catalogo
from cc_campos.dependencias import colaboradores, constancias, ip_cliente, motor, usuario_actual
from cc_campos.servicios import campos as servicio

router = APIRouter(tags=["campos"])

Tipo = Literal["TEXTO", "NUMERO", "FECHA", "LISTA", "SI_NO"]
Nombre = Annotated[str, Field(min_length=1, max_length=100)]
Clave = Annotated[str, Field(pattern=catalogo.CLAVE_PATRON.pattern)]
Formato = Annotated[str, Field(min_length=1, max_length=catalogo.FORMATO_MAXIMO)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CampoCrear(_Base):
    nombre_campo: Nombre
    clave: Clave
    tipo_dato: Tipo
    formato_validacion: Formato | None = None
    obligatorio: bool = False
    es_sensible: bool = False
    orden: int | None = Field(default=None, ge=0, le=100000)

    @field_validator("clave", mode="before")
    @classmethod
    def _minusculas(cls, v):
        return v.strip().lower() if isinstance(v, str) else v


class CampoActualizar(_Base):
    """Parcial. El código interno no está: no cambia nunca (CC-REQ-046)."""

    nombre_campo: Nombre | None = None
    clave: Clave | None = None
    tipo_dato: Tipo | None = None
    formato_validacion: Formato | None = None
    obligatorio: bool | None = None
    es_sensible: bool | None = None
    activo: bool | None = None
    confirmar: bool = False

    @model_validator(mode="after")
    def _no_nulos(self):
        for c in self.model_fields_set - {"formato_validacion", "confirmar"}:
            if getattr(self, c) is None:
                raise ValueError(f"{c} no puede quedar vacío.")
        return self


class OpcionDto(BaseModel):
    id: int
    etiqueta: str
    valor: str
    descripcion: str | None
    orden: int
    activo: bool


class CampoDto(BaseModel):
    id: int
    nombre_campo: str
    clave: str
    codigo_interno: str
    tipo_dato: Tipo
    formato_validacion: str | None
    obligatorio: bool
    orden: int
    activo: bool
    es_sensible: bool
    es_sugerido: bool
    usada_en_plantillas: int | None = None  # None: `constancias` no respondió
    opciones: list[OpcionDto] | None = None

    @classmethod
    def de_fila(cls, f: dict) -> CampoDto:
        opciones = f.get("opciones")
        return cls(
            **{k: f[k] for k in cls.model_fields if k not in ("opciones", "usada_en_plantillas")},
            usada_en_plantillas=f.get("usada_en_plantillas"),
            opciones=None if opciones is None else [OpcionDto(**o) for o in opciones],
        )


class CampoFijoDto(BaseModel):
    clave: str
    nombre: str
    tipo_dato: Tipo
    obligatorio: bool


class ListadoCampos(BaseModel):
    fijos: list[CampoFijoDto]
    dinamicos: list[CampoDto]


class OrdenItem(_Base):
    id: int = Field(ge=1)
    orden: int = Field(ge=0, le=100000)


Administrar = Permiso.CAMPOS_ADMINISTRAR


@router.get("/campos", response_model=ListadoCampos, summary="Listado de campos (CAM-01)")
async def listar(
    estado: Literal["todos", "activos", "inactivos"] = Query(default="todos"),
    tipo: Literal["todos", "sugeridos", "personalizados"] = Query(default="todos"),
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
    c=Depends(constancias),
) -> ListadoCampos:
    filas = await servicio.listar(m, c, u, estado, tipo)
    return ListadoCampos(
        fijos=[
            CampoFijoDto(
                clave=f.clave, nombre=f.nombre, tipo_dato=f.tipo_dato, obligatorio=f.obligatorio
            )
            for f in catalogo.FIJOS
        ],
        dinamicos=[CampoDto.de_fila(f) for f in filas],
    )


@router.post("/campos", status_code=201, response_model=CampoDto, summary="Alta (CAM-02)")
async def crear(
    entrada: CampoCrear,
    request: Request,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
) -> CampoDto:
    campo = await servicio.crear(
        m, request.app.state.config, u, entrada.model_dump(), ip_cliente(request)
    )
    return CampoDto.de_fila(campo)


@router.get("/campos/{campo_id}", response_model=CampoDto, summary="Detalle (CAM-03)")
async def detalle(
    campo_id: int,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
    c=Depends(constancias),
) -> CampoDto:
    return CampoDto.de_fila(await servicio.detalle(m, c, u, campo_id))


@router.patch("/campos/{campo_id}", response_model=CampoDto, summary="Edición (CAM-04)")
async def actualizar(
    campo_id: int,
    entrada: CampoActualizar,
    request: Request,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
    col=Depends(colaboradores),
    c=Depends(constancias),
) -> CampoDto:
    cambios = entrada.model_dump(exclude_unset=True, exclude={"confirmar"})
    campo = await servicio.actualizar(
        m,
        request.app.state.config,
        col,
        c,
        u,
        campo_id,
        cambios,
        entrada.confirmar,
        ip_cliente(request),
    )
    return CampoDto.de_fila(campo)


@router.delete("/campos/{campo_id}", status_code=204, summary="Eliminación lógica (CAM-05)")
async def eliminar(
    campo_id: int,
    request: Request,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
    col=Depends(colaboradores),
) -> Response:
    await servicio.eliminar(m, request.app.state.config, col, u, campo_id, ip_cliente(request))
    return Response(status_code=204)


@router.put("/campos/orden", status_code=204, summary="Reordenamiento (CAM-06)")
async def ordenar(
    entrada: Annotated[list[OrdenItem], Field(min_length=1, max_length=200)],
    request: Request,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
) -> Response:
    await servicio.ordenar(
        m,
        request.app.state.config,
        u,
        [(i.id, i.orden) for i in entrada],
        ip_cliente(request),
    )
    return Response(status_code=204)
