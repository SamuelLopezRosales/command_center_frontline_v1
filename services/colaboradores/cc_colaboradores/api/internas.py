"""Rutas ``/internal`` de colaboradores (INT-COL-01 a 05, 07 y 08).

No están en API Gateway: solo se alcanzan desde las tareas y Lambdas por grupo de seguridad, con
el token interno (design.md §11.1). Cada ruta declara qué servicios pueden llamarla, y la empresa
llega en ``X-Empresa-Id``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from cc_common.internal_client import LlamadaInterna, requiere_servicio
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from cc_colaboradores.dependencias import campos, cifrador, motor
from cc_colaboradores.servicios import internas as servicio

router = APIRouter(prefix="/internal", tags=["internas"])

Variables = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=80)]], Field(max_length=100)
]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BuscarCelular(_Entrada):
    celular: str = Field(min_length=1, max_length=30)


class Busqueda(BaseModel):
    encontrado: bool
    celular_hash: str
    colaborador_id: int | None = None
    estatus: str | None = None
    consentimiento_vigente: bool | None = None
    elegible: bool | None = None
    motivo: str | None = None


class Desafio(BaseModel):
    tipo: Literal["NSS_ULTIMOS4", "FECHA_INGRESO_DDMM"]


class Verificar(_Entrada):
    dato: str = Field(min_length=1, max_length=20)


class Verificacion(BaseModel):
    valido: bool


class DatosConstancia(_Entrada):
    variables: Variables


class Datos(BaseModel):
    valores: dict[str, str]
    faltantes: list[str]


class ResolverContactos(_Entrada):
    ids: list[int] = Field(min_length=1, max_length=500)
    proposito: Literal["NOTIFICACION", "CONSTANCIA", "VERIFICACION", "CHAT", "CORREO"]
    variables: Variables | None = None


class Contacto(BaseModel):
    id: int
    elegible: bool
    motivo: str | None = None
    celular: str | None = None
    correo: str | None = None
    valores: dict[str, str] = Field(default_factory=dict)


class Contactos(BaseModel):
    items: list[Contacto]


WHATSAPP = requiere_servicio("whatsapp")
CONSTANCIAS = requiere_servicio("constancias")
EMISORES = requiere_servicio("whatsapp", "notificaciones", "constancias")


@router.post("/colaboradores/buscar-por-celular", response_model=Busqueda, summary="INT-COL-01")
async def buscar_por_celular(
    entrada: BuscarCelular, ll: LlamadaInterna = WHATSAPP, m=Depends(motor), cif=Depends(cifrador)
) -> Busqueda:
    return Busqueda(**await servicio.buscar_por_celular(m, cif, ll.empresa_id, entrada.celular))


@router.post(
    "/colaboradores/{colaborador_id}/desafio", response_model=Desafio, summary="INT-COL-02"
)
async def desafio(
    colaborador_id: int, ll: LlamadaInterna = WHATSAPP, m=Depends(motor), c=Depends(campos)
) -> Desafio:
    return Desafio(tipo=await servicio.desafio(m, c, ll.empresa_id, colaborador_id))


@router.post(
    "/colaboradores/{colaborador_id}/verificar", response_model=Verificacion, summary="INT-COL-03"
)
async def verificar(
    colaborador_id: int,
    entrada: Verificar,
    ll: LlamadaInterna = WHATSAPP,
    m=Depends(motor),
    cif=Depends(cifrador),
    c=Depends(campos),
) -> Verificacion:
    ok = await servicio.verificar(m, cif, c, ll.empresa_id, colaborador_id, entrada.dato)
    return Verificacion(valido=ok)


@router.post(
    "/colaboradores/{colaborador_id}/datos-constancia", response_model=Datos, summary="INT-COL-04"
)
async def datos_constancia(
    colaborador_id: int,
    entrada: DatosConstancia,
    ll: LlamadaInterna = CONSTANCIAS,
    m=Depends(motor),
    cif=Depends(cifrador),
    c=Depends(campos),
) -> Datos:
    valores, faltantes = await servicio.datos_constancia(
        m, cif, c, ll.empresa_id, colaborador_id, entrada.variables
    )
    return Datos(valores=valores, faltantes=faltantes)


@router.post("/colaboradores/contactos:resolver", response_model=Contactos, summary="INT-COL-05")
async def resolver_contactos(
    entrada: ResolverContactos,
    ll: LlamadaInterna = EMISORES,
    m=Depends(motor),
    cif=Depends(cifrador),
    c=Depends(campos),
) -> Contactos:
    items = await servicio.resolver_contactos(
        m, cif, c, ll.empresa_id, entrada.ids, entrada.proposito, entrada.variables
    )
    return Contactos(items=[Contacto(**i.__dict__) for i in items])


@router.get("/colaboradores/{colaborador_id}/resumen", summary="INT-COL-07")
async def resumen(
    colaborador_id: int, ll: LlamadaInterna = WHATSAPP, m=Depends(motor)
) -> dict[str, Any]:
    return await servicio.resumen(m, ll.empresa_id, colaborador_id)


@router.get("/organizaciones/{organizacion_id}", summary="INT-COL-08")
async def organizacion(
    organizacion_id: int, ll: LlamadaInterna = CONSTANCIAS, m=Depends(motor)
) -> dict[str, Any]:
    return await servicio.organizacion(m, ll.empresa_id, organizacion_id)
