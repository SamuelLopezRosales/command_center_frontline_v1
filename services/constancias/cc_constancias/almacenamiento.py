"""Acceso a S3 del servicio constancias (bucket ``plantillas``; design.md §13.4).

Borrador: ``plantillas/{empresa}/{plantilla}/borrador.json``. Versiones publicadas:
``plantillas/{empresa}/{plantilla}/v{n}.json`` (la política del bucket niega su borrado).

El cliente de boto3 es síncrono: las llamadas se ejecutan en un hilo. Los errores de S3 se
traducen sin filtrar detalles al cliente.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from cc_common.errores import ErrorProveedor


def clave_borrador(empresa_id: int, plantilla_id: int) -> str:
    return f"plantillas/{empresa_id}/{plantilla_id}/borrador.json"


def clave_version(empresa_id: int, plantilla_id: int, numero: int) -> str:
    return f"plantillas/{empresa_id}/{plantilla_id}/v{numero}.json"


class Almacen(Protocol):
    async def escribir(self, clave: str, cuerpo: bytes) -> None: ...
    async def leer(self, clave: str) -> bytes | None: ...


class AlmacenS3:
    def __init__(self, bucket: str, cliente: Any) -> None:
        self._bucket = bucket
        self._s3 = cliente

    async def escribir(self, clave: str, cuerpo: bytes) -> None:
        try:
            await asyncio.to_thread(
                self._s3.put_object,
                Bucket=self._bucket,
                Key=clave,
                Body=cuerpo,
                ContentType="application/json",
            )
        except Exception as exc:  # noqa: BLE001
            raise ErrorProveedor("S3_NO_DISPONIBLE", "No fue posible guardar el archivo.") from exc

    async def leer(self, clave: str) -> bytes | None:
        """Contenido del objeto o ``None`` si no existe."""
        from botocore.exceptions import ClientError

        try:
            r = await asyncio.to_thread(self._s3.get_object, Bucket=self._bucket, Key=clave)
            return await asyncio.to_thread(r["Body"].read)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise ErrorProveedor("S3_NO_DISPONIBLE", "No fue posible leer el archivo.") from exc
        except Exception as exc:  # noqa: BLE001
            raise ErrorProveedor("S3_NO_DISPONIBLE", "No fue posible leer el archivo.") from exc


def almacen_desde_config(cfg: Any) -> AlmacenS3:
    import boto3
    from botocore.config import Config

    cliente = boto3.client(
        "s3",
        region_name=cfg.region,
        endpoint_url=cfg.s3_endpoint or None,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return AlmacenS3(cfg.bucket_plantillas, cliente)


def clave_constancia(empresa_id: int, anio: int, folio: str) -> str:
    return f"constancias/{empresa_id}/{anio}/{folio}.pdf"


class AlmacenConstancias:
    """Bucket ``constancias``: PDF inmutables con Object Lock y suma de verificación SHA-256
    (design.md §5.6, §13.4; CC-REQ-077, 160)."""

    def __init__(self, bucket: str, cliente: Any, retencion_dias: int | None = None) -> None:
        self._bucket = bucket
        self._s3 = cliente
        self._retencion_dias = retencion_dias

    async def guardar_pdf(self, clave: str, cuerpo: bytes, sha256_hex: str) -> None:
        import base64
        from datetime import UTC, datetime, timedelta

        extra: dict[str, Any] = {
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(sha256_hex)).decode("ascii")
        }
        if self._retencion_dias:
            extra["ObjectLockMode"] = "GOVERNANCE"
            extra["ObjectLockRetainUntilDate"] = datetime.now(UTC) + timedelta(
                days=self._retencion_dias
            )
        try:
            await asyncio.to_thread(
                self._s3.put_object,
                Bucket=self._bucket,
                Key=clave,
                Body=cuerpo,
                ContentType="application/pdf",
                **extra,
            )
        except Exception as exc:  # noqa: BLE001
            raise ErrorProveedor("S3_NO_DISPONIBLE", "No fue posible guardar el archivo.") from exc


def almacen_constancias_desde_config(cfg: Any) -> AlmacenConstancias:
    import boto3
    from botocore.config import Config

    cliente = boto3.client(
        "s3",
        region_name=cfg.region,
        endpoint_url=cfg.s3_endpoint or None,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return AlmacenConstancias(cfg.bucket_constancias, cliente, cfg.retencion_constancias_dias)
