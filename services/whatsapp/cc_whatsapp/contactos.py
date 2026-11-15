"""Cliente síncrono de INT-COL-05 (``contactos:resolver``) para el ``enviador`` (design.md §3.8).

Corre en una Lambda: usa ``httpx`` síncrono con el token interno de 60 s de ``cc_common``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from cc_common.internal_client import emitir_token_interno


class ContactosNoDisponible(Exception):  # noqa: N818
    """`colaboradores` no respondió: el mensaje se reintenta."""


class ContactosHttp:
    def __init__(
        self,
        base_url: str,
        secreto: Callable[[], str],
        *,
        cliente: httpx.Client | None = None,
        timeout_s: float = 3.0,
    ) -> None:
        self._url = base_url.rstrip("/") + "/internal/colaboradores/contactos:resolver"
        self._secreto = secreto
        self._http = cliente or httpx.Client(timeout=timeout_s)

    def resolver(self, empresa_id: int, colaborador_id: int, proposito: str) -> dict[str, Any]:
        """Contacto del colaborador: ``{id, elegible, motivo, celular}``."""
        try:
            r = self._http.post(
                self._url,
                json={"ids": [colaborador_id], "proposito": proposito},
                headers={
                    "Authorization": f"Bearer {emitir_token_interno(self._secreto(), 'whatsapp')}",
                    "X-Empresa-Id": str(empresa_id),
                },
            )
        except httpx.HTTPError as exc:
            raise ContactosNoDisponible from exc
        if r.status_code != 200:
            raise ContactosNoDisponible
        for item in r.json()["items"]:
            if item["id"] == colaborador_id:
                return item
        return {"id": colaborador_id, "elegible": False, "motivo": "NO_ENCONTRADO"}
