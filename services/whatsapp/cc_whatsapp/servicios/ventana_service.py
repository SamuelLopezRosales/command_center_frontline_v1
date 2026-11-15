"""Ventana de 24 horas y tipo de mensaje a enviar (design.md §7.3; CC-REQ-104, 116, 085).

La ventana se mide con ``conversacion_whatsapp.ultimo_mensaje_entrante_at``. Dentro de la ventana
se puede enviar texto libre; fuera, solo plantillas aprobadas. Las notificaciones de RH son siempre
plantilla.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

TEXTO = "TEXTO"
PLANTILLA = "PLANTILLA"
RECHAZAR = "RECHAZAR"


@dataclass(frozen=True)
class Decision:
    accion: str  # TEXTO, PLANTILLA o RECHAZAR
    motivo: str | None = None


class VentanaService:
    def __init__(self, horas: int = 24) -> None:
        self._ventana = timedelta(hours=horas)

    def abierta(self, ultimo_entrante: datetime | None, ahora: datetime | None = None) -> bool:
        if ultimo_entrante is None:
            return False
        return (ahora or datetime.now(UTC)) - ultimo_entrante < self._ventana

    def decidir(
        self,
        *,
        origen_tipo: str,
        tipo_pedido: str,
        abierta: bool,
        plantilla: str | None,
    ) -> Decision:
        """Qué enviar. ``plantilla`` es el nombre de la plantilla aprobada disponible (la del
        mensaje o, para constancias, la de "constancia lista")."""
        if origen_tipo == "NOTIFICACION":  # siempre plantilla aprobada
            if plantilla:
                return Decision(PLANTILLA)
            return Decision(
                RECHAZAR, "VENTANA_24H_CERRADA" if not abierta else "PLANTILLA_REQUERIDA"
            )
        if tipo_pedido == PLANTILLA and plantilla:
            return Decision(PLANTILLA)
        if abierta:
            return Decision(TEXTO)
        if origen_tipo in ("CONSTANCIA", "CHAT") and plantilla:
            return Decision(PLANTILLA)
        return Decision(
            RECHAZAR, "VENTANA_24H_CERRADA" if origen_tipo == "CHAT" else "VENTANA_CERRADA"
        )
