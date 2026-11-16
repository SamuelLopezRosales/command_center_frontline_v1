"""Variables de la plantilla de una notificación (``notificacion.variables_json``).

Formato (``cc_notificaciones.servicios.variables``)::

    {"1": {"origen": "COLABORADOR", "campo": "nombre_completo"},
     "2": {"origen": "FIJO", "valor": "13 nov 2026"}}

Las de origen ``COLABORADOR`` se piden por destinatario a `colaboradores`; las ``FIJO`` son
iguales para todos. Aquí solo se arma la lista ordenada que consume Meta y el texto del correo.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


def _claves(variables_json: Mapping[str, Any] | None) -> list[str]:
    return sorted((variables_json or {}), key=lambda k: int(k) if str(k).isdigit() else 10**9)


def campos_colaborador(variables_json: Mapping[str, Any] | None) -> list[str]:
    """Los ``campo`` distintos (en orden de aparición) de las variables de colaborador."""
    vistos: dict[str, None] = {}
    for k in _claves(variables_json):
        v = (variables_json or {})[k]
        if isinstance(v, dict) and v.get("origen") == "COLABORADOR" and v.get("campo"):
            vistos[str(v["campo"])] = None
    return list(vistos)


def armar_variables(
    variables_json: Mapping[str, Any] | None, valores: Mapping[str, str] | None = None
) -> list[str]:
    """Lista ordenada ``["valor de {{1}}", "valor de {{2}}", ...]``. Una de colaborador sin valor
    queda vacía (Meta la rechaza como permanente y el destinatario queda FALLIDO)."""
    valores = valores or {}
    salida: list[str] = []
    for k in _claves(variables_json):
        v = (variables_json or {})[k]
        if not isinstance(v, dict):
            salida.append("")
        elif v.get("origen") == "FIJO":
            salida.append(str(v.get("valor", "")))
        else:
            salida.append(str(valores.get(str(v.get("campo")), "")))
    return salida


def renderizar(texto: str, variables: list[str]) -> str:
    """Sustituye ``{{n}}`` por la variable ``n`` (1 es la primera)."""

    def uno(m: re.Match[str]) -> str:
        i = int(m.group(1)) - 1
        return variables[i] if 0 <= i < len(variables) else ""

    return re.sub(r"\{\{(\d+)\}\}", uno, texto)
