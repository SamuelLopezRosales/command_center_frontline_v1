import httpx
import pytest
from cc_common.errores import ErrorNoAutenticado, ErrorProveedor
from cc_common.internal_client import (
    CircuitoAbierto,
    ClienteInterno,
    emitir_token_interno,
    verificar_token_interno,
)

SECRETO = "secreto-de-prueba-interno-0123456789"


def cliente(manejador, **kw) -> ClienteInterno:
    return ClienteInterno(
        "http://colaboradores.interno",
        servicio="whatsapp",
        secreto=lambda: SECRETO,
        transporte=httpx.MockTransport(manejador),
        espera_s=0,
        **kw,
    )


def test_token_interno_ida_y_vuelta():
    t = emitir_token_interno(SECRETO, "whatsapp")
    assert verificar_token_interno(t, SECRETO) == "whatsapp"
    assert verificar_token_interno(t, SECRETO, frozenset({"whatsapp"})) == "whatsapp"
    with pytest.raises(ErrorNoAutenticado):
        verificar_token_interno(t, SECRETO, frozenset({"constancias"}))
    with pytest.raises(ErrorNoAutenticado):
        verificar_token_interno(t, "otro-secreto-distinto-0123456789")


def test_token_interno_vencido():
    t = emitir_token_interno(SECRETO, "whatsapp", ttl_s=60, ahora=lambda: 1_000)
    with pytest.raises(ErrorNoAutenticado):
        verificar_token_interno(t, SECRETO)


async def test_envia_token_y_correlacion():
    vistos = {}

    def manejador(req: httpx.Request):
        vistos["auth"] = req.headers["authorization"]
        vistos["corr"] = req.headers["x-correlation-id"]
        return httpx.Response(200, json={"ok": True})

    c = cliente(manejador)
    r = await c.solicitar("POST", "/internal/x", correlacion_id="abc", json={})
    assert r.status_code == 200 and vistos["corr"] == "abc"
    assert verificar_token_interno(vistos["auth"].split(" ", 1)[1], SECRETO) == "whatsapp"
    await c.cerrar()


async def test_reintenta_get_ante_503():
    llamadas = []

    def manejador(_req):
        llamadas.append(1)
        return httpx.Response(503) if len(llamadas) < 3 else httpx.Response(200)

    c = cliente(manejador)
    assert (await c.solicitar("GET", "/internal/y")).status_code == 200
    assert len(llamadas) == 3
    await c.cerrar()


async def test_no_reintenta_post():
    llamadas = []

    def manejador(_req):
        llamadas.append(1)
        return httpx.Response(503)

    c = cliente(manejador)
    with pytest.raises(ErrorProveedor):
        await c.solicitar("POST", "/internal/z", json={})
    assert len(llamadas) == 1
    await c.cerrar()


async def test_no_reintenta_4xx():
    llamadas = []

    def manejador(_req):
        llamadas.append(1)
        return httpx.Response(404)

    c = cliente(manejador)
    assert (await c.solicitar("GET", "/internal/no")).status_code == 404
    assert len(llamadas) == 1
    await c.cerrar()


async def test_corte_de_circuito():
    reloj = {"t": 0.0}

    def manejador(_req):
        raise httpx.ConnectError("sin red")

    c = cliente(manejador, reintentos=0, umbral_fallos=5, apertura_s=30, reloj=lambda: reloj["t"])
    for _ in range(5):
        with pytest.raises(ErrorProveedor):
            await c.solicitar("GET", "/internal/a")
    assert c.circuito_abierto
    with pytest.raises(CircuitoAbierto):
        await c.solicitar("GET", "/internal/a")
    reloj["t"] = 31
    assert not c.circuito_abierto
    await c.cerrar()
