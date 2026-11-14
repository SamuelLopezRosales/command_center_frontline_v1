"""Paginación por cursor (keyset) y por página (design.md §3.1).

El cursor codifica la última llave de orden (por ejemplo ``(fecha_hora, id)``) en base64
URL-safe. Es opaco para el cliente y no contiene datos personales.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

LIMITE_PAGINA_MAX = 100
LIMITE_CURSOR_MAX = 200


class CursorInvalido(ValueError):
    pass


def _a_json(v: Any) -> Any:
    if isinstance(v, datetime):
        return {"__dt": v.isoformat()}
    return v


def _de_json(v: Any) -> Any:
    if isinstance(v, dict) and "__dt" in v:
        return datetime.fromisoformat(v["__dt"])
    return v


def codificar_cursor(llave: tuple[Any, ...]) -> str:
    crudo = json.dumps([_a_json(v) for v in llave], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(crudo).decode().rstrip("=")


def decodificar_cursor(cursor: str) -> tuple[Any, ...]:
    try:
        relleno = "=" * (-len(cursor) % 4)
        datos = json.loads(base64.urlsafe_b64decode(cursor + relleno))
    except (ValueError, json.JSONDecodeError) as exc:
        raise CursorInvalido("cursor inválido") from exc
    if not isinstance(datos, list) or not datos:
        raise CursorInvalido("cursor inválido")
    return tuple(_de_json(v) for v in datos)


def acotar(limite: int | None, maximo: int, por_defecto: int = 20) -> int:
    if limite is None:
        return por_defecto
    return max(1, min(int(limite), maximo))


@dataclass(frozen=True)
class PaginaCursor[T]:
    items: list[T]
    siguiente: str | None


@dataclass(frozen=True)
class Pagina[T]:
    items: list[T]
    pagina: int
    limite: int
    total: int
