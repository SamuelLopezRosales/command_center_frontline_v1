"""Errores propios del servicio y traducción de restricciones de PostgreSQL (design.md §9.2)."""

from __future__ import annotations

from typing import Any

from cc_common.errores import CATALOGO_RESTRICCIONES, ErrorConflicto, ErrorDominio, desde_violacion

# ``cc_common.errores`` deja el catálogo para que cada servicio lo complete.
CATALOGO_RESTRICCIONES.update(
    {
        "organizacion_empresa_id_clave_key": (ErrorConflicto, "ORGANIZACION_DUPLICADA", "clave"),
        "planta_empresa_id_nombre_key": (ErrorConflicto, "PLANTA_DUPLICADA", "nombre"),
    }
)


def nombre_restriccion(exc: BaseException) -> str | None:
    """Nombre de la restricción violada en un ``IntegrityError`` de SQLAlchemy con asyncpg."""
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
