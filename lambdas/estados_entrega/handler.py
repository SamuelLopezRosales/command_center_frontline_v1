"""``estados-entrega`` (LAM-03; design.md §4.4; CC-REQ-114, 118).

Consume ``wa-estados`` (lotes de 10). El estado de un mensaje **solo avanza**: el ``UPDATE`` exige
``rango(estado) < rango(nuevo)``, así que los duplicados y los estados fuera de orden no retroceden
nada. Cada avance escribe ``wa.mensaje_estado`` en el ``outbox``; un ``failed`` por número no válido
escribe además ``wa.numero_invalido``; un cambio de plantilla escribe ``wa.plantilla_estado``.
Un estado de un mensaje desconocido se cuenta y no cambia nada. Devuelve
``batchItemFailures`` con los registros que fallaron.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from cc_whatsapp import bd_lambda
from cc_whatsapp.meta import NUMERO_INVALIDO, PERMANENTES
from cc_whatsapp.metricas import metrica

log = logging.getLogger("estados_entrega")

ESTADOS_META = {
    "sent": "ENVIADO",
    "delivered": "ENTREGADO",
    "read": "LEIDO",
    "failed": "FALLIDO",
}


def _motivo(codigo: str | None) -> str | None:
    if codigo is None:
        return None
    return PERMANENTES.get(codigo, f"META_{codigo}")


def procesar_mensaje(conn, cfg, e: dict[str, Any]) -> str:
    nuevo = ESTADOS_META.get(e.get("estado") or "")
    if nuevo is None:
        metrica("estados_desconocidos")
        return "DESCONOCIDO"
    fila = conn.execute(
        "SELECT id, empresa_id FROM whatsapp.mensaje_por_proveedor(%s)", (e["id"],)
    ).fetchone()
    if fila is None:
        metrica("estados_desconocidos")
        log.info("estado de un mensaje desconocido")  # sin identificadores
        return "DESCONOCIDO"
    mensaje_id, empresa_id = fila
    bd_lambda.fijar_empresa(conn, empresa_id)
    codigo = e.get("error_codigo") if nuevo == "FALLIDO" else None
    r = conn.execute(
        "UPDATE whatsapp.mensaje_whatsapp SET estado = %s, "
        "error_codigo = COALESCE(%s, error_codigo) "
        "WHERE id = %s AND whatsapp.rango_estado_mensaje(estado) "
        "< whatsapp.rango_estado_mensaje(%s) "
        "RETURNING clave_idempotencia, origen_tipo, origen_id, colaborador_id",
        (nuevo, _motivo(codigo), mensaje_id, nuevo),
    ).fetchone()
    if r is None:
        return "SIN_CAMBIO"
    uuid_, origen_tipo, origen_id, colaborador_id = r
    bd_lambda.escribir_evento(
        conn,
        cfg,
        "wa.mensaje_estado",
        {
            "mensaje_uuid": str(uuid_),
            "origen_tipo": origen_tipo,
            "origen_id": origen_id,
            "colaborador_id": colaborador_id,
            "estado": nuevo,
            "error_codigo": _motivo(codigo),
            "empresa_id": empresa_id,
        },
        empresa_id,
    )
    if codigo in NUMERO_INVALIDO and colaborador_id is not None:
        bd_lambda.escribir_evento(
            conn,
            cfg,
            "wa.numero_invalido",
            {"colaborador_id": colaborador_id, "empresa_id": empresa_id},
            empresa_id,
        )
    metrica("estados_procesados")
    return "ACTUALIZADO"


def procesar_plantilla(conn, cfg, e: dict[str, Any]) -> str:
    """Los estados de plantilla son de la cuenta, sin empresa: las plantillas se asocian por
    nombre en `notificaciones`."""
    bd_lambda.escribir_evento(
        conn,
        cfg,
        "wa.plantilla_estado",
        {
            "nombre": e.get("nombre"),
            "estado_meta": e.get("evento"),
            "motivo_rechazo": e.get("motivo"),
        },
        None,
    )
    metrica("estados_procesados")
    return "PLANTILLA"


def procesar(conn, cfg, e: dict[str, Any]) -> str:
    if e.get("clase") == "plantilla":
        return procesar_plantilla(conn, cfg, e)
    return procesar_mensaje(conn, cfg, e)


def manejar(
    evento: dict[str, Any], *, abrir: Callable[[], Any], cfg
) -> dict[str, list[dict[str, str]]]:
    fallos: list[dict[str, str]] = []
    for registro in evento.get("Records", []):
        try:
            e = json.loads(registro["body"])
            with abrir() as conn:  # confirma al salir sin error
                procesar(conn, cfg, e)
        except Exception:
            log.exception("falló un estado")
            fallos.append({"itemIdentifier": registro["messageId"]})
    return {"batchItemFailures": fallos}


def lambda_handler(evento, _contexto):  # pragma: no cover - requiere AWS
    from cc_whatsapp.config import ConfigWhatsapp

    cfg = ConfigWhatsapp()
    return manejar(evento, abrir=lambda: bd_lambda.abrir_conexion(cfg), cfg=cfg)
