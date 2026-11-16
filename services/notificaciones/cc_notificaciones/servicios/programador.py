"""Confirmación, horario y programación del envío (NOT-19; design.md §3.6, §6.3, §4.5;
CC-REQ-108, 109, 110).

``confirmar`` pasa una notificación de BORRADOR a ENVIANDO (enviar ahora) o PROGRAMADA:

1. Todo ocurre con la fila bloqueada (``FOR UPDATE``) y la transición es comparar y cambiar
   (``WHERE estado = 'BORRADOR'``): dos confirmaciones simultáneas no duplican nada.
2. Exige plantilla APROBADA, haber revisado (422 ``REVISION_PENDIENTE``) y al menos un destinatario
   PENDIENTE (422 ``SIN_DESTINATARIOS_VALIDOS``, CC-REQ-107). Esos controles van antes que el
   horario.
3. **Programar**: ``programada_para`` es obligatoria, con zona, futura (422 ``PROGRAMACION_PASADA``)
   y dentro de 08:00 a 20:00 inclusive en la zona de la notificación (422 ``FUERA_DE_HORARIO``). No
   hay confirmación de excepción para programar; ``confirmar_fuera_horario`` se ignora. Crea el
   **schedule único** (``programador.crear_unico``, idempotente) con nombre ``cc-notif-{id}``,
   guardado en ``schedule_nombre``. Si Scheduler falla: 502 ``ERROR_PROVEEDOR_PROGRAMADOR`` y no
   cambia nada. (Si el commit fallara después de crear el schedule, quedaría uno huérfano que, al
   dispararse, encuentra la notificación en BORRADOR y no hace nada: el despachador solo actúa
   sobre PROGRAMADA o ENVIANDO.)
4. **Enviar ahora**: fuera de horario, 409 ``FUERA_DE_HORARIO_REQUIERE_CONFIRMACION`` hasta que el
   cliente repita con ``confirmar_fuera_horario=true``. Entonces se guarda
   ``confirmada_fuera_horario``, quién confirmó (``confirmada_por_usuario_id``) y cuándo
   (``confirmada_en``), y la bitácora lleva ``confirmada_fuera_horario`` y el usuario. Escribe en el
   ``outbox`` (misma transacción) el mensaje de ``notif-despacho`` ``{notificacion_id, tipo:
   "INICIO", empresa_id}`` que consume el despachador (T-217).
5. Idempotencia: repetir la misma confirmación (mismo modo y, al programar, la misma fecha) sobre
   una notificación ya confirmada devuelve 202 con el estado actual y **no** crea otro schedule ni
   otro mensaje. Una confirmación distinta sobre una ya confirmada: 409 ``ESTADO_INVALIDO``.
6. Bitácora ``NOTIFICACION_ENVIO`` con ``criterios`` (snapshot de la revisión) y ``totales``
   (seleccionados, excluidos y válidos); nunca nombres ni celulares.
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

from cc_notificaciones.repos import notificaciones as repo
from cc_notificaciones.scheduler import (
    ScheduleUnico,
    cuerpo_despacho,
    nombre_schedule,
)
from cc_notificaciones.servicios import horario

log = logging.getLogger("cc.notificaciones.programador")

ESTADOS_CONFIRMADOS = ("PROGRAMADA", "ENVIANDO", "COMPLETADA", "CON_FALLAS")


def evento_confirmacion(notificacion_id: int) -> uuid.UUID:
    """Identificador determinista del mensaje de despacho: no se publica dos veces."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"cc:notificacion.confirmada:{notificacion_id}")


def _campo(campo: str, codigo: str, mensaje: str) -> ErrorValidacion:
    return ErrorValidacion(codigo, mensaje, errores=[ErrorCampo(campo, codigo, mensaje)])


def exigir_confirmacion_fuera_horario(cfg, zona: str, ahora: datetime, confirmada: bool) -> bool:
    """Enviar ahora, y reintentar fallidos (NOT-22), fuera de horario exigen confirmación: 409
    ``FUERA_DE_HORARIO_REQUIERE_CONFIRMACION`` hasta que el cliente la manda. Devuelve si el envío
    es fuera de horario (y ya confirmado)."""
    if horario.dentro_de_horario(ahora, zona, cfg.horario_inicio, cfg.horario_fin):
        return False
    if not confirmada:
        raise ErrorConflicto(
            "FUERA_DE_HORARIO_REQUIERE_CONFIRMACION",
            "Es fuera del horario permitido; confirme para enviar de todos modos.",
        )
    return True


def _misma_confirmacion(n: dict[str, Any], modo_envio: str, programada_para: datetime | None):
    if n["estado"] not in ESTADOS_CONFIRMADOS or n["modo_envio"] != modo_envio:
        return False
    if modo_envio == "AHORA":
        return True
    return (
        programada_para is not None
        and programada_para.tzinfo is not None
        and n["programada_para"] == programada_para
    )


