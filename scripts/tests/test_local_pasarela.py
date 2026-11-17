"""Pasarela local y proveedor de identidad de desarrollo (scripts/local/pasarela.py)."""

import json

import httpx
import jwt
import pytest
from cc_common.auth import VerificadorToken
from cc_common.errores import ErrorNoAutenticado

from scripts.local import constantes as c
from scripts.local.pasarela import crear_app, destino

URLS = {
    n: f"http://{n}.test"
    for n in ("dashboard", "colaboradores", "campos", "constancias", "whatsapp")
}


@pytest.mark.parametrize(
    ("ruta", "servicio"),
    [
        ("/api/v1/constancias/historial", "dashboard"),
        ("/api/v1/constancias/variables", "constancias"),
        ("/api/v1/constancias/12", "constancias"),
        ("/api/v1/constancias/12/descarga", "constancias"),
        ("/api/v1/plantillas", "constancias"),
        ("/api/v1/plantillas/3/borrador", "constancias"),
        ("/api/v1/publico/verificar/abc", "constancias"),
        ("/d/token/descargar", "constancias"),
        ("/api/v1/colaboradores/7", "colaboradores"),
        ("/api/v1/cargas/plantilla", "colaboradores"),
        ("/api/v1/organizaciones/1/logotipo", "colaboradores"),
        ("/api/v1/plantas", "colaboradores"),
        ("/api/v1/campos/3/opciones", "campos"),
        ("/api/v1/dashboard/resumen", "dashboard"),
        ("/api/v1/usuarios/yo", "dashboard"),
        ("/api/v1/sesion/iniciar", "dashboard"),
        ("/api/v1/bitacora", "dashboard"),
        ("/api/v1/integraciones/meta", "notificaciones"),
        ("/api/v1/integraciones/meta/verify-token:generar", "notificaciones"),
        ("/api/v1/integraciones/meta/probar", "notificaciones"),
    ],
)
def test_tabla_de_rutas(ruta, servicio):
    assert destino(ruta) == servicio


@pytest.mark.parametrize(
    "ruta",
    ["/internal/campos", "/internal", "/api/v1/plantillasX", "/api/v1/camposx", "/dx", "/otra"],
)
def test_lo_que_no_es_publico_no_se_enruta(ruta):
    assert destino(ruta) is None


def test_se_niega_a_arrancar_fuera_de_local(monkeypatch, tmp_path):
    for ambiente in ("dev", "prod", "test", ""):
        monkeypatch.setenv("CC_AMBIENTE", ambiente)
        with pytest.raises(RuntimeError, match="CC_AMBIENTE=local"):
            crear_app(archivo_llave=tmp_path / "k.pem", archivo_usuarios=tmp_path / "u.json")
    monkeypatch.delenv("CC_AMBIENTE")
    with pytest.raises(RuntimeError):
        crear_app(archivo_llave=tmp_path / "k.pem", archivo_usuarios=tmp_path / "u.json")


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_AMBIENTE", "local")
    usuarios = tmp_path / "usuarios.json"
    usuarios.write_text(
        json.dumps(
            [
                {
                    "correo": "ana.rh@demo.test",
                    "sub": "sub-ana",
                    "empresa_id": 4,
                    "usuario_id": 9,
                    "rol": "RH",
                }
            ]
        )
    )
    recibidas: list[httpx.Request] = []

    def responder(req: httpx.Request) -> httpx.Response:
        recibidas.append(req)
        return httpx.Response(200, json={"host": req.url.host}, headers={"x-origen": "servicio"})

    app = crear_app(
        urls=URLS,
        archivo_llave=tmp_path / "idp.pem",
        archivo_usuarios=usuarios,
        transporte=httpx.MockTransport(responder),
    )
    cliente = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://pasarela")
    return cliente, recibidas, app


