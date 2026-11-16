"""Rutas ``/internal`` de notificaciones (INT-NOT-01).

No están en API Gateway: solo se alcanzan desde las tareas por grupo de seguridad, con el token
interno (design.md §11.1). La empresa llega en ``X-Empresa-Id`` y fija la RLS.
"""

from __future__ import annotations

from cc_common.db import transaccion
from cc_common.errores import ErrorNoEncontrado
from cc_common.internal_client import LlamadaInterna, requiere_servicio
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from cc_notificaciones.dependencias import motor

router = APIRouter(prefix="/internal", tags=["internas"])

WHATSAPP = requiere_servicio("whatsapp")


class PlantillaInterna(BaseModel):
    id: int
    nombre: str
    estado_meta: str
    idioma: str
    texto_con_variables: str


@router.get(
    "/plantillas-mensaje/{plantilla_id}", response_model=PlantillaInterna, summary="INT-NOT-01"
)
async def plantilla(
    plantilla_id: int, ll: LlamadaInterna = WHATSAPP, m=Depends(motor)
) -> PlantillaInterna:
    """La plantilla de mensaje de la empresa: el chat de RH (WAP-04) la usa para exigir que esté
    APROBADA y para armar el texto. Solo lectura; sin datos personales."""
    async with transaccion(m, ll.empresa_id) as conn:
        f = (
            (
                await conn.execute(
                    text(
                        "SELECT id, nombre, estado_meta, idioma, texto_con_variables "
                        "FROM notificaciones.plantilla_mensaje WHERE id = :id"
                    ),
                    {"id": plantilla_id},
                )
            )
            .mappings()
            .first()
        )
    if f is None:
        raise ErrorNoEncontrado()
    return PlantillaInterna(**dict(f))
