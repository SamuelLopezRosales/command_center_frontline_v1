"""Consulta de la bitácora de auditoría (DSH-05; CC-REQ-015)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from cc_common.auth import UsuarioActual
from cc_common.db import transaccion
from cc_common.errores import ErrorValidacion
from cc_common.paginacion import (
    LIMITE_PAGINA_MAX,
    PaginaCursor,
    acotar,
    codificar_cursor,
    decodificar_cursor,
)

from cc_dashboard.repos import bitacora as repo
from cc_dashboard.repos import usuarios as repo_usuarios
from cc_dashboard.servicios.sesion import _usuario_vigente


async def consultar(
    motor: Any, actual: UsuarioActual, filtro: repo.FiltroBitacora, cursor: str | None
) -> PaginaCursor[dict[str, Any]]:
    if filtro.desde and filtro.hasta and filtro.desde > filtro.hasta:
        raise ErrorValidacion(
            "RANGO_INVALIDO", "La fecha inicial no puede ser posterior a la final."
        )
    limite = acotar(filtro.limite, LIMITE_PAGINA_MAX)
    try:
        llave = decodificar_cursor(cursor) if cursor else None
    except ValueError as exc:  # CursorInvalido o fecha mal formada
        raise ErrorValidacion("CURSOR_INVALIDO", "El cursor no es válido.") from exc
    if llave is not None and not (
        len(llave) == 2 and isinstance(llave[0], datetime) and isinstance(llave[1], int)
    ):
        raise ErrorValidacion("CURSOR_INVALIDO", "El cursor no es válido.")
    filtro = replace(filtro, limite=limite, cursor=llave)
    async with transaccion(motor, actual.empresa_id) as conn:
        fila = await _usuario_vigente(conn, actual)
        await repo_usuarios.tocar_actividad(conn, fila.id)
        filas = await repo.consultar(conn, filtro)
    hay_mas = len(filas) > limite
    items = filas[:limite]
    siguiente = codificar_cursor((items[-1]["fecha_hora"], items[-1]["id"])) if hay_mas else None
    return PaginaCursor(items=items, siguiente=siguiente)
