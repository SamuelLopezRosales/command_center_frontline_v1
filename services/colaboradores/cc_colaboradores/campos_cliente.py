"""Definiciones de campos dinámicos (INT-CAM-01) con caché de 60 segundos (design.md §3.3).

``CamposHttp`` es el cliente de INT-CAM-01 y ``CacheCampos`` lo envuelve con una caché por empresa
que el evento ``campo.actualizado`` invalida (``consumidores.py``). Se piden también los campos
desactivados no eliminados: conservan sus valores y siguen resolviendo variables ya publicadas
(``DefinicionCampo.activo`` dice cuáles no se capturan ni se filtran).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

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


class CamposHttp:
    """Cliente de INT-CAM-01 (``GET /internal/campos``) con el token de ``colaboradores``."""

    def __init__(self, cliente: Any) -> None:
        self._c = cliente

    async def definiciones(self, empresa_id: int) -> list[DefinicionCampo]:
        from cc_common.errores import ErrorProveedor

        r = await self._c.solicitar(
            "GET",
            "/internal/campos",
            params={"incluir_inactivos": "true"},
            headers={"X-Empresa-Id": str(empresa_id)},
        )
        if r.status_code != 200:
            raise ErrorProveedor()
        return [
            DefinicionCampo(
                id=int(c["id"]),
                nombre_campo=c["nombre_campo"],
                clave=c["clave"],
                codigo_interno=c["codigo_interno"],
                tipo_dato=c["tipo_dato"],
                obligatorio=c["obligatorio"],
                activo=c["activo"],
                es_sensible=c["es_sensible"],
                es_sugerido=c["es_sugerido"],
                formato_validacion=c.get("formato_validacion"),
                orden=c["orden"],
                opciones=tuple(
                    OpcionCampo(
                        id=int(o["id"]),
                        etiqueta=o["etiqueta"],
                        valor=o["valor"],
                        activo=o["activo"],
                        descripcion=o.get("descripcion"),
                        orden=o["orden"],
                    )
                    for o in c.get("opciones", [])
                ),
            )
            for c in r.json()["campos"]
        ]


def cache_desde_config(cfg: Any, secreto: Callable[[], str]) -> CacheCampos:
    """Caché sobre el cliente real; falla si ``CC_CAMPOS_URL`` no está configurada."""
    from cc_common.errores import ErrorInterno
    from cc_common.internal_client import ClienteInterno

    if not cfg.campos_url:
        raise ErrorInterno("SERVICIO_NO_CONFIGURADO", "Servicio no configurado.")
    return CacheCampos(
        CamposHttp(ClienteInterno(cfg.campos_url, servicio="colaboradores", secreto=secreto))
    )
