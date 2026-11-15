"""Errores propios del servicio constancias y traducción de restricciones (design.md §9.2)."""

from __future__ import annotations

from typing import Any

from cc_common.errores import (
    CATALOGO_RESTRICCIONES,
    ErrorConflicto,
    ErrorDominio,
    desde_violacion,
)

CATALOGO_RESTRICCIONES.update(
    {"plantilla_nombre_key": (ErrorConflicto, "NOMBRE_DUPLICADO", "nombre")}
)


def nombre_restriccion(exc: BaseException) -> str | None:
    actual: Any = exc
    for _ in range(4):
        nombre = getattr(actual, "constraint_name", None)
        if nombre:
            return str(nombre)
        actual = getattr(actual, "orig", None) or getattr(actual, "__cause__", None)
        if actual is None:
            return None
    return None


def desde_integridad(exc: BaseException) -> ErrorDominio:
    return desde_violacion(nombre_restriccion(exc))


def contenido_demasiado_grande(maximo: int) -> ErrorDominio:
    """413: el JSON de la plantilla pasa de 512 KB (CC-REQ-060)."""
    return ErrorDominio(
        codigo="CONTENIDO_DEMASIADO_GRANDE",
        mensaje_publico=f"El contenido de la plantilla no puede pasar de {maximo // 1024} KB.",
        detalle={"limite": maximo},
        http=413,
    )


def version_desactualizada() -> ErrorDominio:
    """412: el ``If-Match`` no coincide con el borrador actual (bloqueo optimista, §8.2)."""
    return ErrorDominio(
        codigo="VERSION_DESACTUALIZADA",
        mensaje_publico="El borrador cambió desde que se leyó; recárguelo.",
        http=412,
    )


def precondicion_requerida() -> ErrorDominio:
    """428: guardar sobre un borrador existente exige ``If-Match`` con su ``ETag``."""
    return ErrorDominio(
        codigo="PRECONDICION_REQUERIDA",
        mensaje_publico="Falta el encabezado If-Match con la versión leída.",
        http=428,
    )
