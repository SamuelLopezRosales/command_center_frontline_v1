"""Normalización de números (design.md §7.5): se busca por los últimos 10 dígitos y se envía con
prefijo 52. El formato exacto de los móviles mexicanos se confirma al vincular la cuenta (PQ-07)."""

from __future__ import annotations

import hashlib
import re

_NO_DIGITO = re.compile(r"\D")


def ultimos_10(numero: str) -> str:
    return _NO_DIGITO.sub("", numero)[-10:]


def destino_meta(numero: str) -> str:
    return "52" + ultimos_10(numero)


def grupo_de(wa_id: str) -> str:
    """Grupo FIFO de ``wa-entrada``: SHA-256 del ``wa_id`` (el número no viaja como grupo)."""
    return hashlib.sha256(wa_id.encode()).hexdigest()