async def test_reenvia_al_servicio_correcto_con_consulta_y_encabezados(entorno):
    http, recibidas, _ = entorno
    r = await http.get("/api/v1/colaboradores?q=a&q=b", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json() == {"host": "colaboradores.test"}
    assert r.headers["x-origen"] == "servicio"
    assert recibidas[0].url.params.get_list("q") == ["a", "b"]
    assert recibidas[0].headers["authorization"] == "Bearer x"
    assert recibidas[0].headers["host"] == "colaboradores.test"


async def test_internal_y_rutas_desconocidas_no_se_exponen(entorno):
    http, recibidas, _ = entorno
    for ruta in ("/internal/campos", "/internal/plantillas/activas", "/api/v1/otra"):
        assert (await http.get(ruta)).status_code == 404
    assert recibidas == []


async def test_servicio_caido_da_502_claro(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_AMBIENTE", "local")

    def caido(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin conexión", request=req)

    app = crear_app(
        urls=URLS,
        archivo_llave=tmp_path / "k.pem",
        archivo_usuarios=tmp_path / "u.json",
        transporte=httpx.MockTransport(caido),
    )
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://p")
    r = await http.get("/api/v1/campos")
    assert r.status_code == 502
    assert r.json()["codigo"] == "SERVICIO_NO_DISPONIBLE:campos"


async def test_flujo_de_acceso_emite_un_token_que_los_servicios_aceptan(entorno):
    http, _, app = entorno
    r = await http.post(
        "/api/dev/auth/iniciar",
        json={"correo": "ANA.rh@demo.test", "contrasena": c.CONTRASENA_DEV},
    )
    assert r.status_code == 200 and r.json()["paso"] == "TOTP"
    sesion = r.json()["sesion"]

    # Un código que no son 6 dígitos se rechaza; la sesión sigue vigente para reintentar.
    malo = await http.post("/api/dev/auth/totp", json={"sesion": sesion, "codigo": "12ab"})
    assert malo.status_code == 401 and malo.json()["codigo"] == "CODIGO_INVALIDO"
    ok = await http.post("/api/dev/auth/totp", json={"sesion": sesion, "codigo": "000000"})
    assert ok.status_code == 200
    token = ok.json()["access_token"]

    # Los servicios lo validan con el verificador real, usando el JWKS que publica la pasarela.
    jwks = (await http.get("/.well-known/jwks.json")).json()
    llave = jwt.PyJWK(jwks["keys"][0]).key
    verificador = VerificadorToken(c.EMISOR, c.CLIENT_ID, resolver_llave=lambda _t: llave)
    u = verificador.verificar(token)
    assert (u.sub, u.empresa_id, u.rol, u.usuario_id) == ("sub-ana", 4, "RH", 9)
    # Con otro cliente o emisor el token no sirve.
    with pytest.raises(ErrorNoAutenticado):
        VerificadorToken(c.EMISOR, "otro-cliente", resolver_llave=lambda _t: llave).verificar(token)
    with pytest.raises(ErrorNoAutenticado):
        VerificadorToken("http://otro", c.CLIENT_ID, resolver_llave=lambda _t: llave).verificar(
            token
        )
    assert app.state.idp.kid == jwt.get_unverified_header(token)["kid"]

    # La sesión de acceso es de un solo uso.
    de_nuevo = await http.post("/api/dev/auth/totp", json={"sesion": sesion, "codigo": "000000"})
    assert de_nuevo.status_code == 401


async def test_credenciales_incorrectas_no_distinguen_usuario_de_contrasena(entorno):
    http, _, _ = entorno
    for correo, clave in (
        ("ana.rh@demo.test", "mala"),
        ("nadie@demo.test", c.CONTRASENA_DEV),
        ("", ""),
    ):
        r = await http.post("/api/dev/auth/iniciar", json={"correo": correo, "contrasena": clave})
        assert (r.status_code, r.json()) == (401, {"codigo": "CREDENCIALES"})


async def test_la_llave_se_genera_una_vez_y_se_reutiliza(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_AMBIENTE", "local")
    primera = crear_app(
        urls=URLS, archivo_llave=tmp_path / "k.pem", archivo_usuarios=tmp_path / "u"
    )
    segunda = crear_app(
        urls=URLS, archivo_llave=tmp_path / "k.pem", archivo_usuarios=tmp_path / "u"
    )
    assert primera.state.idp.kid == segunda.state.idp.kid
