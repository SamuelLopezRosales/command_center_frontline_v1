"""Acceso a S3 para los logotipos (bucket ``plantillas``, prefijo ``logotipos/{empresa_id}/``).

El cliente de boto3 es síncrono: las llamadas se ejecutan en un hilo. Los errores de S3 se
traducen sin filtrar detalles al cliente.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from cc_common.errores import ErrorProveedor


@dataclass(frozen=True)
class Cabecera:
    tamano: int
    content_type: str | None


class Almacen(Protocol):
    async def url_subida(self, clave: str, content_type: str, segundos: int) -> str: ...
    async def cabecera(self, clave: str) -> Cabecera | None: ...
    async def inicio(self, clave: str, n: int) -> bytes: ...


class AlmacenS3:
    def __init__(self, bucket: str, cliente: Any) -> None:
        self._bucket = bucket
        self._s3 = cliente

    async def url_subida(self, clave: str, content_type: str, segundos: int) -> str:
        try:
            return await asyncio.to_thread(
                self._s3.generate_presigned_url,
                "put_object",
                Params={"Bucket": self._bucket, "Key": clave, "ContentType": content_type},
                ExpiresIn=segundos,
            )
        except Exception as exc:  # noqa: BLE001
            raise ErrorProveedor("S3_NO_DISPONIBLE", "No fue posible preparar la subida.") from exc

    async def cabecera(self, clave: str) -> Cabecera | None:
        from botocore.exceptions import ClientError

        try:
            r = await asyncio.to_thread(self._s3.head_object, Bucket=self._bucket, Key=clave)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise ErrorProveedor("S3_NO_DISPONIBLE", "No fue posible leer el archivo.") from exc
        return Cabecera(int(r["ContentLength"]), r.get("ContentType"))

    async def inicio(self, clave: str, n: int) -> bytes:
        try:
            r = await asyncio.to_thread(
                self._s3.get_object, Bucket=self._bucket, Key=clave, Range=f"bytes=0-{n - 1}"
            )
            return await asyncio.to_thread(r["Body"].read)
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
