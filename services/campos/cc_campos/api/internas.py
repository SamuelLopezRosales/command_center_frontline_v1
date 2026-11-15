"""Rutas ``/internal`` de campos (INT-CAM-01 y INT-CAM-02).

No están en API Gateway: solo se alcanzan desde las tareas por grupo de seguridad, con el token
interno (design.md §11.1). La empresa llega en ``X-Empresa-Id``.
"""

from __future__ import annotations

from cc_common.db import transaccion
from cc_common.errores import ErrorCampo, ErrorValidacion
from cc_common.internal_client import LlamadaInterna, requiere_servicio
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from cc_campos.api.campos import CampoDto, OpcionDto
from cc_campos.dependencias import motor
from cc_campos.repos import campos as repo
from cc_campos.servicios import sembrado

router = APIRouter(prefix="/internal", tags=["internas"])

CONSUMIDORES_DEP = requiere_servicio(
    "colaboradores", "constancias", "notificaciones", "whatsapp", "dashboard"
)
SEMBRADORES_DEP = requiere_servicio("dashboard", "bootstrap")


class Definicion(CampoDto):
    opciones: list[OpcionDto] = []  # noqa: RUF012 - modelo de pydantic


class Definiciones(BaseModel):
    campos: list[Definicion]


class Sembrado(BaseModel):
    creados: int
    existentes: int


@router.get(
    "/campos",
    response_model=Definiciones,
    summary="Definiciones de campos con sus opciones (INT-CAM-01)",
)
async def definiciones(
    incluir_inactivos: bool = Query(default=False),
    llamada: LlamadaInterna = CONSUMIDORES_DEP,
    m=Depends(motor),
) -> Definiciones:
    """Por defecto solo los campos activos. Con ``incluir_inactivos`` también los desactivados
    no eliminados, que conservan sus valores y siguen resolviendo variables ya publicadas."""
    async with transaccion(m, llamada.empresa_id) as conn:
        filas = await repo.definiciones(conn, incluir_inactivos=incluir_inactivos)
    return Definiciones(campos=[Definicion(**CampoDto.de_fila(f).model_dump()) for f in filas])


@router.post(
    "/empresas/{empresa_id}/campos-sugeridos",
    status_code=201,
    response_model=Sembrado,
    summary="Siembra el catálogo de campos sugeridos (INT-CAM-02)",
)
async def sembrar(
    empresa_id: int,
    request: Request,
    llamada: LlamadaInterna = SEMBRADORES_DEP,
    m=Depends(motor),
) -> Sembrado:
    """Idempotente: lo ya existente no se duplica. La empresa de la ruta debe ser la del
    encabezado ``X-Empresa-Id`` (la que fija RLS)."""
    if empresa_id != llamada.empresa_id:
        raise ErrorValidacion(
            "EMPRESA_NO_COINCIDE",
            "La empresa de la ruta no coincide con la del encabezado.",
            errores=[ErrorCampo("empresa_id", "EMPRESA_NO_COINCIDE", "No coincide.")],
        )
    creados, existentes = await sembrado.sembrar(m, request.app.state.config, empresa_id)
    return Sembrado(creados=creados, existentes=existentes)
