"""Variables de la plantilla de una notificación (``notificacion.variables_json``).

Formato (``cc_notificaciones.servicios.variables``)::

    {"1": {"origen": "COLABORADOR", "campo": "nombre_completo"},
     "2": {"origen": "FIJO", "valor": "13 nov 2026"}}

Las de origen ``COLABORADOR`` se piden por destinatario a `colaboradores`; las ``FIJO`` son
iguales para todos. Aquí solo se arma la lista ordenada que consume Meta y el texto del correo.

Una plantilla **con nombre** (``{{guest_name}}``) lleva ``variables_json`` por nombre::

    {"guest_name": {"origen": "COLABORADOR", "campo": "nombre_completo"}}

En ese caso la lista sale en el orden de primera aparición de los nombres **en el texto** (el JSONB
no conserva el orden) y ``nombres_variables(texto)`` da la lista paralela de ``parameter_name``.
Con una posicional, ``nombres_variables`` devuelve ``None`` y todo funciona como siempre.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cc_common import plantillas_meta as pm


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


def nombres_variables(texto: str | None) -> list[str] | None:
    """``parameter_name`` de cada variable (en el orden de ``armar_variables``) si la plantilla es
    con nombre; ``None`` si es posicional o no hay texto."""
    return pm.nombres_para_envio(texto) if texto else None


def _valor(v: Any, valores: Mapping[str, str]) -> str:
    if not isinstance(v, dict):
        return ""
    if v.get("origen") == "FIJO":
        return str(v.get("valor", ""))
    return str(valores.get(str(v.get("campo")), ""))


def armar_variables(
    variables_json: Mapping[str, Any] | None,
    valores: Mapping[str, str] | None = None,
    texto: str | None = None,
) -> list[str]:
    """Lista ordenada ``["valor de {{1}}", "valor de {{2}}", ...]`` (con una plantilla con nombre
    cuyo ``texto`` se indica, en el orden de aparición de los nombres). Una de colaborador sin
    valor queda vacía: el enviador la rechaza antes de llamar a Meta si la plantilla es con nombre
    y Meta la rechaza como permanente en las demás (el destinatario queda FALLIDO)."""
    valores = valores or {}
    nombres = nombres_variables(texto)
    if nombres is not None:
        return [_valor((variables_json or {}).get(n), valores) for n in nombres]
    return [_valor((variables_json or {})[k], valores) for k in _claves(variables_json)]


def renderizar(texto: str, variables: list[str]) -> str:
    """Sustituye cada marcador por su variable: ``{{n}}`` por la variable ``n`` (1 es la primera)
    o, en una plantilla con nombre, ``{{nombre}}`` por la que ocupa su lugar en el orden."""
    nombres = nombres_variables(texto)
    if nombres is None:
        return pm.TOKEN.sub(lambda m: _posicional(m, variables), texto)
    por_nombre = pm.valores_por_nombre(texto, variables, nombres=nombres)
    return pm.TOKEN.sub(lambda m: por_nombre.get(m.group(1), ""), texto)


def _posicional(m, variables: list[str]) -> str:
    if not m.group(1).isdigit():
        return m.group(0)
    i = int(m.group(1)) - 1
    return variables[i] if 0 <= i < len(variables) else ""
