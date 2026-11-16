"""Reintentar fallidos (NOT-22) y cancelar (NOT-20) (T-115; design.md §3.6, §6.2, §6.3, §6.5;
CC-REQ-108, 109, 118).

**Cancelar** (``cancelar``): solo desde BORRADOR o PROGRAMADA (comparar y cambiar con la fila
bloqueada). Una notificación ya ``ENVIANDO``, ``COMPLETADA`` o ``CON_FALLAS`` no se cancela:
409 ``ESTADO_INVALIDO``. Elimina el schedule (``ClienteScheduler.eliminar`` es idempotente) dentro
de la misma operación: si Scheduler falla, 502 ``ERROR_PROVEEDOR_PROGRAMADOR`` y no cambia nada.
Repetir la cancelación de una ya ``CANCELADA`` devuelve el estado sin efectos. Bitácora
``NOTIFICACION_CANCELADA`` con ids y estados; el motivo libre se guarda en la notificación y
**no** en la bitácora (podría traer datos personales).

**Reintentar** (``reintentar``):

1. Solo una notificación ``CON_FALLAS`` (otra, 409 ``ESTADO_INVALIDO``). Repetir la petición
   cuando el reintento ya está en curso (``ENVIANDO`` con un mensaje ``REINTENTO`` en el
   outbox) devuelve el estado actual y no escribe nada más.
2. Solo toca destinatarios ``FALLIDO``; nunca a quien ya recibió (``ENVIADO``, ``ENTREGADO``,
   ``LEIDO``, ``RESPONDIO``) ni a un ``EXCLUIDO``. Se consulta la elegibilidad vigente a
   `colaboradores` (INT-COL-05 con ``solo_elegibilidad``, sin celulares): quien hoy tiene
   ``celular_invalido``, está dado de baja o sin consentimiento no se incluye y sigue
   ``FALLIDO``. Si nadie es reintentable: 422 ``SIN_FALLIDOS_REINTENTABLES``.
3. Horario: el mismo mecanismo de NOT-19 (``exigir_confirmacion_fuera_horario``): fuera de
   horario,
   409 ``FUERA_DE_HORARIO_REQUIERE_CONFIRMACION`` hasta ``confirmar_fuera_horario``; se guarda
   ``confirmada_fuera_horario`` y quién lo confirmó, y el despachador lo respeta.
4. Los elegibles pasan a ``PENDIENTE`` (``encolado_en`` y ``respaldo_enviado_en`` libres,
   ``intentos`` + 1: el ``mensaje_uuid``
   del despachador depende de ``intentos``, así el reintento es un mensaje nuevo), la notificación
   pasa a ``ENVIANDO`` (``CON_FALLAS -> ENVIANDO``, comparar y cambiar) y se escribe en el outbox
   ``notificacion.confirmada`` con ``{notificacion_id, tipo: "REINTENTO", empresa_id}`` hacia
   ``notif-despacho``. El ``evento_id`` es determinista por (notificación, número de ronda): una
   petición repetida no publica dos veces.
5. Bitácora ``NOTIFICACION_ENVIO`` con ``motivo = "REINTENTO"`` y totales (reintentados y
   omitidos); nunca nombres ni celulares.

La consulta de elegibilidad es una llamada HTTP, así que se hace **fuera** de la transacción; la
escritura vuelve a leer los fallidos con la fila bloqueada y solo cambia a los que siguen
``FALLIDO`` y siguen siendo elegibles.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from cc_common import outbox
from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.bitacora import registrar
from cc_common.db import transaccion
from cc_common.errores import (
    ErrorCampo,
    ErrorConflicto,
    ErrorNoEncontrado,
    ErrorProveedor,
    ErrorValidacion,
)

from cc_notificaciones.repos import estados as repo_estados
from cc_notificaciones.repos import notificaciones as repo
from cc_notificaciones.scheduler import cuerpo_despacho
from cc_notificaciones.servicios.programador import exigir_confirmacion_fuera_horario

log = logging.getLogger("cc.notificaciones.reintentar")

MAX_MOTIVO = 200
LOTE_ELEGIBILIDAD = 500


def evento_reintento(notificacion_id: int, ronda: int) -> uuid.UUID:
    """Identificador determinista del mensaje de reintento (uno por ronda)."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"cc:notificacion.reintento:{notificacion_id}:{ronda}")


def _estado_invalido(actual: str, esperado: str) -> ErrorConflicto:
    return ErrorConflicto(
        "ESTADO_INVALIDO",
        "La notificación no está en un estado que permita esta acción.",
        detalle={"estado_actual": actual, "estado_esperado": esperado},
    )


# ------------------------------------------------------------------------------ cancelar


async def cancelar(
    motor, scheduler, u: UsuarioActual, notificacion_id: int, *, motivo: str | None
) -> dict[str, Any]:
    """NOT-20."""
    usuario_id = requerir_usuario_id(u)
    motivo = (motivo or "").strip()[:MAX_MOTIVO] or None
    async with transaccion(motor, u.empresa_id) as conn:
        n = await repo.obtener(conn, notificacion_id, bloquear=True)
        if n is None:
            raise ErrorNoEncontrado()
        if n["estado"] == "CANCELADA":
            return n  # repetición: ya estaba cancelada
        if n["estado"] not in ("BORRADOR", "PROGRAMADA"):
            raise _estado_invalido(n["estado"], "BORRADOR o PROGRAMADA")
        if not await repo_estados.cancelar(conn, notificacion_id, motivo):
            raise _estado_invalido(n["estado"], "BORRADOR o PROGRAMADA")
        if n["schedule_nombre"]:
            try:
                await scheduler.eliminar(n["schedule_nombre"])
            except Exception as exc:
                log.warning("falló la eliminación del schedule: %s", type(exc).__name__)
                raise ErrorProveedor(
                    "ERROR_PROVEEDOR_PROGRAMADOR",
                    "No se pudo cancelar el envío programado. Intente de nuevo.",
                ) from exc
        await registrar(
            conn,
            empresa_id=u.empresa_id,
            usuario_id=usuario_id,
            accion="NOTIFICACION_CANCELADA",
            entidad="notificacion",
            entidad_id=notificacion_id,
            detalle={
                "notificacion_id": notificacion_id,
                "estado_anterior": n["estado"],
                "estado_nuevo": "CANCELADA",
            },
        )
        log.info("notificación %s cancelada (era %s)", notificacion_id, n["estado"])
        return await repo.obtener(conn, notificacion_id)  # type: ignore[return-value]


