"""SQL de la máquina de estados del destinatario y de la notificación (design.md §6.2; T-217).

Todas las transiciones son **comparar y cambiar**: el ``WHERE`` lleva el estado esperado (o el
rango, ``notificaciones.rango_estado_envio``) y el ``rowcount`` dice si esta llamada fue la que
cambió algo. Nada de aquí lee ni escribe datos personales.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_DEST = "notificaciones.notificacion_destinatario"
_NOT = "notificaciones.notificacion"


async def avanzar_destinatario(
    conn: AsyncConnection,
    notificacion_id: int,
    colaborador_id: int,
    nuevo: str,
    motivo_fallo: str | None,
) -> tuple[int, int] | None:
    """Lleva al destinatario a ``nuevo`` solo si ``rango(actual) < rango(nuevo)``: un estado
    repetido o fuera de orden no cambia nada. El destinatario es único por ``(notificacion_id,
    colaborador_id)``. Devuelve ``(destinatario_id, notificacion_id)`` si avanzó."""
    r = await conn.execute(
        text(
            f"UPDATE {_DEST} d SET estado_envio = :nuevo, fecha_estado = now(), "  # noqa: S608
            "canal_usado = CASE WHEN :nuevo = 'FALLIDO' THEN d.canal_usado "
            "                   ELSE COALESCE(d.canal_usado, 'WHATSAPP') END, "
            "motivo_fallo = CASE WHEN :nuevo = 'FALLIDO' THEN :motivo ELSE NULL END "
            "WHERE d.notificacion_id = :n AND d.colaborador_id = :c "
            "AND notificaciones.rango_estado_envio(d.estado_envio) "
            "< notificaciones.rango_estado_envio(CAST(:nuevo AS text)) "
            "RETURNING d.id, d.notificacion_id"
        ),
        {"n": notificacion_id, "c": colaborador_id, "nuevo": nuevo, "motivo": motivo_fallo},
    )
    fila = r.first()
    return (int(fila[0]), int(fila[1])) if fila else None


async def marcar_respondio(
    conn: AsyncConnection,
    *,
    colaborador_id: int,
    conversacion_id: int | None,
    destinatario_id: int | None,
    desde_horas: int,
) -> list[tuple[int, int]]:
    """Marca ``RESPONDIO`` el envío más reciente del colaborador que ya salió (``ENVIADO``,
    ``ENTREGADO`` o ``LEIDO``) dentro de la ventana, o el ``destinatario_id`` indicado. Vincula la
    conversación. Devuelve ``[(destinatario_id, notificacion_id)]`` de lo que cambió."""
    filtro = "d.id = :did" if destinatario_id is not None else "d.colaborador_id = :c"
    r = await conn.execute(
        text(
            f"WITH objetivo AS (SELECT d.id FROM {_DEST} d WHERE {filtro} "  # noqa: S608
            "  AND d.estado_envio IN ('ENVIADO', 'ENTREGADO', 'LEIDO') "
            "  AND d.fecha_estado >= now() - make_interval(hours => :horas) "
            "  ORDER BY d.fecha_estado DESC, d.id DESC LIMIT 1) "
            f"UPDATE {_DEST} d SET estado_envio = 'RESPONDIO', fecha_estado = now(), "
            "conversacion_id = COALESCE(CAST(:conv AS bigint), d.conversacion_id) "
            "FROM objetivo o WHERE d.id = o.id "
            "AND notificaciones.rango_estado_envio(d.estado_envio) "
            "< notificaciones.rango_estado_envio('RESPONDIO') "
            "RETURNING d.id, d.notificacion_id"
        ),
        {
            "did": destinatario_id,
            "c": colaborador_id,
            "conv": conversacion_id,
            "horas": desde_horas,
        },
    )
    return [(int(i), int(n)) for i, n in r.all()]


async def bloquear_notificacion(conn: AsyncConnection, notificacion_id: int) -> str | None:
    """``SELECT ... FOR UPDATE`` de la notificación; devuelve su estado. Serializa a los
    consumidores que cierran la misma notificación: el siguiente ve lo que confirmó el anterior."""
    r = await conn.execute(
        text(f"SELECT estado FROM {_NOT} WHERE id = :id FOR UPDATE"),  # noqa: S608
        {"id": notificacion_id},
    )
    return r.scalar_one_or_none()


async def cerrar_si_termino(conn: AsyncConnection, notificacion_id: int) -> str | None:
    """``ENVIANDO`` -> ``COMPLETADA`` (sin pendientes ni fallidos) o ``CON_FALLAS`` (sin pendientes
    y con fallidos). Devuelve el estado nuevo o ``None`` si no cambió. Hay que llamarla con la fila
    bloqueada (``bloquear_notificacion``)."""
    r = await conn.execute(
        text(
            f"UPDATE {_NOT} n SET estado = CASE WHEN EXISTS (SELECT 1 FROM {_DEST} d "  # noqa: S608
            "  WHERE d.notificacion_id = n.id AND d.estado_envio = 'FALLIDO') "
            "  THEN 'CON_FALLAS' ELSE 'COMPLETADA' END "
            "WHERE n.id = :id AND n.estado = 'ENVIANDO' AND NOT EXISTS (SELECT 1 FROM "
            f"  {_DEST} d WHERE d.notificacion_id = n.id AND d.estado_envio = 'PENDIENTE') "
            "RETURNING n.estado"
        ),
        {"id": notificacion_id},
    )
    return r.scalar_one_or_none()


async def reabrir_por_fallido_tardio(conn: AsyncConnection, notificacion_id: int) -> bool:
    """``COMPLETADA`` -> ``CON_FALLAS`` si un ``failed`` de Meta llegó después de cerrar (Meta
    acepta el mensaje y lo rechaza segundos después). Devuelve si cambió."""
    r = await conn.execute(
        text(
            f"UPDATE {_NOT} n SET estado = 'CON_FALLAS' "  # noqa: S608
            "WHERE n.id = :id AND n.estado = 'COMPLETADA' AND EXISTS (SELECT 1 FROM "
            f"  {_DEST} d WHERE d.notificacion_id = n.id AND d.estado_envio = 'FALLIDO')"
        ),
        {"id": notificacion_id},
    )
    return bool(r.rowcount)


async def fallidos(conn: AsyncConnection, notificacion_id: int) -> list[tuple[int, int]]:
    """``[(destinatario_id, colaborador_id)]`` de los destinatarios ``FALLIDO``."""
    r = await conn.execute(
        text(
            f"SELECT id, colaborador_id FROM {_DEST} "  # noqa: S608
            "WHERE notificacion_id = :n AND estado_envio = 'FALLIDO' ORDER BY id"
        ),
        {"n": notificacion_id},
    )
    return [(int(i), int(c)) for i, c in r.all()]


async def reintentar_fallidos(
    conn: AsyncConnection, notificacion_id: int, colaboradores: list[int]
) -> int:
    """``FALLIDO`` -> ``PENDIENTE`` solo de los colaboradores indicados. Libera ``encolado_en`` y
    ``respaldo_enviado_en`` (un nuevo ciclo vuelve a tener respaldo) y suma ``intentos`` (el
    ``mensaje_uuid`` del despachador depende de él, así que el reintento es un mensaje nuevo).
    Quien ya no está ``FALLIDO`` (llegó un ``ENTREGADO`` tardío) no se toca."""
    r = await conn.execute(
        text(
            f"UPDATE {_DEST} SET estado_envio = 'PENDIENTE', encolado_en = NULL, "  # noqa: S608
            "respaldo_enviado_en = NULL, motivo_fallo = NULL, intentos = intentos + 1, "
            "fecha_estado = now() "
            "WHERE notificacion_id = :n AND estado_envio = 'FALLIDO' "
            "AND colaborador_id = ANY(CAST(:cols AS bigint[]))"
        ),
        {"n": notificacion_id, "cols": colaboradores},
    )
    return int(r.rowcount or 0)


async def rondas_de_reintento(conn: AsyncConnection, notificacion_id: int) -> int:
    """Cuántos reintentos se han pedido (mensajes ``REINTENTO`` en el outbox)."""
    r = await conn.execute(
        text(
            "SELECT count(*) FROM notificaciones.outbox WHERE tipo = 'notificacion.confirmada' "
            "AND payload ->> 'tipo' = 'REINTENTO' "
            "AND (payload ->> 'notificacion_id')::bigint = :n"
        ),
        {"n": notificacion_id},
    )
    return int(r.scalar_one())


async def pasar_a_reintento(
    conn: AsyncConnection,
    notificacion_id: int,
    *,
    fuera_horario: bool,
    usuario_id: int,
) -> bool:
    """``CON_FALLAS`` -> ``ENVIANDO`` (comparar y cambiar). Con confirmación fuera de horario deja
    ``confirmada_fuera_horario`` (el despachador revalida el horario) y quién la dio."""
    r = await conn.execute(
        text(
            f"UPDATE {_NOT} SET estado = 'ENVIANDO', "  # noqa: S608
            "confirmada_fuera_horario = confirmada_fuera_horario OR :fh, "
            "confirmada_por_usuario_id = CASE WHEN :fh THEN :u ELSE confirmada_por_usuario_id END, "
            "confirmada_en = CASE WHEN :fh THEN now() ELSE confirmada_en END "
            "WHERE id = :id AND estado = 'CON_FALLAS'"
        ),
        {"id": notificacion_id, "fh": fuera_horario, "u": usuario_id},
    )
    return bool(r.rowcount)


async def cancelar(conn: AsyncConnection, notificacion_id: int, motivo: str | None) -> bool:
    """BORRADOR o PROGRAMADA -> CANCELADA (comparar y cambiar). ``False`` si ya no estaba en un
    estado cancelable."""
    r = await conn.execute(
        text(
            f"UPDATE {_NOT} SET estado = 'CANCELADA', motivo_cancelacion = :m "  # noqa: S608
            "WHERE id = :id AND estado IN ('BORRADOR', 'PROGRAMADA')"
        ),
        {"id": notificacion_id, "m": motivo},
    )
    return bool(r.rowcount)
