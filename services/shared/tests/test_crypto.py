import os

import pytest
from cc_common.crypto import (
    DekCifrada,
    EnvelopeCrypto,
    ErrorCifrado,
    aad,
    hmac_celular,
    iguales,
)


class KmsFalso:
    """Simula KMS: la DEK "cifrada" es la clara XOR una máscara, ligada al contexto."""

    def __init__(self):
        self.llamadas = {"generate": 0, "decrypt": 0}
        self._mascara = os.urandom(32)

    def _envolver(self, claro: bytes, contexto: dict) -> bytes:
        etiqueta = repr(sorted(contexto.items())).encode()
        return bytes(a ^ b for a, b in zip(claro, self._mascara, strict=True)) + etiqueta

    def generate_data_key(self, **kw):
        self.llamadas["generate"] += 1
        assert kw["KeySpec"] == "AES_256"
        claro = os.urandom(32)
        return {
            "Plaintext": claro,
            "CiphertextBlob": self._envolver(claro, kw["EncryptionContext"]),
        }

    def decrypt(self, **kw):
        self.llamadas["decrypt"] += 1
        blob, contexto = kw["CiphertextBlob"], kw["EncryptionContext"]
        etiqueta = repr(sorted(contexto.items())).encode()
        if not blob.endswith(etiqueta):
            raise RuntimeError("InvalidCiphertextException: contexto no coincide")
        envuelta = blob[:32]
        return {"Plaintext": bytes(a ^ b for a, b in zip(envuelta, self._mascara, strict=True))}


class Almacen:
    def __init__(self):
        self.filas: dict[tuple[int, int], DekCifrada] = {}
        self.activas: dict[int, int] = {}

    def activa(self, empresa_id):
        v = self.activas.get(empresa_id)
        return self.filas.get((empresa_id, v)) if v else None

    def obtener(self, empresa_id, version):
        return self.filas.get((empresa_id, version))

    def guardar(self, empresa_id, dek):
        self.filas[(empresa_id, dek.version)] = dek
        self.activas[empresa_id] = dek.version


@pytest.fixture
def entorno():
    kms, almacen = KmsFalso(), Almacen()
    reloj = {"t": 0.0}
    crypto = EnvelopeCrypto(
        kms, almacen, "alias/cc-test-datos", "colaboradores", lambda: reloj["t"]
    )
    return crypto, kms, almacen, reloj


AAD = aad("valor_campo", "valor_cifrado", 10, 1)


def test_ida_y_vuelta(entorno):
    crypto, *_ = entorno
    blob = crypto.cifrar("XAXX010101000", empresa_id=1, datos_aut=AAD)
    assert b"XAXX010101000" not in blob
    assert blob[0] == 1  # versión de formato
    assert crypto.descifrar(blob, empresa_id=1, datos_aut=AAD) == "XAXX010101000"


def test_nonce_distinto_por_cifrado(entorno):
    crypto, *_ = entorno
    assert crypto.cifrar("x", empresa_id=1, datos_aut=AAD) != crypto.cifrar(
        "x", empresa_id=1, datos_aut=AAD
    )


def test_valor_copiado_a_otra_fila_no_descifra(entorno):
    crypto, *_ = entorno
    blob = crypto.cifrar("12345678901", empresa_id=1, datos_aut=AAD)
    with pytest.raises(ErrorCifrado) as exc:
        crypto.descifrar(blob, empresa_id=1, datos_aut=aad("valor_campo", "valor_cifrado", 11, 1))
    assert "12345678901" not in str(exc.value)


def test_otra_empresa_no_descifra(entorno):
    crypto, *_ = entorno
    blob = crypto.cifrar("dato", empresa_id=1, datos_aut=AAD)
    with pytest.raises(ErrorCifrado):
        crypto.descifrar(blob, empresa_id=2, datos_aut=AAD)


def test_version_de_dek_se_respeta_al_rotar(entorno):
    crypto, kms, almacen, _ = entorno
    v1 = crypto.cifrar("antes", empresa_id=1, datos_aut=AAD)
    # Rotación: nueva versión activa.
    nueva = kms.generate_data_key(
        KeyId="k",
        KeySpec="AES_256",
        EncryptionContext={"servicio": "colaboradores", "empresa_id": "1"},
    )
    almacen.guardar(1, DekCifrada(2, nueva["CiphertextBlob"]))
    v2 = crypto.cifrar("despues", empresa_id=1, datos_aut=AAD)
    assert int.from_bytes(v1[1:5], "big") == 1 and int.from_bytes(v2[1:5], "big") == 2
    assert crypto.descifrar(v1, empresa_id=1, datos_aut=AAD) == "antes"
    assert crypto.descifrar(v2, empresa_id=1, datos_aut=AAD) == "despues"


def test_cache_de_dek_15_minutos(entorno):
    crypto, kms, _almacen, reloj = entorno
    blob = crypto.cifrar("x", empresa_id=1, datos_aut=AAD)
    otro = EnvelopeCrypto(kms, _almacen, "k", "colaboradores", lambda: reloj["t"])
    otro.descifrar(blob, empresa_id=1, datos_aut=AAD)
    otro.descifrar(blob, empresa_id=1, datos_aut=AAD)
    assert kms.llamadas["decrypt"] == 1
    reloj["t"] = 15 * 60 + 1
    otro.descifrar(blob, empresa_id=1, datos_aut=AAD)
    assert kms.llamadas["decrypt"] == 2


def test_formato_invalido(entorno):
    crypto, *_ = entorno
    with pytest.raises(ErrorCifrado, match="formato"):
        crypto.descifrar(b"\x01abc", empresa_id=1, datos_aut=AAD)


def test_hmac_celular_determinista_y_con_llave():
    llave = b"k" * 32
    h1 = hmac_celular(llave, "8112345678")
    assert h1 == hmac_celular(llave, "8112345678")
    assert h1 != hmac_celular(b"z" * 32, "8112345678")
    assert len(h1) == 32 and iguales(h1, hmac_celular(llave, "8112345678"))
    with pytest.raises(ValueError):
        hmac_celular(llave, "+528112345678")
