"""Horario permitido de envío (design.md §6.3; CC-REQ-109; RN-19; PQ-06).

Copia mínima de ``cc_notificaciones.servicios.horario`` (misma regla): una hora es válida si
``inicio <= hora_local <= fin`` (extremos inclusivos; 08:00 y 20:00 por defecto) en la zona de la
notificación. Los momentos siempre llevan zona.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

INICIO_DEFECTO = time(8, 0)
FIN_DEFECTO = time(20, 0)


def _con_zona(momento: datetime) -> datetime:
    if momento.tzinfo is None or momento.utcoffset() is None:
        raise ValueError("el momento debe llevar zona horaria")
    return momento


def a_local(momento: datetime, nombre_zona: str) -> datetime:
    return _con_zona(momento).astimezone(ZoneInfo(nombre_zona))


def dentro_de_horario(
    momento: datetime, nombre_zona: str, inicio: time = INICIO_DEFECTO, fin: time = FIN_DEFECTO
) -> bool:
    return inicio <= a_local(momento, nombre_zona).time() <= fin


def siguiente_inicio(
    momento: datetime, nombre_zona: str, inicio: time = INICIO_DEFECTO, fin: time = FIN_DEFECTO
) -> datetime:
    """El mismo momento si ya está en horario; si no, el siguiente ``inicio`` (hoy si todavía no
    llega, mañana si ya pasó ``fin``), con la zona de la notificación."""
    z = ZoneInfo(nombre_zona)
    local = _con_zona(momento).astimezone(z)
    hora = local.time()
    if inicio <= hora <= fin:
        return local
    dia = local.date() if hora < inicio else local.date() + timedelta(days=1)
    return datetime.combine(dia, inicio, tzinfo=z).astimezone(UTC).astimezone(z)


def expresion_at(momento: datetime, nombre_zona: str) -> str:
    """Expresión ``at(...)`` de EventBridge Scheduler: hora local sin zona (la zona viaja en
    ``ScheduleExpressionTimezone``)."""
    return "at(" + a_local(momento, nombre_zona).strftime("%Y-%m-%dT%H:%M:%S") + ")"
