"""Carga masiva, lado API (COL-16 a COL-22; design.md §3.3, §4.7; CC-REQ-034 a 040).

Flujo: ``iniciar`` crea la carga ``EN_PROCESO`` y una URL de subida firmada (15 minutos);
``confirmar`` verifica el objeto, calcula el SHA-256, valida la estructura y el límite de filas y
escribe el mensaje de ``cola-cargas`` en el ``outbox``; el ``worker-cargas`` hace el resto.

Una carga que no se confirma en 1 hora se cancela con motivo ``NO_CONFIRMADA``. El worker no puede
enumerar empresas (RLS), así que la cancelación se aplica a la empresa de quien llama, al inicio de
cada operación de cargas (hallazgo de T-204).
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from cc_common import bitacora, outbox
from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.db import transaccion
from cc_common.errores import ErrorCampo, ErrorConflicto, ErrorNoEncontrado, ErrorValidacion

from cc_colaboradores.campos_cliente import DefinicionCampo
from cc_colaboradores.excel import generador, lector
from cc_colaboradores.excel.modelo import ArchivoInvalido
from cc_colaboradores.repos import carga as repo
from cc_colaboradores.repos import catalogos as repo_catalogos

log = logging.getLogger("cc.cargas")

CONTENT_TYPE_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NOMBRE_ARCHIVO_MAX = 200
PREFIJOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _fila_carga_estado_invalido(estado: str) -> ErrorConflicto:
    return ErrorConflicto(
        "ESTADO_INVALIDO",
        "La operación no aplica al estado actual de la carga.",
        detalle={"estado_actual": estado},
    )


async def _borrar(almacen, clave: str | None) -> None:
    if not clave:
        return
    try:
        await almacen.borrar(clave)
    except Exception:  # noqa: BLE001 - la regla de ciclo de vida de 7 días cubre el resto
        log.warning("no se pudo borrar el archivo de una carga")


async def expirar_vencidas(motor, almacen, cfg, empresa_id: int) -> int:
    """Cancela las cargas de la empresa sin confirmar tras ``carga_sin_confirmar_segundos``."""
    async with transaccion(motor, empresa_id) as conn:
        vencidas = await repo.cancelar_vencidas(conn, float(cfg.carga_sin_confirmar_segundos))
        for v in vencidas:
            await bitacora.registrar(
                conn,
                empresa_id=empresa_id,
                accion="CARGA_CANCELADA",
                entidad="carga_colaboradores",
                entidad_id=v["id"],
                usuario_id=v["usuario_id"],
                origen="SISTEMA",
                detalle={"carga_id": v["id"], "motivo": "NO_CONFIRMADA"},
            )
    for v in vencidas:
        await _borrar(almacen, v["s3_key"])
    return len(vencidas)


# ------------------------------------------------------------------ COL-16


async def plantilla(motor, campos_cli, u: UsuarioActual) -> bytes:
    definiciones: list[DefinicionCampo] = await campos_cli.definiciones(u.empresa_id)
    async with transaccion(motor, u.empresa_id) as conn:
        organizaciones = await repo_catalogos.listar_organizaciones(conn, solo_activas=True)
        plantas = await repo_catalogos.listar_plantas(conn, solo_activas=True)
    return await asyncio.to_thread(
        generador.generar, definiciones, organizaciones, [p["nombre"] for p in plantas]
    )


# ------------------------------------------------------------------ COL-17


def _nombre_valido(nombre: str) -> str:
    limpio = nombre.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not limpio.lower().endswith(".xlsx") or len(limpio) > NOMBRE_ARCHIVO_MAX:
        raise ErrorValidacion(
            errores=[
                ErrorCampo("nombre_archivo", "FORMATO_INVALIDO", "Solo se admiten archivos .xlsx.")
            ]
        )
    return limpio


async def iniciar(
    motor, almacen, cfg, u: UsuarioActual, nombre_archivo: str, tamano: int
) -> tuple[dict[str, Any], str, datetime]:
    usuario_id = requerir_usuario_id(u)
    nombre = _nombre_valido(nombre_archivo)
    if tamano < 1 or tamano > cfg.carga_max_bytes:
        raise ErrorValidacion(
            errores=[
                ErrorCampo(
                    "tamano", "ARCHIVO_DEMASIADO_GRANDE", "El archivo no puede pasar de 5 MB."
                )
            ]
        )
    await expirar_vencidas(motor, almacen, cfg, u.empresa_id)
    clave = f"{u.empresa_id}/{uuid.uuid4().hex}.xlsx"
    async with transaccion(motor, u.empresa_id) as conn:
        carga = await repo.crear(
            conn,
            empresa_id=u.empresa_id,
            usuario_id=usuario_id,
            nombre_archivo=nombre,
            s3_key=clave,
        )
    url = await almacen.url_subida(clave, CONTENT_TYPE_XLSX, cfg.url_subida_segundos)
    expira = datetime.now(UTC) + timedelta(seconds=cfg.url_subida_segundos)
    return carga, url, expira


# ------------------------------------------------------------------ COL-18


async def _cancelar_por_archivo(motor, almacen, u, carga_id: int, clave: str, motivo: str) -> None:
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.cerrar(conn, carga_id, estado="CANCELADA", motivo=motivo):
            await bitacora.registrar(
                conn,
                empresa_id=u.empresa_id,
                accion="CARGA_CANCELADA",
                entidad="carga_colaboradores",
                entidad_id=carga_id,
                usuario_id=requerir_usuario_id(u),
                detalle={"carga_id": carga_id, "motivo": motivo},
            )
    await _borrar(almacen, clave)


def _archivo_invalido(mensaje: str) -> ErrorValidacion:
    return ErrorValidacion(
        "CARGA_ARCHIVO_INVALIDO",
        mensaje,
        errores=[ErrorCampo("archivo", "CARGA_ARCHIVO_INVALIDO", mensaje)],
    )


async def confirmar(motor, almacen, cfg, u: UsuarioActual, carga_id: int, ip: str | None) -> dict:
    usuario_id = requerir_usuario_id(u)
    await expirar_vencidas(motor, almacen, cfg, u.empresa_id)
    async with transaccion(motor, u.empresa_id) as conn:
        carga = await repo.obtener(conn, carga_id)
    if carga is None:
        raise ErrorNoEncontrado()
    if carga["estado"] != "EN_PROCESO" or carga["hash_archivo"]:
        raise _fila_carga_estado_invalido(carga["estado"])
    clave = carga["s3_key"]
    cabecera = await almacen.cabecera(clave)
    if cabecera is None:
        raise ErrorValidacion(
            "ARCHIVO_NO_SUBIDO",
            "Todavía no se recibió el archivo; suba el archivo y confirme de nuevo.",
            errores=[ErrorCampo("archivo", "ARCHIVO_NO_SUBIDO", "No se recibió el archivo.")],
        )
    if cabecera.tamano > cfg.carga_max_bytes:
        await _cancelar_por_archivo(motor, almacen, u, carga_id, clave, "CARGA_ARCHIVO_INVALIDO")
        raise _archivo_invalido("El archivo pesa más de 5 MB.")
    contenido = await almacen.leer(clave, cfg.carga_max_bytes)
    if contenido is None:
        raise ErrorValidacion(
            "ARCHIVO_NO_SUBIDO",
            "Todavía no se recibió el archivo; suba el archivo y confirme de nuevo.",
        )
    try:
        archivo = await asyncio.to_thread(lector.leer, contenido)
    except ArchivoInvalido as exc:
        await _cancelar_por_archivo(motor, almacen, u, carga_id, clave, "CARGA_ARCHIVO_INVALIDO")
        raise _archivo_invalido(exc.mensaje) from None
    sha = hashlib.sha256(contenido).hexdigest()
    async with transaccion(motor, u.empresa_id) as conn:
        actual = await repo.obtener(conn, carga_id, bloquear=True)
        if actual is None or actual["estado"] != "EN_PROCESO" or actual["hash_archivo"]:
            raise _fila_carga_estado_invalido(actual["estado"] if actual else "INEXISTENTE")
        await repo.confirmar(
            conn,
            carga_id,
            hash_archivo=sha,
            total_filas=len(archivo.filas),
            version=archivo.version,
        )
        await bitacora.registrar(
            conn,
            empresa_id=u.empresa_id,
            accion="CARGA_INICIADA",
            entidad="carga_colaboradores",
            entidad_id=carga_id,
            usuario_id=usuario_id,
            ip=ip,
            detalle={"carga_id": carga_id, "totales": {"total_filas": len(archivo.filas)}},
        )
        await outbox.escribir(
            conn,
            "colaboradores",
            destino_tipo="SQS",
            destino=cfg.cola_cargas_url,
            tipo="carga.confirmada",
            payload={"carga_id": carga_id, "empresa_id": u.empresa_id},
            empresa_id=u.empresa_id,
            deduplicacion=f"carga-{carga_id}",
        )
        return await repo.obtener(conn, carga_id)  # type: ignore[return-value]


# ------------------------------------------------------------------ COL-19 a COL-22


async def listar(motor, almacen, cfg, u: UsuarioActual, pagina: int, limite: int):
    await expirar_vencidas(motor, almacen, cfg, u.empresa_id)
    async with transaccion(motor, u.empresa_id) as conn:
        return await repo.listar(conn, pagina=pagina, limite=limite)


async def detalle(
    motor,
    almacen,
    cfg,
    u: UsuarioActual,
    carga_id: int,
    resultado: str | None,
    pagina: int,
    limite: int,
):
    await expirar_vencidas(motor, almacen, cfg, u.empresa_id)
    async with transaccion(motor, u.empresa_id) as conn:
        carga = await repo.obtener(conn, carga_id)
        if carga is None:
            raise ErrorNoEncontrado()
        filas, total = await repo.listar_filas(
            conn, carga_id, resultado=resultado, pagina=pagina, limite=limite
        )
    return carga, filas, total


def neutralizar(celda: str) -> str:
    """Una celda que Excel interpretaría como fórmula se antepone con un apóstrofo."""
    return "'" + celda if celda.startswith(PREFIJOS_FORMULA) else celda


def _lineas_de_error(mensaje: str | None) -> list[tuple[str, str]]:
    salida = []
    for linea in (mensaje or "").splitlines():
        codigo, _, texto = linea.partition(": ")
        salida.append((codigo, texto))
    return salida


async def reporte_errores(motor, u: UsuarioActual, carga_id: int) -> bytes:
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.obtener(conn, carga_id) is None:
            raise ErrorNoEncontrado()
        filas = await repo.filas_con_error(conn, carga_id)
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\r\n")
    escritor.writerow(["fila", "codigo", "mensaje"])
    for f in filas:
        for codigo, texto in _lineas_de_error(f["mensaje"]):
            escritor.writerow([f["numero_fila"], neutralizar(codigo), neutralizar(texto)])
    return b"\xef\xbb\xbf" + salida.getvalue().encode("utf-8")


async def cancelar(motor, almacen, u: UsuarioActual, carga_id: int) -> dict:
    usuario_id = requerir_usuario_id(u)
    async with transaccion(motor, u.empresa_id) as conn:
        carga = await repo.obtener(conn, carga_id, bloquear=True)
        if carga is None:
            raise ErrorNoEncontrado()
        if carga["estado"] != "EN_PROCESO":
            raise _fila_carga_estado_invalido(carga["estado"])
        await repo.cerrar(conn, carga_id, estado="CANCELADA", motivo="CANCELADA_POR_USUARIO")
        await bitacora.registrar(
            conn,
            empresa_id=u.empresa_id,
            accion="CARGA_CANCELADA",
            entidad="carga_colaboradores",
            entidad_id=carga_id,
            usuario_id=usuario_id,
            detalle={"carga_id": carga_id, "motivo": "CANCELADA_POR_USUARIO"},
        )
        actualizada = await repo.obtener(conn, carga_id)
    await _borrar(almacen, carga["s3_key"])
    return actualizada  # type: ignore[return-value]
