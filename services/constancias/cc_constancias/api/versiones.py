"""Validación, publicación, versiones y restauración (CON-09 a CON-13)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, ConfigDict

from cc_constancias.contenido import ContenidoPlantilla
from cc_constancias.dependencias import (
    almacen,
    campos,
    colaboradores,
    ip_cliente,
    motor,
    usuario_actual,
)
from cc_constancias.servicios import publicacion as servicio
from cc_constancias.workers.alertas_plantilla import recalcular_sin_fallar

router = APIRouter(tags=["versiones"])

Editar = Permiso.PLANTILLAS_EDITAR
Publicar = Permiso.PLANTILLAS_PUBLICAR


class Hallazgo(BaseModel):
    codigo: str
    mensaje: str
    variables: list[str]
    total: int | None = None


class ResultadoValidacion(BaseModel):
    errores: list[Hallazgo]
    advertencias: list[Hallazgo]


class PublicarEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmar_sensibles: bool = False


class Version(BaseModel):
    numero: int
    hash: str
    fecha_creacion: datetime
    vigente: bool

    @classmethod
    def de_fila(cls, f: dict[str, Any]) -> Version:
        return cls(
            numero=f["numero"],
            hash=f["hash_sha256"],
            fecha_creacion=f["fecha_creacion"],
            vigente=f["vigente"],
        )


class VersionDetalle(Version):
    contenido: ContenidoPlantilla


class VersionesSalida(BaseModel):
    items: list[Version]


@router.post(
    "/plantillas/{plantilla_id}/borrador/validar",
    response_model=ResultadoValidacion,
    summary="Valida el borrador (CON-09)",
)
async def validar(
    plantilla_id: int,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen),
    c=Depends(campos),
    col=Depends(colaboradores),
) -> ResultadoValidacion:
    r = await servicio.validar(m, a, c, col, u, plantilla_id)
    return ResultadoValidacion(
        errores=[Hallazgo(**h.__dict__) for h in r.errores],
        advertencias=[Hallazgo(**h.__dict__) for h in r.advertencias],
    )


@router.post(
    "/plantillas/{plantilla_id}/publicar",
    status_code=201,
    response_model=Version,
    summary="Publica el borrador como una versión nueva (CON-10)",
)
async def publicar(
    plantilla_id: int,
    request: Request,
    segundo_plano: BackgroundTasks,
    entrada: PublicarEntrada | None = None,
    u: UsuarioActual = requiere_permiso(Publicar, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen),
    c=Depends(campos),
    col=Depends(colaboradores),
) -> Version:
    confirmar = bool(entrada and entrada.confirmar_sensibles)
    f = await servicio.publicar(m, a, c, col, u, plantilla_id, confirmar, ip_cliente(request))
    segundo_plano.add_task(recalcular_sin_fallar, m, a, c, col, u.empresa_id, plantilla_id)
    return Version.de_fila(f)


@router.get(
    "/plantillas/{plantilla_id}/versiones",
    response_model=VersionesSalida,
    summary="Versiones publicadas (CON-11)",
)
async def listar(
    plantilla_id: int,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> VersionesSalida:
    filas = await servicio.listar_versiones(m, u, plantilla_id)
    return VersionesSalida(items=[Version.de_fila(f) for f in filas])


@router.get(
    "/plantillas/{plantilla_id}/versiones/{numero}",
    response_model=VersionDetalle,
    response_model_exclude_none=True,  # el contenido se entrega en su forma canónica
    summary="Una versión con su contenido (CON-12)",
)
async def detalle(
    plantilla_id: int,
    numero: int,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen),
) -> VersionDetalle:
    fila, contenido = await servicio.obtener_version(m, a, u, plantilla_id, numero)
    return VersionDetalle(
        **Version.de_fila(fila).model_dump(), contenido=ContenidoPlantilla.model_validate(contenido)
    )


@router.post(
    "/plantillas/{plantilla_id}/versiones/{numero}/restaurar",
    status_code=201,
    response_model=Version,
    summary="Restaura una versión como una versión nueva (CON-13)",
)
async def restaurar(
    plantilla_id: int,
    numero: int,
    request: Request,
    segundo_plano: BackgroundTasks,
    u: UsuarioActual = requiere_permiso(Publicar, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen),
    c=Depends(campos),
    col=Depends(colaboradores),
) -> Version:
    f = await servicio.restaurar(m, a, c, col, u, plantilla_id, numero, ip_cliente(request))
    segundo_plano.add_task(recalcular_sin_fallar, m, a, c, col, u.empresa_id, plantilla_id)
    return Version.de_fila(f)
