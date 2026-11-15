"""Plantillas de constancia: listado, alta, detalle, edición, duplicado y eliminación
(CON-01 a CON-06; CC-REQ-064, 069, 070, 161).

- La plantilla nace inactiva y sin versión: estado visible ``BORRADOR``. Activarla exige al menos
  una versión publicada (409 ``PLANTILLA_SIN_VERSION``); desactivarla siempre se puede y la quita
  del menú de WhatsApp (CC-REQ-070).
- El nombre es único por empresa sin distinguir mayúsculas (409 ``NOMBRE_DUPLICADO``).
- Duplicar crea una plantilla nueva e inactiva cuyo **borrador** es una copia del último
  contenido: el borrador actual si existe y, si no, la última versión publicada. No copia versiones.
- Eliminar es lógico: oculta la plantilla y la desactiva, sin tocar versiones ni constancias
  emitidas (CC-REQ-069, 161).
- Cada cambio queda en la bitácora con nombres de campos, nunca valores.
"""

from __future__ import annotations

from typing import Any

from cc_common import bitacora
from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.db import transaccion
from cc_common.errores import ErrorConflicto, ErrorNoEncontrado
from sqlalchemy.exc import IntegrityError

from cc_constancias import contenido as esquema
from cc_constancias.almacenamiento import clave_borrador
from cc_constancias.errores import desde_integridad
from cc_constancias.repos import plantillas as repo

NOMBRE_MAXIMO = 120


async def _registrar(conn, u: UsuarioActual, accion: str, plantilla_id: int, detalle, ip) -> None:
    await bitacora.registrar(
        conn,
        empresa_id=u.empresa_id,
        accion=accion,
        entidad="plantilla_constancia",
        entidad_id=plantilla_id,
        usuario_id=requerir_usuario_id(u),
        ip=ip,
        detalle=detalle,
    )


async def listar(motor, u: UsuarioActual) -> list[dict[str, Any]]:
    async with transaccion(motor, u.empresa_id) as conn:
        return await repo.listar(conn)


async def detalle(motor, u: UsuarioActual, plantilla_id: int) -> dict[str, Any]:
    async with transaccion(motor, u.empresa_id) as conn:
        p = await repo.obtener(conn, plantilla_id)
    if p is None:
        raise ErrorNoEncontrado()
    return p


async def crear(
    motor, u: UsuarioActual, nombre: str, descripcion: str | None, ip: str | None
) -> dict[str, Any]:
    requerir_usuario_id(u)
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            plantilla_id = await repo.insertar(
                conn, empresa_id=u.empresa_id, nombre=nombre, descripcion=descripcion
            )
            await _registrar(conn, u, "PLANTILLA_CREADA", plantilla_id, {}, ip)
            return await repo.obtener(conn, plantilla_id)  # type: ignore[return-value]
    except IntegrityError as exc:
        raise desde_integridad(exc) from None


async def actualizar(
    motor, u: UsuarioActual, plantilla_id: int, cambios: dict[str, Any], ip: str | None
) -> dict[str, Any]:
    requerir_usuario_id(u)
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            if await repo.obtener(conn, plantilla_id, bloquear=True) is None:
                raise ErrorNoEncontrado()
            actual = await repo.obtener(conn, plantilla_id)
            assert actual is not None
            distintos = {k: v for k, v in cambios.items() if actual[k] != v}
            if distintos.get("activa") and actual["version"] is None:
                raise ErrorConflicto(
                    "PLANTILLA_SIN_VERSION",
                    "La plantilla necesita al menos una versión publicada para activarse.",
                )
            if distintos:
                await repo.actualizar(conn, plantilla_id, distintos)
                await _registrar(
                    conn, u, "PLANTILLA_MODIFICADA", plantilla_id, {"campos": sorted(distintos)}, ip
                )
            return await repo.obtener(conn, plantilla_id)  # type: ignore[return-value]
    except IntegrityError as exc:
        raise desde_integridad(exc) from None


def nombre_de_copia(origen: str, existentes: list[str]) -> str:
    """``X (copia)``, ``X (copia 2)``... sin chocar con ningún nombre existente."""
    usados = {n.casefold() for n in existentes}
    n = 1
    while True:
        sufijo = " (copia)" if n == 1 else f" (copia {n})"
        candidato = origen[: NOMBRE_MAXIMO - len(sufijo)].rstrip() + sufijo
        if candidato.casefold() not in usados:
            return candidato
        n += 1


async def duplicar(motor, almacen, u: UsuarioActual, plantilla_id: int, ip: str | None) -> dict:
    requerir_usuario_id(u)
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            origen = await repo.obtener(conn, plantilla_id)
            if origen is None:
                raise ErrorNoEncontrado()
            borrador = await repo.obtener_borrador(conn, plantilla_id)
            ultima = await repo.ultima_version(conn, plantilla_id)
            fuente = (borrador or {}).get("contenido_s3_key") or (ultima or {}).get(
                "contenido_s3_key"
            )
            cuerpo = await almacen.leer(fuente) if fuente else None
            nuevo_id = await repo.insertar(
                conn,
                empresa_id=u.empresa_id,
                nombre=nombre_de_copia(origen["nombre"], await repo.nombres(conn)),
                descripcion=origen["descripcion"],
            )
            if cuerpo is not None:
                clave = clave_borrador(u.empresa_id, nuevo_id)
                await almacen.escribir(clave, cuerpo)
                await repo.guardar_borrador(
                    conn,
                    empresa_id=u.empresa_id,
                    plantilla_id=nuevo_id,
                    clave=clave,
                    hash_sha256=esquema.hash_de(cuerpo),
                    usuario_id=requerir_usuario_id(u),
                )
            await _registrar(
                conn, u, "PLANTILLA_CREADA", nuevo_id, {"plantilla_id": plantilla_id}, ip
            )
            return await repo.obtener(conn, nuevo_id)  # type: ignore[return-value]
    except IntegrityError as exc:
        raise desde_integridad(exc) from None


async def eliminar(motor, u: UsuarioActual, plantilla_id: int, ip: str | None) -> None:
    requerir_usuario_id(u)
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.obtener(conn, plantilla_id, bloquear=True) is None:
            raise ErrorNoEncontrado()
        await repo.marcar_eliminada(conn, plantilla_id)
        await _registrar(conn, u, "PLANTILLA_ELIMINADA", plantilla_id, {}, ip)
