"""T-211 (T-093): el servicio whatsapp arranca y responde ``/salud`` sin infraestructura."""

import httpx
from cc_common.auth import rutas_sin_permiso
from cc_whatsapp.config import ConfigWhatsapp
from cc_whatsapp.main import crear_app


async def test_salud_responde_sin_conectarse_a_nada():
    app = crear_app(ConfigWhatsapp(), motor=object())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/salud")
    assert r.status_code == 200 and r.json()["servicio"] == "whatsapp"
    assert rutas_sin_permiso(app) == []
