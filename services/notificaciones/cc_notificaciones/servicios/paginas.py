"""Cursor por identificador para los listados del servicio (orden ``id DESC``)."""

from __future__ import annotations

from cc_common.errores import ErrorCampo, ErrorValidacion
from cc_common.paginacion import CursorInvalido, decodificar_cursor


def decodificar_id(cursor: str | None) -> int | None:
    if not cursor:
        return None
    try:
        (valor,) = decodificar_cursor(cursor)
        return int(valor)
    except (CursorInvalido, ValueError, TypeError) as exc:
        raise ErrorValidacion(
            errores=[ErrorCampo("cursor", "CURSOR_INVALIDO", "El cursor no es válido.")]
        ) from exc
