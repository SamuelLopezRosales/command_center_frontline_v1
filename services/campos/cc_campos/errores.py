"""Errores propios del servicio campos y traducción de restricciones (design.md §9.2)."""

from __future__ import annotations

from typing import Any

from cc_common.errores import CATALOGO_RESTRICCIONES, ErrorConflicto, desde_violacion

CATALOGO_RESTRICCIONES.update(
    {
        "campo_empresa_id_clave_key": (ErrorConflicto, "CLAVE_DUPLICADA", "clave"),
        "opcion_campo_id_valor_key": (ErrorConflicto, "OPCION_DUPLICADA", "valor"),
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
