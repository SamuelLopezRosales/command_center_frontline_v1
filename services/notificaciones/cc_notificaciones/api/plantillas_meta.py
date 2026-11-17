"""Importar plantillas ya aprobadas en Meta: ``/api/v1/plantillas-mensaje/meta`` e ``importar``.

Exigen ``notificaciones:editar``. Solo leen de Meta (``GET message_templates``); nunca crean ni
editan nada allá. Ninguna respuesta lleva credenciales y todas van con ``Cache-Control: no-store``.
Qué es "compatible", cómo se identifica cada plantilla y la limitación de nombre/idioma:
``servicios/plantillas_meta.py`` y ``docs/meta-configuracion.md``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from cc_notificaciones.dependencias import meta, motor, usuario_actual
from cc_notificaciones.servicios import plantillas_meta as servicio

router = APIRouter(prefix="/plantillas-mensaje", tags=["plantillas-mensaje"])

Editar = Permiso.NOTIFICACIONES_EDITAR
_RESPUESTAS_META = {
    422: {"description": "META_NO_CONFIGURADA: faltan las credenciales de Meta."},
    502: {"description": "ERROR_PROVEEDOR_META: Meta no pudo atender la consulta."},
}


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BotonDeMeta(BaseModel):
    tipo: str = Field(description="QUICK_REPLY, URL, PHONE_NUMBER, COPY_CODE, OTP, FLOW...")
    texto: str


class EncabezadoDeMeta(BaseModel):
    tipo: Literal["TEXTO", "MEDIA", "UBICACION", "OTRO"]
    formato: str | None = Field(description="Formato de Meta: TEXT, IMAGE, VIDEO, DOCUMENT...")
    texto: str | None = Field(description="El texto, si el encabezado es de texto.")


class MotivoIncompatible(BaseModel):
    codigo: str
    motivo: str = Field(description="El motivo, en español.")


class PlantillaDeMeta(BaseModel):
    nombre: str
    idioma: str
    categoria: str = Field(description="UTILITY, MARKETING, AUTHENTICATION u otra de Meta.")
    estado_meta: str = Field(description="Estado en Meta: APPROVED, PENDING, REJECTED, PAUSED...")
    id_plantilla_meta: str
    texto: str = Field(
        description="Texto del cuerpo con las variables {{1}}, {{2}}... o {{nombre}}."
    )
    num_variables: int
    formato_variables: Literal["POSICIONAL", "NOMBRADO"] = Field(
        description="POSICIONAL ({{1}}) o NOMBRADO ({{guest_name}}), inferido del texto."
    )
    variables: list[str] = Field(
        description="Las variables en orden de aparición: '1', '2'... o sus nombres."
    )
    compatible: bool = Field(description="Se puede importar y usar tal cual.")
    codigo_incompatible: str | None = Field(
        description="ESTADO_NO_APROBADO, ENCABEZADO_IMAGEN, BOTON_OTP, VARIABLES_MEZCLADAS..."
    )
    motivo_incompatible: str | None = Field(description="El motivo, en español.")
    motivos_incompatibles: list[MotivoIncompatible] = Field(
        description="Todos los motivos de incompatibilidad (el primero es codigo_incompatible)."
    )
    botones: list[BotonDeMeta] = Field(description="Los botones de la plantilla, en orden.")
    encabezado: EncabezadoDeMeta | None = Field(description="El encabezado, si lo tiene.")
    advertencias: list[str] = Field(description="Cosas que se toleran pero conviene saber.")
    ya_importada: bool = Field(description="Ya hay una plantilla local con ese id de Meta.")
    nombre_en_uso: bool = Field(
        description="Ya existe una plantilla local con ese nombre y otro id: no se podría importar."
    )


class ListadoDeMeta(BaseModel):
    items: list[PlantillaDeMeta]
    truncado: bool = Field(description="Meta tiene más plantillas de las que se trajeron (500).")


class PlantillaAImportar(_Base):
    nombre: Annotated[str, Field(min_length=1, max_length=512)]
    idioma: Annotated[str, Field(min_length=2, max_length=10)]


class ImportarEntrada(_Base):
    plantillas: Annotated[
        list[PlantillaAImportar], Field(min_length=1, max_length=servicio.MAX_IMPORTAR)
    ]


class ResultadoImportacion(BaseModel):
    nombre: str
    idioma: str
    resultado: Literal["IMPORTADA", "YA_EXISTIA", "OMITIDA"]
    motivo: str | None = Field(description="Por qué se omitió (en español); nulo en los demás.")
    codigo: str | None = Field(
        description="Código del motivo (NO_ENCONTRADA_EN_META, NOMBRE_EN_USO...)."
    )
    plantilla_id: int | None = Field(description="La plantilla local, si se importó o ya existía.")


class ResultadoImportar(BaseModel):
    items: list[ResultadoImportacion]


def _sin_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get(
    "/meta",
    response_model=ListadoDeMeta,
    summary="Plantillas que existen en Meta y si se pueden importar",
    responses=_RESPUESTAS_META,
)
async def listar_de_meta(
    response: Response,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    cliente=Depends(meta),
) -> dict[str, Any]:
    _sin_cache(response)
    return await servicio.listar_de_meta(m, cliente, u)


@router.post(
    "/importar",
    response_model=ResultadoImportar,
    summary="Importar plantillas ya aprobadas en Meta (una transacción por plantilla)",
    responses=_RESPUESTAS_META,
)
async def importar(
    entrada: ImportarEntrada,
    response: Response,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    cliente=Depends(meta),
) -> dict[str, Any]:
    _sin_cache(response)
    items = await servicio.importar(
        m, cliente, u, [(p.nombre, p.idioma) for p in entrada.plantillas]
    )
    return {"items": items}
