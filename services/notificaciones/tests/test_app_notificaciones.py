"""T-215: el servicio notificaciones arranca, declara permisos en todas sus rutas y su contrato."""

import json

from cc_common.auth import rutas_sin_permiso
from cc_notificaciones.config import ConfigNotificaciones
from cc_notificaciones.main import crear_app
from fastapi.testclient import TestClient

from scripts.exportar_openapi import generar, main


def _app():
    return crear_app(ConfigNotificaciones(), motor=object(), verificador=object())


def test_salud_responde_sin_conectarse_a_nada():
    r = TestClient(_app()).get("/salud")
    assert r.status_code == 200 and r.json()["servicio"] == "notificaciones"


def test_todas_las_rutas_declaran_permiso():
    assert rutas_sin_permiso(_app()) == []


def test_openapi_determinista_y_contrato_al_dia():
    a, b = generar("notificaciones"), generar("notificaciones")
    assert a == b
    assert {
        "/api/v1/audiencias",
        "/api/v1/audiencias/{audiencia_id}",
        "/api/v1/audiencias/previsualizar",
        "/api/v1/notificaciones/{notificacion_id}/revisar",
        "/api/v1/notificaciones/{notificacion_id}/confirmar",
        "/api/v1/notificaciones/{notificacion_id}/destinatarios",
        "/api/v1/notificaciones/{notificacion_id}/duplicar",
        "/api/v1/notificaciones/indicadores",
        "/api/v1/plantillas-mensaje",
        "/api/v1/plantillas-mensaje/{plantilla_id}/enviar-revision",
        "/api/v1/plantillas-mensaje/{plantilla_id}/sincronizar",
        "/api/v1/plantillas-mensaje/{plantilla_id}/duplicar",
    } <= set(json.loads(a)["paths"])
    assert main(["exportar_openapi.py", "notificaciones", "--verificar"]) == 0


def test_el_contrato_de_colaboradores_incluye_int_col_06():
    rutas = json.loads(generar("colaboradores"))["paths"]
    assert "/internal/colaboradores/audiencias:evaluar" in rutas
    assert main(["exportar_openapi.py", "colaboradores", "--verificar"]) == 0


def test_con_eventos_activos_arranca_el_relay_del_outbox(monkeypatch):
    import asyncio

    from cc_notificaciones import main as principal

    arrancado = asyncio.Event()

    async def relay_falso(app, parar):
        arrancado.set()
        await parar.wait()

    monkeypatch.setattr(principal, "_relay", relay_falso)
    app = crear_app(
        ConfigNotificaciones(eventos_activos=True), motor=object(), verificador=object()
    )
    with TestClient(app):
        pass
    assert arrancado.is_set()


def test_sin_eventos_activos_no_arranca_nada(monkeypatch):
    from cc_notificaciones import main as principal

    def no_debe_llamarse(*_a, **_k):
        raise AssertionError("no debe arrancar el relay")

    monkeypatch.setattr(principal, "_relay", no_debe_llamarse)
    with TestClient(_app()):
        pass
