"""T-218: INT-NOT-01 (plantilla de mensaje para el chat de RH de `whatsapp`) y su cliente."""

import httpx
import pytest
from ayudantes_notificaciones import SECRETO_INTERNO, insertar_plantilla
from cc_common.internal_client import ClienteInterno, emitir_token_interno

pytestmark = pytest.mark.docker


def cab_interna(empresa: int, servicio: str = "whatsapp") -> dict[str, str]:
    return {
        "Authorization": "Bearer " + emitir_token_interno(SECRETO_INTERNO, servicio),
        "X-Empresa-Id": str(empresa),
    }


async def test_devuelve_la_plantilla_de_la_empresa(http, datos):
    pid = insertar_plantilla(datos, nombre="aviso_cita", texto="Hola {{1}}")
    r = await http.get(f"/internal/plantillas-mensaje/{pid}", headers=cab_interna(datos["a"]))
    assert r.status_code == 200, r.text
    assert r.json() == {
        "id": pid, "nombre": "aviso_cita", "estado_meta": "APROBADA", "idioma": "es_MX",
        "texto_con_variables": "Hola {{1}}",
    }  # fmt: skip


async def test_otra_empresa_inexistente_y_servicios_no_permitidos(http, datos):
    pid = insertar_plantilla(datos)
    assert (
        await http.get(f"/internal/plantillas-mensaje/{pid}", headers=cab_interna(datos["b"]))
    ).status_code == 404  # RLS: la plantilla es de A
    assert (
        await http.get("/internal/plantillas-mensaje/99999", headers=cab_interna(datos["a"]))
    ).status_code == 404
    for servicio in ("constancias", "colaboradores"):
        r = await http.get(
            f"/internal/plantillas-mensaje/{pid}", headers=cab_interna(datos["a"], servicio)
        )
        assert r.status_code == 401
    assert (await http.get(f"/internal/plantillas-mensaje/{pid}")).status_code == 401


async def test_el_cliente_de_whatsapp_la_lee_y_distingue_la_inexistente(http, datos, motor):
    from ayudantes_notificaciones import construir_app
    from cc_whatsapp.clientes import NotificacionesHttp

    pid = insertar_plantilla(datos, estado="EN_REVISION")
    app = construir_app(motor)
    cliente = NotificacionesHttp(
        ClienteInterno(
            "http://nots",
            servicio="whatsapp",
            secreto=lambda: SECRETO_INTERNO,
            transporte=httpx.ASGITransport(app=app),
            reintentos=0,
        )  # fmt: skip
    )
    p = await cliente.plantilla(datos["a"], pid)
    assert p["estado_meta"] == "EN_REVISION" and p["nombre"] == "aviso_uniformes_v1"
    assert await cliente.plantilla(datos["a"], 99999) is None
    assert await cliente.plantilla(datos["b"], pid) is None
