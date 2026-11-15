"""Recursos compartidos por las Lambdas de whatsapp: secreto interno con caché de 5 minutos."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


def secreto_interno(cfg) -> Callable[[], str]:
    estado: dict[str, Any] = {"valor": None, "hasta": 0.0}

    def leer() -> str:
        if estado["valor"] is None or time.monotonic() > estado["hasta"]:
            from cc_common.recursos import leer_secreto

            estado["valor"] = leer_secreto(cfg.internal_auth_secreto_id, cfg.region)
            estado["hasta"] = time.monotonic() + 300
        return estado["valor"]

    return leer
