"""Logotipo de la organización como URI ``data:`` (design.md §5.4; CC-REQ-062).

Se lee de S3 (``logotipo_s3_key``), se comprueba por sus bytes iniciales que sea PNG o JPEG (no se
confía en la extensión) y se guarda en memoria 10 minutos. Un objeto ausente, demasiado grande o de
otro tipo devuelve ``None``: el renderizador omite el logotipo y no incrusta nada dudoso.
"""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Callable

log = logging.getLogger("cc.logotipo")

FIRMAS = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"))


def tipo_de(contenido: bytes) -> str | None:
    for firma, tipo in FIRMAS:
        if contenido.startswith(firma):
            return tipo
    return None


class CargadorLogotipo:
    def __init__(
        self,
        almacen,
        *,
        ttl_s: float = 600,
        maximo: int = 1_048_576,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._almacen = almacen
        self._ttl = ttl_s
        self._maximo = maximo
        self._reloj = reloj
        self._cache: dict[str, tuple[float, str]] = {}

    async def data_uri(self, clave: str | None) -> str | None:
        if not clave:
            return None
        hit = self._cache.get(clave)
        if hit and self._reloj() < hit[0]:
            return hit[1]
        contenido = await self._almacen.leer(clave)
        if contenido is None or len(contenido) > self._maximo:
            log.warning("logotipo no disponible o demasiado grande")
            return None
        tipo = tipo_de(contenido)
        if tipo is None:
            log.warning("el logotipo no es PNG ni JPEG")
            return None
        uri = f"data:{tipo};base64,{base64.b64encode(contenido).decode('ascii')}"
        self._cache[clave] = (self._reloj() + self._ttl, uri)
        return uri

    def invalidar(self) -> None:
        self._cache.clear()
