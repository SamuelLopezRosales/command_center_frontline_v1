import time

import jwt
import pytest
from cc_common.auth import (
    UsuarioActual,
    VerificadorToken,
    extraer_bearer,
    requiere_permiso,
    ruta_publica,
    rutas_sin_permiso,
)
from cc_common.errores import ErrorNoAutenticado, instalar_manejadores
from cc_common.permisos import ROL_PERMISOS, Permiso
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

EMISOR = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_PRUEBA"
CLIENTE = "cliente-spa"
LLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTRA = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(llave=LLAVE, **cambios) -> str:
    ahora = int(time.time())
    claims = {
        "sub": "u-1",
        "iss": EMISOR,
        "client_id": CLIENTE,
        "token_use": "access",
        "iat": ahora,
        "exp": ahora + 900,
        "jti": "j-1",
        "empresa_id": "7",
        "rol": "RH",
    }
    claims.update(cambios)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, llave, algorithm="RS256")


VERIFICADOR = VerificadorToken(EMISOR, CLIENTE, resolver_llave=lambda _t: LLAVE.public_key())


def test_token_valido():
    u = VERIFICADOR.verificar(token())
    assert u == UsuarioActual(sub="u-1", empresa_id=7, rol="RH", jti="j-1")
    assert u.usuario_id is None


def test_claim_usuario_id():
    from cc_common.auth import requerir_usuario_id

    u = VERIFICADOR.verificar(token(usuario_id="42"))
    assert u.usuario_id == 42 and requerir_usuario_id(u) == 42
    with pytest.raises(ErrorNoAutenticado):
        requerir_usuario_id(VERIFICADOR.verificar(token()))  # token anterior al claim
    for malo in ("x", "0", "-3"):
        with pytest.raises(ErrorNoAutenticado):
            VERIFICADOR.verificar(token(usuario_id=malo))


@pytest.mark.parametrize(
    "cambios",
    [
        {"iss": "https://otro-emisor"},
        {"client_id": "otro-cliente"},
        {"token_use": "id"},
        {"exp": int(time.time()) - 3600},
        {"empresa_id": None},
        {"rol": None},
        {"empresa_id": "no-numero"},
        {"token_use": None},
    ],
)
def test_tokens_invalidos(cambios):
    with pytest.raises(ErrorNoAutenticado):
        VERIFICADOR.verificar(token(**cambios))


def test_firma_de_otra_llave():
    with pytest.raises(ErrorNoAutenticado):
        VERIFICADOR.verificar(token(llave=OTRA))


def test_bearer():
    assert extraer_bearer("Bearer abc") == "abc"
    for malo in (None, "", "Basic abc"):
        with pytest.raises(ErrorNoAutenticado):
            extraer_bearer(malo)


def test_rh_tiene_todos_los_permisos():
    assert ROL_PERMISOS["RH"] == frozenset(Permiso)


def _app() -> FastAPI:
    app = FastAPI()
    instalar_manejadores(app)

    def usuario(authorization: str | None = Header(default=None)) -> UsuarioActual:
        return VERIFICADOR.verificar(extraer_bearer(authorization))

    @app.get("/salud")
    def salud():
        return {"ok": True}

    @app.get("/colaboradores")
    def listar(u: UsuarioActual = requiere_permiso(Permiso.COLABORADORES_VER, usuario)):
        return {"empresa_id": u.empresa_id}

    @app.get("/publico/verificar/{codigo}", dependencies=[ruta_publica()])
    def verificar(codigo: str):
        return {"codigo": codigo}

    return app


def test_ruta_protegida_con_y_sin_token():
    c = TestClient(_app())
    assert c.get("/colaboradores").status_code == 401
    r = c.get("/colaboradores", headers={"Authorization": f"Bearer {token()}"})
    assert r.status_code == 200 and r.json() == {"empresa_id": 7}


def test_rol_sin_permiso_da_403():
    c = TestClient(_app())
    r = c.get("/colaboradores", headers={"Authorization": f"Bearer {token(rol='OTRO')}"})
    assert r.status_code == 403


def test_todas_las_rutas_declaran_permiso():
    assert rutas_sin_permiso(_app()) == []


def test_detecta_ruta_sin_permiso():
    app = _app()

    @app.get("/olvidada")
    def olvidada():
        return {}

    assert rutas_sin_permiso(app) == ["GET /olvidada"]


def test_detecta_rutas_sin_permiso_dentro_de_routers_incluidos():
    """Con FastAPI reciente las rutas de ``include_router`` no están en ``app.routes``: el
    recorrido debe entrar en ellas, con su prefijo (regresión de T-207)."""
    from fastapi import APIRouter

    def usuario(authorization: str | None = Header(default=None)) -> UsuarioActual:
        raise NotImplementedError  # nunca se invoca: solo se inspeccionan las rutas

    app = _app()
    router = APIRouter()

    @router.get("/olvidada")
    def olvidada():
        return {}

    @router.get("/protegida")
    def protegida(u=requiere_permiso(Permiso.COLABORADORES_VER, usuario)):  # noqa: B008
        return {}

    interno = APIRouter()

    @interno.delete("/profunda")
    def profunda():
        return {}

    router.include_router(interno, prefix="/anidado")
    app.include_router(router, prefix="/api/v1")
    assert sorted(rutas_sin_permiso(app)) == [
        "DELETE /api/v1/anidado/profunda",
        "GET /api/v1/olvidada",
    ]
