"""``worker-cargas`` (WRK-02; design.md §4.7, §8.1; CC-REQ-036, 037, 041, CC-NFR-004).

Procesa una carga confirmada:

1. Descarga el archivo, comprueba su SHA-256 y lo lee con ``excel.lector``.
2. Valida todas las filas en memoria (``excel.validador``), con la detección de repetidos dentro
   del archivo.
3. Aplica las filas en lotes de 200, una transacción por lote. Cada fila va en un ``SAVEPOINT``:
   una fila con error no detiene a las demás. ``UNIQUE (carga_id, numero_fila)`` hace idempotente
   la repetición del mensaje: las filas ya registradas se omiten.
4. Entre lotes revisa si la carga se canceló (COL-22) y se detiene; las filas ya aplicadas se
   conservan.
5. Al terminar pasa la carga a ``TERMINADA`` y borra el archivo de S3 (DS-11).

Regla de negocio (§8.1): ``numero_empleado`` nuevo se crea sin consentimiento de WhatsApp; el
existente se actualiza sin tocar su consentimiento; quien no aparece no cambia. Una celda vacía no
borra un valor (DS-18). ``estatus = BAJA`` da de baja sin borrar; ``ACTIVO`` sobre una baja
existente es un error (reactivar exige consentimiento y se hace desde la ficha).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from cc_common import bitacora
from cc_common.db import transaccion
from sqlalchemy.exc import IntegrityError

from cc_colaboradores.errores import nombre_restriccion
from cc_colaboradores.excel import lector
from cc_colaboradores.excel.modelo import MAX_BYTES, ArchivoInvalido, normalizar
from cc_colaboradores.excel.validador import (
    ErrorFila,
    FilaValida,
    Referencias,
    ValidadorCarga,
    error,
)
from cc_colaboradores.repos import carga as repo_carga
from cc_colaboradores.repos import colaborador as repo
from cc_colaboradores.repos import valor_campo as repo_valor

log = logging.getLogger("cc.worker_cargas")

ZONA_MX = timezone(timedelta(hours=-6))
CODIGO_CELULAR = "celular"
DespuesDeLote = Callable[[int], Awaitable[None]]


class _ErrorFilaCarga(Exception):
    def __init__(self, *errores: ErrorFila) -> None:
        super().__init__(errores[0].codigo)
        self.errores = list(errores)


@dataclass(frozen=True)
class ResultadoFila:
    resultado: str  # NUEVO, ACTUALIZADO o ERROR
    colaborador_id: int | None = None
    errores: tuple[ErrorFila, ...] = ()


def formatear_mensaje(errores: list[ErrorFila] | tuple[ErrorFila, ...]) -> str:
    """Un error por línea: ``CODIGO: mensaje``. Sin valores ni datos personales."""
    return "\n".join(f"{e.codigo}: {e.mensaje}" for e in errores)


def hoy_mx() -> date:
    return datetime.now(ZONA_MX).date()


# ------------------------------------------------------------------ una fila


async def _aplicar_fila(
    conn, cif, *, empresa_id: int, usuario_id: int, carga_id: int, f: FilaValida
):
    d = f.datos
    hash_nuevo = cif.hash_celular(d.celular)
    actual = await repo_carga.existente(conn, d.numero_empleado)
    dueno = await repo.por_hash_celular(conn, hash_nuevo)
    if dueno is not None and (actual is None or dueno != actual["id"]):
        raise _ErrorFilaCarga(error("CELULAR_REPETIDO"))
    if actual is not None and actual["estatus"] == "BAJA" and f.estatus == "ACTIVO":
        raise _ErrorFilaCarga(
            ErrorFila(
                "ESTATUS_INVALIDO",
                "Un colaborador en baja se reactiva desde su ficha (requiere consentimiento).",
            )
        )
    campos_tocados: list[str] = []
    if actual is None:
        colaborador_id = await repo.insertar(
            conn, cif, empresa_id=empresa_id, datos=d, consentimiento=False
        )
        resultado, accion = "NUEVO", "ALTA"
    else:
        colaborador_id = int(actual["id"])
        cambios = {
            "nombres": d.nombres,
            "apellido_paterno": d.apellido_paterno,
            "apellido_materno": d.apellido_materno,
            "organizacion_id": d.organizacion_id,
            "planta_id": d.planta_id,
            "fecha_ingreso": d.fecha_ingreso,
            "puesto": d.puesto,
            "tipo_empleado": d.tipo_empleado,
        }
        await repo.actualizar(conn, colaborador_id, cambios)
        campos_tocados = sorted(cambios)
        if bytes(actual["celular_hash"]) != hash_nuevo:
            await repo.cambiar_celular(
                conn, cif, empresa_id=empresa_id, colaborador_id=colaborador_id, celular=d.celular
            )
            campos_tocados.append(CODIGO_CELULAR)
        resultado, accion = "ACTUALIZADO", "MODIFICACION"
    codigos = await repo_valor.guardar(
        conn, cif, empresa_id=empresa_id, colaborador_id=colaborador_id, valores=f.valores
    )
    detalle = {"carga_id": carga_id}
    if accion == "MODIFICACION":
        detalle["campos"] = sorted([*campos_tocados, *codigos])
    elif codigos:
        detalle["campos"] = sorted(codigos)
    await bitacora.registrar(
        conn,
        empresa_id=empresa_id,
        accion=accion,
        entidad="colaborador",
        entidad_id=colaborador_id,
        colaborador_id=colaborador_id,
        usuario_id=usuario_id,
        detalle=detalle,
    )
    if f.estatus == "BAJA" and (actual is None or actual["estatus"] == "ACTIVO"):
        fecha = max(hoy_mx(), d.fecha_ingreso)
        if await repo.dar_de_baja(conn, colaborador_id, fecha):
            await bitacora.registrar(
                conn,
                empresa_id=empresa_id,
                accion="BAJA",
                entidad="colaborador",
                entidad_id=colaborador_id,
                colaborador_id=colaborador_id,
                usuario_id=usuario_id,
                detalle={"carga_id": carga_id, "estado_anterior": "ACTIVO", "estado_nuevo": "BAJA"},
            )
    return ResultadoFila(resultado, colaborador_id)


async def _procesar_fila(
    conn, cif, *, empresa_id, usuario_id, carga_id, f: FilaValida
) -> ResultadoFila:
    """Aplica una fila dentro de un ``SAVEPOINT``; una falla de la fila no afecta al lote."""
    for intento in (1, 2):
        try:
            async with conn.begin_nested():
                return await _aplicar_fila(
                    conn, cif, empresa_id=empresa_id, usuario_id=usuario_id, carga_id=carga_id, f=f
                )
        except _ErrorFilaCarga as exc:
            return ResultadoFila("ERROR", errores=tuple(exc.errores))
        except IntegrityError as exc:
            nombre = nombre_restriccion(exc) or ""
            if "celular_hash" in nombre:
                return ResultadoFila("ERROR", errores=(error("CELULAR_REPETIDO"),))
            if "numero_empleado" in nombre and intento == 1:
                continue  # otra carga lo creó entre la lectura y el alta: se reintenta como alta
            return ResultadoFila(
                "ERROR", errores=(ErrorFila("ERROR_AL_GUARDAR", "La fila no se pudo guardar."),)
            )
    raise AssertionError("inalcanzable")  # pragma: no cover


# ------------------------------------------------------------------ una carga


async def _cancelar(motor, almacen, *, empresa_id, carga_id, usuario_id, clave, motivo) -> str:
    async with transaccion(motor, empresa_id) as conn:
        if await repo_carga.cerrar(conn, carga_id, estado="CANCELADA", motivo=motivo):
            await bitacora.registrar(
                conn,
                empresa_id=empresa_id,
                accion="CARGA_CANCELADA",
                entidad="carga_colaboradores",
                entidad_id=carga_id,
                usuario_id=usuario_id,
                origen="SISTEMA",
                detalle={"carga_id": carga_id, "motivo": motivo},
            )
    await _borrar(almacen, clave)
    return "CANCELADA"


async def _borrar(almacen, clave: str | None) -> None:
    if not clave:
        return
    try:
        await almacen.borrar(clave)
    except Exception:  # noqa: BLE001 - la regla de ciclo de vida de 7 días cubre el resto
        log.warning("no se pudo borrar el archivo de la carga")


async def procesar_carga(
    motor,
    cif,
    campos_cli,
    almacen,
    *,
    empresa_id: int,
    carga_id: int,
    lote: int = 200,
    despues_de_lote: DespuesDeLote | None = None,
) -> str:
    """Devuelve ``TERMINADA``, ``CANCELADA`` o ``IGNORADA`` (carga inexistente o ya cerrada)."""
    async with transaccion(motor, empresa_id) as conn:
        carga = await repo_carga.obtener(conn, carga_id)
        if (
            carga is None
            or carga["estado"] != "EN_PROCESO"
            or not carga["hash_archivo"]
            or not carga["s3_key"]
        ):
            return "IGNORADA"
        organizaciones, plantas = await repo_carga.referencias(conn)
        registradas = await repo_carga.filas_registradas(conn, carga_id)
    usuario_id, clave = int(carga["usuario_id"]), carga["s3_key"]
    cancelar = lambda motivo: _cancelar(  # noqa: E731
        motor,
        almacen,
        empresa_id=empresa_id,
        carga_id=carga_id,
        usuario_id=usuario_id,
        clave=clave,
        motivo=motivo,
    )

    contenido = await almacen.leer(clave, MAX_BYTES)
    if contenido is None:
        return await cancelar("ARCHIVO_NO_ENCONTRADO")
    if hashlib.sha256(contenido).hexdigest() != carga["hash_archivo"]:
        return await cancelar("ARCHIVO_ALTERADO")
    try:
        archivo = await asyncio.to_thread(lector.leer, contenido)
    except ArchivoInvalido:
        return await cancelar("CARGA_ARCHIVO_INVALIDO")

    definiciones = await campos_cli.definiciones(empresa_id)
    validador = ValidadorCarga(
        definiciones,
        Referencias(
            {normalizar(c): i for c, i in organizaciones}, {normalizar(n): i for n, i in plantas}
        ),
        archivo.columnas,
    )
    validadas = [(fila, validador.validar(fila)) for fila in archivo.filas]
    pendientes = [(fila, r) for fila, r in validadas if fila.numero_fila not in registradas]

    for inicio in range(0, len(pendientes), lote):
        async with transaccion(motor, empresa_id) as conn, cif.transaccion(conn, empresa_id):
            if await repo_carga.estado(conn, carga_id) != "EN_PROCESO":
                await _borrar(almacen, clave)
                return "CANCELADA"
            for fila, r in pendientes[inicio : inicio + lote]:
                numero = fila.valores.get("numero_empleado")
                numero = str(numero).strip().upper()[:30] if numero is not None else None
                if isinstance(r, list):
                    res = ResultadoFila("ERROR", errores=tuple(r))
                else:
                    res = await _procesar_fila(
                        conn,
                        cif,
                        empresa_id=empresa_id,
                        usuario_id=usuario_id,
                        carga_id=carga_id,
                        f=r,
                    )
                await repo_carga.registrar_fila(
                    conn,
                    empresa_id=empresa_id,
                    carga_id=carga_id,
                    numero_fila=fila.numero_fila,
                    numero_empleado=numero,
                    resultado=res.resultado,
                    colaborador_id=res.colaborador_id,
                    mensaje=formatear_mensaje(res.errores) if res.errores else None,
                )
            await repo_carga.actualizar_conteos(conn, carga_id)
        if despues_de_lote is not None:
            await despues_de_lote(inicio // lote + 1)

    async with transaccion(motor, empresa_id) as conn:
        ok, err = await repo_carga.actualizar_conteos(conn, carga_id)
        if await repo_carga.cerrar(conn, carga_id, estado="TERMINADA"):
            await bitacora.registrar(
                conn,
                empresa_id=empresa_id,
                accion="CARGA_TERMINADA",
                entidad="carga_colaboradores",
                entidad_id=carga_id,
                usuario_id=usuario_id,
                origen="SISTEMA",
                detalle={"carga_id": carga_id, "totales": {"filas_ok": ok, "filas_error": err}},
            )
            estado = "TERMINADA"
        else:
            estado = "CANCELADA"
    await _borrar(almacen, clave)
    return estado


# ------------------------------------------------------------------ SQS


async def ejecutar(cfg: Any | None = None) -> None:  # pragma: no cover - requiere AWS
    """Proceso del contenedor: lee ``cola-cargas`` hasta recibir ``SIGTERM`` y termina el mensaje
    en curso antes de salir. El mensaje se borra de SQS solo tras procesarlo."""
    import boto3
    from cc_common.logging import configurar_logging
    from cc_common.recursos import motor_desde_config

    from cc_colaboradores.almacenamiento import almacen_cargas_desde_config
    from cc_colaboradores.campos_cliente import cache_desde_config
    from cc_colaboradores.cifrado import cifrador_desde_config
    from cc_colaboradores.config import ConfigColaboradores
    from cc_colaboradores.main import _secreto_interno_de

    cfg = cfg or ConfigColaboradores()
    configurar_logging("worker-cargas", cfg.ambiente, cfg.log_nivel)
    motor = motor_desde_config(cfg)
    cif = cifrador_desde_config(cfg)
    almacen = almacen_cargas_desde_config(cfg)
    campos = cache_desde_config(cfg, _secreto_interno_de(cfg))
    sqs = boto3.client("sqs", region_name=cfg.region, endpoint_url=cfg.sqs_endpoint or None)
    parar = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, parar.set)
    while not parar.is_set():
        r = await asyncio.to_thread(
            sqs.receive_message,
            QueueUrl=cfg.cola_cargas_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=900,
        )
        for m in r.get("Messages", []):
            cuerpo = json.loads(m["Body"])

            async def extender(_n: int, m=m) -> None:
                await asyncio.to_thread(
                    sqs.change_message_visibility,
                    QueueUrl=cfg.cola_cargas_url,
                    ReceiptHandle=m["ReceiptHandle"],
                    VisibilityTimeout=900,
                )

            try:
                await procesar_carga(
                    motor,
                    cif,
                    campos,
                    almacen,
                    empresa_id=int(cuerpo["empresa_id"]),
                    carga_id=int(cuerpo["carga_id"]),
                    lote=cfg.carga_lote,
                    despues_de_lote=extender,
                )
            except Exception:
                log.exception("falló el procesamiento de una carga")
                continue  # sin borrar: SQS reentrega y la idempotencia evita duplicados
            await asyncio.to_thread(
                sqs.delete_message, QueueUrl=cfg.cola_cargas_url, ReceiptHandle=m["ReceiptHandle"]
            )
    await motor.dispose()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(ejecutar())
