"""Jerarquía de errores de dominio y respuestas problem+json (design.md §9.1, §9.4).

Reglas:
- Ninguna respuesta incluye el valor recibido ni datos personales (CC-REQ-162).
- El texto de PostgreSQL (que trae los valores de la llave duplicada) nunca llega al cliente:
  las violaciones se traducen a códigos por el nombre de la restricción.
- Los errores no controlados devuelven 500 genérico con ``correlacion_id``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

PROBLEM_JSON = "application/problem+json"

# Claves permitidas en ``detalle``: identificadores y nombres, nunca valores personales.
CLAVES_DETALLE_PERMITIDAS = frozenset(
    {
        "campo",
        "campos",
        "codigo_interno",
        "entidad",
        "entidad_id",
        "plantillas",
        "total",
        "estado_actual",
        "estado_esperado",
        "limite",
        "reintentar_en_s",
    }
)


@dataclass(frozen=True)
class ErrorCampo:
    campo: str
    codigo: str
    mensaje: str


@dataclass
class ErrorDominio(Exception):
    codigo: str = "ERROR_INTERNO"
    mensaje_publico: str = "Ocurrió un error interno."
    detalle: Mapping[str, Any] = field(default_factory=dict)
    errores: list[ErrorCampo] = field(default_factory=list)
    reintentable: bool = False
    http: int = 500

    def __post_init__(self) -> None:
        prohibidas = set(self.detalle) - CLAVES_DETALLE_PERMITIDAS
        if prohibidas:
            raise ValueError(f"claves de detalle no permitidas: {sorted(prohibidas)}")
        super().__init__(self.codigo)


def _clase(nombre: str, http: int, codigo: str, mensaje: str, reintentable: bool = False):
    def __init__(self, codigo_: str = codigo, mensaje_publico: str = mensaje, **kw):
        ErrorDominio.__init__(
            self,
            codigo=codigo_,
            mensaje_publico=mensaje_publico,
            reintentable=kw.pop("reintentable", reintentable),
            http=http,
            **kw,
        )

    return type(nombre, (ErrorDominio,), {"__init__": __init__})


ErrorValidacion = _clase("ErrorValidacion", 422, "VALIDACION_FALLIDA", "Validación fallida.")
ErrorNoEncontrado = _clase(
    "ErrorNoEncontrado", 404, "RECURSO_NO_ENCONTRADO", "Recurso no encontrado."
)
ErrorConflicto = _clase("ErrorConflicto", 409, "CONFLICTO", "El recurso está en conflicto.")
ErrorNoAutenticado = _clase("ErrorNoAutenticado", 401, "NO_AUTENTICADO", "Sesión no válida.")
ErrorProhibido = _clase("ErrorProhibido", 403, "PROHIBIDO", "Permiso insuficiente.")
ErrorLimite = _clase("ErrorLimite", 429, "LIMITE_TASA", "Demasiadas solicitudes.", True)
ErrorProveedor = _clase(
    "ErrorProveedor", 502, "ERROR_PROVEEDOR", "Un servicio externo no respondió.", True
)
ErrorInterno = _clase("ErrorInterno", 500, "ERROR_INTERNO", "Ocurrió un error interno.")

# Restricción de PostgreSQL -> (excepción, código). Se completa en cada servicio.
CATALOGO_RESTRICCIONES: dict[str, tuple[type[ErrorDominio], str, str]] = {
    "colaborador_empresa_id_numero_empleado_key": (
        ErrorConflicto,
        "NUMERO_EMPLEADO_DUPLICADO",
        "numero_empleado",
    ),
    "colaborador_empresa_id_celular_hash_key": (ErrorConflicto, "CELULAR_DUPLICADO", "celular"),
}


def desde_violacion(nombre_restriccion: str | None) -> ErrorDominio:
    """Traduce una violación de restricción a un error sin el texto de PostgreSQL."""
    if nombre_restriccion and nombre_restriccion in CATALOGO_RESTRICCIONES:
        clase, codigo, campo = CATALOGO_RESTRICCIONES[nombre_restriccion]
        return clase(codigo, errores=[ErrorCampo(campo, codigo, "El valor ya existe.")])
    return ErrorConflicto()


def problema(error: ErrorDominio, correlacion_id: str | None = None) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {
        "type": "about:blank",
        "title": error.mensaje_publico,
        "status": error.http,
        "codigo": error.codigo,
        "correlacion_id": correlacion_id or str(uuid.uuid4()),
    }
    if error.detalle:
        cuerpo["detalle"] = dict(error.detalle)
    if error.errores:
        cuerpo["errores"] = [e.__dict__ for e in error.errores]
    return cuerpo


_MENSAJES_PYDANTIC = {
    "missing": ("REQUERIDO", "El campo es obligatorio."),
    "string_too_long": ("DEMASIADO_LARGO", "El valor es demasiado largo."),
    "string_too_short": ("DEMASIADO_CORTO", "El valor es demasiado corto."),
    "extra_forbidden": ("CAMPO_NO_PERMITIDO", "Campo no permitido."),
    "date_from_datetime_parsing": ("FECHA_INVALIDA", "Fecha inválida."),
    "date_parsing": ("FECHA_INVALIDA", "Fecha inválida."),
    "date_type": ("FECHA_INVALIDA", "Fecha inválida."),
    "literal_error": ("VALOR_NO_PERMITIDO", "Valor no permitido."),
    "enum": ("VALOR_NO_PERMITIDO", "Valor no permitido."),
}


def desde_errores_pydantic(errores: list[Mapping[str, Any]]) -> ErrorDominio:
    """Convierte errores de Pydantic sin incluir ``input`` ni ``ctx`` (podrían traer el valor)."""
    lista: list[ErrorCampo] = []
    for e in errores:
        loc = [str(p) for p in e.get("loc", ()) if p not in ("body", "query", "path")]
        campo = ".".join(loc) or "solicitud"
        tipo = str(e.get("type", ""))
        if tipo.startswith("value_error") or tipo == "assertion_error":
            # Mensaje de nuestros validadores: es fijo y no contiene el valor.
            msg = (
                str(e.get("msg", ""))
                .removeprefix("Value error, ")
                .removeprefix("Assertion failed, ")
            )
            codigo, mensaje = "FORMATO_INVALIDO", msg or "Formato inválido."
        else:
            codigo, mensaje = _MENSAJES_PYDANTIC.get(
                tipo, ("FORMATO_INVALIDO", "Formato inválido.")
            )
        lista.append(ErrorCampo(campo, codigo, mensaje))
    return ErrorValidacion(errores=lista)


def instalar_manejadores(app: Any) -> None:
    """Registra los manejadores en una app de FastAPI."""
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    def _correlacion(request: Request) -> str:
        return request.headers.get("x-correlation-id") or str(uuid.uuid4())

    async def _dominio(request: Request, exc: ErrorDominio):
        return JSONResponse(
            problema(exc, _correlacion(request)), status_code=exc.http, media_type=PROBLEM_JSON
        )

    async def _validacion(request: Request, exc: RequestValidationError):
        err = desde_errores_pydantic(list(exc.errors()))
        return JSONResponse(
            problema(err, _correlacion(request)), status_code=422, media_type=PROBLEM_JSON
        )

    async def _inesperado(request: Request, _exc: Exception):
        return JSONResponse(
            problema(ErrorInterno(), _correlacion(request)),
            status_code=500,
            media_type=PROBLEM_JSON,
        )

    from starlette.exceptions import HTTPException as StarletteHTTPException

    async def _http(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            err: ErrorDominio = ErrorNoEncontrado()
        elif exc.status_code == 405:
            err = ErrorDominio(
                codigo="METODO_NO_PERMITIDO", mensaje_publico="Método no permitido.", http=405
            )
        else:
            err = ErrorDominio(
                codigo="ERROR_HTTP", mensaje_publico="Solicitud no válida.", http=exc.status_code
            )
        return JSONResponse(
            problema(err, _correlacion(request)), status_code=err.http, media_type=PROBLEM_JSON
        )

    app.add_exception_handler(ErrorDominio, _dominio)
    app.add_exception_handler(StarletteHTTPException, _http)
    app.add_exception_handler(RequestValidationError, _validacion)
    app.add_exception_handler(Exception, _inesperado)
