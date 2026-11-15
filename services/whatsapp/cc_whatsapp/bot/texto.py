"""Normalización y lectura del texto del colaborador (design.md §7.2)."""

from __future__ import annotations

import re
import unicodedata

PALABRAS_CLAVE = frozenset({"constancia", "constancias"})  # lista por confirmar (PQ-17)
_RESPUESTA_VERIFICACION = re.compile(r"^(\d{6})\s+(\S.{0,19})$")


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin acentos, sin signos en los extremos y con espacios simples."""
    if not texto:
        return ""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", sin_acentos.lower()).strip(" \t\n.,;:!¡?¿*_\"'")


def es_palabra_clave(texto: str | None) -> bool:
    return normalizar(texto) in PALABRAS_CLAVE


def leer_respuesta_de_verificacion(texto: str | None) -> tuple[str, str] | None:
    """``(código, dato)`` de un mensaje como ``123456 1234`` o ``123456 15/03``; ``None`` si no
    tiene esa forma. El dato se entrega tal cual a `colaboradores`, que lo valida (INT-COL-03)."""
    m = _RESPUESTA_VERIFICACION.match((texto or "").strip())
    return (m.group(1), m.group(2).strip()) if m else None
