"""Errores propios del servicio notificaciones y traducción de restricciones (design.md §9.2)."""

from __future__ import annotations

from typing import Any

from cc_common.errores import CATALOGO_RESTRICCIONES, ErrorConflicto, desde_violacion

CATALOGO_RESTRICCIONES.update(
    {
        "audiencia_nombre_key": (ErrorConflicto, "AUDIENCIA_NOMBRE_DUPLICADO", "nombre"),
        "plantilla_mensaje_empresa_id_nombre_key": (
            ErrorConflicto,
            "PLANTILLA_NOMBRE_DUPLICADO",
            "nombre",
        ),
    }
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


def desde_integridad(exc: BaseException):
    return desde_violacion(nombre_restriccion(exc))
