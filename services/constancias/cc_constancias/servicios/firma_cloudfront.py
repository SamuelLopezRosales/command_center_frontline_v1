"""URL firmada de CloudFront para servir el PDF (design.md §11.3; CC-REQ-088, 084).

El bucket de constancias es privado y solo lo lee CloudFront (OAC). Una URL firmada de CloudFront
permite 24 horas para RH y 60 segundos para el colaborador; una prefirmada de S3 creada con las
credenciales temporales de la tarea no podría garantizar 24 horas. Usa la política "enlatada"
(``Expires`` y ``Signature``) con RSA-SHA1, que es lo que CloudFront exige para firmar.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

_DOMINIO = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


def _b64_cloudfront(datos: bytes) -> str:
    """Base64 con el alfabeto seguro de CloudFront: ``+ = /`` pasan a ``- _ ~``."""
    return base64.b64encode(datos).decode("ascii").translate(str.maketrans("+=/", "-_~"))


@dataclass(frozen=True)
class UrlFirmada:
    url: str
    expira: datetime


class FirmadorCloudFront:
    def __init__(self, dominio: str, key_pair_id: str, clave_privada_pem: str | bytes) -> None:
        if not _DOMINIO.match(dominio):
            raise ValueError("dominio de CloudFront inválido")
        self._dominio = dominio
        self._key_pair_id = key_pair_id
        pem = (
            clave_privada_pem.encode() if isinstance(clave_privada_pem, str) else clave_privada_pem
        )
        self._clave = serialization.load_pem_private_key(pem, password=None)

    def firmar(self, clave_s3: str, segundos: int, ahora: datetime | None = None) -> UrlFirmada:
        if segundos <= 0:
            raise ValueError("la vigencia debe ser positiva")
        expira = (ahora or datetime.now(UTC)) + timedelta(seconds=segundos)
        epoch = int(expira.timestamp())
        recurso = f"https://{self._dominio}/{clave_s3.lstrip('/')}"
        politica = (
            '{"Statement":[{"Resource":"%s","Condition":{"DateLessThan":{"AWS:EpochTime":%d}}}]}'  # noqa: UP031
            % (recurso, epoch)
        )
        firma = self._clave.sign(politica.encode(), padding.PKCS1v15(), hashes.SHA1())  # noqa: S303
        return UrlFirmada(
            f"{recurso}?Expires={epoch}&Signature={_b64_cloudfront(firma)}"
            f"&Key-Pair-Id={self._key_pair_id}",
            expira,
        )


def firmador_desde_config(cfg: Any) -> FirmadorCloudFront:
    from cc_common.recursos import leer_secreto

    if not (
        cfg.cloudfront_dominio and cfg.cloudfront_key_pair_id and cfg.cloudfront_clave_secreto_id
    ):
        raise RuntimeError("Falta la configuración de CloudFront (dominio, key pair y secreto).")
    pem = leer_secreto(cfg.cloudfront_clave_secreto_id, cfg.region)
    return FirmadorCloudFront(cfg.cloudfront_dominio, cfg.cloudfront_key_pair_id, pem)
