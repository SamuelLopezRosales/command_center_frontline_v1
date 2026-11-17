"""Chat de RH: conversaciones, mensajes, envío y asignación (WAP-01 a WAP-05).

Todas las rutas exigen ``chat:responder``. Los contenidos viajan cifrados en la base y solo se
descifran en WAP-02.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from cc_whatsapp.dependencias import (
    cifrador,
    colaboradores,
    ip_cliente,
    motor,
    notificaciones,
    reloj,
    usuario_actual,
    ventana,
)
from cc_whatsapp.servicios import chat_service as servicio

router = APIRouter(prefix="/conversaciones", tags=["conversaciones"])

PERMISO = Permiso.CHAT_RESPONDER


class ConversacionItem(BaseModel):
    id: int
    colaborador_id: int
    colaborador_nombre: str | None = None
    estado: Literal["VERIFICANDO", "ACTIVA", "BLOQUEADA", "CERRADA"]
    origen: Literal["CONSTANCIA", "NOTIFICACION"]
    verificada: bool
    ventana_abierta: bool
    ultimo_mensaje_entrante_at: datetime | None = None
    fecha_ultimo_mensaje: datetime
    asignada_a_usuario_id: int | None = None
    fecha_asignacion: datetime | None = None
    ultima_notificacion_id: int | None = None


class PaginaConversaciones(BaseModel):
    items: list[ConversacionItem]
    siguiente: str | None = None


class Mensaje(BaseModel):
    id: int
    direccion: Literal["ENTRANTE", "SALIENTE"]
    tipo: Literal["TEXTO", "PLANTILLA", "INTERACTIVO"]
    plantilla: str | None = None
    contenido: str | None = None
    estado: str
    error_codigo: str | None = None
    origen_tipo: str
    enviado_por_usuario_id: int | None = None
    fecha_hora: datetime


class PaginaMensajes(BaseModel):
    items: list[Mensaje]
    siguiente: str | None = None


class EntradaTexto(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    texto: str = Field(min_length=1, max_length=1000)


class EntradaPlantilla(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plantilla_mensaje_id: int = Field(gt=0)
    variables: list[str] = Field(
        default_factory=list, max_length=20, description="Variables numeradas, en orden."
    )
    variables_nombradas: dict[str, str] | None = Field(
        default=None,
        max_length=20,
        description="Valor por nombre de variable, si la plantilla usa variables con nombre.",
    )


class EntradaAsignacion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    usuario_id: int = Field(gt=0)


class MensajeEncolado(BaseModel):
    mensaje_id: int


@router.get("", response_model=PaginaConversaciones, summary="Conversaciones del chat (WAP-01)")
async def listar(
    notificacion_id: int | None = Query(default=None, gt=0),
    asignada_a: int | None = Query(default=None, gt=0),
    estado: Literal["VERIFICANDO", "ACTIVA", "BLOQUEADA", "CERRADA"] | None = None,
    cursor: str | None = Query(default=None, max_length=300),
    limite: int | None = Query(default=None, ge=1, le=servicio.LIMITE_CONVERSACIONES),
    u: UsuarioActual = requiere_permiso(PERMISO, usuario_actual),
    m=Depends(motor),
    col=Depends(colaboradores),
    v=Depends(ventana),
    ahora=Depends(reloj),
) -> PaginaConversaciones:
    r = await servicio.listar(
        m, col, v, u, notificacion_id=notificacion_id, asignada_a=asignada_a, estado=estado,
        cursor=cursor, limite=limite, reloj=lambda: ahora,
    )  # fmt: skip
    return PaginaConversaciones(**r)


@router.get(
    "/{conversacion_id}/mensajes",
    response_model=PaginaMensajes,
    summary="Mensajes de una conversación, del más reciente al más antiguo (WAP-02)",
)
async def listar_mensajes(
    conversacion_id: int,
    cursor: str | None = Query(default=None, max_length=300),
    limite: int | None = Query(default=None, ge=1, le=servicio.LIMITE_MENSAJES),
    u: UsuarioActual = requiere_permiso(PERMISO, usuario_actual),
    m=Depends(motor),
    cif=Depends(cifrador),
) -> PaginaMensajes:
    r = await servicio.mensajes(m, cif, u, conversacion_id, cursor=cursor, limite=limite)
    return PaginaMensajes(**r)


@router.post(
    "/{conversacion_id}/mensajes",
    status_code=202,
    response_model=MensajeEncolado,
    summary="Envía texto libre con la ventana de 24 horas abierta (WAP-03)",
)
async def enviar_texto(
    conversacion_id: int,
    entrada: EntradaTexto,
    request: Request,
    u: UsuarioActual = requiere_permiso(PERMISO, usuario_actual),
    m=Depends(motor),
    cif=Depends(cifrador),
    v=Depends(ventana),
    ahora=Depends(reloj),
) -> MensajeEncolado:
    mensaje_id = await servicio.enviar_texto(
        m, request.app.state.config, cif, v, u, conversacion_id, entrada.texto,
        ip_cliente(request), reloj=lambda: ahora,
    )  # fmt: skip
    return MensajeEncolado(mensaje_id=mensaje_id)


@router.post(
    "/{conversacion_id}/mensajes/plantilla",
    status_code=202,
    response_model=MensajeEncolado,
    summary="Envía una plantilla aprobada, con la ventana abierta o cerrada (WAP-04)",
)
async def enviar_plantilla(
    conversacion_id: int,
    entrada: EntradaPlantilla,
    request: Request,
    u: UsuarioActual = requiere_permiso(PERMISO, usuario_actual),
    m=Depends(motor),
    cif=Depends(cifrador),
    nots=Depends(notificaciones),
) -> MensajeEncolado:
    mensaje_id = await servicio.enviar_plantilla(
        m, request.app.state.config, cif, nots, u, conversacion_id, entrada.plantilla_mensaje_id,
        [v.strip() for v in entrada.variables], ip_cliente(request),
        variables_nombradas=entrada.variables_nombradas,
    )  # fmt: skip
    return MensajeEncolado(mensaje_id=mensaje_id)


@router.put(
    "/{conversacion_id}/asignacion",
    response_model=ConversacionItem,
    summary="Asigna la conversación a una persona de RH (WAP-05)",
)
async def asignar(
    conversacion_id: int,
    entrada: EntradaAsignacion,
    request: Request,
    u: UsuarioActual = requiere_permiso(PERMISO, usuario_actual),
    m=Depends(motor),
    col=Depends(colaboradores),
    v=Depends(ventana),
    ahora=Depends(reloj),
) -> ConversacionItem:
    r = await servicio.asignar(
        m, col, v, u, conversacion_id, entrada.usuario_id, ip_cliente(request),
        reloj=lambda: ahora,
    )  # fmt: skip
    return ConversacionItem(**r)
