"""Definiciones de campos dinámicos (INT-CAM-01) con caché de 60 segundos (design.md §3.3).

``StubCampos`` devuelve definiciones fijas y es **temporal**: T-206 lo reemplaza por el cliente
HTTP de INT-CAM-01, y el evento ``campo.actualizado`` invalida la caché.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

TTL_CACHE_S = 60


@dataclass(frozen=True)
class OpcionCampo:
    id: int
    etiqueta: str
    valor: str
    activo: bool = True
    descripcion: str | None = None
    orden: int = 0


@dataclass(frozen=True)
class DefinicionCampo:
    id: int
    nombre_campo: str
    clave: str
    codigo_interno: str
    tipo_dato: str  # TEXTO, NUMERO, FECHA, LISTA, SI_NO
    obligatorio: bool = False
    activo: bool = True
    es_sensible: bool = False
    es_sugerido: bool = False
    formato_validacion: str | None = None
    orden: int = 0
    opciones: tuple[OpcionCampo, ...] = field(default_factory=tuple)


class ClienteCampos(Protocol):
    async def definiciones(self, empresa_id: int) -> list[DefinicionCampo]: ...


class StubCampos:
    """Temporal (se reemplaza en T-206 por INT-CAM-01): definiciones fijas por empresa."""

    def __init__(self, por_empresa: dict[int, list[DefinicionCampo]] | None = None) -> None:
        self.por_empresa = por_empresa or {}
        self.llamadas = 0

    async def definiciones(self, empresa_id: int) -> list[DefinicionCampo]:
        self.llamadas += 1
        return list(self.por_empresa.get(empresa_id, []))


class CacheCampos:
    """Caché en memoria por empresa con vencimiento; ``invalidar`` la limpia (evento)."""

    def __init__(
        self,
        origen: ClienteCampos,
        ttl_s: float = TTL_CACHE_S,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._origen = origen
        self._ttl = ttl_s
        self._reloj = reloj
        self._cache: dict[int, tuple[list[DefinicionCampo], float]] = {}

    async def definiciones(self, empresa_id: int) -> list[DefinicionCampo]:
        entrada = self._cache.get(empresa_id)
        if entrada and self._reloj() - entrada[1] < self._ttl:
            return list(entrada[0])
        datos = await self._origen.definiciones(empresa_id)
        self._cache[empresa_id] = (list(datos), self._reloj())
        return list(datos)

    def invalidar(self, empresa_id: int | None = None) -> None:
        if empresa_id is None:
            self._cache.clear()
        else:
            self._cache.pop(empresa_id, None)
