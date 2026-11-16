"""``conciliador`` (LAM-05; design.md §4.5, §6.2, §6.3; CC-REQ-108, 110, 113).

Corre cada 5 minutos (EventBridge ``rate(5 minutes)``, concurrencia reservada 1). Es la red de
seguridad de la programación y del despacho. Cada ciclo hace cuatro pasos independientes (uno que
falle no impide los otros) y es **idempotente**: dos ciclos seguidos no generan trabajo duplicado.

1. **PROGRAMADA atrasada** (``programada_para`` hace más de 10 minutos, sin despacho): publica un
   ``INICIO`` en ``notif-despacho`` y marca ``reencolada_en``; no vuelve a reencolarla en 30
   minutos. Cubre el schedule que no llegó a existir o falló. Si el schedule vivo dispara después,
   el despachador es idempotente. Métrica ``programadas_atrasadas``.
2. **Destinatarios atascados**: ``PENDIENTE`` con ``encolado_en`` de hace más de 30 minutos (el
   mensaje se perdió o el enviador nunca avanzó): vuelven a ``encolado_en = NULL`` y se publica un
   ``CONTINUAR`` para que el despachador los reenvíe (con el mismo ``mensaje_uuid``: si el original
   sí se envió, el enviador lo ignora). Métrica ``destinatarios_liberados`` (alarma: es un mensaje
   perdido). Tras liberar no queda nada que liberar: el siguiente ciclo no hace nada.
3. **Respaldos por correo pendientes**: notificaciones con respaldo cuyos destinatarios
   ``ENVIADO``/``FALLIDO`` siguen sin atender pasadas 24 horas más 10 minutos de gracia (el
   schedule no llegó): publica ``{notificacion_id, empresa_id}`` en ``notif-respaldo`` y marca
   ``reencolada_en``. Si es fuera de horario no publica (el respaldo lo diferiría igual) y espera
   al ciclo siguiente. Métrica ``respaldos_programados``.
4. **Cierre**: ``ENVIANDO`` sin ningún destinatario ``PENDIENTE`` pasa a ``COMPLETADA`` (sin
   ``FALLIDO``) o ``CON_FALLAS`` (con alguno), por comparar y cambiar (``WHERE estado =
   'ENVIANDO'``) y fijando ``fecha_envio`` si faltaba. Es la misma regla de §6.2 que aplica la
   máquina por eventos (T-113); aquí solo es la red de seguridad, y es idempotente con ella.
   Métrica ``notificaciones_cerradas``.

Recorre todas las empresas con las funciones ``notificaciones.conciliar_*`` (SECURITY DEFINER, solo
devuelven ids; ver ``notif_comun/sql/conciliacion.sql``) y actúa sobre cada notificación con su
``app.empresa_id`` fijado. No registra datos personales.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from notif_comun import horario
from notif_comun.bd import fijar_empresa
from notif_comun.metricas import metrica

log = logging.getLogger("conciliador")


def _ahora_utc() -> datetime:
    return datetime.now(UTC)


def _publicar(sqs, url: str, cuerpo: dict[str, Any]) -> None:
    sqs.send_message(QueueUrl=url, MessageBody=json.dumps(cuerpo, separators=(",", ":")))


def _programadas_atrasadas(conn, cfg, sqs, ahora) -> int:
    filas = conn.execute(
        "SELECT id, empresa_id FROM notificaciones.conciliar_programadas_atrasadas(%s, %s, %s)",
        (ahora, cfg.atraso_programada_min, cfg.reencolado_min),
    ).fetchall()
    conn.rollback()
    hechas = 0
    for nid, eid in filas:
        fijar_empresa(conn, eid)
        marcada = conn.execute(
            "UPDATE notificaciones.notificacion SET reencolada_en = %s "
            "WHERE id = %s AND estado = 'PROGRAMADA' RETURNING id",
            (ahora, nid),
        ).fetchone()
        conn.commit()
        if marcada is None:
            continue
        try:
            _publicar(
                sqs,
                cfg.cola_despacho_url,
                {
                    "evento_id": str(uuid.uuid4()),
                    "tipo": "INICIO",
                    "notificacion_id": nid,
                    "empresa_id": eid,
                },
            )
        except Exception:  # noqa: BLE001 - se deshace la marca para que el siguiente ciclo reintente
            fijar_empresa(conn, eid)
            conn.execute(
                "UPDATE notificaciones.notificacion SET reencolada_en = NULL WHERE id = %s", (nid,)
            )
            conn.commit()
            raise
        hechas += 1
    if hechas:
        metrica("programadas_atrasadas", hechas)
    return hechas


def _liberar_atascados(conn, cfg, sqs, ahora) -> int:
    filas = conn.execute(
        "SELECT id, empresa_id FROM notificaciones.conciliar_encolados_atascados(%s, %s)",
        (ahora, cfg.atascado_min),
    ).fetchall()
    conn.rollback()
    total = 0
    for nid, eid in filas:
        fijar_empresa(conn, eid)
        cur = conn.execute(
            "UPDATE notificaciones.notificacion_destinatario SET encolado_en = NULL "
            "WHERE notificacion_id = %s AND estado_envio = 'PENDIENTE' AND encolado_en IS NOT NULL "
            "AND encolado_en <= %s - make_interval(mins => %s)",
            (nid, ahora, cfg.atascado_min),
        )
        n = cur.rowcount
        conn.commit()
        if not n:
            continue
        total += n
        log.warning("destinatarios liberados: notificacion=%s cantidad=%s", nid, n)
        _publicar(
            sqs,
            cfg.cola_despacho_url,
            {
                "evento_id": str(uuid.uuid4()),
                "tipo": "CONTINUAR",
                "notificacion_id": nid,
                "empresa_id": eid,
            },
        )
    if total:
        metrica("destinatarios_liberados", total)
    return total


def _respaldos(conn, cfg, sqs, ahora) -> int:
    filas = conn.execute(
        "SELECT id, empresa_id, zona_horaria FROM notificaciones.conciliar_respaldos_pendientes"
        "(%s, %s, %s, %s)",
        (ahora, cfg.respaldo_horas, cfg.respaldo_gracia_min, cfg.reencolado_min),
    ).fetchall()
    conn.rollback()
    hechos = 0
    for nid, eid, zona in filas:
        if not horario.dentro_de_horario(ahora, zona, cfg.horario_inicio, cfg.horario_fin):
            metrica("respaldos_fuera_de_horario")
            continue
        fijar_empresa(conn, eid)
        marcada = conn.execute(
            "UPDATE notificaciones.notificacion SET reencolada_en = %s "
            "WHERE id = %s AND respaldo_correo RETURNING id",
            (ahora, nid),
        ).fetchone()
        conn.commit()
        if marcada is None:
            continue
        try:
            _publicar(sqs, cfg.cola_respaldo_url, {"notificacion_id": nid, "empresa_id": eid})
        except Exception:  # noqa: BLE001
            fijar_empresa(conn, eid)
            conn.execute(
                "UPDATE notificaciones.notificacion SET reencolada_en = NULL WHERE id = %s", (nid,)
            )
            conn.commit()
            raise
        hechos += 1
    if hechos:
        metrica("respaldos_programados", hechos)
    return hechos


def _cerrar(conn, cfg, ahora) -> int:
    filas = conn.execute(
        "SELECT id, empresa_id FROM notificaciones.conciliar_cierres_pendientes()"
    ).fetchall()
    conn.rollback()
    cerradas = 0
    for nid, eid in filas:
        fijar_empresa(conn, eid)
        r = conn.execute(
            "UPDATE notificaciones.notificacion n SET "
            "estado = CASE WHEN EXISTS (SELECT 1 FROM notificaciones.notificacion_destinatario d "
            "WHERE d.notificacion_id = n.id AND d.estado_envio = 'FALLIDO') "
            "THEN 'CON_FALLAS' ELSE 'COMPLETADA' END, "
            "fecha_envio = COALESCE(fecha_envio, %s) "
            "WHERE n.id = %s AND n.estado = 'ENVIANDO' "
            "AND NOT EXISTS (SELECT 1 FROM notificaciones.notificacion_destinatario d "
            "WHERE d.notificacion_id = n.id AND d.estado_envio = 'PENDIENTE') RETURNING n.estado",
            (ahora, nid),
        ).fetchone()
        conn.commit()
        if r is not None:
            cerradas += 1
    if cerradas:
        metrica("notificaciones_cerradas", cerradas)
    return cerradas


def conciliar(conn, cfg, *, sqs, ahora: datetime) -> dict[str, int]:
    """Un ciclo. Devuelve cuánto trabajo generó cada paso (todo en 0 si no había nada)."""
    resumen: dict[str, int] = {}
    pasos: list[tuple[str, Callable[[], int]]] = [
        ("programadas_reencoladas", lambda: _programadas_atrasadas(conn, cfg, sqs, ahora)),
        ("destinatarios_liberados", lambda: _liberar_atascados(conn, cfg, sqs, ahora)),
        ("respaldos_encolados", lambda: _respaldos(conn, cfg, sqs, ahora)),
        ("notificaciones_cerradas", lambda: _cerrar(conn, cfg, ahora)),
    ]
    errores = 0
    for nombre, paso in pasos:
        try:
            resumen[nombre] = paso()
        except Exception as exc:  # noqa: BLE001 - un paso no bloquea a los demás; el ciclo repite
            conn.rollback()
            errores += 1
            resumen[nombre] = 0
            log.warning("falló un paso del conciliador (%s): %s", nombre, type(exc).__name__)
    if errores:
        metrica("conciliador_pasos_con_error", errores)
    resumen["errores"] = errores
    return resumen


def manejar(
    _evento: dict[str, Any],
    *,
    abrir: Callable[[], Any],
    cfg,
    sqs,
    reloj: Callable[[], datetime] = _ahora_utc,
) -> dict[str, int]:
    conn = abrir()
    try:
        return conciliar(conn, cfg, sqs=sqs, ahora=reloj())
    finally:
        try:
            conn.rollback()
            conn.close()
        except Exception:  # noqa: BLE001, S110
            pass


def lambda_handler(evento, _contexto):  # pragma: no cover - requiere AWS
    import boto3
    from notif_comun import bd
    from notif_comun.config import obtener

    cfg = obtener()
    sqs = boto3.client("sqs", region_name=cfg.region, endpoint_url=cfg.aws_endpoint or None)
    return manejar(evento, abrir=lambda: bd.abrir_conexion(cfg), cfg=cfg, sqs=sqs)
