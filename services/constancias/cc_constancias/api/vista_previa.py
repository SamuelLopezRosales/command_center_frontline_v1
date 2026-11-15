"""Vista previa de una plantilla (CON-14)."""

from __future__ import annotations

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cc_constancias.dependencias import (
    almacen,
    campos,
    cargador_logotipo,
    colaboradores,
    ip_cliente,
    motor,
    usuario_actual,
)
from cc_constancias.servicios import vista_previa as servicio

router = APIRouter(tags=["vista-previa"])


class VistaPreviaEntrada(BaseModel):
    """Una de las dos fuentes: una ``version`` publicada o el borrador (``usar_borrador``)."""

    model_config = ConfigDict(extra="forbid")

    colaborador_id: int = Field(ge=1)
    version: int | None = Field(default=None, ge=1)
    usar_borrador: bool = False

    @model_validator(mode="after")
    def _una_fuente(self):
        if (self.version is None) == (not self.usar_borrador):
            raise ValueError("Indique una versión o use el borrador, no ambos ni ninguno.")
        return self


class VistaPreviaSalida(BaseModel):
    html: str
    faltantes: list[str]
    desconocidas: list[str]


@router.post(
    "/plantillas/{plantilla_id}/vista-previa",
    response_model=VistaPreviaSalida,
    summary="Vista previa con los datos de un colaborador (CON-14)",
)
async def vista_previa(
    plantilla_id: int,
    entrada: VistaPreviaEntrada,
    request: Request,
    u: UsuarioActual = requiere_permiso(Permiso.PLANTILLAS_EDITAR, usuario_actual),
    m=Depends(motor),
    a=Depends(almacen),
    c=Depends(campos),
    col=Depends(colaboradores),
    logos=Depends(cargador_logotipo),
) -> VistaPreviaSalida:
    r = await servicio.generar(
        m, a, c, col, logos, request.app.state.config, u, plantilla_id, entrada.colaborador_id,
        version=entrada.version, usar_borrador=entrada.usar_borrador, ip=ip_cliente(request),
    )  # fmt: skip
    return VistaPreviaSalida(html=r.html, faltantes=r.faltantes, desconocidas=r.desconocidas)
