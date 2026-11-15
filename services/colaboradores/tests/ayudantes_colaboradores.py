"""Ayudantes de prueba del servicio colaboradores: tokens firmados y KMS simulado."""

import os
import time
import uuid

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

EMISOR = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_PRUEBA"
CLIENTE = "cliente-spa"
LLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
LLAVE_HMAC = b"h" * 32
LLAVE_KMS = "alias/cc-test-datos"


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


class KmsFalso:
    """La DEK "cifrada" es la clara XOR una máscara, ligada al contexto de cifrado."""

    def __init__(self):
        self.llamadas = {"generate": 0, "decrypt": 0}
        self._mascara = os.urandom(32)

    def _etiqueta(self, contexto: dict) -> bytes:
        return repr(sorted(contexto.items())).encode()

    def generate_data_key(self, **kw):
        self.llamadas["generate"] += 1
        assert kw["KeySpec"] == "AES_256" and kw["EncryptionContext"]["servicio"] == "colaboradores"
        claro = os.urandom(32)
        envuelta = bytes(a ^ b for a, b in zip(claro, self._mascara, strict=True))
        return {
            "Plaintext": claro,
            "CiphertextBlob": envuelta + self._etiqueta(kw["EncryptionContext"]),
        }

    def decrypt(self, **kw):
        self.llamadas["decrypt"] += 1
        blob = kw["CiphertextBlob"]
        if not blob.endswith(self._etiqueta(kw["EncryptionContext"])):
            raise RuntimeError("InvalidCiphertextException")
        return {"Plaintext": bytes(a ^ b for a, b in zip(blob[:32], self._mascara, strict=True))}


SECRETO_INTERNO = "secreto-interno-de-prueba-0123456789-abcdef"


def interno(servicio: str, empresa_id: int | None) -> dict[str, str]:
    from cc_common.internal_client import emitir_token_interno

    h = {"Authorization": f"Bearer {emitir_token_interno(SECRETO_INTERNO, servicio)}"}
    if empresa_id is not None:
        h["X-Empresa-Id"] = str(empresa_id)
    return h


def construir_app(motor, cifrador, almacen=None, campos=None, **cfg):
    from cc_colaboradores.campos_cliente import CacheCampos, StubCampos
    from cc_colaboradores.config import ConfigColaboradores
    from cc_colaboradores.main import crear_app
    from cc_common.auth import VerificadorToken

    return crear_app(
        ConfigColaboradores(cognito_emisor=EMISOR, cognito_client_id=CLIENTE, **cfg),
        motor=motor,
        verificador=VerificadorToken(EMISOR, CLIENTE, resolver_llave=lambda _t: LLAVE.public_key()),
        cifrador=cifrador,
        almacen=almacen,
        campos=campos or CacheCampos(StubCampos()),
        secreto_interno=lambda: SECRETO_INTERNO,
    )
