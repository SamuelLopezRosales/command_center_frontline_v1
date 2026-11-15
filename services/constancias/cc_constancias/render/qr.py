"""Código QR de verificación (design.md §5.4; CC-REQ-080).

Codifica ``https://{dominio}/v/{codigo_verificacion}`` con corrección de errores M. Se genera como
SVG (``segno``, sin dependencias nativas) y se entrega como URI ``data:`` para incrustarlo en el
HTML sin pedir ningún recurso externo.
"""

from __future__ import annotations

import re

import segno

CODIGO = re.compile(r"^[A-Za-z0-9_-]{22,64}$")
DOMINIO = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(:\d{1,5})?$")


def url_verificacion(dominio: str, codigo: str) -> str:
    """``https://{dominio}/v/{codigo}``. Valida ambos: terminan dentro de HTML y CSS."""
    if not DOMINIO.match(dominio):
        raise ValueError("dominio inválido")
    if not CODIGO.match(codigo):
        raise ValueError("código de verificación inválido")
    return f"https://{dominio}/v/{codigo}"


def qr_data_uri(url: str, *, escala: int = 2) -> str:
    """SVG del QR (nivel M) como ``data:image/svg+xml``. Sin margen: el pie ya deja aire."""
    return segno.make(url, error="m").svg_data_uri(scale=escala, border=0)
