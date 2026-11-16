"""Horario permitido de envío (design.md §6.3; CC-REQ-109; RN-19; PQ-06). Módulo puro.

Una hora es válida si ``inicio <= hora_local <= fin`` (ambos extremos inclusivos; por defecto 08:00
y 20:00) en la zona de la notificación. La hora local se compara con segundos: 20:00:00 es válida y
20:00:01 ya no. Los momentos siempre llevan zona (``datetime`` con ``tzinfo``): uno sin zona es un
error de programación, no de entrada, y lanza ``ValueError``.

Lo usan la confirmación (NOT-19) y, en T-217, el despachador (que revalida al disparar y reprograma
al siguiente inicio con ``siguiente_inicio``) y el reintento de fallidos (NOT-22).
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cc_common.errores import ErrorCampo, ErrorValidacion

INICIO_DEFECTO = time(8, 0)
FIN_DEFECTO = time(20, 0)


def zona(nombre: str) -> ZoneInfo:
    """``ZoneInfo`` de un nombre IANA; si no existe lanza 422 sobre ``zona_horaria``."""
    try:
        if not nombre or len(nombre) > 64 or nombre.startswith("/") or ".." in nombre:
            raise ZoneInfoNotFoundError(nombre)
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ErrorValidacion(
            "ZONA_HORARIA_INVALIDA",
            "La zona horaria no es válida.",
            errores=[
                ErrorCampo("zona_horaria", "ZONA_HORARIA_INVALIDA", "Use un nombre IANA válido.")
            ],
        ) from exc


def _con_zona(momento: datetime) -> datetime:
    if momento.tzinfo is None or momento.utcoffset() is None:
        raise ValueError("el momento debe llevar zona horaria")
    return momento


def a_local(momento: datetime, nombre_zona: str) -> datetime:
    return _con_zona(momento).astimezone(zona(nombre_zona))


def dentro_de_horario(
    momento: datetime,
    nombre_zona: str,
    inicio: time = INICIO_DEFECTO,
    fin: time = FIN_DEFECTO,
) -> bool:
    return inicio <= a_local(momento, nombre_zona).time() <= fin


def siguiente_inicio(
    momento: datetime,
    nombre_zona: str,
    inicio: time = INICIO_DEFECTO,
    fin: time = FIN_DEFECTO,
) -> datetime:
    """El mismo momento si ya está en horario; si no, el siguiente ``inicio`` (hoy si todavía no
    llega, mañana si ya pasó ``fin``), con la zona de la notificación."""
    z = zona(nombre_zona)
    local = _con_zona(momento).astimezone(z)
    hora = local.time()
    if inicio <= hora <= fin:
        return local
    dia = local.date() if hora < inicio else local.date() + timedelta(days=1)
    candidato = datetime.combine(dia, inicio, tzinfo=z)
    # Normaliza por UTC: en una zona con cambio de hora, un inicio inexistente se desplaza.
    return candidato.astimezone(UTC).astimezone(z)


def expresion_at(momento: datetime, nombre_zona: str) -> str:
    """Expresión ``at(...)`` de EventBridge Scheduler: hora local sin zona (la zona viaja en
    ``ScheduleExpressionTimezone``)."""
    return "at(" + a_local(momento, nombre_zona).strftime("%Y-%m-%dT%H:%M:%S") + ")"


def inicio_de_mes(momento: datetime, nombre_zona: str) -> tuple[datetime, datetime]:
    """Límites ``[inicio, fin)`` del mes local de ``momento`` (indicadores del mes, NOT-24)."""
    z = zona(nombre_zona)
    local = _con_zona(momento).astimezone(z)
    ini = datetime(local.year, local.month, 1, tzinfo=z)
    sig = datetime(local.year + (local.month == 12), local.month % 12 + 1, 1, tzinfo=z)
    return ini, sig
