"""Avisos a RH por SNS (``alertas-rh``; design.md §7.4, CC-REQ-072, 074).

El aviso lleva el tipo y, a lo más, identificadores y motivos: nunca nombres, números ni valores.
Es de mejor esfuerzo: si SNS falla, se registra y la conversación sigue.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol

log = logging.getLogger("cc.alertas")

NO_DISPONIBLE = "SERVICIO_NO_DISPONIBLE"  # colaborador en BAJA o sin consentimiento vigente
ACCESO_BLOQUEADO = "ACCESO_BLOQUEADO"  # tres intentos fallidos de verificación


class Alertas(Protocol):
    async def avisar(self, empresa_id: int, tipo: str, datos: dict[str, Any]) -> None: ...


class AlertasNulas:
    async def avisar(self, empresa_id: int, tipo: str, datos: dict[str, Any]) -> None:
        log.info("alerta sin destino configurado", extra={"tipo": tipo})


class AlertasSns:
    def __init__(self, sns: Any, topic_arn: str) -> None:
        self._sns = sns
        self._arn = topic_arn

    async def avisar(self, empresa_id: int, tipo: str, datos: dict[str, Any]) -> None:
        mensaje = json.dumps({"tipo": tipo, "empresa_id": empresa_id, **datos})
        try:
            await asyncio.to_thread(
                self._sns.publish, TopicArn=self._arn, Subject=f"alerta-rh {tipo}", Message=mensaje
            )
        except Exception:  # noqa: BLE001
            log.warning("no se pudo publicar la alerta", extra={"tipo": tipo})
