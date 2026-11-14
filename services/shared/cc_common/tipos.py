"""Tipos de validación reutilizables (design.md §10.1, §10.2).

Los mensajes de error son fijos y nunca incluyen el valor recibido (CC-REQ-162).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BeforeValidator

_CELULAR = re.compile(r"^\d{10}$")
_RFC_PERSONA = re.compile(r"^[A-ZÑ&]{4}\d{6}[A-Z0-9]{3}$")
_RFC_ORG = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")
_CURP = re.compile(r"^[A-Z]{4}\d{6}[HMX][A-Z]{2}[B-DF-HJ-NP-TV-Z]{3}[A-Z0-9]\d$")
_NSS = re.compile(r"^\d{11}$")
_REG_PATRONAL = re.compile(r"^[A-Z0-9]{11}$")
_CORREO = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def _texto(v: Any) -> str:
    if not isinstance(v, str | int):
        raise ValueError("Debe ser texto.")
    return str(v).strip()


def _mayus(v: Any) -> str:
    return _texto(v).upper()


def _celular(v: Any) -> str:
    limpio = re.sub(r"[\s-]", "", _texto(v))
    if not _CELULAR.match(limpio):
        raise ValueError("Debe tener 10 dígitos.")
    return limpio


def _patron(regex: re.Pattern[str], mensaje: str):
    def validar(v: str) -> str:
        if not regex.match(v):
            raise ValueError(mensaje)
        return v

    return validar


def _numero_empleado(v: Any) -> str:
    v = _mayus(v)
    if not v:
        raise ValueError("No puede estar vacío.")
    if len(v) > 30:
        raise ValueError("Máximo 30 caracteres.")
    return v


def _fecha(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()
        for formato in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, formato).date()  # noqa: DTZ007
            except ValueError:
                continue
    raise ValueError("Fecha inválida; use dd/mm/aaaa.")


def _correo(v: Any) -> str:
    v = _texto(v)
    if len(v) > 254 or not _CORREO.match(v):
        raise ValueError("Correo inválido.")
    return v.lower()


Celular10 = Annotated[str, BeforeValidator(_celular)]
Rfc13 = Annotated[
    str,
    BeforeValidator(_mayus),
    AfterValidator(_patron(_RFC_PERSONA, "RFC inválido; debe tener 13 caracteres.")),
]
RfcOrg = Annotated[
    str,
    BeforeValidator(_mayus),
    AfterValidator(_patron(_RFC_ORG, "RFC inválido; debe tener 12 o 13 caracteres.")),
]
Curp = Annotated[
    str,
    BeforeValidator(_mayus),
    AfterValidator(_patron(_CURP, "CURP inválida; debe tener 18 caracteres.")),
]
Nss = Annotated[
    str,
    BeforeValidator(_texto),
    AfterValidator(_patron(_NSS, "NSS inválido; debe tener 11 dígitos.")),
]
RegistroPatronal = Annotated[
    str,
    BeforeValidator(_mayus),
    AfterValidator(_patron(_REG_PATRONAL, "Registro patronal inválido; debe tener 11 caracteres.")),
]
NumeroEmpleado = Annotated[str, BeforeValidator(_numero_empleado)]
FechaIngreso = Annotated[date, BeforeValidator(_fecha)]
Correo = Annotated[str, BeforeValidator(_correo)]
