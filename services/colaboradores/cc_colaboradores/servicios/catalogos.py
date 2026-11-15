"""Organizaciones, logotipo y plantas (COL-08 a COL-15; CC-REQ-043, 044, 062, 161).

- Cada cambio queda en la bitácora como ``CATALOGO_MODIFICADO``, con los nombres de los campos
  cambiados y sin valores.
- Claves y nombres duplicados dan 409 ``ORGANIZACION_DUPLICADA`` y ``PLANTA_DUPLICADA``, sin
  exponer el texto de PostgreSQL.
- Logotipo: la URL firmada solo admite el tipo declarado. La confirmación verifica que el objeto
  exista bajo ``logotipos/{empresa}/{organizacion}/``, que pese como máximo 1 MB y que sus bytes
  iniciales sean de PNG o JPEG, antes de guardar ``logotipo_s3_key``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from cc_common import bitacora
from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.db import transaccion
from cc_common.errores import ErrorCampo, ErrorNoEncontrado, ErrorValidacion
from sqlalchemy.exc import IntegrityError

from cc_colaboradores.almacenamiento import Almacen
from cc_colaboradores.errores import desde_integridad
from cc_colaboradores.repos import catalogos as repo

FIRMAS = {"image/png": (b"\x89PNG\r\n\x1a\n", "png"), "image/jpeg": (b"\xff\xd8\xff", "jpg")}


@dataclass(frozen=True)
class UrlSubida:
    url: str
    s3_key: str
    expira: datetime


async def _registrar(conn, u: UsuarioActual, entidad: str, entidad_id: int, campos, ip) -> None:
    await bitacora.registrar(
        conn,
        empresa_id=u.empresa_id,
        accion="CATALOGO_MODIFICADO",
        entidad=entidad,
        entidad_id=entidad_id,
        usuario_id=requerir_usuario_id(u),
        ip=ip,
        detalle={"campos": sorted(campos)} if campos else {},
    )


# ---------------------------------------------------------------- organizaciones


async def listar_organizaciones(motor: Any, u: UsuarioActual, solo_activas: bool) -> list[dict]:
    async with transaccion(motor, u.empresa_id) as conn:
        return await repo.listar_organizaciones(conn, solo_activas=solo_activas)


async def crear_organizacion(motor: Any, u: UsuarioActual, datos: dict, ip: str | None) -> dict:
    requerir_usuario_id(u)
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            org_id = await repo.crear_organizacion(conn, empresa_id=u.empresa_id, datos=datos)
            await _registrar(conn, u, "organizacion", org_id, [], ip)
            return await repo.organizacion(conn, org_id)
    except IntegrityError as exc:
        raise desde_integridad(exc) from None


async def actualizar_organizacion(
    motor: Any, u: UsuarioActual, organizacion_id: int, cambios: dict, ip: str | None
) -> dict:
    requerir_usuario_id(u)
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            actual = await repo.organizacion(conn, organizacion_id)
            if actual is None:
                raise ErrorNoEncontrado()
            diferentes = {k: v for k, v in cambios.items() if actual.get(k) != v}
            if diferentes:
                await repo.actualizar_organizacion(conn, organizacion_id, diferentes)
                await _registrar(conn, u, "organizacion", organizacion_id, diferentes, ip)
            return await repo.organizacion(conn, organizacion_id)
    except IntegrityError as exc:
        raise desde_integridad(exc) from None


async def solicitar_logotipo(
    motor: Any,
    almacen: Almacen,
    u: UsuarioActual,
    organizacion_id: int,
    content_type: str,
    tamano: int,
    *,
    maximo: int,
    segundos: int,
) -> UrlSubida:
    if content_type not in FIRMAS:
        raise _logotipo("LOGOTIPO_TIPO_INVALIDO", "Solo se admite PNG o JPG.", "content_type")
    if not 0 < tamano <= maximo:
        raise _logotipo("LOGOTIPO_DEMASIADO_GRANDE", "El logotipo pesa más de 1 MB.", "tamano")
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.organizacion(conn, organizacion_id) is None:
            raise ErrorNoEncontrado()
    clave = f"{_prefijo(u.empresa_id, organizacion_id)}{uuid.uuid4().hex}.{FIRMAS[content_type][1]}"
    url = await almacen.url_subida(clave, content_type, segundos)
    return UrlSubida(url, clave, datetime.now(UTC) + timedelta(seconds=segundos))


async def confirmar_logotipo(
    motor: Any,
    almacen: Almacen,
    u: UsuarioActual,
    organizacion_id: int,
    s3_key: str,
    *,
    maximo: int,
    ip: str | None,
) -> dict:
    requerir_usuario_id(u)
    if not s3_key.startswith(_prefijo(u.empresa_id, organizacion_id)) or ".." in s3_key:
        raise _logotipo("LOGOTIPO_CLAVE_INVALIDA", "La clave del archivo no es válida.", "s3_key")
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.organizacion(conn, organizacion_id) is None:
            raise ErrorNoEncontrado()
    cab = await almacen.cabecera(s3_key)
    if cab is None:
        raise _logotipo("LOGOTIPO_NO_ENCONTRADO", "No se encontró el archivo subido.", "s3_key")
    if cab.tamano > maximo or cab.tamano == 0:
        raise _logotipo("LOGOTIPO_DEMASIADO_GRANDE", "El logotipo pesa más de 1 MB.", "s3_key")
    inicio = await almacen.inicio(s3_key, 8)
    if not any(inicio.startswith(firma) for firma, _ in FIRMAS.values()):
        raise _logotipo("LOGOTIPO_TIPO_INVALIDO", "El archivo no es PNG ni JPG.", "s3_key")
    async with transaccion(motor, u.empresa_id) as conn:
        await repo.fijar_logotipo(conn, organizacion_id, s3_key)
        await _registrar(conn, u, "organizacion", organizacion_id, ["logotipo_s3_key"], ip)
        return await repo.organizacion(conn, organizacion_id)


def _prefijo(empresa_id: int, organizacion_id: int) -> str:
    return f"logotipos/{empresa_id}/{organizacion_id}/"


def _logotipo(codigo: str, mensaje: str, campo: str) -> ErrorValidacion:
    return ErrorValidacion(codigo, mensaje, errores=[ErrorCampo(campo, codigo, mensaje)])


# ---------------------------------------------------------------- plantas


async def listar_plantas(motor: Any, u: UsuarioActual, solo_activas: bool) -> list[dict]:
    async with transaccion(motor, u.empresa_id) as conn:
        return await repo.listar_plantas(conn, solo_activas=solo_activas)


async def crear_planta(motor: Any, u: UsuarioActual, nombre: str, ip: str | None) -> dict:
    requerir_usuario_id(u)
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            planta_id = await repo.crear_planta(conn, empresa_id=u.empresa_id, nombre=nombre)
            await _registrar(conn, u, "planta", planta_id, [], ip)
            return await repo.planta(conn, planta_id)
    except IntegrityError as exc:
        raise desde_integridad(exc) from None


async def actualizar_planta(
    motor: Any, u: UsuarioActual, planta_id: int, cambios: dict, ip: str | None
) -> dict:
    requerir_usuario_id(u)
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            actual = await repo.planta(conn, planta_id)
            if actual is None:
                raise ErrorNoEncontrado()
            diferentes = {k: v for k, v in cambios.items() if actual.get(k) != v}
            if diferentes:
                await repo.actualizar_planta(conn, planta_id, diferentes)
                await _registrar(conn, u, "planta", planta_id, diferentes, ip)
            return await repo.planta(conn, planta_id)
    except IntegrityError as exc:
        raise desde_integridad(exc) from None
