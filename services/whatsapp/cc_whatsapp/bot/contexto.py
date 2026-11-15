"""Dependencias del bot y resultado de procesar un mensaje."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cc_whatsapp.clientes import ClienteColaboradores, ClienteConstancias
from cc_whatsapp.servicios.alertas import Alertas


@dataclass
class Contexto:
    cfg: Any
    motor: Any
    colaboradores: ClienteColaboradores
    constancias: ClienteConstancias
    alertas: Alertas
    llave_codigos: bytes  # llave HMAC de los códigos (cc/{env}/whatsapp-hmac)


@dataclass
class Mensaje:
    """Mensaje entrante ya reducido por ``webhook-meta``."""

    wamid: str
    wa_id: str
    texto: str | None = None
    interactivo_id: str | None = None

    @classmethod
    def de(cls, cuerpo: dict[str, Any]) -> Mensaje:
        return cls(
            cuerpo["wamid"], cuerpo["wa_id"], cuerpo.get("texto"), cuerpo.get("interactivo_id")
        )


@dataclass
class Turno:
    """Estado de un mensaje en proceso: conexión, conversación y avisos pendientes de publicar
    cuando la transacción confirme."""

    ctx: Contexto
    conn: Any
    msg: Mensaje
    huella: bytes
    alertas: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    @property
    def empresa_id(self) -> int:
        return self.ctx.cfg.empresa_id
