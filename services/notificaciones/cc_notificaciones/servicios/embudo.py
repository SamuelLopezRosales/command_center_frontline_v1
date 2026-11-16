"""Embudo y revisión de una notificación (NOT-18; design.md §3.6, §6.1; CC-REQ-105 a 107).

``revisar`` evalúa la audiencia en `colaboradores` (INT-COL-06), reemplaza los renglones de
destinatarios y guarda ``criterios_snapshot_json`` con los totales.

Decisiones donde el diseño no es explícito (lo más conservador):
- Solo se revisa una notificación en BORRADOR (otro estado: 409 ``ESTADO_INVALIDO``).
- Criterios: los de la audiencia guardada (``audiencia_id``) y, si no hay, el
  ``criterios_snapshot_json`` que dejó la creación o edición (T-216). Sin ninguno: 422
  ``SIN_CRITERIOS``. Los criterios se revalidan: un campo desactivado o hecho sensible desde que
  se guardó la audiencia da 422 y pide corregirla.
- ``total_seleccionados`` es el total de la audiencia (los 61 del ejemplo, con excluidos) y
  ``total_excluidos`` los que no pasan el embudo (7); los válidos son su diferencia.
- La evaluación (HTTP) ocurre fuera de la transacción de base de datos; al escribir se bloquea la
  fila y se confirma que sigue en BORRADOR, así dos revisiones simultáneas no mezclan renglones.
- Los motivos de exclusión los asigna `colaboradores` (un solo motivo por colaborador, en el
  orden consentimiento, estatus y celular).
- No se registran nombres ni celulares en logs ni en bitácora: solo ids y totales.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from cc_common.auth import UsuarioActual
from cc_common.criterios_audiencia import validar
from cc_common.db import transaccion
from cc_common.errores import ErrorCampo, ErrorConflicto, ErrorNoEncontrado, ErrorValidacion

from cc_notificaciones.clientes import ItemAudiencia
from cc_notificaciones.repos import destinatarios as repo

MOTIVOS = ("SIN_CONSENTIMIENTO", "ESTATUS_BAJA", "SIN_CELULAR_VALIDO")


def _estado_invalido(actual: str) -> ErrorConflicto:
    return ErrorConflicto(
        "ESTADO_INVALIDO",
        "Solo se puede revisar una notificación en borrador.",
        detalle={"estado_actual": actual, "estado_esperado": "BORRADOR"},
    )


async def revisar(
    motor, cfg, campos_cli, colaboradores_cli, u: UsuarioActual, notificacion_id: int
) -> dict[str, Any]:
    async with transaccion(motor, u.empresa_id) as conn:
        n = await repo.obtener_notificacion(conn, notificacion_id)
    if n is None:
        raise ErrorNoEncontrado()
    if n["estado"] != "BORRADOR":
        raise _estado_invalido(n["estado"])
    criterios = n["criterios_audiencia"] if n["audiencia_id"] else n["criterios_snapshot_json"]
    if not criterios:
        raise ErrorValidacion(
            "SIN_CRITERIOS",
            "La notificación no tiene audiencia ni criterios.",
            errores=[ErrorCampo("criterios", "SIN_CRITERIOS", "Indique la audiencia.")],
        )
    validar(criterios, await campos_cli.definiciones(u.empresa_id))

    items: list[ItemAudiencia] = []
    embudo = None
    cursor = None
    while True:
        r = await colaboradores_cli.evaluar_audiencia(
            u.empresa_id,
            criterios,
            cursor=cursor,
            limite=cfg.audiencia_pagina,
            zona_horaria=n["zona_horaria"],
        )
        embudo = embudo or r.embudo
        items.extend(r.items)
        if len(items) > cfg.audiencia_maximo:
            raise ErrorValidacion(
                "AUDIENCIA_DEMASIADO_GRANDE",
                "La audiencia es demasiado grande. Acote los criterios.",
                errores=[ErrorCampo("criterios", "AUDIENCIA_DEMASIADO_GRANDE", "Acote.")],
            )
        cursor = r.siguiente_cursor
        if not cursor:
            break

    por_motivo = dict.fromkeys(MOTIVOS, 0)
    for i in items:
        if i.motivo_exclusion:
            por_motivo[i.motivo_exclusion] += 1
    excluidos = sum(por_motivo.values())

    async with transaccion(motor, u.empresa_id) as conn:
        actual = await repo.obtener_notificacion(conn, notificacion_id, bloquear=True)
        if actual is None:
            raise ErrorNoEncontrado()
        if actual["estado"] != "BORRADOR":
            raise _estado_invalido(actual["estado"])
        await repo.reemplazar(
            conn, empresa_id=u.empresa_id, notificacion_id=notificacion_id, items=items
        )
        revisada_en = await repo.guardar_revision(
            conn,
            notificacion_id,
            criterios=criterios,
            seleccionados=len(items),
            excluidos=excluidos,
        )
    return {
        "embudo": asdict(embudo) if embudo else {},
        "excluidos_por_motivo": por_motivo,
        "total_seleccionados": len(items),
        "total_excluidos": excluidos,
        "revisada_en": revisada_en,
    }
