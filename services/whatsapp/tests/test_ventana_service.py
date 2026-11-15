"""T-211 (T-096): VentanaService (design.md §7.3)."""

from datetime import UTC, datetime, timedelta

import pytest
from cc_whatsapp.servicios.ventana_service import PLANTILLA, RECHAZAR, TEXTO, VentanaService

AHORA = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
V = VentanaService()


def test_la_ventana_dura_24_horas_desde_el_ultimo_mensaje_entrante():
    assert V.abierta(AHORA - timedelta(hours=23, minutes=59), AHORA)
    assert not V.abierta(AHORA - timedelta(hours=24), AHORA)
    assert not V.abierta(None, AHORA)


@pytest.mark.parametrize(
    ("origen", "tipo", "abierta", "plantilla", "accion", "motivo"),
    [
        ("NOTIFICACION", "PLANTILLA", True, "aviso", PLANTILLA, None),  # siempre plantilla
        ("NOTIFICACION", "TEXTO", True, None, RECHAZAR, "PLANTILLA_REQUERIDA"),
        ("NOTIFICACION", "TEXTO", False, None, RECHAZAR, "VENTANA_24H_CERRADA"),
        ("CONSTANCIA", "TEXTO", True, "constancia_lista", TEXTO, None),
        ("CONSTANCIA", "TEXTO", False, "constancia_lista", PLANTILLA, None),
        ("CONSTANCIA", "TEXTO", False, None, RECHAZAR, "VENTANA_CERRADA"),
        ("CHAT", "TEXTO", True, None, TEXTO, None),
        ("CHAT", "TEXTO", False, None, RECHAZAR, "VENTANA_24H_CERRADA"),
        ("CHAT", "PLANTILLA", False, "aviso", PLANTILLA, None),
        ("BOT", "TEXTO", True, None, TEXTO, None),
        ("BOT", "TEXTO", False, None, RECHAZAR, "VENTANA_CERRADA"),
    ],
)
def test_tabla_de_decisiones(origen, tipo, abierta, plantilla, accion, motivo):
    d = V.decidir(origen_tipo=origen, tipo_pedido=tipo, abierta=abierta, plantilla=plantilla)
    assert (d.accion, d.motivo) == (accion, motivo)
