"""Notificaciones: CRUD, duplicar, destinatarios, indicadores, revisión (NOT-18), confirmación
(NOT-19), cancelar (NOT-20) y reintentar fallidos (NOT-22).

El contrato **no admite texto libre**: ``NotificacionCrear`` solo lleva la plantilla aprobada y sus
variables (``extra="forbid"``: un ``mensaje``, ``texto`` o ``canal`` da 422 ``CAMPO_NO_PERMITIDO``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cc_notificaciones.dependencias import (
    campos,
    colaboradores,
    motor,
    programador,
    usuario_actual,
)
from cc_notificaciones.servicios import embudo as servicio_embudo
from cc_notificaciones.servicios import notificaciones as servicio
from cc_notificaciones.servicios import programador as servicio_programador
from cc_notificaciones.servicios import reintentar_cancelar as servicio_acciones
from cc_notificaciones.servicios import variables as servicio_variables

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])

Editar = Permiso.NOTIFICACIONES_EDITAR
Enviar = Permiso.NOTIFICACIONES_ENVIAR
Modo = Literal["CRITERIOS", "INDIVIDUAL", "GRUPO"]
Estado = Literal["BORRADOR", "PROGRAMADA", "ENVIANDO", "COMPLETADA", "CON_FALLAS", "CANCELADA"]
EstadoDestinatario = Literal[
    "PENDIENTE", "EXCLUIDO", "ENVIADO", "ENTREGADO", "LEIDO", "RESPONDIO", "FALLIDO"
]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------------- entrada


class VariableAsignada(_Base):
    origen: Literal["COLABORADOR", "FIJO"]
    campo: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    valor: Annotated[str, Field(min_length=1, max_length=200)] | None = None

    @model_validator(mode="after")
    def _segun_origen(self):
        if self.origen == "COLABORADOR" and (self.campo is None or self.valor is not None):
            raise ValueError("Una variable de colaborador lleva solo campo.")
        if self.origen == "FIJO" and (self.valor is None or self.campo is not None):
            raise ValueError("Una variable fija lleva solo valor.")
        return self


Titulo = Annotated[str, Field(min_length=1, max_length=150)]
Variables = dict[Annotated[str, Field(max_length=3)], VariableAsignada]


class NotificacionCrear(_Base):
    titulo: Titulo
    modo: Modo
    criterios: dict[str, Any] | None = None  # modo CRITERIOS
    colaborador_id: Annotated[int, Field(gt=0)] | None = None  # modo INDIVIDUAL
    audiencia_id: Annotated[int, Field(gt=0)] | None = None  # modo GRUPO
    plantilla_mensaje_id: Annotated[int, Field(gt=0)]
    variables: Variables = {}
    respaldo_correo: bool = False
    zona_horaria: Annotated[str, Field(min_length=1, max_length=64)] | None = None


class NotificacionActualizar(_Base):
    titulo: Titulo | None = None
    modo: Modo | None = None
    criterios: dict[str, Any] | None = None
    colaborador_id: Annotated[int, Field(gt=0)] | None = None
    audiencia_id: Annotated[int, Field(gt=0)] | None = None
    plantilla_mensaje_id: Annotated[int, Field(gt=0)] | None = None
    variables: Variables | None = None
    respaldo_correo: bool | None = None
    zona_horaria: Annotated[str, Field(min_length=1, max_length=64)] | None = None

    @model_validator(mode="after")
    def _no_nulos(self):
        for c in self.model_fields_set:
            if getattr(self, c) is None:
                raise ValueError(f"{c} no puede quedar vacío.")
        return self


class Confirmar(_Base):
    modo_envio: Literal["AHORA", "PROGRAMAR"]
    programada_para: datetime | None = None
    respaldo_correo: bool | None = None
    confirmar_fuera_horario: bool = False


class Cancelar(_Base):
    motivo: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class Reintentar(_Base):
    confirmar_fuera_horario: bool = False


# ---------------------------------------------------------------------------------- salida


class EmbudoDto(BaseModel):
    seleccionados: int
    con_consentimiento: int
    activos: int
    celular_valido: int


class ExcluidosPorMotivo(BaseModel):
    SIN_CONSENTIMIENTO: int
    ESTATUS_BAJA: int
    SIN_CELULAR_VALIDO: int


class Revision(BaseModel):
    embudo: EmbudoDto
    excluidos_por_motivo: ExcluidosPorMotivo
    total_seleccionados: int
    total_excluidos: int
    revisada_en: datetime


class PlantillaResumen(BaseModel):
    id: int
    nombre: str
    estado_meta: str


class Contadores(BaseModel):
    seleccionados: int
    excluidos: int
    validos: int
    enviados: int
    entregados: int
    leidos: int
    respondieron: int
    fallidos: int


class HitoLineaTiempo(BaseModel):
    evento: Literal["CREADA", "REVISADA", "CONFIRMADA", "PROGRAMADA_PARA", "ENVIADA"]
    en: datetime


class NotificacionDto(BaseModel):
    id: int
    titulo: str
    modo: Modo
    estado: Estado
    canal: Literal["PLANTILLA_META"] = "PLANTILLA_META"
    audiencia_id: int | None
    audiencia_nombre: str | None
    colaborador_id: int | None
    criterios: dict[str, Any] | None
    plantilla: PlantillaResumen | None
    variables: dict[str, Any]
    vista_previa: str | None
    respaldo_correo: bool
    zona_horaria: str
    modo_envio: Literal["AHORA", "PROGRAMAR"] | None
    programada_para: datetime | None
    revisada_en: datetime | None
    confirmada_en: datetime | None
    confirmada_por_usuario_id: int | None
    confirmada_fuera_horario: bool
    motivo_cancelacion: str | None
    contadores: Contadores
    linea_de_tiempo: list[HitoLineaTiempo]
    usuario_id: int
    fecha_creacion: datetime
    fecha_envio: datetime | None

    @classmethod
    def de_fila(cls, f: dict[str, Any]) -> NotificacionDto:
        criterios = (
            f["criterios_snapshot_json"]
            if f["criterios_snapshot_json"] is not None
            else f["criterios_audiencia"]
        )
        hitos = [("CREADA", f["fecha_creacion"]), ("REVISADA", f["revisada_en"])]
        hitos += [("CONFIRMADA", f["confirmada_en"]), ("PROGRAMADA_PARA", f["programada_para"])]
        hitos += [("ENVIADA", f["fecha_envio"])]
        return cls(
            id=f["id"],
            titulo=f["titulo"],
            modo=f["modo"],
            estado=f["estado"],
            audiencia_id=f["audiencia_id"],
            audiencia_nombre=f["audiencia_nombre"],
            colaborador_id=servicio.colaborador_de(f["criterios_snapshot_json"])
            if f["modo"] == "INDIVIDUAL"
            else None,
            criterios=criterios,
            plantilla=PlantillaResumen(
                id=f["plantilla_mensaje_id"],
                nombre=f["plantilla_nombre"],
                estado_meta=f["plantilla_estado"],
            )
            if f["plantilla_mensaje_id"]
            else None,
            variables=f["variables_json"] or {},
            vista_previa=servicio_variables.vista_previa(f["plantilla_texto"], f["variables_json"])
            if f["plantilla_texto"]
            else None,
            respaldo_correo=f["respaldo_correo"],
            zona_horaria=f["zona_horaria"],
            modo_envio=f["modo_envio"],
            programada_para=f["programada_para"],
            revisada_en=f["revisada_en"],
            confirmada_en=f["confirmada_en"],
            confirmada_por_usuario_id=f["confirmada_por_usuario_id"],
            confirmada_fuera_horario=f["confirmada_fuera_horario"],
            motivo_cancelacion=f["motivo_cancelacion"],
            contadores=Contadores(
                seleccionados=f["renglones"],
                excluidos=f["excluidos"],
                validos=f["renglones"] - f["excluidos"],
                enviados=f["enviados"],
                entregados=f["entregados"],
                leidos=f["leidos"],
                respondieron=f["respondieron"],
                fallidos=f["fallidos"],
            ),
            # Cronológica (PQ-17): los hitos sin fecha no aparecen.
            linea_de_tiempo=[
                HitoLineaTiempo(evento=e, en=t)  # type: ignore[arg-type]
                for e, t in sorted((h for h in hitos if h[1] is not None), key=lambda h: h[1])
            ],
            usuario_id=f["usuario_id"],
            fecha_creacion=f["fecha_creacion"],
            fecha_envio=f["fecha_envio"],
        )


class ConteoPestanas(BaseModel):
    envios: int
    programadas: int
    borradores: int


class PaginaNotificaciones(BaseModel):
    items: list[NotificacionDto]
    siguiente: str | None = None
    conteos: ConteoPestanas


class DestinatarioDto(BaseModel):
    id: int
    colaborador_id: int
    nombre: str
    planta: str | None
    celular_enmascarado: str | None
    estado: EstadoDestinatario
    motivo_exclusion: str | None
    motivo_fallo: str | None
    canal_usado: str | None
    conversacion_id: int | None
    intentos: int
    fecha_estado: datetime


class PaginaDestinatarios(BaseModel):
    items: list[DestinatarioDto]
    siguiente: str | None = None


class Indicadores(BaseModel):
    mes: str
    enviadas: int
    entregadas: int
    leidas: int
    fallidas: int
    porcentaje_entregadas: float
    porcentaje_leidas: float
    conteos: ConteoPestanas


# ---------------------------------------------------------------------------------- rutas


@router.get("", response_model=PaginaNotificaciones, summary="Listado por pestañas (NOT-14)")
async def listar(
    pestana: Literal["envios", "programadas", "borradores"] = Query(default="envios"),
    estado: Estado | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=200),
    limite: int | None = Query(default=None, ge=1, le=200),
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> PaginaNotificaciones:
    p, conteos = await servicio.listar(
        m, u, pestana=pestana, estado=estado, cursor=cursor, limite=limite
    )
    return PaginaNotificaciones(
        items=[NotificacionDto.de_fila(f) for f in p.items],
        siguiente=p.siguiente,
        conteos=ConteoPestanas(**conteos),
    )


@router.post("", status_code=201, response_model=NotificacionDto, summary="Alta (NOT-15)")
async def crear(
    entrada: NotificacionCrear,
    request: Request,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    c=Depends(campos),
    col=Depends(colaboradores),
) -> NotificacionDto:
    datos = entrada.model_dump(exclude_none=True)
    f = await servicio.crear(m, request.app.state.config, c, col, u, datos)
    return NotificacionDto.de_fila(f)


@router.get("/indicadores", response_model=Indicadores, summary="Indicadores del mes (NOT-24)")
async def indicadores(
    request: Request,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> Indicadores:
    ahora = request.app.state.reloj()
    return Indicadores(**await servicio.indicadores(m, request.app.state.config, u, ahora))


@router.get("/{notificacion_id}", response_model=NotificacionDto, summary="Detalle (NOT-16)")
async def detalle(
    notificacion_id: int,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> NotificacionDto:
    return NotificacionDto.de_fila(await servicio.detalle(m, u, notificacion_id))


@router.patch("/{notificacion_id}", response_model=NotificacionDto, summary="Edición (NOT-17)")
async def actualizar(
    notificacion_id: int,
    entrada: NotificacionActualizar,
    request: Request,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    c=Depends(campos),
    col=Depends(colaboradores),
) -> NotificacionDto:
    cambios = entrada.model_dump(exclude_unset=True, exclude_none=True)
    f = await servicio.actualizar(m, request.app.state.config, c, col, u, notificacion_id, cambios)
    return NotificacionDto.de_fila(f)


@router.post(
    "/{notificacion_id}/duplicar",
    status_code=201,
    response_model=NotificacionDto,
    summary="Duplicar como borrador (NOT-23)",
)
async def duplicar(
    notificacion_id: int,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> NotificacionDto:
    return NotificacionDto.de_fila(await servicio.duplicar(m, u, notificacion_id))


@router.get(
    "/{notificacion_id}/destinatarios",
    response_model=PaginaDestinatarios,
    summary="Destinatarios con celular enmascarado (NOT-21)",
)
async def destinatarios(
    notificacion_id: int,
    estado: EstadoDestinatario | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=200),
    limite: int | None = Query(default=None, ge=1, le=200),
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
) -> PaginaDestinatarios:
    p = await servicio.destinatarios(
        m, u, notificacion_id, estado=estado, cursor=cursor, limite=limite
    )
    return PaginaDestinatarios(
        items=[
            DestinatarioDto(
                id=f["id"],
                colaborador_id=f["colaborador_id"],
                nombre=f["colaborador_nombre"],
                planta=f["planta_nombre"],
                celular_enmascarado=servicio.mascara_celular(f["celular_ultimos4"]),
                estado=f["estado_envio"],
                motivo_exclusion=f["motivo_exclusion"],
                motivo_fallo=f["motivo_fallo"],
                canal_usado=f["canal_usado"],
                conversacion_id=f["conversacion_id"],
                intentos=f["intentos"],
                fecha_estado=f["fecha_estado"],
            )
            for f in p.items
        ],
        siguiente=p.siguiente,
    )


@router.post(
    "/{notificacion_id}/revisar",
    response_model=Revision,
    summary="Revisión de la audiencia y embudo (NOT-18)",
)
async def revisar(
    notificacion_id: int,
    request: Request,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    c=Depends(campos),
    col=Depends(colaboradores),
) -> Revision:
    r = await servicio_embudo.revisar(m, request.app.state.config, c, col, u, notificacion_id)
    return Revision(**r)


@router.post(
    "/{notificacion_id}/confirmar",
    status_code=202,
    response_model=NotificacionDto,
    summary="Confirmar: enviar ahora o programar (NOT-19)",
)
async def confirmar(
    notificacion_id: int,
    entrada: Confirmar,
    request: Request,
    u: UsuarioActual = requiere_permiso(Enviar, usuario_actual),
    m=Depends(motor),
    prog=Depends(programador),
) -> NotificacionDto:
    f = await servicio_programador.confirmar(
        m,
        request.app.state.config,
        prog,
        u,
        notificacion_id,
        modo_envio=entrada.modo_envio,
        programada_para=entrada.programada_para,
        respaldo_correo=entrada.respaldo_correo,
        confirmar_fuera_horario=entrada.confirmar_fuera_horario,
        ahora=request.app.state.reloj(),
    )
    return NotificacionDto.de_fila(f)


@router.post(
    "/{notificacion_id}/cancelar",
    response_model=NotificacionDto,
    summary="Cancelar un borrador o una programada (NOT-20)",
)
async def cancelar(
    notificacion_id: int,
    request: Request,
    entrada: Cancelar | None = None,
    u: UsuarioActual = requiere_permiso(Enviar, usuario_actual),
    m=Depends(motor),
    prog=Depends(programador),
) -> NotificacionDto:
    f = await servicio_acciones.cancelar(
        m, prog, u, notificacion_id, motivo=entrada.motivo if entrada else None
    )
    return NotificacionDto.de_fila(f)


@router.post(
    "/{notificacion_id}/reintentar",
    status_code=202,
    response_model=NotificacionDto,
    summary="Reintentar los destinatarios fallidos (NOT-22)",
)
async def reintentar(
    notificacion_id: int,
    request: Request,
    entrada: Reintentar | None = None,
    u: UsuarioActual = requiere_permiso(Enviar, usuario_actual),
    m=Depends(motor),
    col=Depends(colaboradores),
) -> NotificacionDto:
    f = await servicio_acciones.reintentar(
        m,
        request.app.state.config,
        col,
        u,
        notificacion_id,
        confirmar_fuera_horario=entrada.confirmar_fuera_horario if entrada else False,
        ahora=request.app.state.reloj(),
    )
    return NotificacionDto.de_fila(f)
