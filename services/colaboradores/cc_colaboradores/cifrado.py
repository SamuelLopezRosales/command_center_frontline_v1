"""Cifrado de datos sensibles del servicio (design.md §8.3 y §8.4).

``EnvelopeCrypto`` (``cc_common.crypto``) es síncrono y pide sus llaves de datos (DEK) a un
almacén síncrono, mientras que el acceso a PostgreSQL es asíncrono. El puente es
``AlmacenDekTransaccional``:

- ``async with cifrador.transaccion(conn, empresa_id):`` carga las DEK de la empresa desde
  ``clave_datos`` dentro de la transacción en curso. Si la empresa aún no tiene DEK, toma un
  candado de transacción (``pg_advisory_xact_lock``) y vuelve a leer, para que dos peticiones
  simultáneas no creen dos DEK.
- Dentro del bloque, ``cifrar`` y ``descifrar`` usan solo memoria (y KMS si hace falta).
- Al salir sin error, una DEK recién generada se inserta antes del ``commit``. Si la transacción
  se revierte, la DEK tampoco se guarda y los valores cifrados con ella no persisten.

La caché de DEK descifradas (15 minutos) vive en ``EnvelopeCrypto`` y es de toda la aplicación.
El estado por transacción va en una ``ContextVar``, que separa las peticiones concurrentes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from cc_common.crypto import DekCifrada, EnvelopeCrypto, aad, hmac_celular
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

SERVICIO = "colaboradores"


@dataclass
class _EstadoDek:
    empresa_id: int
    filas: dict[int, DekCifrada] = field(default_factory=dict)
    activa: int | None = None
    nuevas: list[DekCifrada] = field(default_factory=list)


_estado: ContextVar[_EstadoDek | None] = ContextVar("cc_colaboradores_dek", default=None)


class FueraDeTransaccion(RuntimeError):
    """Se usó el cifrado sin ``cifrador.transaccion(...)``: es un error de programación."""


class AlmacenDekTransaccional:
    """Implementa ``AlmacenDek`` sobre el estado cargado de la transacción en curso."""

    def _actual(self, empresa_id: int) -> _EstadoDek:
        e = _estado.get()
        if e is None or e.empresa_id != empresa_id:
            raise FueraDeTransaccion("cifrado fuera de una transacción de la misma empresa")
        return e

    def activa(self, empresa_id: int) -> DekCifrada | None:
        e = self._actual(empresa_id)
        return e.filas.get(e.activa) if e.activa is not None else None

    def obtener(self, empresa_id: int, version: int) -> DekCifrada | None:
        return self._actual(empresa_id).filas.get(version)

    def guardar(self, empresa_id: int, dek: DekCifrada) -> None:
        e = self._actual(empresa_id)
        e.filas[dek.version] = dek
        e.activa = dek.version
        e.nuevas.append(dek)


async def _leer(conn: AsyncConnection, e: _EstadoDek) -> None:
    filas = await conn.execute(
        text(
            "SELECT version, dek_cifrada, activa FROM colaboradores.clave_datos "
            "WHERE empresa_id = :e"
        ),
        {"e": e.empresa_id},
    )
    for version, cifrada, activa in filas.all():
        e.filas[int(version)] = DekCifrada(int(version), bytes(cifrada))
        if activa:
            e.activa = int(version)


class Cifrador:
    """Cifrado de sobre más el HMAC del celular, con la llave HMAC en memoria."""

    def __init__(self, kms: Any, llave_kms: str, llave_hmac: bytes) -> None:
        if len(llave_hmac) < 32:
            raise ValueError("La llave HMAC debe tener al menos 32 bytes.")
        self._almacen = AlmacenDekTransaccional()
        self._crypto = EnvelopeCrypto(kms, self._almacen, llave_kms, SERVICIO)
        self._llave_hmac = llave_hmac

    @asynccontextmanager
    async def transaccion(self, conn: AsyncConnection, empresa_id: int) -> AsyncIterator[None]:
        e = _EstadoDek(empresa_id)
        await _leer(conn, e)
        if e.activa is None:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('colaboradores.clave_datos'), :e)"),
                {"e": empresa_id},
            )
            await _leer(conn, e)
        marca = _estado.set(e)
        try:
            yield
            for dek in e.nuevas:
                await conn.execute(
                    text(
                        "INSERT INTO colaboradores.clave_datos "
                        "(empresa_id, version, dek_cifrada, activa) VALUES (:e, :v, :d, true)"
                    ),
                    {"e": empresa_id, "v": dek.version, "d": dek.cifrada},
                )
        finally:
            _estado.reset(marca)

    def cifrar(self, valor: str, *, empresa_id: int, tabla: str, columna: str, registro) -> bytes:
        return self._crypto.cifrar(
            valor, empresa_id=empresa_id, datos_aut=aad(tabla, columna, registro, empresa_id)
        )

    def descifrar(self, blob: bytes, *, empresa_id: int, tabla: str, columna: str, registro) -> str:
        return self._crypto.descifrar(
            bytes(blob), empresa_id=empresa_id, datos_aut=aad(tabla, columna, registro, empresa_id)
        )

    def hash_celular(self, celular_10: str) -> bytes:
        return hmac_celular(self._llave_hmac, celular_10)


def cifrador_desde_config(cfg: Any) -> Cifrador:
    """Cifrador de AWS: KMS con la llave ``cc-{env}-datos`` y la llave HMAC de Secrets Manager."""
    import boto3
    from cc_common.recursos import leer_secreto

    if not cfg.kms_llave_datos or not cfg.hmac_celular_secreto_id:
        raise RuntimeError("Faltan CC_KMS_LLAVE_DATOS o CC_HMAC_CELULAR_SECRETO_ID.")
    llave = leer_secreto(cfg.hmac_celular_secreto_id, cfg.region).encode()
    return Cifrador(boto3.client("kms", region_name=cfg.region), cfg.kms_llave_datos, llave)
