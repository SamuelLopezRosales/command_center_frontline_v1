"""Regla única de elegibilidad de contacto (design.md §0.2 punto 3; CC-REQ-027, 157).

Un colaborador es elegible para recibir algo de la empresa si está ``ACTIVO`` y tiene
consentimiento vigente: ``consentimiento_whatsapp AND (vigente_hasta IS NULL OR vigente_hasta >
now())`` (design.md §2.2). Para los propósitos por WhatsApp, además, el celular no debe estar
marcado como inválido. La aplica INT-COL-05 (T-203) para todo envío; aquí vive la regla.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

PROPOSITOS = frozenset({"NOTIFICACION", "CONSTANCIA", "VERIFICACION", "CHAT", "CORREO"})
POR_WHATSAPP = frozenset({"NOTIFICACION", "CONSTANCIA", "VERIFICACION", "CHAT"})

# Misma regla en SQL, para listados y consultas por lote (alias de tabla ``c``).
SQL_CONSENTIMIENTO_VIGENTE = (
    "(c.consentimiento_whatsapp AND (c.consentimiento_vigente_hasta IS NULL "
    "OR c.consentimiento_vigente_hasta > now()))"
)


@dataclass(frozen=True)
class Elegibilidad:
    elegible: bool
    motivo: str | None = None  # BAJA, SIN_CONSENTIMIENTO, CONSENTIMIENTO_VENCIDO, CELULAR_INVALIDO


def consentimiento_vigente(fila: dict[str, Any], ahora: datetime | None = None) -> bool:
    if not fila.get("consentimiento_whatsapp"):
        return False
    hasta = fila.get("consentimiento_vigente_hasta")
    return hasta is None or hasta > (ahora or datetime.now(UTC))


def evaluar(
    fila: dict[str, Any], proposito: str = "NOTIFICACION", ahora: datetime | None = None
) -> Elegibilidad:
    if proposito not in PROPOSITOS:
        raise ValueError(f"propósito desconocido: {proposito}")
    if fila.get("estatus") != "ACTIVO":
        return Elegibilidad(False, "BAJA")
    if not fila.get("consentimiento_whatsapp"):
        return Elegibilidad(False, "SIN_CONSENTIMIENTO")
    if not consentimiento_vigente(fila, ahora):
        return Elegibilidad(False, "CONSENTIMIENTO_VENCIDO")
    if proposito in POR_WHATSAPP and fila.get("celular_invalido"):
        return Elegibilidad(False, "CELULAR_INVALIDO")
    return Elegibilidad(True)
