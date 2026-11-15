"""Organizaciones y logotipo (COL-08 a COL-12). Sin endpoint de borrado (DS-04)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from cc_common.tipos import Correo, RegistroPatronal, RfcOrg
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cc_colaboradores.dependencias import almacen, ip_cliente, motor, usuario_actual
from cc_colaboradores.servicios import catalogos as servicio

router = APIRouter(tags=["organizaciones"])

Texto = Annotated[str, Field(min_length=1, max_length=250)]
TextoCorto = Annotated[str, Field(min_length=1, max_length=150)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OrganizacionCrear(_Base):
    clave: Annotated[str, Field(min_length=1, max_length=30)]
    razon_social: Texto
    rfc: RfcOrg | None = None
    registro_patronal: RegistroPatronal | None = None
    domicilio_fiscal: Annotated[str, Field(max_length=500)] | None = None
    ciudad: Annotated[str, Field(max_length=120)] | None = None
    nombre_firmante: TextoCorto | None = None
    cargo_firmante: TextoCorto | None = None
    correo_firmante: Correo | None = None

    @field_validator("clave")
    @classmethod
    def _clave(cls, v: str) -> str:
        v = v.upper()
        if not v.replace("_", "").replace("-", "").isalnum() or not v.isascii():
            raise ValueError("La clave solo admite letras, números, guion y guion bajo.")
        return v


class OrganizacionActualizar(_Base):
    """La clave no está: es inmutable (DS-04); enviarla da 422 ``CAMPO_NO_PERMITIDO``."""

    razon_social: Texto | None = None
    rfc: RfcOrg | None = None
    registro_patronal: RegistroPatronal | None = None
    domicilio_fiscal: Annotated[str, Field(max_length=500)] | None = None
    ciudad: Annotated[str, Field(max_length=120)] | None = None
    nombre_firmante: TextoCorto | None = None
    cargo_firmante: TextoCorto | None = None
    correo_firmante: Correo | None = None
    activa: bool | None = None

    @model_validator(mode="after")
    def _no_nulos(self):
        for campo in ("razon_social", "activa"):
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"{campo} no puede quedar vacío.")
        return self


class Organizacion(BaseModel):
    id: int
    clave: str
    razon_social: str
    rfc: str | None
    registro_patronal: str | None
    domicilio_fiscal: str | None
    ciudad: str | None
    nombre_firmante: str | None
    cargo_firmante: str | None
    correo_firmante: str | None
    activa: bool
    tiene_logotipo: bool

    @classmethod
    def de_fila(cls, f: dict) -> Organizacion:
        datos = {k: v for k, v in f.items() if k != "logotipo_s3_key"}
        return cls(**datos, tiene_logotipo=bool(f.get("logotipo_s3_key")))


class OrganizacionesSalida(BaseModel):
    items: list[Organizacion]


class LogotipoSolicitud(_Base):
    content_type: str = Field(max_length=40)
    tamano: int = Field(ge=1)


class UrlSubida(BaseModel):
    url: str
    s3_key: str
    expira: datetime


class LogotipoConfirmar(_Base):
    s3_key: str = Field(min_length=1, max_length=300)


Ver = Permiso.COLABORADORES_VER
Administrar = Permiso.CATALOGOS_ADMINISTRAR


@router.get(
    "/organizaciones", response_model=OrganizacionesSalida, summary="Organizaciones (COL-08)"
)
async def listar(
    solo_activas: bool = Query(default=False),
    u: UsuarioActual = requiere_permiso(Ver, usuario_actual),
    m=Depends(motor),
) -> OrganizacionesSalida:
    filas = await servicio.listar_organizaciones(m, u, solo_activas)
    return OrganizacionesSalida(items=[Organizacion.de_fila(f) for f in filas])


@router.post(
    "/organizaciones",
    status_code=201,
    response_model=Organizacion,
    summary="Crea una organización (COL-09)",
)
async def crear(
    entrada: OrganizacionCrear,
    request: Request,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
) -> Organizacion:
    fila = await servicio.crear_organizacion(m, u, entrada.model_dump(), ip_cliente(request))
    return Organizacion.de_fila(fila)


@router.patch(
    "/organizaciones/{organizacion_id}",
    response_model=Organizacion,
    summary="Actualiza o desactiva una organización (COL-10)",
)
async def actualizar(
    organizacion_id: int,
    entrada: OrganizacionActualizar,
    request: Request,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
) -> Organizacion:
    cambios = entrada.model_dump(exclude_unset=True)
    fila = await servicio.actualizar_organizacion(
        m, u, organizacion_id, cambios, ip_cliente(request)
    )
    return Organizacion.de_fila(fila)


@router.post(
    "/organizaciones/{organizacion_id}/logotipo",
    response_model=UrlSubida,
    summary="URL firmada para subir el logotipo (COL-11)",
)
async def solicitar_logotipo(
    organizacion_id: int,
    entrada: LogotipoSolicitud,
    request: Request,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen),
) -> UrlSubida:
    cfg = request.app.state.config
    r = await servicio.solicitar_logotipo(
        m,
        a,
        u,
        organizacion_id,
        entrada.content_type,
        entrada.tamano,
        maximo=cfg.logotipo_max_bytes,
        segundos=cfg.url_subida_segundos,
    )
    return UrlSubida(url=r.url, s3_key=r.s3_key, expira=r.expira)


@router.post(
    "/organizaciones/{organizacion_id}/logotipo/confirmar",
    response_model=Organizacion,
    summary="Verifica el logotipo subido y lo asigna (COL-12)",
)
async def confirmar_logotipo(
    organizacion_id: int,
    entrada: LogotipoConfirmar,
    request: Request,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen),
) -> Organizacion:
    fila = await servicio.confirmar_logotipo(
        m,
        a,
        u,
        organizacion_id,
        entrada.s3_key,
        maximo=request.app.state.config.logotipo_max_bytes,
        ip=ip_cliente(request),
    )
    return Organizacion.de_fila(fila)
