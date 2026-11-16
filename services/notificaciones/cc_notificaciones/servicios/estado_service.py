"""Máquina de estados de la notificación y del destinatario por eventos (T-113; design.md §3.8,
§6.2; CC-REQ-111, 114, 115, 118).

**Quién escribe qué** (la división con las Lambdas de la parte A de T-217):

=====================  =========================================================================
Despachador (Lambda)   ``notificacion``: ``PROGRAMADA -> ENVIANDO``, ``fecha_envio`` y la
                       reprogramación al siguiente inicio de horario. ``destinatario``:
                       ``encolado_en`` (y ``intentos`` solo si lo define así; el reintento ya lo
                       suma). Nunca escribe ``ENVIADO`` ni otro estado de entrega.
Este módulo            ``destinatario.estado_envio`` (``ENVIADO``, ``ENTREGADO``, ``LEIDO``,
                       ``RESPONDIO``, ``FALLIDO``), ``motivo_fallo``, ``canal_usado``,
                       ``conversacion_id`` y ``fecha_estado``; ``notificacion``:
                       ``ENVIANDO -> COMPLETADA | CON_FALLAS`` (``COMPLETADA -> CON_FALLAS`` si un
                       ``failed`` tardío de Meta llega después de cerrar).
Conciliador (Lambda)   Puede recalcular ``COMPLETADA`` o ``CON_FALLAS`` con la misma regla
                       (``cerrar_si_termino``, abajo) para los eventos perdidos.
=====================  =========================================================================

**Correlación.** El mensaje que despacha el despachador lleva ``origen_tipo = 'NOTIFICACION'``,
``origen_id`` = ``notificacion.id`` (como ``origen_id`` es la constancia o la conversación en los
otros orígenes) y ``colaborador_id``; ``wa.mensaje_estado`` los trae tal cual. El destinatario es
único por ``(notificacion_id, colaborador_id)``, así que se encuentra con esa pareja (no hace falta
guardar ``mensaje_uuid`` ni el id del proveedor).
Los eventos de otros orígenes (``CONSTANCIA``, ``BOT``...) se ignoran: no son de este servicio.

**Reglas.**

- Los estados de entrega solo avanzan por ``rango_estado_envio``: el ``UPDATE`` lleva
  ``rango(actual) < rango(nuevo)``, así que repetir un evento o recibirlo fuera de orden no
  retrocede nada. Además, cada evento se registra en ``evento_procesado`` en la misma transacción.
- Cerrar la notificación bloquea su fila (``FOR UPDATE``) antes de contar: dos consumidores que
  actualizan los dos últimos destinatarios a la vez se serializan y el segundo ve lo que confirmó el
  primero (sin el bloqueo ambos verían al otro como pendiente y la notificación se quedaría en
  ``ENVIANDO``). La transición es comparar y cambiar (``WHERE estado = 'ENVIANDO'``).
- ``COMPLETADA`` si no quedan ``PENDIENTE`` ni ``FALLIDO``; ``CON_FALLAS`` si no quedan
  ``PENDIENTE`` y hay ``FALLIDO`` (§6.2). Los ``ENTREGADO``, ``LEIDO`` y ``RESPONDIO`` posteriores
  solo cambian los contadores. **Desviación documentada:** un ``FALLIDO`` que llega con la
  notificación ya ``COMPLETADA`` la pasa a ``CON_FALLAS`` (Meta acepta y rechaza después); así RH
  puede reintentarlo y el estado no contradice a los destinatarios.
- ``wa.respuesta_recibida`` (``{colaborador_id, empresa_id, conversacion_id?,
  notificacion_destinatario_id?, recibido_en?}``) marca ``RESPONDIO`` al envío **más reciente** del
  colaborador que ya salió (``ENVIADO``, ``ENTREGADO`` o ``LEIDO``) dentro de las últimas 24 horas
  (la ventana de servicio; CC-REQ-104) y vincula la conversación. Sin envío reciente no hace nada.
- Nada de esto registra celulares ni nombres: solo ids y estados.
"""

from __future__ import annotations

import logging
from typing import Any

from cc_common.db import transaccion
from cc_common.eventos import procesar_una_vez

