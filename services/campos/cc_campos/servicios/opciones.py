"""Opciones de los campos de lista (CAM-07 a CAM-09; CC-REQ-047, 050).

Solo los campos ``LISTA`` tienen opciones. El ``valor`` es único por campo y no cambia; la
``etiqueta`` tampoco se repite (la carga masiva busca por etiqueta). Una opción no se borra: se
desactiva y los valores históricos que la usan se conservan. ``descripcion`` guarda, por ejemplo,
el horario de un turno.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from cc_common import bitacora
from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.db import transaccion
from cc_common.errores import ErrorCampo, ErrorConflicto, ErrorNoEncontrado, ErrorValidacion
from sqlalchemy.exc import IntegrityError

from cc_campos.errores import desde_integridad
from cc_campos.repos import campos as repo_campos
from cc_campos.repos import opciones as repo
from cc_campos.servicios import eventos


def _normalizar(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto.strip().casefold())
    return "".join(c for c in base if not unicodedata.combining(c))


async def _lista(conn, campo_id: int) -> dict:
    campo = await repo_campos.obtener(conn, campo_id)
    if campo is None:
        raise ErrorNoEncontrado()
    if campo["tipo_dato"] != "LISTA":
        raise ErrorValidacion(
            "CAMPO_NO_ES_LISTA",
            "Solo los campos de tipo lista tienen opciones.",
            errores=[ErrorCampo("campo", "CAMPO_NO_ES_LISTA", "El campo no es de tipo lista.")],
        )
    return campo


def _etiqueta_repetida(existentes: list[dict], etiqueta: str, excepto: int | None = None) -> bool:
    buscada = _normalizar(etiqueta)
    return any(o["id"] != excepto and _normalizar(o["etiqueta"]) == buscada for o in existentes)


async def _registrar(conn, u, campo: dict, opcion_id: int, nombres, ip) -> None:
    await bitacora.registrar(
        conn,
        empresa_id=u.empresa_id,
        accion="CAMPO_MODIFICADO",
        entidad="opcion_campo",
        entidad_id=opcion_id,
        usuario_id=requerir_usuario_id(u),
        ip=ip,
        detalle={"codigos_internos": [campo["codigo_interno"]], "campos": sorted(nombres)},
    )


def _duplicada() -> ErrorConflicto:
    return ErrorConflicto(
        "OPCION_DUPLICADA",
        "Ya existe una opción con esa etiqueta o ese valor.",
        errores=[ErrorCampo("etiqueta", "OPCION_DUPLICADA", "El valor ya existe.")],
    )


async def listar(motor, u: UsuarioActual, campo_id: int) -> list[dict]:
    async with transaccion(motor, u.empresa_id) as conn:
        await _lista(conn, campo_id)
        return await repo.listar(conn, campo_id)


async def crear(
    motor, cfg, u: UsuarioActual, campo_id: int, datos: dict[str, Any], ip: str | None
) -> dict:
    requerir_usuario_id(u)
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            campo = await _lista(conn, campo_id)
            if _etiqueta_repetida(await repo.listar(conn, campo_id), datos["etiqueta"]):
                raise _duplicada()
            orden = datos.get("orden")
            if orden is None:
                orden = await repo.siguiente_orden(conn, campo_id)
            opcion_id = await repo.crear(
                conn,
                empresa_id=u.empresa_id,
                campo_id=campo_id,
                datos={**datos, "orden": orden},
            )
            await _registrar(conn, u, campo, opcion_id, ["opciones"], ip)
            await eventos.publicar(conn, cfg, u.empresa_id, campo_id, "MODIFICADO")
            return await repo.obtener(conn, campo_id, opcion_id)  # type: ignore[return-value]
    except IntegrityError as exc:
        raise desde_integridad(exc) from None


async def actualizar(
    motor,
    cfg,
    u: UsuarioActual,
    campo_id: int,
    opcion_id: int,
    cambios: dict[str, Any],
    ip: str | None,
) -> dict:
    requerir_usuario_id(u)
    async with transaccion(motor, u.empresa_id) as conn:
        campo = await _lista(conn, campo_id)
        actual = await repo.obtener(conn, campo_id, opcion_id)
        if actual is None:
            raise ErrorNoEncontrado()
        distintos = {k: v for k, v in cambios.items() if actual[k] != v}
        if "etiqueta" in distintos and _etiqueta_repetida(
            await repo.listar(conn, campo_id), distintos["etiqueta"], excepto=opcion_id
        ):
            raise _duplicada()
        if distintos:
            await repo.actualizar(conn, opcion_id, distintos)
            await _registrar(conn, u, campo, opcion_id, list(distintos), ip)
            await eventos.publicar(conn, cfg, u.empresa_id, campo_id, "MODIFICADO")
        return await repo.obtener(conn, campo_id, opcion_id)  # type: ignore[return-value]
