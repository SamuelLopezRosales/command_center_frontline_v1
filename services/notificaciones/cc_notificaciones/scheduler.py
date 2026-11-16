"""Cliente de EventBridge Scheduler para el envío programado (design.md §4.5, §6.3; CC-REQ-108).

Un envío programado es **un schedule único** (``at(...)``), sin ventana flexible y con acción
``DELETE`` al terminar, cuyo destino es la cola ``notif-despacho`` y cuyo cuerpo es
``{"notificacion_id", "tipo": "INICIO", "empresa_id"}`` (lo que el despachador de T-217 espera).
El nombre es determinista (``nombre_schedule``) y se guarda en ``notificacion.schedule_nombre``.

``crear_unico`` es idempotente: si el schedule ya existe (``ConflictException``) lo **actualiza**
con los mismos datos, así repetir la confirmación no crea un segundo schedule. ``eliminar`` ignora
un schedule inexistente (cancelación segura ante repetición).

El cliente es inyectable: ``SchedulerBoto`` usa boto3 (síncrono, en un hilo) y ``StubScheduler``
registra las llamadas en memoria para las pruebas y el modo local sin LocalStack de Scheduler.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol


def nombre_schedule(notificacion_id: int, intento: int = 0) -> str:
    """``cc-notif-{id}``; ``-{n}`` para las reprogramaciones del despachador (T-217). Cumple el
    formato de Scheduler (``[0-9a-zA-Z-_.]``, hasta 64 caracteres)."""
    base = f"cc-notif-{notificacion_id}"
    return base if intento == 0 else f"{base}-{intento}"


def cuerpo_despacho(notificacion_id: int, empresa_id: int, tipo: str = "INICIO") -> dict[str, Any]:
    return {"notificacion_id": notificacion_id, "tipo": tipo, "empresa_id": empresa_id}


@dataclass(frozen=True)
class ScheduleUnico:
    nombre: str
    expresion: str  # at(AAAA-MM-DDTHH:MM:SS), hora local de ``zona``
    zona: str
    cuerpo: dict[str, Any]


class ClienteScheduler(Protocol):
    async def crear_unico(self, s: ScheduleUnico) -> None: ...

    async def eliminar(self, nombre: str) -> None: ...


class StubScheduler:
    """Guarda los schedules por nombre (un nombre repetido sustituye al anterior)."""

    def __init__(self) -> None:
        self.schedules: dict[str, ScheduleUnico] = {}
        self.llamadas_crear = 0
        self.eliminados: list[str] = []
        self.error: Exception | None = None

    async def crear_unico(self, s: ScheduleUnico) -> None:
        if self.error:
            raise self.error
        self.llamadas_crear += 1
        self.schedules[s.nombre] = s

    async def eliminar(self, nombre: str) -> None:
        if self.error:
            raise self.error
        self.eliminados.append(nombre)
        self.schedules.pop(nombre, None)


class SchedulerBoto:
    def __init__(
        self,
        *,
        destino_arn: str,
        rol_arn: str,
        grupo: str = "default",
        region: str = "us-east-1",
        endpoint: str | None = None,
        cliente: Any | None = None,
    ) -> None:
        if cliente is None:  # pragma: no cover - requiere AWS o LocalStack
            import boto3

            cliente = boto3.client("scheduler", region_name=region, endpoint_url=endpoint or None)
        self._c = cliente
        self._destino = destino_arn
        self._rol = rol_arn
        self._grupo = grupo

    def _parametros(self, s: ScheduleUnico) -> dict[str, Any]:
        return {
            "Name": s.nombre,
            "GroupName": self._grupo,
            "ScheduleExpression": s.expresion,
            "ScheduleExpressionTimezone": s.zona,
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "ActionAfterCompletion": "DELETE",
            "State": "ENABLED",
            "Description": "Envio programado de notificacion",
            "Target": {
                "Arn": self._destino,
                "RoleArn": self._rol,
                "Input": json.dumps(s.cuerpo, separators=(",", ":")),
            },
        }

    def _crear_sync(self, s: ScheduleUnico) -> None:
        params = self._parametros(s)
        try:
            self._c.create_schedule(**params)
        except self._c.exceptions.ConflictException:
            self._c.update_schedule(**params)  # ya existía: se deja igual (idempotente)

    def _eliminar_sync(self, nombre: str) -> None:
        try:
            self._c.delete_schedule(Name=nombre, GroupName=self._grupo)
        except self._c.exceptions.ResourceNotFoundException:
            pass

    async def crear_unico(self, s: ScheduleUnico) -> None:
        await asyncio.to_thread(self._crear_sync, s)

    async def eliminar(self, nombre: str) -> None:
        await asyncio.to_thread(self._eliminar_sync, nombre)
