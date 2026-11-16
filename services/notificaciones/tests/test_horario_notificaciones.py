"""T-110: horario permitido (08:00 a 20:00 inclusive en la zona de la notificación). Sin base."""

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest
from cc_common.errores import ErrorValidacion
from cc_notificaciones.servicios import horario

MX = "America/Mexico_City"
ZMX = ZoneInfo(MX)


def _local(h, m=0, s=0, dia=17):
    return datetime(2026, 11, dia, h, m, s, tzinfo=ZMX)


@pytest.mark.parametrize(
    ("hora", "esperado"),
    [
        (_local(7, 59, 59), False),
        (_local(8, 0, 0), True),  # inicio inclusivo
        (_local(12), True),
        (_local(20, 0, 0), True),  # fin inclusivo
        (_local(20, 0, 1), False),
        (_local(23, 59), False),
        (_local(0, 0), False),
    ],
)
def test_bordes_inclusivos(hora, esperado):
    assert horario.dentro_de_horario(hora, MX) is esperado


def test_se_evalua_en_la_zona_de_la_notificacion_no_en_utc():
    # 14:00 UTC = 08:00 en Ciudad de México (UTC-6) pero 09:00 en Nueva York (UTC-5)
    utc = datetime(2026, 11, 17, 14, 0, tzinfo=UTC)
    assert horario.dentro_de_horario(utc, MX)
    assert horario.dentro_de_horario(utc, "America/New_York")
    # 13:59 UTC: 07:59 en México (fuera) y 08:59 en Nueva York (dentro)
    antes = datetime(2026, 11, 17, 13, 59, tzinfo=UTC)
    assert not horario.dentro_de_horario(antes, MX)
    assert horario.dentro_de_horario(antes, "America/New_York")
    # 02:00 UTC del día siguiente = 20:00 en México (borde) del día 17
    assert horario.dentro_de_horario(datetime(2026, 11, 18, 2, 0, tzinfo=UTC), MX)
    assert not horario.dentro_de_horario(datetime(2026, 11, 18, 2, 0, 1, tzinfo=UTC), MX)


def test_el_horario_es_configurable():
    assert horario.dentro_de_horario(_local(21), MX, time(9, 0), time(22, 0))
    assert not horario.dentro_de_horario(_local(8, 59), MX, time(9, 0), time(22, 0))


def test_un_momento_sin_zona_es_un_error_de_programacion():
    with pytest.raises(ValueError, match="zona"):
        horario.dentro_de_horario(datetime(2026, 11, 17, 12, 0), MX)


def test_zona_invalida_da_422_sobre_el_campo():
    for malo in ("", "Marte/Olimpo", "../etc", "x" * 80):
        with pytest.raises(ErrorValidacion) as e:
            horario.zona(malo)
        assert e.value.errores[0].campo == "zona_horaria"


def test_siguiente_inicio_cambio_de_dia():
    # ya pasó el fin: mañana a las 08:00
    assert horario.siguiente_inicio(_local(20, 0, 1), MX) == _local(8, dia=18)
    # 23:30 cruza la medianoche: sigue siendo el día siguiente
    assert horario.siguiente_inicio(_local(23, 30), MX) == _local(8, dia=18)
    # madrugada: el mismo día
    assert horario.siguiente_inicio(_local(3, 15), MX) == _local(8)
    # fin de mes
    fin_de_mes = datetime(2026, 11, 30, 21, 0, tzinfo=ZMX)
    assert horario.siguiente_inicio(fin_de_mes, MX) == datetime(2026, 12, 1, 8, 0, tzinfo=ZMX)
    # ya en horario: el mismo momento
    assert horario.siguiente_inicio(_local(8), MX) == _local(8)
    assert horario.siguiente_inicio(_local(20), MX) == _local(20)


def test_siguiente_inicio_con_instante_utc_devuelve_hora_local():
    s = horario.siguiente_inicio(datetime(2026, 11, 18, 3, 0, tzinfo=UTC), MX)  # 21:00 del 17
    assert (s.day, s.hour) == (18, 8)
    assert s.utcoffset() == _local(8).utcoffset()


def test_cambio_de_hora_de_verano_en_otra_zona():
    # En Nueva York el 8 de marzo de 2026 se adelanta la hora (02:00 -> 03:00): 08:00 existe.
    z = ZoneInfo("America/New_York")
    s = horario.siguiente_inicio(datetime(2026, 3, 8, 6, 0, tzinfo=z), "America/New_York")
    assert (s.day, s.hour, s.minute) == (8, 8, 0)
    assert s.utcoffset().total_seconds() == -4 * 3600  # ya con horario de verano


def test_expresion_at_usa_la_hora_local_sin_zona():
    assert horario.expresion_at(datetime(2026, 11, 18, 15, 0, tzinfo=UTC), MX) == (
        "at(2026-11-18T09:00:00)"
    )


def test_limites_del_mes_local():
    ini, fin = horario.inicio_de_mes(datetime(2026, 12, 31, 23, 0, tzinfo=ZMX), MX)
    assert ini == datetime(2026, 12, 1, tzinfo=ZMX) and fin == datetime(2027, 1, 1, tzinfo=ZMX)
    # 04:00 UTC del 1 de diciembre sigue siendo noviembre en México (22:00 del 30)
    ini, fin = horario.inicio_de_mes(datetime(2026, 12, 1, 4, 0, tzinfo=UTC), MX)
    assert ini.month == 11 and fin.month == 12