# ------------------------------------------------------------------------------ reintentar


async def _motivos_de_no_elegibilidad(
    col_cli, empresa_id: int, colaboradores: list[int]
) -> dict[int, str | None]:
    """``{colaborador_id: motivo | None}`` en lotes (``None``: es elegible)."""
    salida: dict[int, str | None] = {}
    for i in range(0, len(colaboradores), LOTE_ELEGIBILIDAD):
        salida.update(
            await col_cli.elegibilidad(empresa_id, colaboradores[i : i + LOTE_ELEGIBILIDAD])
        )
    return salida


async def reintentar(
    motor,
    cfg,
    col_cli,
    u: UsuarioActual,
    notificacion_id: int,
    *,
    confirmar_fuera_horario: bool,
    ahora: datetime,
) -> dict[str, Any]:
    """NOT-22."""
    usuario_id = requerir_usuario_id(u)
    async with transaccion(motor, u.empresa_id) as conn:
        n = await repo.obtener(conn, notificacion_id)
        if n is None:
            raise ErrorNoEncontrado()
        if n["estado"] == "ENVIANDO" and await repo_estados.rondas_de_reintento(conn, n["id"]):
            return n  # repetición de un reintento ya en curso
        if n["estado"] != "CON_FALLAS":
            raise _estado_invalido(n["estado"], "CON_FALLAS")
        fallidos = await repo_estados.fallidos(conn, notificacion_id)

    motivos = await _motivos_de_no_elegibilidad(
        col_cli, u.empresa_id, sorted({c for _, c in fallidos})
    )
    elegibles = sorted(c for c, motivo in motivos.items() if motivo is None)
    if not elegibles:
        raise ErrorValidacion(
            "SIN_FALLIDOS_REINTENTABLES",
            "No hay destinatarios fallidos que se puedan reintentar.",
            errores=[
                ErrorCampo(
                    "notificacion",
                    "SIN_FALLIDOS_REINTENTABLES",
                    "Ningún fallido es elegible hoy (celular no válido, baja, sin consentimiento).",
                )
            ],
        )

    async with transaccion(motor, u.empresa_id) as conn:
        n = await repo.obtener(conn, notificacion_id, bloquear=True)
        if n is None:
            raise ErrorNoEncontrado()
        if n["estado"] == "ENVIANDO" and await repo_estados.rondas_de_reintento(conn, n["id"]):
            return n  # otro proceso lo hizo entre las dos lecturas
        if n["estado"] != "CON_FALLAS":
            raise _estado_invalido(n["estado"], "CON_FALLAS")
        fuera_horario = exigir_confirmacion_fuera_horario(
            cfg, n["zona_horaria"], ahora, confirmar_fuera_horario
        )
        reintentados = await repo_estados.reintentar_fallidos(conn, notificacion_id, elegibles)
        if reintentados == 0:  # todos recibieron algo mientras tanto
            raise ErrorValidacion(
                "SIN_FALLIDOS_REINTENTABLES",
                "No hay destinatarios fallidos que se puedan reintentar.",
                errores=[
                    ErrorCampo("notificacion", "SIN_FALLIDOS_REINTENTABLES", "No quedan fallidos.")
                ],
            )
        if not await repo_estados.pasar_a_reintento(
            conn, notificacion_id, fuera_horario=fuera_horario, usuario_id=usuario_id
        ):
            raise _estado_invalido("CAMBIO_CONCURRENTE", "CON_FALLAS")
        ronda = await repo_estados.rondas_de_reintento(conn, notificacion_id) + 1
        await outbox.escribir(
            conn,
            "notificaciones",
            destino_tipo="SQS",
            destino=cfg.cola_despacho_url,
            tipo="notificacion.confirmada",
            payload=cuerpo_despacho(notificacion_id, u.empresa_id, "REINTENTO"),
            empresa_id=u.empresa_id,
            evento_id=evento_reintento(notificacion_id, ronda),
        )
        omitidos = len(fallidos) - reintentados
        await registrar(
            conn,
            empresa_id=u.empresa_id,
            usuario_id=usuario_id,
            accion="NOTIFICACION_ENVIO",
            entidad="notificacion",
            entidad_id=notificacion_id,
            detalle={
                "notificacion_id": notificacion_id,
                "motivo": "REINTENTO",
                "estado_anterior": "CON_FALLAS",
                "estado_nuevo": "ENVIANDO",
                "totales": {"reintentados": reintentados, "omitidos": omitidos},
                "confirmada_fuera_horario": fuera_horario,
            },
        )
        log.info("notificación %s: reintento de %s fallidos", notificacion_id, reintentados)
        return await repo.obtener(conn, notificacion_id)  # type: ignore[return-value]
