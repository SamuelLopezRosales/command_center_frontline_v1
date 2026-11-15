"""Colaboradores (COL-01 a COL-07). Sin endpoint de borrado: la baja cambia el estatus."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.errores import ErrorProhibido
from cc_common.paginacion import LIMITE_PAGINA_MAX
from cc_common.permisos import Permiso, tiene_permiso
from cc_common.tipos import Celular10, FechaIngreso, NumeroEmpleado
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cc_colaboradores.dependencias import campos, cifrador, ip_cliente, motor, usuario_actual
from cc_colaboradores.repos import colaborador as repo
from cc_colaboradores.repos.listado import Consulta
from cc_colaboradores.servicios import colaboradores as servicio
from cc_colaboradores.servicios import elegibilidad

router = APIRouter(tags=["colaboradores"])

Nombre = Annotated[str, Field(min_length=1, max_length=100)]
Puesto = Annotated[str, Field(min_length=1, max_length=150)]
TipoEmpleado = Literal["ADMINISTRATIVO", "OPERATIVO"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("tipo_empleado", mode="before", check_fields=False)
    @classmethod
    def _mayusculas(cls, v: Any) -> Any:
        return v.upper() if isinstance(v, str) else v


class ColaboradorCrear(_Base):
    """Los once campos fijos son obligatorios (CC-REQ-020); ``estatus`` nace ``ACTIVO``."""

    numero_empleado: NumeroEmpleado
    nombres: Nombre
    apellido_paterno: Nombre
    apellido_materno: Nombre
    celular: Celular10
    organizacion_id: int = Field(ge=1)
    planta_id: int = Field(ge=1)
    fecha_ingreso: FechaIngreso
    puesto: Puesto
    tipo_empleado: TipoEmpleado
    campos: dict[str, Any] = Field(default_factory=dict, max_length=200)
    consentimiento: bool = False


class ColaboradorActualizar(_Base):
    """Parcial. ``numero_empleado`` y ``estatus`` no están: no cambian aquí (COL-04)."""

    nombres: Nombre | None = None
    apellido_paterno: Nombre | None = None
    apellido_materno: Nombre | None = None
    celular: Celular10 | None = None
    organizacion_id: int | None = Field(default=None, ge=1)
    planta_id: int | None = Field(default=None, ge=1)
    fecha_ingreso: FechaIngreso | None = None
    puesto: Puesto | None = None
    tipo_empleado: TipoEmpleado | None = None
    campos: dict[str, Any] | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _no_nulos(self):
        for c in self.model_fields_set - {"campos"}:
            if getattr(self, c) is None:
                raise ValueError(f"{c} no puede quedar vacío.")
        return self


class Baja(_Base):
    fecha_baja: FechaIngreso


class Reactivar(_Base):
    consentimiento: bool = False


class Consentimiento(_Base):
    otorgado: bool
    vigente_hasta: datetime | None = None


class Referencia(BaseModel):
    id: int
    nombre: str


class EstadoConsentimiento(BaseModel):
    otorgado: bool
    vigente: bool
    fecha: datetime | None
    vigente_hasta: datetime | None


class ColaboradorDetalle(BaseModel):
    id: int
    numero_empleado: str
    nombres: str
    apellido_paterno: str
    apellido_materno: str
    celular: str  # enmascarado salvo incluir_sensibles
    celular_invalido: bool
    organizacion: Referencia
    planta: Referencia
    fecha_ingreso: date
    puesto: str
    tipo_empleado: str
    estatus: str
    fecha_baja: date | None
    consentimiento: EstadoConsentimiento
    elegible: bool
    motivo_no_elegible: str | None
    campos: dict[str, Any]
    fecha_modificacion: datetime


class ColaboradorFila(BaseModel):
    id: int
    numero_empleado: str
    nombre_completo: str
    celular: str
    puesto: str
    tipo_empleado: str
    estatus: str
    fecha_ingreso: date
    organizacion: Referencia
    planta: Referencia
    consentimiento_vigente: bool
    campos: dict[str, Any]


class PaginaColaboradores(BaseModel):
    items: list[ColaboradorFila]
    pagina: int
    limite: int
    total: int


def _enmascarar(ultimos4: str) -> str:
    return f"******{ultimos4}"


def _a_detalle(d: servicio.Detalle, response: Response) -> ColaboradorDetalle:
    f = d.fila
    response.headers["ETag"] = d.etag
    e = elegibilidad.evaluar(f)
    return ColaboradorDetalle(
        id=f["id"],
        numero_empleado=f["numero_empleado"],
        nombres=f["nombres"],
        apellido_paterno=f["apellido_paterno"],
        apellido_materno=f["apellido_materno"],
        celular=d.celular or _enmascarar(f["celular_ultimos4"]),
        celular_invalido=f["celular_invalido"],
        organizacion=Referencia(id=f["organizacion_id"], nombre=f["organizacion_clave"]),
        planta=Referencia(id=f["planta_id"], nombre=f["planta_nombre"]),
        fecha_ingreso=f["fecha_ingreso"],
        puesto=f["puesto"],
        tipo_empleado=f["tipo_empleado"],
        estatus=f["estatus"],
        fecha_baja=f["fecha_baja"],
        consentimiento=EstadoConsentimiento(
            otorgado=f["consentimiento_whatsapp"],
            vigente=elegibilidad.consentimiento_vigente(f),
            fecha=f["fecha_consentimiento"],
            vigente_hasta=f["consentimiento_vigente_hasta"],
        ),
        elegible=e.elegible,
        motivo_no_elegible=e.motivo,
        campos=d.campos,
        fecha_modificacion=f["fecha_modificacion"],
    )


Ver = Permiso.COLABORADORES_VER
Editar = Permiso.COLABORADORES_EDITAR


@router.get("/colaboradores", response_model=PaginaColaboradores, summary="Listado (COL-01)")
async def listar(
    request: Request,
    q: str | None = Query(default=None, max_length=100),
    organizacion_id: int | None = Query(default=None, ge=1),
    planta_id: int | None = Query(default=None, ge=1),
    estatus: Literal["ACTIVO", "BAJA"] | None = Query(default=None),
    tipo_empleado: TipoEmpleado | None = Query(default=None),
    columnas: list[str] = Query(default=[], max_length=20),
    pagina: int = Query(default=1, ge=1),
    limite: int = Query(default=20, ge=1, le=LIMITE_PAGINA_MAX),
    u: UsuarioActual = requiere_permiso(Ver, usuario_actual),
    m=Depends(motor),
    c=Depends(campos),
) -> PaginaColaboradores:
    # Filtros por campo dinámico: ``f.CAMP-0002=VENTAS`` (solo campos activos no sensibles).
    filtros = {k[2:]: v for k, v in request.query_params.items() if k.startswith("f.")}
    consulta = Consulta(
        q=(q or "").strip() or None,
        organizacion_id=organizacion_id,
        planta_id=planta_id,
        estatus=estatus,
        tipo_empleado=tipo_empleado,
        pagina=pagina,
        limite=limite,
    )
    items, total, elegidas = await servicio.listar(m, c, u, consulta, filtros, columnas)
    filas = [
        ColaboradorFila(
            id=i["id"],
            numero_empleado=i["numero_empleado"],
            nombre_completo=f"{i['nombres']} {i['apellido_paterno']} {i['apellido_materno']}",
            celular=_enmascarar(i["celular_ultimos4"]),
            puesto=i["puesto"],
            tipo_empleado=i["tipo_empleado"],
            estatus=i["estatus"],
            fecha_ingreso=i["fecha_ingreso"],
            organizacion=Referencia(id=i["organizacion_id"], nombre=i["organizacion_clave"]),
            planta=Referencia(id=i["planta_id"], nombre=i["planta_nombre"]),
            consentimiento_vigente=i["consentimiento_vigente"],
            campos={d.codigo_interno: i.get("valores", {}).get(d.id) for d in elegidas},
        )
        for i in items
    ]
    return PaginaColaboradores(items=filas, pagina=pagina, limite=limite, total=total)


@router.post(
    "/colaboradores", status_code=201, response_model=ColaboradorDetalle, summary="Alta (COL-02)"
)
async def crear(
    entrada: ColaboradorCrear,
    request: Request,
    response: Response,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    cif=Depends(cifrador),
    c=Depends(campos),
) -> ColaboradorDetalle:
    fijos = repo.DatosFijos(
        **entrada.model_dump(exclude={"campos", "consentimiento"}),
    )
    d = await servicio.crear(
        m, cif, c, u, fijos, entrada.campos, entrada.consentimiento, ip_cliente(request)
    )
    return _a_detalle(d, response)


@router.get(
    "/colaboradores/{colaborador_id}", response_model=ColaboradorDetalle, summary="Detalle (COL-03)"
)
async def detalle(
    colaborador_id: int,
    request: Request,
    response: Response,
    incluir_sensibles: bool = Query(default=False),
    u: UsuarioActual = requiere_permiso(Ver, usuario_actual),
    m=Depends(motor),
    cif=Depends(cifrador),
    c=Depends(campos),
) -> ColaboradorDetalle:
    if incluir_sensibles and not tiene_permiso(u.rol, Permiso.COLABORADORES_VER_SENSIBLES):
        raise ErrorProhibido()
    d = await servicio.detalle(m, cif, c, u, colaborador_id, incluir_sensibles, ip_cliente(request))
    return _a_detalle(d, response)


@router.patch(
    "/colaboradores/{colaborador_id}",
    response_model=ColaboradorDetalle,
    summary="Edición con If-Match (COL-04)",
)
async def actualizar(
    colaborador_id: int,
    entrada: ColaboradorActualizar,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None),
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    cif=Depends(cifrador),
    c=Depends(campos),
) -> ColaboradorDetalle:
    cambios = entrada.model_dump(exclude_unset=True, exclude={"campos"})
    d = await servicio.actualizar(
        m, cif, c, u, colaborador_id, cambios, entrada.campos, if_match, ip_cliente(request)
    )
    return _a_detalle(d, response)


@router.post(
    "/colaboradores/{colaborador_id}/baja",
    response_model=ColaboradorDetalle,
    summary="Baja (COL-05)",
)
async def baja(
    colaborador_id: int,
    entrada: Baja,
    request: Request,
    response: Response,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    cif=Depends(cifrador),
    c=Depends(campos),
) -> ColaboradorDetalle:
    d = await servicio.baja(m, cif, c, u, colaborador_id, entrada.fecha_baja, ip_cliente(request))
    return _a_detalle(d, response)


@router.post(
    "/colaboradores/{colaborador_id}/reactivar",
    response_model=ColaboradorDetalle,
    summary="Reactivación (COL-06)",
)
async def reactivar(
    colaborador_id: int,
    entrada: Reactivar,
    request: Request,
    response: Response,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    cif=Depends(cifrador),
    c=Depends(campos),
) -> ColaboradorDetalle:
    d = await servicio.reactivar(
        m, cif, c, u, colaborador_id, entrada.consentimiento, ip_cliente(request)
    )
    return _a_detalle(d, response)


@router.put(
    "/colaboradores/{colaborador_id}/consentimiento",
    response_model=ColaboradorDetalle,
    summary="Consentimiento de WhatsApp (COL-07)",
)
async def consentimiento(
    colaborador_id: int,
    entrada: Consentimiento,
    request: Request,
    response: Response,
    u: UsuarioActual = requiere_permiso(Editar, usuario_actual),
    m=Depends(motor),
    cif=Depends(cifrador),
    c=Depends(campos),
) -> ColaboradorDetalle:
    d = await servicio.consentimiento(
        m, cif, c, u, colaborador_id, entrada.otorgado, entrada.vigente_hasta, ip_cliente(request)
    )
    return _a_detalle(d, response)
