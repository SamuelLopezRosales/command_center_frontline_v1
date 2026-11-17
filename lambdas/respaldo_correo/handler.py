"""``respaldo-correo`` (LAM-06; design.md §4.5, §6.4; CC-REQ-110, 113, 157; DS-10).

Consume ``notif-respaldo`` (EventBridge Scheduler a las 24 horas del envío, o el conciliador).
Cuerpo: ``{"notificacion_id": 12, "empresa_id": 3}``.

**Respaldo.** Solo para notificaciones ``ENVIANDO``, ``COMPLETADA`` o ``CON_FALLAS`` con
``respaldo_correo``; otra cosa (``CANCELADA``...) se ignora. Toma, en bloques con
``FOR UPDATE SKIP LOCKED``, los destinatarios ``ENVIADO`` o ``FALLIDO`` (nunca los ``ENTREGADO``,
``LEIDO`` ni ``RESPONDIO``) con ``encolado_en`` de hace 24 horas o más y sin
``respaldo_enviado_en``. Pide el correo a ``contactos:resolver`` con propósito ``CORREO`` (exige
ACTIVO y consentimiento vigente) junto con las variables no sensibles de la plantilla.

* **Con correo**: envía por SES el texto de la plantilla con las variables ya resueltas y registra
  ``canal_usado = 'CORREO'`` y ``respaldo_enviado_en``. El estado del destinatario no cambia (un
  ``FALLIDO`` de WhatsApp sigue ``FALLIDO``: el correo no es una entrega confirmada).
* **Sin correo** (o no elegible: ``SIN_CORREO``, ``ESTATUS_BAJA``, ``SIN_CONSENTIMIENTO``...): pasa
  a ``FALLIDO`` con ``motivo_fallo`` (si ya era ``FALLIDO`` con un motivo, conserva el original) y
  se marca atendido (``respaldo_enviado_en``: significa "respaldo resuelto", haya salido o no). Se
  avisa a RH por SNS ``alertas-rh`` con ``{tipo, notificacion_id, empresa_id, cantidad, motivos}``:
  **solo ids y motivos**, sin nombres, correos ni celulares.
* **Horario**: fuera de 08:00 a 20:00 (zona de la notificación) no envía; crea el schedule
  ``cc-notif-respaldo-{id}-d{AAAAMMDD}`` para el siguiente inicio y termina.
* **Idempotencia**: lo atendido no se vuelve a tomar; repetir el mensaje no reenvía. Garantía
  *al menos una vez*: un fallo del proceso entre el envío de SES y la confirmación del bloque
  (50 destinatarios) puede duplicar el correo de ese bloque.
* Un error transitorio de SES o de `colaboradores` confirma lo ya hecho y reintenta el mensaje.

**Rebotes y quejas (contrato).** El conjunto de configuración de SES publica sus eventos en un
tema de SNS suscrito a ``notif-respaldo`` (la Lambda desenvuelve el sobre de SNS). Se consume el
evento de SES (*event publishing*)::

    {"eventType": "Bounce" | "Complaint" | "Delivery" | ...,
     "bounce": {"bounceType": "Permanent" | "Transient" | "Undetermined"},
     "mail": {"tags": {"notificacion_id": ["12"], "destinatario_id": ["34"], "empresa_id": ["3"]}}}

Un ``Bounce`` permanente o un ``Complaint`` cuenta ``rebotes`` y marca al destinatario ``FALLIDO``
con ``motivo_fallo`` ``CORREO_REBOTADO`` o ``CORREO_QUEJA`` (solo si aún no entregó por WhatsApp:
``rango_estado_envio <= FALLIDO``) y avisa a RH. Un rebote transitorio solo cuenta la métrica.

Métricas: ``respaldos_enviados``, ``rebotes``, ``sin_correo``.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from notif_comun import horario, plantilla
from notif_comun.bd import fijar_empresa
from notif_comun.metricas import metrica
from notif_comun.scheduler import (
    RESPALDO,
    ScheduleUnico,
    cuerpo_respaldo,
    nombre_respaldo,
)

from respaldo_correo.correo import CorreoRechazado, CorreoTransitorio

log = logging.getLogger("respaldo_correo")

ENVIADOS_O_FALLIDOS = ("ENVIADO", "FALLIDO")
PIE = "\n\nEste correo respalda el aviso que se le envió por WhatsApp."

ENVIADO, DIFERIDO, IGNORADO = "ENVIADO", "DIFERIDO", "IGNORADO"


def _ahora_utc() -> datetime:
    return datetime.now(UTC)


def _entero(valor: Any) -> int | None:
    try:
        return int(valor[0] if isinstance(valor, list) else valor)
    except (TypeError, ValueError, IndexError):
        return None


def desenvolver(cuerpo: Any) -> Any:
    """El mensaje real: desenvuelve el sobre de SNS (``{"Type": "Notification", ...}``)."""
    if isinstance(cuerpo, dict) and cuerpo.get("Type") == "Notification" and "Message" in cuerpo:
        try:
            return json.loads(cuerpo["Message"])
        except (TypeError, ValueError):
            return None
    return cuerpo


def _alerta(sns, cfg, tipo: str, nid: int, eid: int, cantidad: int, motivos: dict[str, int]):
    """Aviso a RH: solo identificadores y motivos (CC-REQ-162)."""
    if not cfg.alertas_topic_arn:
        metrica("alertas_sin_destino")
        return
    sns.publish(
        TopicArn=cfg.alertas_topic_arn,
        Subject="Respaldo por correo de una notificación",
        Message=json.dumps(
            {
                "tipo": tipo,
                "notificacion_id": nid,
                "empresa_id": eid,
                "cantidad": cantidad,
                "motivos": motivos,
            },
            separators=(",", ":"),
        ),
    )
    metrica("alertas_rh")


def _cargar(conn, nid: int) -> dict[str, Any] | None:
    r = conn.execute(
        "SELECT n.estado, n.zona_horaria, n.respaldo_correo, n.variables_json, "
        "p.texto_con_variables FROM notificaciones.notificacion n "
        "LEFT JOIN notificaciones.plantilla_mensaje p ON p.id = n.plantilla_mensaje_id "
        "WHERE n.id = %s",
        (nid,),
    ).fetchone()
    if r is None:
        return None
    return {
        "estado": r[0],
        "zona": r[1],
        "respaldo": r[2],
        "variables_json": r[3],
        "texto": r[4] or "",
    }


def _bloque(conn, cfg, m, n, *, contactos, correo, sns, ahora: datetime) -> tuple[int, bool]:
    """Un bloque. Devuelve ``(procesados, hubo_error_transitorio)``."""
    nid, eid = m["notificacion_id"], m["empresa_id"]
    fijar_empresa(conn, eid)
    filas = conn.execute(
        "SELECT id, colaborador_id FROM notificaciones.notificacion_destinatario "
        "WHERE notificacion_id = %s AND estado_envio = ANY(%s) AND respaldo_enviado_en IS NULL "
        "AND encolado_en IS NOT NULL AND encolado_en <= %s ORDER BY id LIMIT %s "
        "FOR UPDATE SKIP LOCKED",
        (nid, list(ENVIADOS_O_FALLIDOS), ahora - timedelta(hours=cfg.respaldo_horas),
         cfg.respaldo_bloque),
    ).fetchall()  # fmt: skip
    if not filas:
        conn.rollback()
        return 0, False
    campos = plantilla.campos_colaborador(n["variables_json"])
    try:
        resueltos = contactos.resolver(eid, [f[1] for f in filas], "CORREO", campos)
    except Exception:
        conn.rollback()
        raise

    con_correo, sin_correo = [], []
    for dest_id, colaborador_id in filas:
        c = resueltos.get(colaborador_id) or {}
        if c.get("elegible") and c.get("correo"):
            con_correo.append((dest_id, colaborador_id, c))
        else:
            motivo = (c.get("motivo") if not c.get("elegible") else None) or "SIN_CORREO"
            sin_correo.append((dest_id, motivo))

    if sin_correo:  # primero el aviso: si falla, se revierte el bloque y no se envió nada
        motivos = dict(Counter(m_ for _, m_ in sin_correo))
        try:
            _alerta(sns, cfg, "RESPALDO_SIN_CORREO", nid, eid, len(sin_correo), motivos)
        except Exception:
            conn.rollback()
            raise
        for dest_id, motivo in sin_correo:
            conn.execute(
                "UPDATE notificaciones.notificacion_destinatario SET estado_envio = 'FALLIDO', "
                "motivo_fallo = CASE WHEN estado_envio = 'FALLIDO' AND motivo_fallo IS NOT NULL "
                "THEN motivo_fallo ELSE %s END, respaldo_enviado_en = %s, fecha_estado = %s "
                "WHERE id = %s",
                (motivo, ahora, ahora, dest_id),
            )
        metrica("sin_correo", len(sin_correo))

    enviados = rechazados = 0
    transitorio = False
    for dest_id, _colaborador_id, c in con_correo:
        variables = plantilla.armar_variables(n["variables_json"], c.get("valores"), n["texto"])
        texto = plantilla.renderizar(n["texto"], variables) + PIE
        try:
            correo.enviar(
                destino=c["correo"],
                asunto=cfg.ses_asunto,
                texto=texto,
                etiquetas={
                    "notificacion_id": str(nid),
                    "destinatario_id": str(dest_id),
                    "empresa_id": str(eid),
                },
            )
        except CorreoRechazado:
            rechazados += 1
            conn.execute(
                "UPDATE notificaciones.notificacion_destinatario SET estado_envio = 'FALLIDO', "
                "motivo_fallo = 'CORREO_RECHAZADO', respaldo_enviado_en = %s, fecha_estado = %s "
                "WHERE id = %s",
                (ahora, ahora, dest_id),
            )
            continue
        except CorreoTransitorio:
            transitorio = True
            break
        enviados += 1
        conn.execute(
            "UPDATE notificaciones.notificacion_destinatario SET canal_usado = 'CORREO', "
            "respaldo_enviado_en = %s, fecha_estado = %s WHERE id = %s",
            (ahora, ahora, dest_id),
        )
    conn.commit()
    if enviados:
        metrica("respaldos_enviados", enviados)
    if rechazados:
        metrica("correos_rechazados", rechazados)
    return enviados + rechazados + len(sin_correo), transitorio


def procesar(
    conn, cfg, m: dict[str, Any], *, contactos, correo, sns, scheduler, ahora: datetime
) -> str:
    nid, eid = m["notificacion_id"], m["empresa_id"]
    fijar_empresa(conn, eid)
    n = _cargar(conn, nid)
    conn.rollback()
    if (
        n is None
        or not n["respaldo"]
        or n["estado"] not in ("ENVIANDO", "COMPLETADA", "CON_FALLAS")
    ):
        metrica("respaldos_ignorados")
        return IGNORADO
    if not horario.dentro_de_horario(ahora, n["zona"], cfg.horario_inicio, cfg.horario_fin):
        inicio = horario.siguiente_inicio(ahora, n["zona"], cfg.horario_inicio, cfg.horario_fin)
        scheduler.crear_unico(
            ScheduleUnico(
                nombre=nombre_respaldo(nid, "d" + inicio.strftime("%Y%m%d")),
                expresion=horario.expresion_at(inicio, n["zona"]),
                zona=n["zona"],
                cuerpo=cuerpo_respaldo(nid, eid),
                destino=RESPALDO,
            )
        )
        metrica("respaldos_diferidos")
        return DIFERIDO
    while True:
        procesados, transitorio = _bloque(
            conn, cfg, m, n, contactos=contactos, correo=correo, sns=sns, ahora=ahora
        )
        if transitorio:
            raise CorreoTransitorio("SES no disponible")  # lo hecho ya se confirmó
        if procesados == 0:
            return ENVIADO


def procesar_rebote(conn, cfg, ev: dict[str, Any], *, sns, ahora: datetime) -> str:
    tipo = ev.get("eventType")
    if tipo not in ("Bounce", "Complaint"):
        return IGNORADO
    permanente = tipo == "Complaint" or (ev.get("bounce") or {}).get("bounceType") == "Permanent"
    metrica("rebotes" if tipo == "Bounce" else "quejas")
    if not permanente:
        return IGNORADO
    etiquetas = (ev.get("mail") or {}).get("tags") or {}
    nid = _entero(etiquetas.get("notificacion_id"))
    did = _entero(etiquetas.get("destinatario_id"))
    eid = _entero(etiquetas.get("empresa_id"))
    if None in (nid, did, eid):
        metrica("rebotes_sin_etiquetas")
        return IGNORADO
    motivo = "CORREO_QUEJA" if tipo == "Complaint" else "CORREO_REBOTADO"
    fijar_empresa(conn, eid)
    r = conn.execute(
        "UPDATE notificaciones.notificacion_destinatario SET estado_envio = 'FALLIDO', "
        "motivo_fallo = %s, fecha_estado = %s WHERE id = %s AND notificacion_id = %s "
        "AND notificaciones.rango_estado_envio(estado_envio) <= "
        "notificaciones.rango_estado_envio('FALLIDO') AND motivo_fallo IS DISTINCT FROM %s "
        "RETURNING id",
        (motivo, ahora, did, nid, motivo),
    ).fetchone()
    if r is not None:
        _alerta(sns, cfg, "RESPALDO_REBOTE", nid, eid, 1, {motivo: 1})
    conn.commit()
    return ENVIADO if r is not None else IGNORADO


def manejar(
    evento: dict[str, Any],
    *,
    abrir: Callable[[], Any],
    cfg,
    contactos,
    correo,
    sns,
    scheduler,
    reloj: Callable[[], datetime] = _ahora_utc,
) -> dict[str, list[dict[str, str]]]:
    fallos: list[dict[str, str]] = []
    for r in evento.get("Records", []):
        try:
            cuerpo = desenvolver(json.loads(r["body"]))
        except (ValueError, KeyError):
            cuerpo = None
        es_evento_ses = isinstance(cuerpo, dict) and "eventType" in cuerpo
        nid = _entero(cuerpo.get("notificacion_id")) if isinstance(cuerpo, dict) else None
        eid = _entero(cuerpo.get("empresa_id")) if isinstance(cuerpo, dict) else None
        if not es_evento_ses and (nid is None or eid is None):
            metrica("mensajes_invalidos")  # no se reintenta: no se arregla solo
            log.warning("mensaje de respaldo inválido")
            continue
        conn = None
        try:
            conn = abrir()
            if es_evento_ses:
                procesar_rebote(conn, cfg, cuerpo, sns=sns, ahora=reloj())
            else:
                procesar(
                    conn, cfg, {"notificacion_id": nid, "empresa_id": eid},
                    contactos=contactos, correo=correo, sns=sns, scheduler=scheduler,
                    ahora=reloj(),
                )  # fmt: skip
        except Exception as exc:  # noqa: BLE001 - se reintenta (3 recepciones y DLQ)
            log.warning("falló un respaldo: %s", type(exc).__name__)
            metrica("respaldos_con_error")
            fallos.append({"itemIdentifier": r["messageId"]})
        finally:
            if conn is not None:
                try:
                    conn.rollback()
                    conn.close()
                except Exception:  # noqa: BLE001, S110
                    pass
    return {"batchItemFailures": fallos}


def lambda_handler(evento, _contexto):  # pragma: no cover - requiere AWS
    import boto3
    from notif_comun import bd
    from notif_comun.config import obtener
    from notif_comun.contactos import ContactosHttp
    from notif_comun.scheduler import DESPACHO, SchedulerBoto

    from respaldo_correo.correo import CorreoSes

    cfg = obtener()
    kw = {"region_name": cfg.region, "endpoint_url": cfg.aws_endpoint or None}
    return manejar(
        evento,
        abrir=lambda: bd.abrir_conexion(cfg),
        cfg=cfg,
        contactos=ContactosHttp(cfg.colaboradores_url, bd.secreto_interno(cfg)),
        correo=CorreoSes(boto3.client("ses", **kw), cfg.ses_origen, cfg.ses_config_set),
        sns=boto3.client("sns", **kw),
        scheduler=SchedulerBoto(
            destinos={DESPACHO: cfg.scheduler_despacho_arn, RESPALDO: cfg.scheduler_respaldo_arn},
            rol_arn=cfg.scheduler_rol_arn,
            grupo=cfg.scheduler_grupo,
            region=cfg.region,
            endpoint=cfg.aws_endpoint,
        ),
    )
