"""El servicio arranca el relay del outbox junto con el consumidor (T-204, hallazgo de T-local)."""

import asyncio

from cc_colaboradores import consumidores, main
from cc_colaboradores.config import ConfigColaboradores


async def test_con_eventos_activos_arranca_el_relay_y_el_consumidor(monkeypatch):
    iniciados: list[str] = []

    async def relay(_app, parar):
        iniciados.append("relay")
        await parar.wait()

    async def consumidor(_app, parar):
        iniciados.append("consumidor")
        await parar.wait()

    monkeypatch.setattr(main, "_relay", relay)
    monkeypatch.setattr(consumidores, "ejecutar", consumidor)
    app = main.crear_app(ConfigColaboradores(eventos_activos=True), motor=object())
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0)
        assert sorted(iniciados) == ["consumidor", "relay"]


async def test_sin_eventos_activos_no_arranca_nada(monkeypatch):
    llamadas: list[str] = []

    async def espia(_app, _parar):
        llamadas.append("x")

    monkeypatch.setattr(main, "_relay", espia)
    monkeypatch.setattr(consumidores, "ejecutar", espia)
    app = main.crear_app(ConfigColaboradores(eventos_activos=False), motor=object())
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0)
    assert llamadas == []
