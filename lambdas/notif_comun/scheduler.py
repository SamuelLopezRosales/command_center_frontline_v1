"""Cliente síncrono de EventBridge Scheduler para las Lambdas (design.md §4.5, §6.3, §6.4).

Mismo formato que ``cc_notificaciones.scheduler`` (schedule único ``at(...)``, sin ventana
flexible, acción ``DELETE`` al terminar, creación idempotente: si ya existe se **actualiza**), pero
síncrono y con dos destinos: ``DESPACHO`` (cola ``notif-despacho``) y ``RESPALDO`` (cola
``notif-respaldo``).

Nombres: ``cc-notif-{id}`` (la programación original del servicio), ``cc-notif-{id}-{n}`` para las
reprogramaciones del despachador y ``cc-notif-respaldo-{id}`` (más un sufijo de fecha cuando el
respaldo espera al siguiente inicio de horario).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

DESPACHO = "DESPACHO"
RESPALDO = "RESPALDO"


def nombre_schedule(notificacion_id: int, intento: int = 0) -> str:
    base = f"cc-notif-{notificacion_id}"
    return base if intento == 0 else f"{base}-{intento}"


def siguiente_nombre(notificacion_id: int, actual: str | None) -> str:
    """El nombre que sigue a ``actual`` (``cc-notif-7`` -> ``cc-notif-7-1`` -> ``cc-notif-7-2``)."""
    m = re.fullmatch(rf"cc-notif-{notificacion_id}(?:-(\d+))?", actual or "")
    n = int(m.group(1) or 0) if m else 0
    return nombre_schedule(notificacion_id, n + 1)


def nombre_respaldo(notificacion_id: int, sufijo: str | None = None) -> str:
    base = f"cc-notif-respaldo-{notificacion_id}"
    return f"{base}-{sufijo}" if sufijo else base


def cuerpo_despacho(notificacion_id: int, empresa_id: int, tipo: str = "INICIO") -> dict[str, Any]:
    """Lo que el servicio `notificaciones` programa y el despachador espera (sin ``evento_id``)."""
    return {"notificacion_id": notificacion_id, "tipo": tipo, "empresa_id": empresa_id}


def cuerpo_respaldo(notificacion_id: int, empresa_id: int) -> dict[str, Any]:
    return {"notificacion_id": notificacion_id, "empresa_id": empresa_id}


@dataclass(frozen=True)
class ScheduleUnico:
    nombre: str
    expresion: str  # at(AAAA-MM-DDTHH:MM:SS), hora local de ``zona``
    zona: str
    cuerpo: dict[str, Any]
    destino: str = DESPACHO


class ClienteScheduler(Protocol):
    def crear_unico(self, s: ScheduleUnico) -> None: ...


class StubScheduler:
    """Guarda los schedules por nombre (uno repetido sustituye al anterior)."""

    def __init__(self) -> None:
        self.schedules: dict[str, ScheduleUnico] = {}
        self.llamadas_crear = 0
        self.error: Exception | None = None

    def crear_unico(self, s: ScheduleUnico) -> None:
        if self.error:
            raise self.error
        self.llamadas_crear += 1
        self.schedules[s.nombre] = s


class SchedulerBoto:
    def __init__(
        self,
        *,
        destinos: dict[str, str],
        rol_arn: str,
        grupo: str = "default",
        region: str = "us-east-1",
        endpoint: str | None = None,
        cliente: Any | None = None,
    ) -> None:
        if cliente is None:  # pragma: no cover - requiere AWS
            import boto3

            cliente = boto3.client("scheduler", region_name=region, endpoint_url=endpoint or None)
        self._c = cliente
        self._destinos = destinos
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
            "Description": "Notificacion: despacho o respaldo por correo",
            "Target": {
                "Arn": self._destinos[s.destino],
                "RoleArn": self._rol,
                "Input": json.dumps(s.cuerpo, separators=(",", ":")),
            },
        }

    def crear_unico(self, s: ScheduleUnico) -> None:
        params = self._parametros(s)
        try:
            self._c.create_schedule(**params)
        except self._c.exceptions.ConflictException:
            self._c.update_schedule(**params)  # ya existía: se deja igual (idempotente)
