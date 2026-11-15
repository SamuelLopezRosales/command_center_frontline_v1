"""``worker-whatsapp-entrada`` (WRK-03; design.md §4.1, §4.7, §7; CC-REQ-071 a 076, 091).

Consume ``wa-entrada.fifo``: los mensajes de un mismo número llegan en orden (grupo = SHA-256 del
número) y se procesan uno por uno. Si un mensaje falla, **no** se procesan los que le siguen en el
lote (se perdería el orden): SQS los reentrega. Un mensaje se borra solo tras procesarse; repetirlo
no duplica efectos porque el ``wamid`` se registra en la misma transacción (``procesar``).

Cada minuto cierra las conversaciones inactivas y depura los contadores viejos.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
from typing import Any

from cc_whatsapp.bot import conversacion, inactividad
from cc_whatsapp.bot.contexto import Contexto, Mensaje

log = logging.getLogger("cc.worker_entrada")

INTERVALO_MANTENIMIENTO_S = 60


async def atender_lote(
    sqs: Any,
    cola_url: str,
    ctx: Contexto,
    *,
    espera_s: int = 0,
    maximo: int = 10,
    visibilidad_s: int = 60,
) -> int:
    """Una lectura de la cola. Devuelve cuántos mensajes se procesaron y borraron."""
    r = await asyncio.to_thread(
        sqs.receive_message,
        QueueUrl=cola_url,
        MaxNumberOfMessages=maximo,
        WaitTimeSeconds=espera_s,
        VisibilityTimeout=visibilidad_s,
    )
    hechos = 0
    for m in r.get("Messages", []):
        try:
            await conversacion.procesar(ctx, Mensaje.de(json.loads(m["Body"])))
        except Exception:
            log.exception("falló un mensaje de entrada; se detiene el lote para conservar el orden")
            break
        await asyncio.to_thread(
            sqs.delete_message, QueueUrl=cola_url, ReceiptHandle=m["ReceiptHandle"]
        )
        hechos += 1
    return hechos


async def mantenimiento(ctx: Contexto) -> None:
    try:
        cerradas = await inactividad.cerrar_inactivas(ctx)
        await inactividad.depurar_contadores(ctx)
        if cerradas:
            log.info("conversaciones cerradas por inactividad: %d", cerradas)
    except Exception:
        log.exception("falló el mantenimiento de conversaciones")


async def ejecutar(cfg: Any | None = None) -> None:  # pragma: no cover - requiere AWS
    """Proceso del contenedor: lee ``wa-entrada.fifo`` hasta recibir ``SIGTERM``."""
    import boto3
    from cc_common.internal_client import ClienteInterno
    from cc_common.logging import configurar_logging
    from cc_common.recursos import leer_secreto, motor_desde_config

    from cc_whatsapp.clientes import ColaboradoresHttp, ConstanciasHttp
    from cc_whatsapp.config import ConfigWhatsapp
    from cc_whatsapp.recursos import secreto_interno
    from cc_whatsapp.servicios.alertas import AlertasNulas, AlertasSns

    cfg = cfg or ConfigWhatsapp()
    configurar_logging("worker-whatsapp-entrada", cfg.ambiente, cfg.log_nivel)
    secreto = secreto_interno(cfg)
    opciones = {"region_name": cfg.region, "endpoint_url": cfg.aws_endpoint or None}
    ctx = Contexto(
        cfg=cfg,
        motor=motor_desde_config(cfg),
        colaboradores=ColaboradoresHttp(
            ClienteInterno(cfg.colaboradores_url, servicio="whatsapp", secreto=secreto)
        ),
        constancias=ConstanciasHttp(
            ClienteInterno(cfg.constancias_url, servicio="whatsapp", secreto=secreto)
        ),
        alertas=AlertasSns(boto3.client("sns", **opciones), cfg.alertas_topic_arn)
        if cfg.alertas_topic_arn
        else AlertasNulas(),
        llave_codigos=leer_secreto(cfg.codigo_hmac_secreto_id, cfg.region).encode(),
    )
    sqs = boto3.client("sqs", **opciones)
    parar = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, parar.set)
    ultimo = 0.0
    while not parar.is_set():
        if time.monotonic() - ultimo >= INTERVALO_MANTENIMIENTO_S:
            await mantenimiento(ctx)
            ultimo = time.monotonic()
        await atender_lote(sqs, cfg.cola_entrada_url, ctx, espera_s=20)
    await ctx.motor.dispose()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(ejecutar())
