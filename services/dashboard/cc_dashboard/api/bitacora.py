"""Consulta de la bitácora de auditoría (DSH-05; CC-REQ-015)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.bitacora import ACCIONES
from cc_common.errores import ErrorValidacion
from cc_common.paginacion import LIMITE_PAGINA_MAX
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from cc_dashboard.dependencias import motor, usuario_actual
from cc_dashboard.repos.bitacora import FiltroBitacora
from cc_dashboard.servicios import bitacora as servicio

router = APIRouter(tags=["bitacora"])


class RegistroBitacora(BaseModel):
    id: int
    fecha_hora: datetime
    usuario_id: int | None
    usuario_nombre: str | None
    colaborador_id: int | None
    accion: str
    entidad: str
    entidad_id: int | None
    ip: str | None
    origen: str
    detalle: dict[str, Any]


class BitacoraSalida(BaseModel):
    items: list[RegistroBitacora]
    siguiente: str | None


@router.get("/bitacora", response_model=BitacoraSalida, summary="Consulta de la bitácora (DSH-05)")
async def consultar(
    desde: datetime | None = Query(default=None),
    hasta: datetime | None = Query(default=None),
    usuario_id: int | None = Query(default=None, ge=1),
    colaborador_id: int | None = Query(default=None, ge=1),
    accion: str | None = Query(default=None, max_length=40),
    orden: Literal["asc", "desc"] = Query(default="desc"),
    cursor: str | None = Query(default=None, max_length=400),
    limite: int = Query(default=20, ge=1, le=LIMITE_PAGINA_MAX),
    u: UsuarioActual = requiere_permiso(Permiso.BITACORA_VER, usuario_actual),
    m=Depends(motor),
) -> BitacoraSalida:
    if accion is not None and accion not in ACCIONES:
        raise ErrorValidacion("ACCION_DESCONOCIDA", "La acción indicada no existe.")
    filtro = FiltroBitacora(
        desde=desde,
        hasta=hasta,
        usuario_id=usuario_id,
        colaborador_id=colaborador_id,
        accion=accion,
        orden=orden,
        limite=limite,
    )
    pagina = await servicio.consultar(m, u, filtro, cursor)
    return BitacoraSalida(
        items=[RegistroBitacora(**f) for f in pagina.items], siguiente=pagina.siguiente
    )
