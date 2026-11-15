"""Catálogo de variables (CON-15)."""

from __future__ import annotations

from typing import Literal

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cc_constancias.dependencias import campos, usuario_actual
from cc_constancias.servicios import variables as servicio

router = APIRouter(tags=["variables"])


class VariableDto(BaseModel):
    grupo: Literal["COLABORADOR", "ORGANIZACION", "SENSIBLES", "SISTEMA"]
    nombre: str
    etiqueta: str
    sensible: bool


class VariablesSalida(BaseModel):
    items: list[VariableDto]


@router.get(
    "/constancias/variables",
    response_model=VariablesSalida,
    summary="Variables disponibles para las plantillas (CON-15)",
)
async def listar(
    u: UsuarioActual = requiere_permiso(Permiso.PLANTILLAS_EDITAR, usuario_actual),
    c=Depends(campos),
) -> VariablesSalida:
    return VariablesSalida(
        items=[
            VariableDto(grupo=v.grupo, nombre=v.nombre, etiqueta=v.etiqueta, sensible=v.sensible)
            for v in await servicio.listar(c, u)
        ]
    )
