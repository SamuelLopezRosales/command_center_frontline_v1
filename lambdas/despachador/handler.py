"""``despachador`` (LAM-04; design.md §4.5, §6.2, §6.3; CC-REQ-103, 108, 109, 111).

Consume ``notif-despacho`` (use ``BatchSize`` 1: el despacho puede durar minutos). Cuerpo::

    {"notificacion_id": 12, "empresa_id": 3, "tipo": "INICIO" | "CONTINUAR" | "REINTENTO",
     "evento_id": "..."}      # ``evento_id`` solo lo traen los mensajes del outbox y del propio
                              # despachador; los de EventBridge Scheduler no lo llevan.

Qué hace, en orden:

1. **Estado** (con la notificación bloqueada, ``FOR UPDATE``). Solo actúa sobre ``PROGRAMADA`` o
   ``ENVIANDO``; ``BORRADOR`` (schedule huérfano), ``CANCELADA``, ``COMPLETADA``, ``CON_FALLAS`` y
   una notificación inexistente (o de otra empresa, por la RLS) se ignoran. Una ``PROGRAMADA``
   cuyo ``programada_para`` queda a más de 60 s en el futuro (mensaje adelantado) también se ignora:
   el schedule real la disparará.
2. **Horario** (08:00 a 20:00 inclusive, zona de la notificación). Fuera de horario y sin
   ``confirmada_fuera_horario`` **no envía**: crea un schedule nuevo (``cc-notif-{id}-{n}``) para el
   siguiente inicio, actualiza ``programada_para`` y ``schedule_nombre`` y deja la notificación
   ``PROGRAMADA`` (CC-ASM-010). ``confirmada_fuera_horario`` autoriza cualquier ``tipo``.
3. ``PROGRAMADA`` -> ``ENVIANDO`` (comparar y cambiar).
4. **Bloques**: toma hasta 500 destinatarios ``PENDIENTE`` sin ``encolado_en`` con
   ``FOR UPDATE SKIP LOCKED``; si la plantilla usa variables de colaborador las pide a
   ``contactos:resolver``; marca ``encolado_en`` y confirma la transacción; publica en
   ``wa-salida.fifo`` con ``SendMessageBatch`` de 10. Antes de cada bloque comprueba que la
   notificación siga ``ENVIANDO`` (``FOR SHARE``): una cancelación detiene el despacho.
5. **Tiempo**: si faltan menos de ``margen_tiempo_ms`` para el timeout, publica un mensaje
   ``CONTINUAR`` en ``notif-despacho`` y termina.
6. **Fin** (sin pendientes sin encolar): fija ``fecha_envio`` (la primera vez) y, con
   ``respaldo_correo``, crea el schedule del respaldo a ``ahora + 24 h``.

**Idempotencia**. ``mensaje_uuid = uuid5(notificacion, destinatario, ronda)`` con ``ronda =
notificacion_destinatario.intentos`` (el despachador **no** lo modifica: lo incrementa el reintento
de fallidos, NOT-22, para que un reenvío tenga otro uuid). El enviador ignora un uuid ya
procesado y la cola FIFO deduplica por ``mensaje_uuid``, así que repetir una invocación, una
liberación del conciliador o un ``SendMessageBatch`` repetido no duplican envíos. Si la publicación
de un lote falla, esos destinatarios vuelven a ``encolado_en = NULL`` y el mensaje se reintenta.

**Estados que escribe** (nada más): ``notificacion.estado`` ``PROGRAMADA``->``ENVIANDO`` y
``ENVIANDO``->``PROGRAMADA`` (solo al diferir por horario), ``programada_para``,
``schedule_nombre``, ``fecha_envio``; ``destinatario.encolado_en`` (y su vuelta a ``NULL`` si la
publicación falla). **Nunca** ``COMPLETADA``/``CON_FALLAS`` ni estados del destinatario: eso es
de la máquina de estados por eventos (T-113) y del conciliador.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from notif_comun import horario, plantilla
from notif_comun.bd import fijar_empresa
from notif_comun.metricas import metrica
from notif_comun.scheduler import (
    DESPACHO,
    RESPALDO,
    ScheduleUnico,
    cuerpo_despacho,
    cuerpo_respaldo,
    nombre_respaldo,
    siguiente_nombre,
)

log = logging.getLogger("despachador")

TIPOS = ("INICIO", "CONTINUAR", "REINTENTO")
ORIGEN = "NOTIFICACION"

# Resultados de ``procesar``
DESPACHADA = "DESPACHADA"
CONTINUA = "CONTINUA"
REPROGRAMADA = "REPROGRAMADA"
IGNORADA = "IGNORADA"
INTERRUMPIDA = "INTERRUMPIDA"
OTRO_DESPACHADOR = "OTRO_DESPACHADOR"


class ErrorPublicacion(Exception):  # noqa: N818
    """Algún lote no se publicó en ``wa-salida.fifo``: se reintenta el mensaje."""


def mensaje_uuid(notificacion_id: int, destinatario_id: int, ronda: int = 0) -> str:
    """Identificador determinista del envío a un destinatario (clave de idempotencia del
    enviador y de la deduplicación de la cola FIFO)."""
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"cc:notificacion:{notificacion_id}:destinatario:{destinatario_id}:{ronda}",
        )
    )


def _ahora_utc() -> datetime:
    return datetime.now(UTC)


def validar(cuerpo: Any) -> dict[str, Any] | None:
    """El cuerpo normalizado o ``None`` si no es un mensaje de despacho válido."""
    if not isinstance(cuerpo, dict):
        return None
    nid, eid = cuerpo.get("notificacion_id"), cuerpo.get("empresa_id")
    tipo = cuerpo.get("tipo", "INICIO")
    if not (isinstance(nid, int) and isinstance(eid, int)) or isinstance(nid, bool):
        return None
    if tipo not in TIPOS:
        return None
    return {"notificacion_id": nid, "empresa_id": eid, "tipo": tipo}


def _cargar(conn, notificacion_id: int) -> dict[str, Any] | None:
    r = conn.execute(
        "SELECT n.estado, n.zona_horaria, n.confirmada_fuera_horario, n.programada_para, "
        "n.schedule_nombre, n.respaldo_correo, n.variables_json, p.nombre "
        "FROM notificaciones.notificacion n "
        "LEFT JOIN notificaciones.plantilla_mensaje p ON p.id = n.plantilla_mensaje_id "
        "WHERE n.id = %s FOR UPDATE OF n",
        (notificacion_id,),
    ).fetchone()
    if r is None:
        return None
    return {
        "estado": r[0],
        "zona": r[1],
        "fuera_horario_ok": r[2],
        "programada_para": r[3],
        "schedule_nombre": r[4],
        "respaldo": r[5],
        "variables_json": r[6],
        "plantilla": r[7],
    }


def _iniciar(conn, cfg, m, *, scheduler, ahora: datetime) -> tuple[str | None, dict | None]:
    """Decide si se despacha. Devuelve ``(resultado, notificacion)``; ``resultado`` es ``None``
    cuando hay que despachar."""
    nid, eid = m["notificacion_id"], m["empresa_id"]
    n = _cargar(conn, nid)
    if n is None or n["estado"] not in ("PROGRAMADA", "ENVIANDO"):
        metrica("despachos_ignorados")
        return IGNORADA, None
    if (
        n["estado"] == "PROGRAMADA"
        and n["programada_para"] is not None
        and n["programada_para"] > ahora + timedelta(seconds=cfg.adelanto_tolerado_s)
    ):
        metrica("despachos_adelantados")
        return IGNORADA, None
    if not n["fuera_horario_ok"] and not horario.dentro_de_horario(
        ahora, n["zona"], cfg.horario_inicio, cfg.horario_fin
    ):
        nuevo = horario.siguiente_inicio(ahora, n["zona"], cfg.horario_inicio, cfg.horario_fin)
        nombre = siguiente_nombre(nid, n["schedule_nombre"])
        scheduler.crear_unico(
            ScheduleUnico(
                nombre=nombre,
                expresion=horario.expresion_at(nuevo, n["zona"]),
                zona=n["zona"],
                cuerpo=cuerpo_despacho(nid, eid),
                destino=DESPACHO,
            )
        )
        conn.execute(
            "UPDATE notificaciones.notificacion SET estado = 'PROGRAMADA', programada_para = %s, "
            "schedule_nombre = %s WHERE id = %s AND estado = %s",
            (nuevo, nombre, nid, n["estado"]),
        )
        metrica("fuera_de_horario_reprogramados")
        return REPROGRAMADA, None
    if n["estado"] == "PROGRAMADA":
        conn.execute(
            "UPDATE notificaciones.notificacion SET estado = 'ENVIANDO' "
            "WHERE id = %s AND estado = 'PROGRAMADA'",
            (nid,),
        )
    return None, n


def _publicar(sqs, cfg, mensajes: list[dict[str, Any]]) -> list[int]:
    """Publica en lotes de 10. Devuelve los ``destinatario_id`` que no se publicaron."""
    fallidos: list[int] = []
    for i in range(0, len(mensajes), 10):
        lote = mensajes[i : i + 10]
        entradas = [
            {
                "Id": str(x["destinatario_id"]),
                "MessageBody": json.dumps(x["cuerpo"], separators=(",", ":")),
                "MessageGroupId": str(x["cuerpo"]["colaborador_id"]),
                "MessageDeduplicationId": x["cuerpo"]["mensaje_uuid"],
            }
            for x in lote
        ]
        try:
            r = sqs.send_message_batch(QueueUrl=cfg.cola_salida_url, Entries=entradas)
        except Exception as exc:  # noqa: BLE001 - se libera el lote y se reintenta el mensaje
            log.warning("falló SendMessageBatch: %s", type(exc).__name__)
            fallidos.extend(x["destinatario_id"] for x in lote)
            continue
        fallidos.extend(int(f["Id"]) for f in r.get("Failed", []))
    return fallidos


def _liberar(conn, empresa_id: int, ids: list[int]) -> None:
    fijar_empresa(conn, empresa_id)
    conn.execute(
        "UPDATE notificaciones.notificacion_destinatario SET encolado_en = NULL "
        "WHERE id = ANY(%s) AND estado_envio = 'PENDIENTE'",
        (ids,),
    )
    conn.commit()


def _bloque(conn, cfg, m, n, *, sqs, contactos, ahora: datetime) -> tuple[str, int]:
    """Un bloque de hasta ``bloque_destinatarios``. Devuelve ``(situación, encolados)`` con
    situación ``"SEGUIR"`` (había trabajo), ``"VACIO"`` (no hay pendientes sin encolar) o
    ``"INTERRUMPIDA"`` (la notificación dejó de estar ENVIANDO)."""
    nid, eid = m["notificacion_id"], m["empresa_id"]
    fijar_empresa(conn, eid)
    estado = conn.execute(
        "SELECT estado FROM notificaciones.notificacion WHERE id = %s FOR SHARE", (nid,)
    ).fetchone()
    if estado is None or estado[0] != "ENVIANDO":
        conn.rollback()
        return "INTERRUMPIDA", 0
    filas = conn.execute(
        "SELECT id, colaborador_id, intentos FROM notificaciones.notificacion_destinatario "
        "WHERE notificacion_id = %s AND estado_envio = 'PENDIENTE' AND encolado_en IS NULL "
        "ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED",
        (nid, cfg.bloque_destinatarios),
    ).fetchall()
    if not filas:
        conn.rollback()
        return "VACIO", 0

    campos = plantilla.campos_colaborador(n["variables_json"])
    resueltos: dict[int, dict[str, Any]] = {}
    if campos:  # un fallo de `colaboradores` revierte el bloque (nada queda marcado)
        try:
            resueltos = contactos.resolver(eid, [f[1] for f in filas], "NOTIFICACION", campos)
        except Exception:
            conn.rollback()
            raise

    mensajes = []
    for dest_id, colaborador_id, ronda in filas:
        valores = (resueltos.get(colaborador_id) or {}).get("valores") or {}
        mensajes.append(
            {
                "destinatario_id": dest_id,
                "cuerpo": {
                    "mensaje_uuid": mensaje_uuid(nid, dest_id, ronda),
                    "origen_tipo": ORIGEN,
                    "origen_id": nid,
                    "colaborador_id": colaborador_id,
                    "conversacion_id": None,
                    "empresa_id": eid,
                    "tipo": "PLANTILLA",
                    "plantilla": n["plantilla"],
                    "variables": plantilla.armar_variables(n["variables_json"], valores),
                    "max_intentos": cfg.max_intentos_mensaje,
                    "proposito": ORIGEN,
                },
            }
        )
    conn.execute(
        "UPDATE notificaciones.notificacion_destinatario SET encolado_en = %s "
        "WHERE id = ANY(%s) AND estado_envio = 'PENDIENTE' AND encolado_en IS NULL",
        (ahora, [x["destinatario_id"] for x in mensajes]),
    )
    conn.commit()  # misma transacción que decidió qué publicar

    fallidos = _publicar(sqs, cfg, mensajes)
    if fallidos:
        _liberar(conn, eid, fallidos)
        metrica("publicaciones_fallidas", len(fallidos))
        raise ErrorPublicacion
    metrica("destinatarios_encolados", len(mensajes))
    return "SEGUIR", len(mensajes)


def _continuar(sqs, cfg, m) -> None:
    sqs.send_message(
        QueueUrl=cfg.cola_despacho_url,
        MessageBody=json.dumps(
            {
                "evento_id": str(uuid.uuid4()),
                "tipo": "CONTINUAR",
                "notificacion_id": m["notificacion_id"],
                "empresa_id": m["empresa_id"],
            },
            separators=(",", ":"),
        ),
    )


def _finalizar(conn, cfg, m, n, *, scheduler, ahora: datetime) -> str:
    """Sin pendientes sin encolar. Si otro despachador aún tiene bloques en curso (filas
    bloqueadas), él finaliza; si no, fija ``fecha_envio`` y crea el respaldo a 24 horas."""
    nid, eid = m["notificacion_id"], m["empresa_id"]
    fijar_empresa(conn, eid)
    (restan,) = conn.execute(
        "SELECT count(*) FROM notificaciones.notificacion_destinatario "
        "WHERE notificacion_id = %s AND estado_envio = 'PENDIENTE' AND encolado_en IS NULL",
        (nid,),
    ).fetchone()
    if restan:
        conn.rollback()
        return OTRO_DESPACHADOR
    if n["respaldo"]:
        inicio = ahora + timedelta(hours=cfg.respaldo_horas)
        scheduler.crear_unico(
            ScheduleUnico(
                nombre=nombre_respaldo(nid),
                expresion=horario.expresion_at(inicio, n["zona"]),
                zona=n["zona"],
                cuerpo=cuerpo_respaldo(nid, eid),
                destino=RESPALDO,
            )
        )
    conn.execute(
        "UPDATE notificaciones.notificacion SET fecha_envio = COALESCE(fecha_envio, %s) "
        "WHERE id = %s",
        (ahora, nid),
    )
    conn.commit()
    return DESPACHADA


def procesar(
    conn,
    cfg,
    m: dict[str, Any],
    *,
    sqs,
    scheduler,
    contactos,
    restante_ms: Callable[[], int],
    reloj: Callable[[], datetime] = _ahora_utc,
) -> str:
    fijar_empresa(conn, m["empresa_id"])
    resultado, n = _iniciar(conn, cfg, m, scheduler=scheduler, ahora=reloj())
    conn.commit()
    if resultado is not None or n is None:
        return resultado or IGNORADA
    metrica("despachos")
    while True:
        if restante_ms() < cfg.margen_tiempo_ms:
            _continuar(sqs, cfg, m)
            metrica("despachos_continuados")
            return CONTINUA
        situacion, _ = _bloque(conn, cfg, m, n, sqs=sqs, contactos=contactos, ahora=reloj())
        if situacion == "INTERRUMPIDA":
            metrica("despachos_interrumpidos")
            return INTERRUMPIDA
        if situacion == "VACIO":
            return _finalizar(conn, cfg, m, n, scheduler=scheduler, ahora=reloj())


def manejar(
    evento: dict[str, Any],
    *,
    abrir: Callable[[], Any],
    cfg,
    sqs,
    scheduler,
    contactos,
    restante_ms: Callable[[], int],
    reloj: Callable[[], datetime] = _ahora_utc,
) -> dict[str, list[dict[str, str]]]:
    fallos: list[dict[str, str]] = []
    for r in evento.get("Records", []):
        try:
            m = validar(json.loads(r["body"]))
        except (ValueError, KeyError):
            m = None
        if m is None:  # no se reintenta: reintentar un mensaje mal formado no lo arregla
            metrica("mensajes_invalidos")
            log.warning("mensaje de despacho inválido")
            continue
        conn = None
        try:
            conn = abrir()
            procesar(
                conn, cfg, m, sqs=sqs, scheduler=scheduler, contactos=contactos,
                restante_ms=restante_ms, reloj=reloj,
            )  # fmt: skip
        except Exception as exc:  # noqa: BLE001 - se reintenta (hasta 3 recepciones y DLQ)
            log.warning("falló un despacho: %s", type(exc).__name__)
            metrica("despachos_con_error")
            fallos.append({"itemIdentifier": r["messageId"]})
        finally:
            if conn is not None:
                try:
                    conn.rollback()
                    conn.close()
                except Exception:  # noqa: BLE001, S110
                    pass
    return {"batchItemFailures": fallos}


def lambda_handler(evento, contexto):  # pragma: no cover - requiere AWS
    import boto3
    from notif_comun import bd
    from notif_comun.config import obtener
    from notif_comun.contactos import ContactosHttp
    from notif_comun.scheduler import SchedulerBoto

    cfg = obtener()
    sqs = boto3.client("sqs", region_name=cfg.region, endpoint_url=cfg.aws_endpoint or None)
    return manejar(
        evento,
        abrir=lambda: bd.abrir_conexion(cfg),
        cfg=cfg,
        sqs=sqs,
        scheduler=SchedulerBoto(
            destinos={DESPACHO: cfg.scheduler_despacho_arn, RESPALDO: cfg.scheduler_respaldo_arn},
            rol_arn=cfg.scheduler_rol_arn,
            grupo=cfg.scheduler_grupo,
            region=cfg.region,
            endpoint=cfg.aws_endpoint,
        ),
        contactos=ContactosHttp(cfg.colaboradores_url, bd.secreto_interno(cfg)),
        restante_ms=contexto.get_remaining_time_in_millis,
    )
