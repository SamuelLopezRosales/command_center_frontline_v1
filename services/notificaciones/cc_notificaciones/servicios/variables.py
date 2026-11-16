"""Variables de una notificación y vista previa (CC-REQ-103; design.md §3.6, §5.2).

Formato de ``variables_json``: un objeto con una entrada por variable de la plantilla (``"1"``,
``"2"``... exactamente las que usa el texto)::

    {"1": {"origen": "COLABORADOR", "campo": "nombre_completo"},
     "2": {"origen": "FIJO", "valor": "13 nov 2026"}}

- ``FIJO``: texto igual para todos (hasta 200 caracteres, una sola línea y sin 5 espacios
  seguidos: reglas de los parámetros de Meta).
- ``COLABORADOR``: se resuelve por destinatario en `colaboradores` (INT-COL-05, T-217). ``campo`` es
  una de las variables fijas de la constancia (``FIJAS``) o el ``codigo_interno`` de un campo
  dinámico **activo y no sensible**. Un sensible nunca se admite.
- **No existe texto libre**: el contrato solo acepta plantilla aprobada más estas variables.

``vista_previa`` sustituye las fijas y deja las de colaborador como ``{{campo}}``.
"""

from __future__ import annotations

import re
from typing import Any

from cc_common.errores import ErrorCampo, ErrorValidacion

from cc_notificaciones.servicios.plantillas import cantidad_variables

# Las mismas variables fijas que resuelve `colaboradores` (``servicios/variables.py``).
FIJAS = (
    "nombre_completo",
    "numero_empleado",
    "puesto",
    "fecha_ingreso",
    "planta",
    "tipo_empleado",
)
MAX_VALOR = 200
_CINCO_ESPACIOS = re.compile(r" {5,}")


def validar(variables: Any, texto_plantilla: str, definiciones: list[Any] | None = None) -> None:
    """Valida ``variables`` contra el texto de la plantilla. ``definiciones`` (INT-CAM-01) solo
    hace falta si alguna variable usa un campo dinámico; sin ellas, esos campos se rechazan."""
    n = cantidad_variables(texto_plantilla)
    errores: list[ErrorCampo] = []
    if not isinstance(variables, dict):
        raise ErrorValidacion(
            errores=[ErrorCampo("variables", "ESTRUCTURA_INVALIDA", "Se esperaba un objeto.")]
        )
    esperadas = {str(i) for i in range(1, n + 1)}
    for faltante in sorted(esperadas - set(variables), key=int):
        errores.append(
            ErrorCampo(f"variables.{faltante}", "VARIABLE_FALTANTE", "Asigne esta variable.")
        )
    for sobrante in sorted(set(variables) - esperadas):
        errores.append(
            ErrorCampo(
                f"variables.{sobrante}"[:60], "VARIABLE_NO_EXISTE", "La plantilla no la usa."
            )
        )
    dinamicos = {d.codigo_interno for d in definiciones or [] if d.activo and not d.es_sensible}
    sensibles = {d.codigo_interno for d in definiciones or [] if d.activo and d.es_sensible}
    for clave in sorted(set(variables) & esperadas, key=int):
        errores.extend(_una(clave, variables[clave], dinamicos, sensibles))
    if errores:
        raise ErrorValidacion(errores=errores)


def _una(clave: str, v: Any, dinamicos: set[str], sensibles: set[str]) -> list[ErrorCampo]:
    ruta = f"variables.{clave}"
    if not isinstance(v, dict) or v.get("origen") not in ("COLABORADOR", "FIJO"):
        return [ErrorCampo(ruta, "ESTRUCTURA_INVALIDA", "Indique el origen de la variable.")]
    if v["origen"] == "FIJO":
        valor = v.get("valor")
        if set(v) != {"origen", "valor"} or not isinstance(valor, str):
            return [ErrorCampo(ruta, "ESTRUCTURA_INVALIDA", "Una variable fija lleva un valor.")]
        if (
            not valor.strip()
            or len(valor) > MAX_VALOR
            or any(c in valor for c in "\n\r\t")
            or _CINCO_ESPACIOS.search(valor)
        ):
            return [
                ErrorCampo(
                    f"{ruta}.valor",
                    "VALOR_INVALIDO",
                    f"Use de 1 a {MAX_VALOR} caracteres en una sola línea.",
                )
            ]
        return []
    campo = v.get("campo")
    if set(v) != {"origen", "campo"} or not isinstance(campo, str):
        return [ErrorCampo(ruta, "ESTRUCTURA_INVALIDA", "Una variable de colaborador lleva campo.")]
    if campo in FIJAS or campo in dinamicos:
        return []
    if campo in sensibles:
        return [
            ErrorCampo(
                f"{ruta}.campo",
                "CAMPO_SENSIBLE_NO_PERMITIDO",
                "Un campo sensible no se puede usar.",
            )
        ]
    return [ErrorCampo(f"{ruta}.campo", "CAMPO_DESCONOCIDO", "El campo no existe o está inactivo.")]


def usa_campos_dinamicos(variables: Any) -> bool:
    if not isinstance(variables, dict):
        return False
    return any(
        isinstance(v, dict)
        and v.get("origen") == "COLABORADOR"
        and isinstance(v.get("campo"), str)
        and v["campo"] not in FIJAS
        for v in variables.values()
    )


def vista_previa(texto_plantilla: str, variables: dict[str, Any] | None) -> str:
    variables = variables or {}

    def sustituir(m: re.Match[str]) -> str:
        v = variables.get(m.group(1))
        if not isinstance(v, dict):
            return m.group(0)
        if v.get("origen") == "FIJO":
            return str(v.get("valor", ""))
        return "{{" + str(v.get("campo", "")) + "}}"

    return re.sub(r"\{\{([0-9]+)\}\}", sustituir, texto_plantilla)
