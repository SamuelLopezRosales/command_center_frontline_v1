"""Estrategias de entrega de la constancia al colaborador (design.md §5.6, D-10).

El mensaje que se escribe en ``wa-salida.fifo`` depende de la modalidad, que se elige con un
parámetro (``modo_entrega``): ``enlace`` (por defecto) manda un enlace de un solo uso y ``adjunto``
manda el PDF como archivo. Cambiar de modalidad solo cambia la estrategia: la generación, el folio
y los estados no cambian.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Entrega:
    empresa_id: int
    constancia_id: int
    solicitud_id: int
    colaborador_id: int
    conversacion_id: int | None
    folio: str
    pdf_s3_key: str
    reenvio: bool = False


class EstrategiaEntrega(Protocol):
    requiere_token: bool

    def mensaje(self, e: Entrega, token: str | None, dominio: str) -> dict: ...


def _base(e: Entrega, tipo: str) -> dict:
    return {
        "tipo": tipo,
        "mensaje_uuid": str(uuid.uuid4()),
        "empresa_id": e.empresa_id,
        "colaborador_id": e.colaborador_id,
        "conversacion_id": e.conversacion_id,
        "solicitud_id": e.solicitud_id,
        "constancia_id": e.constancia_id,
        "folio": e.folio,
    }


class EnlaceUnSoloUso:
    """Enlace ``https://{dominio}/d/{token}``, sin vista previa de enlaces en WhatsApp."""

    requiere_token = True

    def mensaje(self, e: Entrega, token: str | None, dominio: str) -> dict:
        if not token:
            raise ValueError("el modo enlace necesita un token")
        tipo = "CONSTANCIA_REENVIO" if e.reenvio else "CONSTANCIA_ENLACE"
        return _base(e, tipo) | {
            "enlace": f"https://{dominio}/d/{token}",
            "vista_previa_enlace": False,
        }


class AdjuntoPdf:
    """El PDF viaja como adjunto: no hay token ni página de descarga."""

    requiere_token = False

    def mensaje(self, e: Entrega, token: str | None, dominio: str) -> dict:
        tipo = "CONSTANCIA_REENVIO" if e.reenvio else "CONSTANCIA_ADJUNTO"
        return _base(e, tipo) | {"pdf_s3_key": e.pdf_s3_key, "nombre_archivo": f"{e.folio}.pdf"}


def estrategia_por_modo(modo: str) -> EstrategiaEntrega:
    if modo == "enlace":
        return EnlaceUnSoloUso()
    if modo == "adjunto":
        return AdjuntoPdf()
    raise ValueError(f"modo de entrega desconocido: {modo}")
