"""Ayudantes de prueba del servicio dashboard: tokens de Cognito firmados con una llave local."""

import time
import uuid

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

EMISOR = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_PRUEBA"
CLIENTE = "cliente-spa"
LLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def emitir(sub: str, empresa_id: int, rol: str = "RH", jti: str | None = None) -> str:
    ahora = int(time.time())
    return jwt.encode(
        {
            "sub": sub,
            "iss": EMISOR,
            "client_id": CLIENTE,
            "token_use": "access",
            "iat": ahora,
            "exp": ahora + 900,
            "jti": jti or uuid.uuid4().hex,
            "empresa_id": str(empresa_id),
            "rol": rol,
        },
        LLAVE,
        algorithm="RS256",
    )


def cab(token: str, **extra) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **extra}


class CognitoFalso:
    """Registra las llamadas de desactivación; ``falla=True`` simula una caída de Cognito."""

    def __init__(self, falla: bool = False):
        self.llamadas: list[str] = []
        self.falla = falla

    async def deshabilitar_y_cerrar_sesiones(self, username: str) -> None:
        if self.falla:
            from cc_common.errores import ErrorProveedor

            raise ErrorProveedor("COGNITO_NO_DISPONIBLE", "No fue posible desactivar la cuenta.")
        self.llamadas.append(username)
