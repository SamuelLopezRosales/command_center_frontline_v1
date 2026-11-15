"""Dashboard (DSH-01 a DSH-04) e historial de constancias (DSH-11).

CC-REQ-011 a 014, 087. Los permisos: ``dashboard:ver`` y ``constancias:ver``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.paginacion import LIMITE_PAGINA_MAX
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from cc_dashboard.dependencias import motor, usuario_actual
from cc_dashboard.repos.vistas import FiltroHistorial
from cc_dashboard.servicios import dashboard as servicio

router = APIRouter(tags=["dashboard"])


class ResumenDashboard(BaseModel):
    colaboradores_activos: int
    constancias_mes: int
    solicitudes_en_proceso: int
    plantillas_activas: int
    vacio: bool


class ItemSolicitud(BaseModel):
    id: int
    colaborador_nombre: str
    plantilla_nombre: str | None
    version: int | None
    estado: str


class ItemConstancia(BaseModel):
    id: int
    folio: str
    colaborador_nombre: str
    plantilla_nombre: str
    version: int
    fecha: datetime
    estado_entrega: str


class Alerta(BaseModel):
    tipo: Literal[
        "SIN_CONSENTIMIENTO",
        "CONSTANCIA_FALLIDA",
        "CONSTANCIA_PENDIENTE",
        "CAMPO_VACIO_EN_PLANTILLA",
    ]
    titulo: str
    detalle: str
    total: int
    enlace: str


class ItemHistorial(ItemConstancia):
    canal: str


class HistorialSalida(BaseModel):
    items: list[ItemHistorial]
    siguiente: str | None


@router.get("/dashboard/resumen", response_model=ResumenDashboard, summary="Indicadores (DSH-01)")
async def resumen(
    u: UsuarioActual = requiere_permiso(Permiso.DASHBOARD_VER, usuario_actual),
    m=Depends(motor),
) -> ResumenDashboard:
    return ResumenDashboard(**await servicio.resumen(m, u))


@router.get(
    "/dashboard/solicitudes-recientes",
    response_model=list[ItemSolicitud],
    summary="Solicitudes recientes (DSH-02)",
)
async def solicitudes_recientes(
    limite: int = Query(default=10, ge=1, le=20),
    u: UsuarioActual = requiere_permiso(Permiso.DASHBOARD_VER, usuario_actual),
    m=Depends(motor),
) -> list[ItemSolicitud]:
    return [ItemSolicitud(**f) for f in await servicio.solicitudes_recientes(m, u, limite)]


@router.get(
    "/dashboard/constancias-recientes",
    response_model=list[ItemConstancia],
    summary="Constancias recientes (DSH-03)",
)
async def constancias_recientes(
    limite: int = Query(default=10, ge=1, le=20),
    u: UsuarioActual = requiere_permiso(Permiso.DASHBOARD_VER, usuario_actual),
    m=Depends(motor),
) -> list[ItemConstancia]:
    filas = await servicio.constancias_recientes(m, u, limite)
    return [ItemConstancia(**{k: v for k, v in f.items() if k != "canal"}) for f in filas]


@router.get("/dashboard/alertas", response_model=list[Alerta], summary="Alertas (DSH-04)")
async def alertas(
    u: UsuarioActual = requiere_permiso(Permiso.DASHBOARD_VER, usuario_actual),
    m=Depends(motor),
) -> list[Alerta]:
    return [Alerta(**a) for a in await servicio.alertas(m, u)]


@router.get(
    "/constancias/historial",
    response_model=HistorialSalida,
    summary="Historial de constancias (DSH-11)",
)
async def historial(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    plantilla_id: int | None = Query(default=None, ge=1),
    colaborador_id: int | None = Query(default=None, ge=1),
    estado: Literal["PENDIENTE", "ENTREGADA", "FALLIDA"] | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    cursor: str | None = Query(default=None, max_length=400),
    limite: int = Query(default=20, ge=1, le=LIMITE_PAGINA_MAX),
    u: UsuarioActual = requiere_permiso(Permiso.CONSTANCIAS_VER, usuario_actual),
    m=Depends(motor),
) -> HistorialSalida:
    filtro = FiltroHistorial(
        desde=desde,
        hasta=hasta,
        plantilla_id=plantilla_id,
        colaborador_id=colaborador_id,
        estado=estado,
        q=q,
        limite=limite,
    )
    pagina = await servicio.historial(m, u, filtro, cursor)
    return HistorialSalida(
        items=[ItemHistorial(**f) for f in pagina.items], siguiente=pagina.siguiente
    )
