"""Carga masiva de colaboradores (COL-16 a COL-22)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.paginacion import LIMITE_PAGINA_MAX
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from cc_colaboradores.dependencias import almacen_cargas, campos, ip_cliente, motor, usuario_actual
from cc_colaboradores.servicios import cargas as servicio

router = APIRouter(tags=["cargas"])
Ejecutar = Permiso.CARGAS_EJECUTAR


class CargaIniciar(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nombre_archivo: Annotated[str, Field(min_length=1, max_length=300)]
    tamano: Annotated[int, Field(ge=1)]


class CargaIniciada(BaseModel):
    carga_id: int
    url_subida: str
    s3_key: str
    expira: datetime
    content_type: str = servicio.CONTENT_TYPE_XLSX


class Carga(BaseModel):
    id: int
    nombre_archivo: str
    version_plantilla: str
    total_filas: int | None
    filas_ok: int
    filas_error: int
    estado: Literal["EN_PROCESO", "TERMINADA", "CANCELADA"]
    confirmada: bool
    fecha_carga: datetime
    fecha_fin: datetime | None
    motivo_cierre: str | None

    @classmethod
    def de_fila(cls, f: dict) -> Carga:
        return cls(
            id=f["id"],
            nombre_archivo=f["nombre_archivo"],
            version_plantilla=f["version_plantilla"],
            total_filas=f["total_filas"],
            filas_ok=f["filas_ok"],
            filas_error=f["filas_error"],
            estado=f["estado"],
            confirmada=bool(f["hash_archivo"]),
            fecha_carga=f["fecha_carga"],
            fecha_fin=f["fecha_fin"],
            motivo_cierre=f["motivo_cierre"],
        )


class PaginaCargas(BaseModel):
    items: list[Carga]
    pagina: int
    limite: int
    total: int


class ErrorDeFila(BaseModel):
    codigo: str
    mensaje: str


class FilaCarga(BaseModel):
    numero_fila: int
    resultado: Literal["NUEVO", "ACTUALIZADO", "ERROR", "OMITIDO"]
    errores: list[ErrorDeFila]


class PaginaFilas(BaseModel):
    items: list[FilaCarga]
    pagina: int
    limite: int
    total: int


class CargaDetalle(BaseModel):
    carga: Carga
    filas: PaginaFilas


@router.get(
    "/cargas/plantilla",
    summary="Plantilla de Excel con los campos activos (COL-16)",
    response_class=Response,
    responses={200: {"content": {servicio.CONTENT_TYPE_XLSX: {}}}},
)
async def plantilla(
    u: UsuarioActual = requiere_permiso(Ejecutar, usuario_actual),
    m=Depends(motor),
    c=Depends(campos),
) -> Response:
    contenido = await servicio.plantilla(m, c, u)
    return Response(
        contenido,
        media_type=servicio.CONTENT_TYPE_XLSX,
        headers={"Content-Disposition": 'attachment; filename="plantilla_colaboradores.xlsx"'},
    )


@router.post(
    "/cargas", status_code=201, response_model=CargaIniciada, summary="Inicia una carga (COL-17)"
)
async def iniciar(
    entrada: CargaIniciar,
    request: Request,
    u: UsuarioActual = requiere_permiso(Ejecutar, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen_cargas),
) -> CargaIniciada:
    carga, url, expira = await servicio.iniciar(
        m, a, request.app.state.config, u, entrada.nombre_archivo, entrada.tamano
    )
    return CargaIniciada(
        carga_id=carga["id"], url_subida=url, s3_key=carga["s3_key"], expira=expira
    )


@router.post(
    "/cargas/{carga_id}/confirmar",
    status_code=202,
    response_model=Carga,
    summary="Confirma el archivo subido y lo encola (COL-18)",
)
async def confirmar(
    carga_id: int,
    request: Request,
    u: UsuarioActual = requiere_permiso(Ejecutar, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen_cargas),
) -> Carga:
    fila = await servicio.confirmar(
        m, a, request.app.state.config, u, carga_id, ip_cliente(request)
    )
    return Carga.de_fila(fila)


@router.get("/cargas", response_model=PaginaCargas, summary="Historial de cargas (COL-19)")
async def listar(
    request: Request,
    pagina: int = Query(default=1, ge=1),
    limite: int = Query(default=20, ge=1, le=LIMITE_PAGINA_MAX),
    u: UsuarioActual = requiere_permiso(Ejecutar, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen_cargas),
) -> PaginaCargas:
    filas, total = await servicio.listar(m, a, request.app.state.config, u, pagina, limite)
    return PaginaCargas(
        items=[Carga.de_fila(f) for f in filas], pagina=pagina, limite=limite, total=total
    )


@router.get(
    "/cargas/{carga_id}",
    response_model=CargaDetalle,
    summary="Resumen y filas de una carga (COL-20)",
)
async def detalle(
    carga_id: int,
    request: Request,
    resultado: Literal["NUEVO", "ACTUALIZADO", "ERROR", "OMITIDO"] | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    limite: int = Query(default=50, ge=1, le=LIMITE_PAGINA_MAX),
    u: UsuarioActual = requiere_permiso(Ejecutar, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen_cargas),
) -> CargaDetalle:
    carga, filas, total = await servicio.detalle(
        m, a, request.app.state.config, u, carga_id, resultado, pagina, limite
    )
    items = [
        FilaCarga(
            numero_fila=f["numero_fila"],
            resultado=f["resultado"],
            errores=[
                ErrorDeFila(codigo=c, mensaje=t) for c, t in servicio._lineas_de_error(f["mensaje"])
            ],
        )
        for f in filas
    ]
    return CargaDetalle(
        carga=Carga.de_fila(carga),
        filas=PaginaFilas(items=items, pagina=pagina, limite=limite, total=total),
    )


@router.get(
    "/cargas/{carga_id}/errores",
    summary="Reporte de errores en CSV (COL-21)",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def errores(
    carga_id: int,
    u: UsuarioActual = requiere_permiso(Ejecutar, usuario_actual),
    m=Depends(motor),
) -> Response:
    contenido = await servicio.reporte_errores(m, u, carga_id)
    return Response(
        contenido,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="errores_carga_{carga_id}.csv"'},
    )


@router.post(
    "/cargas/{carga_id}/cancelar", response_model=Carga, summary="Cancela una carga (COL-22)"
)
async def cancelar(
    carga_id: int,
    u: UsuarioActual = requiere_permiso(Ejecutar, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen_cargas),
) -> Carga:
    return Carga.de_fila(await servicio.cancelar(m, a, u, carga_id))
