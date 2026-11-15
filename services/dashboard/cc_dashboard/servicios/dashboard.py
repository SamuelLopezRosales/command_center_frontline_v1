"""Indicadores, solicitudes, constancias recientes, alertas e historial (DSH-01 a 04 y DSH-11).

Todo sale de las vistas contractuales y solo cubre la empresa del usuario (CC-REQ-150).
"""

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

from cc_dashboard.repos import usuarios as repo_usuarios
from cc_dashboard.repos import vistas as repo
from cc_dashboard.servicios.sesion import _usuario_vigente

LIMITE_RECIENTES = 20
MAX_ALERTAS_FALLIDAS = 5


async def _con_usuario(motor: Any, actual: UsuarioActual, leer):
    async with transaccion(motor, actual.empresa_id) as conn:
        fila = await _usuario_vigente(conn, actual)
        await repo_usuarios.tocar_actividad(conn, fila.id)
        return await leer(conn)


async def resumen(motor: Any, actual: UsuarioActual) -> dict[str, Any]:
    cifras = await _con_usuario(motor, actual, repo.resumen)
    return {**cifras, "vacio": not any(cifras.values())}


async def solicitudes_recientes(motor: Any, actual: UsuarioActual, limite: int) -> list[dict]:
    n = acotar(limite, LIMITE_RECIENTES, 10)
    return await _con_usuario(motor, actual, lambda c: repo.solicitudes_recientes(c, n))


async def constancias_recientes(motor: Any, actual: UsuarioActual, limite: int) -> list[dict]:
    n = acotar(limite, LIMITE_RECIENTES, 10)
    return await _con_usuario(motor, actual, lambda c: repo.constancias_recientes(c, n))


def _lista_de_nombres(nombres: list[str], total: int) -> str:
    """Hasta tres nombres; el resto se resume como "y N más"."""
    visibles = nombres[:3]
    resto = total - len(visibles)
    if resto > 0:
        return f"{', '.join(visibles)} y {resto} más"
    if len(visibles) > 1:
        return f"{', '.join(visibles[:-1])} y {visibles[-1]}"
    return visibles[0] if visibles else ""


def _plural(n: int, uno: str, varios: str) -> str:
    return uno if n == 1 else varios


async def alertas(motor: Any, actual: UsuarioActual) -> list[dict[str, Any]]:
    async def leer(conn):
        return await repo.alertas_consentimiento(conn), await repo.alertas_constancias(conn)

    (sin_consentimiento, nombres), de_constancias = await _con_usuario(motor, actual, leer)
    salida: list[dict[str, Any]] = []

    if sin_consentimiento:
        salida.append(
            {
                "tipo": "SIN_CONSENTIMIENTO",
                "titulo": f"{sin_consentimiento} "
                + _plural(
                    sin_consentimiento,
                    "colaborador sin consentimiento de WhatsApp",
                    "colaboradores sin consentimiento de WhatsApp",
                ),
                "detalle": _lista_de_nombres(nombres, sin_consentimiento),
                "total": sin_consentimiento,
                "enlace": "/colaboradores",
            }
        )

    fallidas = [a for a in de_constancias if a["tipo"] == "CONSTANCIA_FALLIDA"]
    for a in fallidas[:MAX_ALERTAS_FALLIDAS]:
        salida.append(
            {
                "tipo": "CONSTANCIA_FALLIDA",
                "titulo": "Constancia fallida",
                "detalle": f"{a['dato']} · entrega sin confirmar",
                "total": 1,
                "enlace": "/constancias/historial?estado=FALLIDA",
            }
        )

    pendientes = [a for a in de_constancias if a["tipo"] == "CONSTANCIA_PENDIENTE"]
    if pendientes:
        n = len(pendientes)
        salida.append(
            {
                "tipo": "CONSTANCIA_PENDIENTE",
                "titulo": f"{n} "
                + _plural(
                    n,
                    "constancia sin confirmar entrega",
                    "constancias sin confirmar entrega",
                ),
                "detalle": "Llevan más de 24 horas pendientes",
                "total": n,
                "enlace": "/constancias/historial?estado=PENDIENTE",
            }
        )

    for a in (x for x in de_constancias if x["tipo"] == "CAMPO_VACIO_EN_PLANTILLA"):
        total = int(a["total"])
        salida.append(
            {
                "tipo": "CAMPO_VACIO_EN_PLANTILLA",
                "titulo": f"{a['dato']} vacío en {total} "
                + _plural(total, "colaborador", "colaboradores"),
                "detalle": "Afecta la constancia al emitirse",
                "total": total,
                "enlace": "/colaboradores",
            }
        )
    return salida


async def historial(
    motor: Any, actual: UsuarioActual, filtro: repo.FiltroHistorial, cursor: str | None
) -> PaginaCursor[dict[str, Any]]:
    if filtro.desde and filtro.hasta and filtro.desde > filtro.hasta:
        raise ErrorValidacion(
            "RANGO_INVALIDO", "La fecha inicial no puede ser posterior a la final."
        )
    limite = acotar(filtro.limite, LIMITE_PAGINA_MAX)
    try:
        llave = decodificar_cursor(cursor) if cursor else None
    except ValueError as exc:
        raise ErrorValidacion("CURSOR_INVALIDO", "El cursor no es válido.") from exc
    if llave is not None and not (
        len(llave) == 2 and isinstance(llave[0], datetime) and isinstance(llave[1], int)
    ):
        raise ErrorValidacion("CURSOR_INVALIDO", "El cursor no es válido.")
    f = replace(filtro, limite=limite, cursor=llave)
    filas = await _con_usuario(motor, actual, lambda c: repo.historial(c, f))
    hay_mas = len(filas) > limite
    items = filas[:limite]
    siguiente = codificar_cursor((items[-1]["fecha"], items[-1]["id"])) if hay_mas else None
    return PaginaCursor(items=items, siguiente=siguiente)
