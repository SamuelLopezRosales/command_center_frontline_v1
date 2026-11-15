"""Cifrado de los valores sensibles del snapshot (design.md §5.6, §8.3; CC-REQ-151, 082).

Mismo mecanismo que en `colaboradores`: cifrado de sobre con una clave de datos (DEK) por empresa,
guardada cifrada en ``constancias.clave_datos``. ``async with cifrador.transaccion(conn, empresa)``
carga las DEK dentro de la transacción en curso (con candado si la empresa aún no tiene) y, al salir
sin error, inserta la que se haya creado. Dentro del bloque, ``cifrar`` y ``descifrar`` son
síncronos. El servicio `constancias` nunca descifra para mostrar: solo cifra al emitir.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from cc_common.crypto import DekCifrada, EnvelopeCrypto, aad
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

SERVICIO = "constancias"


@dataclass
class _EstadoDek:
    empresa_id: int
    filas: dict[int, DekCifrada] = field(default_factory=dict)
    activa: int | None = None
    nuevas: list[DekCifrada] = field(default_factory=list)


_estado: ContextVar[_EstadoDek | None] = ContextVar("cc_constancias_dek", default=None)


class FueraDeTransaccion(RuntimeError):
    """Se usó el cifrado sin ``cifrador.transaccion(...)``: es un error de programación."""


class _AlmacenDek:
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
            "SELECT version, dek_cifrada, activa FROM constancias.clave_datos WHERE empresa_id = :e"
        ),
        {"e": e.empresa_id},
    )
    for version, cifrada, activa in filas.all():
        e.filas[int(version)] = DekCifrada(int(version), bytes(cifrada))
        if activa:
            e.activa = int(version)


class Cifrador:
    def __init__(self, kms: Any, llave_kms: str) -> None:
        self._crypto = EnvelopeCrypto(kms, _AlmacenDek(), llave_kms, SERVICIO)

    @asynccontextmanager
    async def transaccion(self, conn: AsyncConnection, empresa_id: int) -> AsyncIterator[None]:
        e = _EstadoDek(empresa_id)
        await _leer(conn, e)
        if e.activa is None:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('constancias.clave_datos'), :e)"),
                {"e": empresa_id},
            )
            await _leer(conn, e)
        marca = _estado.set(e)
        try:
            yield
            for dek in e.nuevas:
                await conn.execute(
                    text(
                        "INSERT INTO constancias.clave_datos "
                        "(empresa_id, version, dek_cifrada, activa) VALUES (:e, :v, :d, true)"
                    ),
                    {"e": empresa_id, "v": dek.version, "d": dek.cifrada},
                )
        finally:
            _estado.reset(marca)

    def cifrar(self, valor: str, *, empresa_id: int, registro: str) -> bytes:
        """Cifra un valor del snapshot; ``registro`` liga el cifrado a esa solicitud y variable."""
        return self._crypto.cifrar(
            valor,
            empresa_id=empresa_id,
            datos_aut=aad("constancia_generada", "datos_snapshot_json", registro, empresa_id),
        )

    def descifrar(self, blob: bytes, *, empresa_id: int, registro: str) -> str:
        return self._crypto.descifrar(
            bytes(blob),
            empresa_id=empresa_id,
            datos_aut=aad("constancia_generada", "datos_snapshot_json", registro, empresa_id),
        )


def cifrador_desde_config(cfg: Any) -> Cifrador:
    import boto3

    if not cfg.kms_llave_datos:
        raise RuntimeError("Falta CC_KMS_LLAVE_DATOS.")
    return Cifrador(boto3.client("kms", region_name=cfg.region), cfg.kms_llave_datos)
