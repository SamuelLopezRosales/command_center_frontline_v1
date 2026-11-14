"""Cifrado de sobre con KMS y HMAC de búsqueda (design.md §8.3, §8.4; CC-REQ-151, 152).

- Una llave de datos (DEK) AES-256 por empresa y servicio, cifrada con la llave de KMS
  ``alias/cc-{env}-datos`` y con contexto ``{servicio, empresa_id}``. Se guarda cifrada en la
  tabla ``clave_datos``; en claro solo vive en memoria 15 minutos.
- Cada valor: AES-256-GCM, nonce aleatorio de 12 bytes y datos autenticados
  ``tabla|columna|registro|empresa_id`` (un valor copiado a otra fila no descifra).
- Formato del ``bytea``: versión de formato (1 byte) | versión de DEK (4 bytes, big endian) |
  nonce (12) | texto cifrado con etiqueta.
- ``hmac_celular``: HMAC-SHA256 con una llave que vive en Secrets Manager, nunca en la base.
Ningún método registra ni devuelve en errores el valor en claro.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION_FORMATO = 1
_CABECERA = struct.Struct(">BI")  # versión de formato, versión de DEK
_NONCE = 12
TTL_DEK_S = 15 * 60


class ErrorCifrado(Exception):
    """Fallo de cifrado o descifrado. El mensaje nunca contiene el valor."""


class ClienteKms(Protocol):
    def generate_data_key(self, **kwargs: Any) -> dict[str, Any]: ...
    def decrypt(self, **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DekCifrada:
    version: int
    cifrada: bytes


class AlmacenDek(Protocol):
    """Acceso a la tabla ``clave_datos`` del servicio (la implementa cada repositorio)."""

    def activa(self, empresa_id: int) -> DekCifrada | None: ...
    def obtener(self, empresa_id: int, version: int) -> DekCifrada | None: ...
    def guardar(self, empresa_id: int, dek: DekCifrada) -> None: ...


def aad(tabla: str, columna: str, registro: int | str, empresa_id: int) -> bytes:
    return f"{tabla}|{columna}|{registro}|{empresa_id}".encode()


class EnvelopeCrypto:
    def __init__(
        self,
        kms: ClienteKms,
        almacen: AlmacenDek,
        llave_kms: str,
        servicio: str,
        reloj=time.monotonic,
    ) -> None:
        self._kms = kms
        self._almacen = almacen
        self._llave = llave_kms
        self._servicio = servicio
        self._reloj = reloj
        self._cache: dict[tuple[int, int], tuple[bytes, float]] = {}
        self._candado = threading.Lock()

    def _contexto(self, empresa_id: int) -> dict[str, str]:
        return {"servicio": self._servicio, "empresa_id": str(empresa_id)}

    def _en_cache(self, empresa_id: int, version: int) -> bytes | None:
        entrada = self._cache.get((empresa_id, version))
        if entrada and self._reloj() - entrada[1] < TTL_DEK_S:
            return entrada[0]
        self._cache.pop((empresa_id, version), None)
        return None

    def _descifrar_dek(self, empresa_id: int, dek: DekCifrada) -> bytes:
        en_cache = self._en_cache(empresa_id, dek.version)
        if en_cache:
            return en_cache
        try:
            r = self._kms.decrypt(
                CiphertextBlob=dek.cifrada,
                EncryptionContext=self._contexto(empresa_id),
                KeyId=self._llave,
            )
        except Exception as exc:  # noqa: BLE001 - el error de KMS no debe filtrar detalles
            raise ErrorCifrado("No se pudo descifrar la llave de datos.") from exc
        claro = r["Plaintext"]
        with self._candado:
            self._cache[(empresa_id, dek.version)] = (claro, self._reloj())
        return claro

    def _dek_activa(self, empresa_id: int) -> tuple[int, bytes]:
        dek = self._almacen.activa(empresa_id)
        if dek is None:
            r = self._kms.generate_data_key(
                KeyId=self._llave, KeySpec="AES_256", EncryptionContext=self._contexto(empresa_id)
            )
            dek = DekCifrada(version=1, cifrada=r["CiphertextBlob"])
            self._almacen.guardar(empresa_id, dek)
            with self._candado:
                self._cache[(empresa_id, 1)] = (r["Plaintext"], self._reloj())
            return 1, r["Plaintext"]
        return dek.version, self._descifrar_dek(empresa_id, dek)

    def cifrar(self, valor: str, *, empresa_id: int, datos_aut: bytes) -> bytes:
        version, llave = self._dek_activa(empresa_id)
        nonce = os.urandom(_NONCE)
        cifrado = AESGCM(llave).encrypt(nonce, valor.encode("utf-8"), datos_aut)
        return _CABECERA.pack(VERSION_FORMATO, version) + nonce + cifrado

    def descifrar(self, blob: bytes, *, empresa_id: int, datos_aut: bytes) -> str:
        if len(blob) < _CABECERA.size + _NONCE + 16:
            raise ErrorCifrado("Valor cifrado con formato inválido.")
        formato, version = _CABECERA.unpack_from(blob)
        if formato != VERSION_FORMATO:
            raise ErrorCifrado("Versión de formato no soportada.")
        dek = self._almacen.obtener(empresa_id, version)
        if dek is None:
            raise ErrorCifrado("No existe la versión de llave de datos.")
        llave = self._descifrar_dek(empresa_id, dek)
        inicio = _CABECERA.size
        nonce = blob[inicio : inicio + _NONCE]
        try:
            claro = AESGCM(llave).decrypt(nonce, blob[inicio + _NONCE :], datos_aut)
        except InvalidTag as exc:
            raise ErrorCifrado("El valor no corresponde a este registro.") from exc
        return claro.decode("utf-8")


def hmac_celular(llave: bytes, celular_10: str) -> bytes:
    """Hash de búsqueda del celular; la llave vive en Secrets Manager (cc/{env}/hmac-celular)."""
    if len(celular_10) != 10 or not celular_10.isdigit():
        raise ValueError("El celular debe tener 10 dígitos.")
    return hmac.new(llave, ("52" + celular_10).encode(), hashlib.sha256).digest()


def hmac_texto(llave: bytes, texto: str) -> bytes:
    """HMAC genérico (por ejemplo, código de verificación ligado a la conversación)."""
    return hmac.new(llave, texto.encode(), hashlib.sha256).digest()


def iguales(a: bytes, b: bytes) -> bool:
    """Comparación en tiempo constante."""
    return hmac.compare_digest(a, b)


def sha256_hex(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()
