"""``worker-pdf`` (WRK-01; design.md §5.6, §8.1; CC-REQ-076, 077, 082, 084, 160).

Atiende un mensaje de ``cola-pdf``:

1. Bloquea la solicitud y la pasa a ``EN_PROCESO``. Una solicitud que ya no está RECIBIDA o
   EN_PROCESO se ignora, así que repetir el mensaje no crea una segunda constancia.
2. Verifica el hash de la versión de plantilla, vuelve a resolver las variables (los datos pudieron
   cambiar desde INT-CON-04) y **reserva el folio** en su propia transacción: un reintento reutiliza
   el folio ya reservado.
3. Renderiza, genera el PDF (en un hilo) y lo sube con su SHA-256 y Object Lock.
4. En **una** transacción guarda el snapshot (los valores sensibles cifrados uno a uno), la
   constancia, el token y el mensaje de entrega en el ``outbox``, la solicitud ``GENERADA`` y la
   bitácora.

Si algo falla, el mensaje vuelve a la cola. Al llegar a ``max_intentos_pdf`` recepciones la
solicitud queda ``FALLIDA`` con ``ERROR_RENDER`` y se emite ``constancia.fallida`` para avisar a RH.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import signal
from typing import Any

from cc_common import bitacora
from cc_common.db import transaccion
from cc_common.errores import ErrorInterno

from cc_constancias import contenido as esquema
from cc_constancias.almacenamiento import clave_constancia
from cc_constancias.entrega.estrategia import Entrega, estrategia_por_modo
from cc_constancias.render import derivadas
from cc_constancias.render.html import DatosRender, renderizar
from cc_constancias.render.pdf import html_a_pdf
from cc_constancias.render.qr import url_verificacion
from cc_constancias.render.resolutor_variables import resolver
from cc_constancias.repos import solicitudes as repo
from cc_constancias.servicios import entrega as servicio_entrega
from cc_constancias.servicios import solicitudes as servicio
from cc_constancias.servicios.vista_previa import _logotipo

log = logging.getLogger("cc.worker_pdf")

ABIERTAS = ("RECIBIDA", "EN_PROCESO")


async def _iniciar(motor, cfg, empresa_id: int, solicitud_id: int) -> dict[str, Any] | None:
    """Pasa a EN_PROCESO y devuelve la solicitud; ``None`` si no hay nada que hacer."""
    async with transaccion(motor, empresa_id) as conn:
        s = await repo.obtener(conn, solicitud_id, bloquear=True)
        if s is None or s["estado"] not in ABIERTAS:
            return None
        if s["version_plantilla_id"] is None:
            await servicio.registrar_fallo(
                conn,
                cfg,
                empresa_id=empresa_id,
                solicitud=s,
                motivo="SIN_PLANTILLA",
                desde=ABIERTAS,
            )
            return None
        if s["estado"] == "RECIBIDA":
            await repo.cambiar_estado(conn, solicitud_id, "EN_PROCESO", desde=("RECIBIDA",))
        return s


async def _folio(motor, empresa_id: int, solicitud_id: int, anio: int) -> str:
    async with transaccion(motor, empresa_id) as conn:
        await repo.obtener(conn, solicitud_id, bloquear=True)
        return await repo.reservar_folio(conn, solicitud_id, anio)


def _snapshot(r, cifrador, *, empresa_id: int, solicitud_id: int, version: int, plantilla_id: int):
    """Valores usados; los sensibles van cifrados, cada uno ligado a su solicitud y variable."""
    sensibles = set(r.sensibles_usadas)
    valores: dict[str, Any] = {}
    for nombre, valor in r.valores.items():
        if nombre in sensibles:
            blob = cifrador.cifrar(
                valor, empresa_id=empresa_id, registro=f"{solicitud_id}:{nombre}"
            )
            valores[nombre] = {"cifrado": base64.b64encode(blob).decode("ascii")}
        else:
            valores[nombre] = valor
    return {
        "plantilla_id": plantilla_id,
        "version": version,
        "factores_version": r.factores_version,
        "valores": valores,
    }


async def procesar_solicitud(
    motor,
    cfg,
    *,
    almacen,
    almacen_constancias,
    cifrador,
    campos,
    colaboradores,
    cargador_logotipo,
    empresa_id: int,
    solicitud_id: int,
    generar_pdf=html_a_pdf,
    ahora=None,
) -> str:
    """Devuelve ``GENERADA``, ``FALLIDA`` o ``IGNORADA``. Una falla técnica se propaga."""
    s = await _iniciar(motor, cfg, empresa_id, solicitud_id)
    if s is None:
        return "IGNORADA"
    version, contenido = await servicio.variables_de_version(
        almacen, motor, empresa_id, s["version_plantilla_id"]
    )
    anio = derivadas.hoy_en_mexico(ahora).year
    folio = await _folio(motor, empresa_id, solicitud_id, anio)
    codigo = secrets.token_urlsafe(16)
    definiciones = await campos.definiciones(empresa_id)
    r = await resolver(
        colaboradores,
        empresa_id=empresa_id,
        colaborador_id=s["colaborador_id"],
        variables=esquema.variables_usadas(contenido),
        definiciones=definiciones,
        sistema={"folio": folio, "qr_verificacion": url_verificacion(cfg.dominio, codigo)},
        ahora=ahora,
    )
    if r.faltantes or r.desconocidas:  # los datos cambiaron desde INT-CON-04
        async with transaccion(motor, empresa_id) as conn:
            await servicio.registrar_fallo(
                conn, cfg, empresa_id=empresa_id, solicitud=s, motivo="CAMPOS_FALTANTES",
                desde=ABIERTAS, campos=[*r.desconocidas, *r.faltantes],
            )  # fmt: skip
        return "FALLIDA"
    resumen = await colaboradores.resumen(empresa_id, s["colaborador_id"])
    numero_empleado = resumen.get("numero_empleado")
    if not numero_empleado:
        raise ErrorInterno("SIN_NUMERO_EMPLEADO", "No fue posible obtener el colaborador.")
    logotipo = None
    if esquema.usa_logotipo(contenido):
        logotipo = await _logotipo(
            colaboradores, cargador_logotipo, empresa_id, s["colaborador_id"]
        )
    html = renderizar(
        contenido,
        DatosRender(
            valores=r.valores,
            folio=folio,
            codigo_verificacion=codigo,
            dominio=cfg.dominio,
            logotipo_data_uri=logotipo,
            vista_previa=False,
        ),
    )
    pdf = await asyncio.to_thread(generar_pdf, html)
    huella = hashlib.sha256(pdf).hexdigest()
    clave = clave_constancia(empresa_id, anio, folio)
    await almacen_constancias.guardar_pdf(clave, pdf, huella)

    estrategia = estrategia_por_modo(cfg.modo_entrega)
    async with transaccion(motor, empresa_id) as conn, cifrador.transaccion(conn, empresa_id):
        actual = await repo.obtener(conn, solicitud_id, bloquear=True)
        if actual is None or actual["estado"] != "EN_PROCESO":
            return "IGNORADA"
        constancia_id = await repo.insertar_constancia(
            conn,
            empresa_id=empresa_id,
            solicitud=s,
            version_id=s["version_plantilla_id"],
            folio=folio,
            pdf_clave=clave,
            pdf_hash=huella,
            snapshot=_snapshot(
                r,
                cifrador,
                empresa_id=empresa_id,
                solicitud_id=solicitud_id,
                version=version["numero"],
                plantilla_id=version["plantilla_id"],
            ),
            numero_empleado=str(numero_empleado),
            codigo=codigo,
        )
        await servicio_entrega.preparar_entrega(
            conn,
            cfg,
            estrategia,
            Entrega(
                empresa_id=empresa_id,
                constancia_id=constancia_id,
                solicitud_id=solicitud_id,
                colaborador_id=s["colaborador_id"],
                conversacion_id=s["conversacion_id"],
                folio=folio,
                pdf_s3_key=clave,
            ),
            generado_por="BOT",
        )
        await repo.cambiar_estado(conn, solicitud_id, "GENERADA", desde=("EN_PROCESO",))
        await bitacora.registrar(
            conn,
            empresa_id=empresa_id,
            accion="CONSTANCIA_GENERADA",
            entidad="constancia_generada",
            entidad_id=constancia_id,
            colaborador_id=s["colaborador_id"],
            origen="SISTEMA",
            detalle={
                "folio": folio,
                "solicitud_id": solicitud_id,
                "plantilla_id": version["plantilla_id"],
                "version": version["numero"],
            },
        )
    return "GENERADA"


async def atender(
    motor, cfg, *, recepciones: int, empresa_id: int, solicitud_id: int, **recursos
) -> str:
    """Procesa un mensaje. Si falla y ya se agotaron las recepciones, marca FALLIDA
    (``ERROR_RENDER``) y devuelve ``FALLIDA`` (el mensaje se borra); si no, relanza para que SQS
    lo reentregue."""
    try:
        return await procesar_solicitud(
            motor, cfg, empresa_id=empresa_id, solicitud_id=solicitud_id, **recursos
        )
    except Exception:
        log.exception("falló la generación de una constancia")
        if recepciones < cfg.max_intentos_pdf:
            raise
    async with transaccion(motor, empresa_id) as conn:
        s = await repo.obtener(conn, solicitud_id, bloquear=True)
        if s is not None:
            await servicio.registrar_fallo(
                conn, cfg, empresa_id=empresa_id, solicitud=s, motivo="ERROR_RENDER", desde=ABIERTAS
            )
    return "FALLIDA"


async def ejecutar(cfg: Any | None = None) -> None:  # pragma: no cover - requiere AWS
    """Proceso del contenedor: lee ``cola-pdf`` hasta recibir ``SIGTERM`` y termina el mensaje en
    curso antes de salir. El mensaje se borra de SQS solo tras procesarlo."""
    import boto3
    from cc_common.logging import configurar_logging
    from cc_common.recursos import motor_desde_config

    from cc_constancias.almacenamiento import (
        almacen_constancias_desde_config,
        almacen_desde_config,
    )
    from cc_constancias.cifrado import cifrador_desde_config
    from cc_constancias.clientes import CamposHttp, ColaboradoresHttp
    from cc_constancias.config import ConfigConstancias
    from cc_constancias.main import _secreto_interno_de
    from cc_constancias.render.logotipo import CargadorLogotipo

    cfg = cfg or ConfigConstancias()
    configurar_logging("worker-pdf", cfg.ambiente, cfg.log_nivel)
    from cc_common.internal_client import ClienteInterno

    secreto = _secreto_interno_de(cfg)
    motor = motor_desde_config(cfg)
    almacen = almacen_desde_config(cfg)
    recursos = {
        "almacen": almacen,
        "almacen_constancias": almacen_constancias_desde_config(cfg),
        "cifrador": cifrador_desde_config(cfg),
        "campos": CamposHttp(
            ClienteInterno(cfg.campos_url, servicio="constancias", secreto=secreto)
        ),
        "colaboradores": ColaboradoresHttp(
            ClienteInterno(cfg.colaboradores_url, servicio="constancias", secreto=secreto)
        ),
        "cargador_logotipo": CargadorLogotipo(
            almacen, ttl_s=cfg.logotipo_cache_segundos, maximo=cfg.logotipo_max_bytes
        ),
    }
    sqs = boto3.client("sqs", region_name=cfg.region, endpoint_url=cfg.aws_endpoint or None)
    parar = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, parar.set)
    while not parar.is_set():
        r = await asyncio.to_thread(
            sqs.receive_message,
            QueueUrl=cfg.cola_pdf_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=120,
            AttributeNames=["ApproximateReceiveCount"],
        )
        for m in r.get("Messages", []):
            cuerpo = json.loads(m["Body"])
            try:
                await atender(
                    motor,
                    cfg,
                    recepciones=int(m["Attributes"]["ApproximateReceiveCount"]),
                    empresa_id=int(cuerpo["empresa_id"]),
                    solicitud_id=int(cuerpo["solicitud_id"]),
                    **recursos,
                )
            except Exception:  # noqa: S112
                continue  # sin borrar: SQS reentrega
            await asyncio.to_thread(
                sqs.delete_message, QueueUrl=cfg.cola_pdf_url, ReceiptHandle=m["ReceiptHandle"]
            )
    await motor.dispose()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(ejecutar())
