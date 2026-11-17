"""``enviador`` (LAM-02; design.md §4.1, §4.3, §7.3; CC-REQ-085, 104, 111, 116, 157).

Consume ``wa-salida.fifo`` (lotes de 10, ``ReportBatchItemFailures``). Por mensaje:

1. Crea o recupera la fila de ``mensaje_whatsapp`` por ``clave_idempotencia`` (``mensaje_uuid``). Si
   ya salió (o falló), lo ignora: el consumo es idempotente.
2. Resuelve el contacto por INT-COL-05. Un colaborador en BAJA o sin consentimiento no recibe nada
   (queda FALLIDO con su motivo). Excepción: el rechazo del bot (``RECHAZO_BOT``) es una respuesta
   fija a quien escribió, dentro de la ventana, y viaja con el ``wa_id`` de quien escribió.
3. ``VentanaService`` decide texto o plantilla; con la ventana cerrada y sin plantilla, FALLIDO.
4. Guarda ``intentos`` **antes** de llamar a Meta (reduce el riesgo de duplicar, DS-09) y envía.
5. Error permanente: FALLIDO sin reintento (un número no válido publica ``wa.numero_invalido``).
   Transitorio: se reintenta con espera creciente (30 y 120 s) hasta ``max_intentos`` recepciones
   (constancias 2, notificaciones 3) y entonces FALLIDO.

En una cola FIFO, tras un fallo no se procesan los demás mensajes del mismo grupo del lote.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from cc_whatsapp import bd_lambda
from cc_whatsapp.meta import ErrorMeta
from cc_whatsapp.metricas import metrica
from cc_whatsapp.normalizacion import destino_meta
from cc_whatsapp.servicios.ventana_service import PLANTILLA, RECHAZAR, TEXTO, VentanaService

log = logging.getLogger("enviador")

ESPERAS_S = (30, 120)  # tras la 1.ª y la 2.ª recepción
PROPOSITO_RECHAZO = "RECHAZO_BOT"
ENVIADOS = ("ENVIADO", "ENTREGADO", "LEIDO", "FALLIDO", "RECIBIDO")

ENVIADO, FALLIDO, IGNORADO, REINTENTAR = "ENVIADO", "FALLIDO", "IGNORADO", "REINTENTAR"


def normalizar(m: dict[str, Any], cfg) -> dict[str, Any]:
    """Lleva el mensaje de ``constancias`` (``CONSTANCIA_ENLACE``, ``_REENVIO``, ``_ADJUNTO``) a la
    forma común ``MensajeSalida``. El resto ya la trae."""
    tipo = str(m.get("tipo", ""))
    if not tipo.startswith("CONSTANCIA_"):
        return {"max_intentos": 3, "proposito": m.get("origen_tipo"), **m}
    folio = m.get("folio", "")
    enlace = m.get("enlace", "")
    return {
        "mensaje_uuid": m["mensaje_uuid"],
        "origen_tipo": "CONSTANCIA",
        "origen_id": m.get("constancia_id"),
        "colaborador_id": m["colaborador_id"],
        "conversacion_id": m.get("conversacion_id"),
        "empresa_id": m["empresa_id"],
        "tipo": "TEXTO",
        "texto": f"Tu constancia {folio} está lista. Descárgala aquí (un solo uso): {enlace}",
        "plantilla": cfg.plantilla_constancia_lista,
        "variables": [folio, enlace],
        "max_intentos": 2,
        "proposito": "CONSTANCIA",
        "adjunto": tipo == "CONSTANCIA_ADJUNTO",
    }


PROPOSITOS_CONTACTO = {"NOTIFICACION", "CONSTANCIA", "VERIFICACION", "CHAT", "CORREO"}


def _proposito_contacto(m: dict[str, Any]) -> str:
    """Propósito de INT-COL-05: el del mensaje o, si es del bot, "VERIFICACION"."""
    p = m.get("proposito")
    return p if p in PROPOSITOS_CONTACTO else "VERIFICACION"


def _evento(conn, cfg, m, estado: str, motivo: str | None = None) -> None:
    bd_lambda.escribir_evento(
        conn,
        cfg,
        "wa.mensaje_estado",
        {
            "mensaje_uuid": m["mensaje_uuid"],
            "origen_tipo": m["origen_tipo"],
            "origen_id": m.get("origen_id"),
            "colaborador_id": m.get("colaborador_id"),
            "estado": estado,
            "error_codigo": motivo,
            "empresa_id": m["empresa_id"],
        },
        m["empresa_id"],
    )


def _fallido(conn, cfg, fila_id: int, m, motivo: str) -> str:
    conn.execute(
        "UPDATE whatsapp.mensaje_whatsapp SET estado = 'FALLIDO', error_codigo = %s WHERE id = %s",
        (motivo, fila_id),
    )
    _evento(conn, cfg, m, "FALLIDO", motivo)
    metrica("envios_fallidos")
    return FALLIDO


def _fila(conn, m: dict[str, Any]) -> tuple[int, str]:
    r = conn.execute(
        "INSERT INTO whatsapp.mensaje_whatsapp (empresa_id, conversacion_id, colaborador_id, "
        "direccion, tipo, plantilla_meta, clave_idempotencia, estado, origen_tipo, origen_id) "
        "VALUES (%s, %s, %s, 'SALIENTE', %s, %s, %s, 'ENCOLADO', %s, %s) "
        "ON CONFLICT (clave_idempotencia) DO NOTHING RETURNING id, estado",
        (
            m["empresa_id"],
            m.get("conversacion_id"),
            m.get("colaborador_id"),
            m.get("tipo", "TEXTO"),
            m.get("plantilla"),
            m["mensaje_uuid"],
            m["origen_tipo"],
            m.get("origen_id"),
        ),
    ).fetchone()
    if r is None:
        r = conn.execute(
            "SELECT id, estado FROM whatsapp.mensaje_whatsapp WHERE clave_idempotencia = %s",
            (m["mensaje_uuid"],),
        ).fetchone()
    return int(r[0]), r[1]


def _ventana(conn, m: dict[str, Any]) -> tuple[int | None, datetime | None]:
    if m.get("conversacion_id"):
        r = conn.execute(
            "SELECT id, ultimo_mensaje_entrante_at FROM whatsapp.conversacion_whatsapp "
            "WHERE id = %s",
            (m["conversacion_id"],),
        ).fetchone()
    elif m.get("colaborador_id"):
        r = conn.execute(
            "SELECT id, ultimo_mensaje_entrante_at FROM whatsapp.conversacion_whatsapp "
            "WHERE colaborador_id = %s ORDER BY fecha_ultimo_mensaje DESC LIMIT 1",
            (m["colaborador_id"],),
        ).fetchone()
    else:
        r = None
    return (r[0], r[1]) if r else (None, None)


def procesar(
    conn,
    cfg,
    m: dict[str, Any],
    *,
    meta,
    contactos,
    ventana: VentanaService,
    recepciones: int,
    ahora: datetime | None = None,
) -> str:
    bd_lambda.fijar_empresa(conn, m["empresa_id"])
    fila_id, estado = _fila(conn, m)
    if estado in ENVIADOS:
        return IGNORADO

    wa_id = m.get("wa_id")
    if wa_id:  # respuesta del bot a quien escribió
        destino = destino_meta(wa_id)
    else:
        contacto = contactos.resolver(m["empresa_id"], m["colaborador_id"], _proposito_contacto(m))
        if not contacto.get("elegible") or not contacto.get("celular"):
            metrica("envios_bloqueados_elegibilidad")
            motivo = contacto.get("motivo") or "NO_ELEGIBLE"
            return _fallido(conn, cfg, fila_id, m, motivo)
        destino = destino_meta(contacto["celular"])

    if m.get("adjunto"):
        return _fallido(conn, cfg, fila_id, m, "ADJUNTO_NO_SOPORTADO")
    conversacion_id, ultimo = _ventana(conn, m)
    if m.get("entrante_at"):  # respuesta del bot: la ventana abrió con el mensaje que contesta
        entrante = datetime.fromisoformat(m["entrante_at"])
        ultimo = entrante if ultimo is None else max(ultimo, entrante)
    decision = ventana.decidir(
        origen_tipo=m["origen_tipo"],
        tipo_pedido=m.get("tipo", "TEXTO"),
        abierta=ventana.abierta(ultimo, ahora),
        plantilla=m.get("plantilla"),
    )
    if decision.accion == RECHAZAR:
        metrica("ventana_cerrada")
        return _fallido(conn, cfg, fila_id, m, decision.motivo or "VENTANA_CERRADA")

    if decision.accion == PLANTILLA and m.get("variables_nombres") is not None:
        # Plantilla con nombre: Meta exige TODOS los parámetros y con valor. Se comprueba antes de
        # llamar (un dato faltante del colaborador no gasta un envío). Sin valores en el motivo.
        nombres, valores = m["variables_nombres"], m.get("variables") or []
        if len(nombres) != len(valores) or any(
            not isinstance(v, str) or not v.strip() for v in valores
        ):
            metrica("variables_nombradas_incompletas")
            return _fallido(conn, cfg, fila_id, m, "VARIABLE_SIN_VALOR")

    # `intentos` queda guardado antes de llamar a Meta (DS-09).
    conn.execute(
        "UPDATE whatsapp.mensaje_whatsapp SET intentos = intentos + 1, tipo = %s, "
        "conversacion_id = COALESCE(conversacion_id, %s) WHERE id = %s",
        (
            PLANTILLA
            if decision.accion == PLANTILLA
            else ("INTERACTIVO" if m.get("tipo") == "INTERACTIVO" else TEXTO),
            conversacion_id,
            fila_id,
        ),
    )
    conn.commit()
    bd_lambda.fijar_empresa(conn, m["empresa_id"])  # la empresa es local a la transacción
    try:
        if decision.accion == PLANTILLA:
            # El idioma es el de la plantilla (el despachador y el chat lo mandan); constancias y
            # bot no lo traen y usan el de la configuración.
            idioma = m.get("idioma") or cfg.plantilla_idioma
            if m.get("variables_nombres") is not None:  # plantilla con nombre
                wamid = meta.enviar_plantilla(
                    destino, m["plantilla"], idioma, m.get("variables"),
                    variables_nombres=m["variables_nombres"],
                )  # fmt: skip
            else:
                wamid = meta.enviar_plantilla(destino, m["plantilla"], idioma, m.get("variables"))
        elif m.get("tipo") == "INTERACTIVO":
            wamid = meta.enviar_interactivo(destino, m["interactivo"])
        else:
            wamid = meta.enviar_texto(destino, m["texto"])
    except ErrorMeta as e:
        metrica(f"meta_error_{e.codigo or e.motivo}")
        if e.permanente:
            _fallido(conn, cfg, fila_id, m, e.motivo)
            if e.numero_invalido and m.get("colaborador_id") is not None:
                bd_lambda.escribir_evento(
                    conn,
                    cfg,
                    "wa.numero_invalido",
                    {"colaborador_id": m["colaborador_id"], "empresa_id": m["empresa_id"]},
                    m["empresa_id"],
                )
            return FALLIDO
        if recepciones >= int(m.get("max_intentos", 3)):
            return _fallido(conn, cfg, fila_id, m, "INTENTOS_AGOTADOS")
        return REINTENTAR
    conn.execute(
        "UPDATE whatsapp.mensaje_whatsapp SET estado = 'ENVIADO', id_mensaje_proveedor = %s, "
        "error_codigo = NULL WHERE id = %s",
        (wamid, fila_id),
    )
    _evento(conn, cfg, m, "ENVIADO")
    metrica("envios_ok")
    return ENVIADO


def manejar(
    evento: dict[str, Any],
    *,
    abrir: Callable[[], Any],
    cfg,
    meta,
    contactos,
    sqs,
    ventana: VentanaService | None = None,
    ahora: datetime | None = None,
) -> dict[str, list[dict[str, str]]]:
    ventana = ventana or VentanaService(cfg.ventana_horas)
    fallos: list[dict[str, str]] = []
    grupos_con_fallo: set[str | None] = set()
    for r in evento.get("Records", []):
        grupo = (r.get("attributes") or {}).get("MessageGroupId")
        if grupo in grupos_con_fallo:  # FIFO: no se adelanta a un mensaje que va a reintentarse
            fallos.append({"itemIdentifier": r["messageId"]})
            continue
        recepciones = int((r.get("attributes") or {}).get("ApproximateReceiveCount", 1))
        try:
            m = normalizar(json.loads(r["body"]), cfg)
            with abrir() as conn:
                resultado = procesar(
                    conn, cfg, m, meta=meta, contactos=contactos, ventana=ventana,
                    recepciones=recepciones, ahora=ahora,
                )  # fmt: skip
        except Exception as exc:  # noqa: BLE001 - incluye ContactosNoDisponible
            log.warning("falló un envío: %s", type(exc).__name__)
            resultado = REINTENTAR
        if resultado == REINTENTAR:
            grupos_con_fallo.add(grupo)
            fallos.append({"itemIdentifier": r["messageId"]})
            espera = ESPERAS_S[min(recepciones, len(ESPERAS_S)) - 1]
            try:
                sqs.change_message_visibility(
                    QueueUrl=cfg.cola_salida_url,
                    ReceiptHandle=r["receiptHandle"],
                    VisibilityTimeout=espera,
                )
            except Exception:  # noqa: BLE001
                log.warning("no se pudo ajustar la visibilidad")
    return {"batchItemFailures": fallos}


def lambda_handler(evento, _contexto):  # pragma: no cover - requiere AWS
    import boto3
    from cc_whatsapp.config import ConfigWhatsapp
    from cc_whatsapp.contactos import ContactosHttp
    from cc_whatsapp.meta import ClienteMeta
    from cc_whatsapp.recursos import secreto_interno
    from webhook_meta.handler import (
        api_version_efectiva,
        phone_number_id_efectivo,
        secretos_meta,
    )

    cfg = ConfigWhatsapp()
    s = secretos_meta(cfg)
    meta = ClienteMeta(
        base=cfg.meta_api_base,
        version=api_version_efectiva(s, cfg),
        phone_number_id=phone_number_id_efectivo(s, cfg),
        token=s["access_token"],
        timeout_s=cfg.meta_timeout_s,
    )
    sqs = boto3.client("sqs", region_name=cfg.region, endpoint_url=cfg.aws_endpoint or None)
    return manejar(
        evento,
        abrir=lambda: bd_lambda.abrir_conexion(cfg),
        cfg=cfg,
        meta=meta,
        contactos=ContactosHttp(cfg.colaboradores_url, secreto_interno(cfg)),
        sqs=sqs,
    )