from cc_notificaciones.repos import estados as repo

log = logging.getLogger("cc.notificaciones.estados")

ORIGEN = "NOTIFICACION"
ESTADOS_ENTREGA = ("ENVIADO", "ENTREGADO", "LEIDO", "FALLIDO")
VENTANA_RESPUESTA_HORAS = 24
MAX_MOTIVO = 120


def _entero(valor: Any) -> int | None:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


async def recalcular(conn, notificacion_id: int) -> str | None:
    """Cierra o reabre la notificación según sus destinatarios. Bloquea la fila antes de contar.
    Devuelve el estado nuevo (``COMPLETADA``, ``CON_FALLAS``) o ``None`` si no cambió."""
    estado = await repo.bloquear_notificacion(conn, notificacion_id)
    if estado == "ENVIANDO":
        return await repo.cerrar_si_termino(conn, notificacion_id)
    if estado == "COMPLETADA" and await repo.reabrir_por_fallido_tardio(conn, notificacion_id):
        return "CON_FALLAS"
    return None


async def _con_idempotencia(motor, evento: dict[str, Any], empresa_id: int, efecto) -> bool:
    evento_id = evento.get("evento_id")
    if evento_id:
        aplicado, resultado = await procesar_una_vez(
            motor, "notificaciones", evento_id, efecto, empresa_id=empresa_id
        )
        return bool(aplicado and resultado)
    async with transaccion(motor, empresa_id) as conn:
        return bool(await efecto(conn))


async def aplicar_mensaje_estado(motor, evento: dict[str, Any]) -> bool:
    """``wa.mensaje_estado`` de un mensaje de notificación. ``True`` si cambió algo."""
    if evento.get("origen_tipo") != ORIGEN:
        return False  # constancias, bot...: no es de este servicio
    notificacion_id = _entero(evento.get("origen_id"))
    colaborador_id = _entero(evento.get("colaborador_id"))
    empresa_id = _entero(evento.get("empresa_id"))
    nuevo = evento.get("estado")
    if (
        notificacion_id is None
        or colaborador_id is None
        or empresa_id is None
        or nuevo not in ESTADOS_ENTREGA
    ):
        log.info("estado de mensaje sin efecto: evento incompleto")
        return False
    motivo = None
    if nuevo == "FALLIDO":
        motivo = str(evento.get("error_codigo") or "ERROR_DE_ENTREGA")[:MAX_MOTIVO]

    async def efecto(conn) -> bool:
        avance = await repo.avanzar_destinatario(
            conn, notificacion_id, colaborador_id, nuevo, motivo
        )
        if avance is None:
            return False  # repetido, fuera de orden o de otra empresa (RLS): no retrocede
        destinatario_id, _ = avance
        cierre = await recalcular(conn, notificacion_id)
        log.info(
            "destinatario %s -> %s (notificación %s%s)",
            destinatario_id,
            nuevo,
            notificacion_id,
            f" -> {cierre}" if cierre else "",
        )
        return True

    return await _con_idempotencia(motor, evento, empresa_id, efecto)


async def aplicar_respuesta(motor, evento: dict[str, Any]) -> bool:
    """``wa.respuesta_recibida``: marca ``RESPONDIO`` y vincula la conversación (CC-REQ-115)."""
    colaborador_id = _entero(evento.get("colaborador_id"))
    empresa_id = _entero(evento.get("empresa_id"))
    if colaborador_id is None or empresa_id is None:
        log.info("respuesta sin efecto: evento incompleto")
        return False
    conversacion_id = _entero(evento.get("conversacion_id"))
    destinatario_id = _entero(evento.get("notificacion_destinatario_id"))

    async def efecto(conn) -> bool:
        cambiados = await repo.marcar_respondio(
            conn,
            colaborador_id=colaborador_id,
            conversacion_id=conversacion_id,
            destinatario_id=destinatario_id,
            desde_horas=VENTANA_RESPUESTA_HORAS,
        )
        for did, _nid in cambiados:
            log.info("destinatario %s respondió", did)
        return bool(cambiados)

    return await _con_idempotencia(motor, evento, empresa_id, efecto)
