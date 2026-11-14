"""Rutas de sesión, usuario actual e invitaciones (DSH-06, DSH-07, DSH-10).

DSH-08 y DSH-09 (listado y desactivación) se agregan en T-035.
"""

from __future__ import annotations

from datetime import datetime

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from cc_common.tipos import Correo
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict

from cc_dashboard.dependencias import ip_cliente, motor, usuario_actual
from cc_dashboard.servicios import sesion

router = APIRouter(tags=["usuarios"])


class UsuarioYo(BaseModel):
    id: int
    empresa_id: int
    nombre: str
    correo: str
    rol: str
    permisos: list[str]


class InvitacionEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correo_destino: Correo | None = None


class InvitacionSalida(BaseModel):
    id: int
    codigo: str
    fecha_expira: datetime


@router.post("/sesion/iniciar", status_code=204, summary="Registra el inicio de sesión (DSH-06)")
async def iniciar(
    request: Request,
    u: UsuarioActual = requiere_permiso(Permiso.DASHBOARD_VER, usuario_actual),
    m=Depends(motor),
) -> Response:
    await sesion.iniciar_sesion(m, u, ip_cliente(request))
    return Response(status_code=204)


@router.get("/usuarios/yo", response_model=UsuarioYo, summary="Usuario actual (DSH-07)")
async def yo(
    u: UsuarioActual = requiere_permiso(Permiso.DASHBOARD_VER, usuario_actual), m=Depends(motor)
) -> UsuarioYo:
    p = await sesion.perfil(m, u)
    return UsuarioYo(**p.__dict__)


@router.post(
    "/usuarios/invitaciones",
    status_code=201,
    response_model=InvitacionSalida,
    summary="Crea una invitación de registro; el código se muestra una sola vez (DSH-10)",
)
async def invitar(
    entrada: InvitacionEntrada,
    request: Request,
    u: UsuarioActual = requiere_permiso(Permiso.USUARIOS_ADMINISTRAR, usuario_actual),
    m=Depends(motor),
) -> InvitacionSalida:
    horas = request.app.state.config.invitacion_horas
    inv = await sesion.crear_invitacion(m, u, entrada.correo_destino, horas)
    return InvitacionSalida(id=inv.id, codigo=inv.codigo, fecha_expira=inv.fecha_expira)
