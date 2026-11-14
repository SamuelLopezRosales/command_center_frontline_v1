"""Logging estructurado en JSON con filtro de datos personales (design.md §15.1, CC-REQ-162).

La regla principal es no registrar datos personales. Este filtro es la segunda barrera:
- elimina el valor de claves sensibles conocidas;
- enmascara patrones de celular, RFC, CURP, NSS, correo y llaves de AWS en cualquier texto.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

REDACTADO = "[REDACTADO]"

CLAVES_SENSIBLES = frozenset(
    {
        "celular",
        "telefono",
        "rfc",
        "curp",
        "nss",
        "sueldo",
        "correo",
        "email",
        "nombre",
        "nombres",
        "apellido_paterno",
        "apellido_materno",
        "password",
        "contrasena",
        "token",
        "authorization",
        "codigo",
        "codigo_verificacion",
        "texto",
        "mensaje_texto",
        "url_firmada",
        "secreto",
        "valor",
        "contenido",
    }
)

# El orden importa: CURP y RFC antes que los patrones numéricos.
_PATRONES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"), "[LLAVE_AWS]"),
    (re.compile(r"\b[A-Z]{4}\d{6}[HMX][A-Z]{5}[A-Z0-9]\d\b", re.I), "[CURP]"),
    (re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b", re.I), "[RFC]"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[CORREO]"),
    (re.compile(r"(?<!\d)(?:\+?52[\s-]?)?(?:\d[\s-]?){9}\d(?!\d)"), "[NUMERO]"),
    (re.compile(r"(?<!\d)\d{11}(?!\d)"), "[NSS]"),
)


def enmascarar_texto(texto: str) -> str:
    for patron, reemplazo in _PATRONES:
        texto = patron.sub(reemplazo, texto)
    return texto


def _filtrar(valor: Any, clave: str | None = None) -> Any:
    if clave is not None and clave.lower() in CLAVES_SENSIBLES:
        return REDACTADO
    if isinstance(valor, str):
        return enmascarar_texto(valor)
    if isinstance(valor, dict):
        return {k: _filtrar(v, str(k)) for k, v in valor.items()}
    if isinstance(valor, list | tuple):
        return [_filtrar(v) for v in valor]
    return valor


def filtro_datos_personales(_logger: Any, _metodo: str, evento: dict[str, Any]) -> dict[str, Any]:
    """Procesador de structlog que limpia el evento antes de serializarlo."""
    return {k: (v if k in ("timestamp", "level") else _filtrar(v, k)) for k, v in evento.items()}


def configurar_logging(servicio: str, ambiente: str, nivel: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=getattr(logging, nivel))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            filtro_datos_personales,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, nivel)),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(servicio=servicio, ambiente=ambiente)


def obtener_logger(nombre: str | None = None) -> Any:
    return structlog.get_logger(nombre)
