"""Ayudantes de prueba del servicio campos: tokens firmados y construcción de la aplicación."""

import time
import uuid

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

EMISOR = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_PRUEBA"
CLIENTE = "cliente-spa"
LLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SECRETO_INTERNO = "secreto-interno-de-prueba-0123456789-abcdef"


def emitir(sub: str, empresa_id: int, usuario_id: int | None, rol: str = "RH") -> str:
    ahora = int(time.time())
    claims = {
        "sub": sub,
        "iss": EMISOR,
        "client_id": CLIENTE,
        "token_use": "access",
        "iat": ahora,
        "exp": ahora + 900,
        "jti": uuid.uuid4().hex,
        "empresa_id": str(empresa_id),
        "rol": rol,
    }
    if usuario_id is not None:
        claims["usuario_id"] = str(usuario_id)
    return jwt.encode(claims, LLAVE, algorithm="RS256")


def cab(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def interno(servicio: str, empresa_id: int | None) -> dict[str, str]:
    from cc_common.internal_client import emitir_token_interno

    h = {"Authorization": f"Bearer {emitir_token_interno(SECRETO_INTERNO, servicio)}"}
    if empresa_id is not None:
        h["X-Empresa-Id"] = str(empresa_id)
    return h


def construir_app(motor, colaboradores=None, constancias=None, **cfg):
    from cc_campos.clientes import StubColaboradores, StubConstancias
    from cc_campos.config import ConfigCampos
    from cc_campos.main import crear_app
    from cc_common.auth import VerificadorToken

    return crear_app(
        ConfigCampos(cognito_emisor=EMISOR, cognito_client_id=CLIENTE, **cfg),
        motor=motor,
        verificador=VerificadorToken(EMISOR, CLIENTE, resolver_llave=lambda _t: LLAVE.public_key()),
        colaboradores=colaboradores or StubColaboradores(),
        constancias=constancias or StubConstancias(),
        secreto_interno=lambda: SECRETO_INTERNO,
    )


def sql(datos, consulta, params=()):
    """Consulta con el rol administrador (sin RLS) para comprobar el estado de la base."""
    import psycopg

    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        cur = c.execute(consulta, params)
        return cur.fetchall() if cur.description else []