async def confirmar(
    motor,
    cfg,
    scheduler,
    u: UsuarioActual,
    notificacion_id: int,
    *,
    modo_envio: str,
    programada_para: datetime | None,
    respaldo_correo: bool | None,
    confirmar_fuera_horario: bool,
    ahora: datetime,
) -> dict[str, Any]:
    usuario_id = requerir_usuario_id(u)
    async with transaccion(motor, u.empresa_id) as conn:
        n = await repo.obtener(conn, notificacion_id, bloquear=True)
        if n is None:
            raise ErrorNoEncontrado()
        if n["estado"] != "BORRADOR":
            if _misma_confirmacion(n, modo_envio, programada_para):
                return n  # repetición: ya se hizo, sin efectos nuevos
            raise ErrorConflicto(
                "ESTADO_INVALIDO",
                "La notificación ya no está en borrador.",
                detalle={"estado_actual": n["estado"], "estado_esperado": "BORRADOR"},
            )
        if n["plantilla_estado"] != "APROBADA":
            raise _campo(
                "plantilla_mensaje_id",
                "PLANTILLA_META_NO_APROBADA",
                "Solo se pueden usar plantillas aprobadas por Meta.",
            )
        if n["revisada_en"] is None:
            raise _campo(
                "notificacion", "REVISION_PENDIENTE", "Revise la audiencia antes de enviar."
            )
        if n["pendientes"] == 0:
            raise _campo(
                "notificacion", "SIN_DESTINATARIOS_VALIDOS", "No hay destinatarios válidos."
            )

        zona = n["zona_horaria"]
        fuera_horario = False
        if modo_envio == "PROGRAMAR":
            _validar_programacion(cfg, programada_para, zona, ahora)
            estado_nuevo = "PROGRAMADA"
            nombre = nombre_schedule(notificacion_id)
        else:
            programada_para = None
            estado_nuevo = "ENVIANDO"
            nombre = None
            fuera_horario = exigir_confirmacion_fuera_horario(
                cfg, zona, ahora, confirmar_fuera_horario
            )

        if modo_envio == "PROGRAMAR":
            try:
                await scheduler.crear_unico(
                    ScheduleUnico(
                        nombre=nombre,  # type: ignore[arg-type]
                        expresion=horario.expresion_at(programada_para, zona),  # type: ignore[arg-type]
                        zona=zona,
                        cuerpo=cuerpo_despacho(notificacion_id, u.empresa_id),
                    )
                )
            except Exception as exc:
                log.warning("falló la creación del schedule: %s", type(exc).__name__)
                raise ErrorProveedor(
                    "ERROR_PROVEEDOR_PROGRAMADOR",
                    "No se pudo programar el envío. Intente de nuevo.",
                ) from exc

        cambio = await repo.marcar_confirmada(
            conn,
            notificacion_id,
            estado_nuevo=estado_nuevo,
            modo_envio=modo_envio,
            programada_para=programada_para,
            schedule_nombre=nombre,
            respaldo_correo=n["respaldo_correo"] if respaldo_correo is None else respaldo_correo,
            fuera_horario=fuera_horario,
            usuario_id=usuario_id,
        )
        if not cambio:  # otro proceso la cambió entre el bloqueo y el cambio (no debería)
            raise ErrorConflicto("ESTADO_INVALIDO", "La notificación ya no está en borrador.")
        if modo_envio == "AHORA":
            await outbox.escribir(
                conn,
                "notificaciones",
                destino_tipo="SQS",
                destino=cfg.cola_despacho_url,
                tipo="notificacion.confirmada",
                payload=cuerpo_despacho(notificacion_id, u.empresa_id),
                empresa_id=u.empresa_id,
                evento_id=evento_confirmacion(notificacion_id),
            )
        await registrar(
            conn,
            empresa_id=u.empresa_id,
            usuario_id=usuario_id,
            accion="NOTIFICACION_ENVIO",
            entidad="notificacion",
            entidad_id=notificacion_id,
            detalle={
                "notificacion_id": notificacion_id,
                "plantilla_id": n["plantilla_mensaje_id"],
                "criterios": n["criterios_snapshot_json"],
                "totales": {
                    "seleccionados": n["total_seleccionados"],
                    "excluidos": n["total_excluidos"],
                    "validos": n["pendientes"],
                },
                "estado_nuevo": estado_nuevo,
                "confirmada_fuera_horario": fuera_horario,
            },
        )
        log.info("notificación %s confirmada como %s", notificacion_id, estado_nuevo)
        return await repo.obtener(conn, notificacion_id)  # type: ignore[return-value]


def _validar_programacion(cfg, programada_para: datetime | None, zona: str, ahora: datetime):
    if programada_para is None:
        raise _campo("programada_para", "REQUERIDO", "Indique la fecha y la hora.")
    if programada_para.tzinfo is None or programada_para.utcoffset() is None:
        raise _campo(
            "programada_para", "FECHA_INVALIDA", "Indique la fecha y la hora con su zona horaria."
        )
    if programada_para <= ahora:
        raise _campo("programada_para", "PROGRAMACION_PASADA", "La hora debe ser futura.")
    if not horario.dentro_de_horario(programada_para, zona, cfg.horario_inicio, cfg.horario_fin):
        raise _campo(
            "programada_para",
            "FUERA_DE_HORARIO",
            "La hora queda fuera del horario permitido; ajústela.",
        )
