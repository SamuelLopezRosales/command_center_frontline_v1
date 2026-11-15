"""Campos dinámicos: listado, alta, detalle, edición, eliminación y orden (CAM-01 a CAM-06;
CC-REQ-045 a 052, 161).

Protecciones:
- ``tipo_dato`` y ``es_sensible`` no cambian si hay valores guardados (INT-COL-10) y nunca en un
  campo sugerido: 409 ``CAMPO_TIPO_INMUTABLE`` (CC-REQ-048).
- Cambiar la ``clave`` de un campo usado en plantillas (INT-CON-06) pide ``confirmar = true``:
  409 ``CLAVE_EN_USO_REQUIERE_CONFIRMACION`` con las plantillas afectadas (CC-REQ-052). La clave
  de un campo sugerido no cambia: ``colaboradores`` y ``constancias`` dependen de ella.
- Un campo sugerido solo se desactiva; uno con valores tampoco se elimina (CC-REQ-049, 050). La
  eliminación es lógica (``eliminado``) y la clave no se reutiliza.
- Cada cambio queda en la bitácora con los nombres de los campos modificados, sin valores, y
  publica ``campo.actualizado``.
"""

from __future__ import annotations

from typing import Any

import re2
from cc_common import bitacora
from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.db import transaccion
from cc_common.errores import (
    ErrorCampo,
    ErrorConflicto,
    ErrorNoEncontrado,
    ErrorProveedor,
    ErrorValidacion,
)
from sqlalchemy.exc import IntegrityError

from cc_campos.catalogo import FORMATO_MAXIMO, RESERVADAS, TIPOS_CON_FORMATO
from cc_campos.errores import desde_integridad
from cc_campos.repos import campos as repo
from cc_campos.repos import opciones as repo_opciones
from cc_campos.servicios import eventos


def _error(campo: str, codigo: str, mensaje: str):
    return ErrorValidacion(codigo, mensaje, errores=[ErrorCampo(campo, codigo, mensaje)])


def validar_clave(clave: str) -> None:
    if clave in RESERVADAS:
        raise _error("clave", "CLAVE_RESERVADA", "La clave ya es una variable del sistema.")


def validar_formato(tipo_dato: str, formato: str | None) -> None:
    """El formato se prueba con ``re2`` (tiempo lineal): lo que ``re2`` no admite, como las
    referencias hacia atrás o los lookahead, se rechaza (CC-REQ-045; design.md §10.1)."""
    if formato is None:
        return
    if tipo_dato not in TIPOS_CON_FORMATO:
        raise _error(
            "formato_validacion",
            "FORMATO_NO_APLICA",
            "Solo los campos de texto o número admiten formato.",
        )
    if len(formato) > FORMATO_MAXIMO:
        raise _error(
            "formato_validacion", "FORMATO_INVALIDO", "El formato no puede pasar de 200 caracteres."
        )
    try:
        re2.compile(formato)
    except Exception:  # noqa: BLE001 - cualquier rechazo del motor es un formato inválido
        raise _error(
            "formato_validacion", "FORMATO_INVALIDO", "El formato no es una expresión válida."
        ) from None


async def _registrar(conn, u: UsuarioActual, accion: str, campo: dict, nombres, ip) -> None:
    detalle: dict[str, Any] = {"codigos_internos": [campo["codigo_interno"]]}
    if nombres:
        detalle["campos"] = sorted(nombres)
    await bitacora.registrar(
        conn,
        empresa_id=u.empresa_id,
        accion=accion,
        entidad="campo_colaborador",
        entidad_id=campo["id"],
        usuario_id=requerir_usuario_id(u),
        ip=ip,
        detalle=detalle,
    )


async def _con_opciones(conn, campo: dict) -> dict:
    return campo | {"opciones": await repo_opciones.listar(conn, campo["id"])}


async def _uso_en_plantillas(constancias, empresa_id: int, claves: list[str]):
    """``{clave: [plantillas]}`` o ``None`` si `constancias` no responde: el listado no debe
    fallar por un dato informativo."""
    try:
        return await constancias.uso_de_variables(empresa_id, claves)
    except ErrorProveedor:
        return None


# ------------------------------------------------------------------ CAM-01 a CAM-03


async def listar(motor, constancias, u: UsuarioActual, estado: str, tipo: str):
    async with transaccion(motor, u.empresa_id) as conn:
        filas = await repo.listar(conn, estado=estado, tipo=tipo)
    usos = await _uso_en_plantillas(constancias, u.empresa_id, [f["clave"] for f in filas])
    return [
        f | {"usada_en_plantillas": None if usos is None else len(usos.get(f["clave"], []))}
        for f in filas
    ]


async def detalle(motor, constancias, u: UsuarioActual, campo_id: int) -> dict:
    async with transaccion(motor, u.empresa_id) as conn:
        campo = await repo.obtener(conn, campo_id)
        if campo is None:
            raise ErrorNoEncontrado()
        campo = await _con_opciones(conn, campo)
    usos = await _uso_en_plantillas(constancias, u.empresa_id, [campo["clave"]])
    return campo | {
        "usada_en_plantillas": None if usos is None else len(usos.get(campo["clave"], []))
    }


async def crear(motor, cfg, u: UsuarioActual, datos: dict[str, Any], ip: str | None) -> dict:
    requerir_usuario_id(u)
    validar_clave(datos["clave"])
    validar_formato(datos["tipo_dato"], datos.get("formato_validacion"))
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            codigo = await repo.siguiente_codigo(conn, u.empresa_id)
            orden = datos.get("orden")
            if orden is None:
                orden = await repo.siguiente_orden(conn)
            campo_id = await repo.insertar(
                conn,
                empresa_id=u.empresa_id,
                codigo_interno=codigo,
                datos={**datos, "orden": orden, "es_sugerido": False},
            )
            campo = await repo.obtener(conn, campo_id)
            await _registrar(conn, u, "CAMPO_CREADO", campo, [], ip)
            await eventos.publicar(conn, cfg, u.empresa_id, campo_id, "CREADO")
            return await _con_opciones(conn, campo) | {"usada_en_plantillas": 0}
    except IntegrityError as exc:
        raise desde_integridad(exc) from None


# ------------------------------------------------------------------ CAM-04


def _tipo_inmutable(motivo: str) -> ErrorConflicto:
    return ErrorConflicto(
        "CAMPO_TIPO_INMUTABLE",
        "El tipo de dato y la sensibilidad no cambian en un campo con valores.",
        detalle={"campo": motivo},
    )


async def actualizar(
    motor,
    cfg,
    colaboradores,
    constancias,
    u: UsuarioActual,
    campo_id: int,
    cambios: dict[str, Any],
    confirmar: bool,
    ip: str | None,
) -> dict:
    requerir_usuario_id(u)
    if "clave" in cambios:
        validar_clave(cambios["clave"])
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            actual = await repo.obtener(conn, campo_id, bloquear=True)
            if actual is None:
                raise ErrorNoEncontrado()
            distintos = {k: v for k, v in cambios.items() if actual[k] != v}
            if not distintos:
                return await _con_opciones(conn, actual) | {"usada_en_plantillas": None}
            tipo = distintos.get("tipo_dato", actual["tipo_dato"])
            if "tipo_dato" in distintos or "formato_validacion" in distintos:
                validar_formato(
                    tipo, distintos.get("formato_validacion", actual["formato_validacion"])
                )
            if "tipo_dato" in distintos or "es_sensible" in distintos:
                protegido = "tipo_dato" if "tipo_dato" in distintos else "es_sensible"
                if actual["es_sugerido"] or await colaboradores.campo_con_valores(
                    u.empresa_id, campo_id
                ):
                    raise _tipo_inmutable(protegido)
            if "clave" in distintos:
                if actual["es_sugerido"]:
                    raise ErrorConflicto(
                        "CAMPO_SUGERIDO_CLAVE_INMUTABLE",
                        "La clave de un campo sugerido no cambia.",
                        detalle={"campo": "clave"},
                    )
                usos = await constancias.uso_de_variables(u.empresa_id, [actual["clave"]])
                plantillas = usos.get(actual["clave"], [])
                if plantillas and not confirmar:
                    raise ErrorConflicto(
                        "CLAVE_EN_USO_REQUIERE_CONFIRMACION",
                        "La clave se usa en plantillas; confirme el cambio.",
                        detalle={
                            "plantillas": [{"id": p.id, "nombre": p.nombre} for p in plantillas],
                            "total": len(plantillas),
                        },
                    )
            await repo.actualizar(conn, campo_id, distintos)
            campo = await repo.obtener(conn, campo_id)
            await _registrar(conn, u, "CAMPO_MODIFICADO", campo, list(distintos), ip)
            await eventos.publicar(conn, cfg, u.empresa_id, campo_id, "MODIFICADO")
            return await _con_opciones(conn, campo) | {"usada_en_plantillas": None}
    except IntegrityError as exc:
        raise desde_integridad(exc) from None


# ------------------------------------------------------------------ CAM-05 y CAM-06


async def eliminar(motor, cfg, colaboradores, u: UsuarioActual, campo_id: int, ip) -> None:
    requerir_usuario_id(u)
    async with transaccion(motor, u.empresa_id) as conn:
        campo = await repo.obtener(conn, campo_id, bloquear=True)
        if campo is None:
            raise ErrorNoEncontrado()
        if campo["es_sugerido"]:
            raise ErrorConflicto(
                "CAMPO_SUGERIDO_NO_ELIMINABLE",
                "Un campo sugerido solo se puede desactivar.",
            )
        if await colaboradores.campo_con_valores(u.empresa_id, campo_id):
            raise ErrorConflicto(
                "CAMPO_CON_VALORES", "El campo tiene valores registrados; desactívelo."
            )
        await repo.marcar_eliminado(conn, campo_id)
        await _registrar(conn, u, "CAMPO_ELIMINADO", campo, [], ip)
        await eventos.publicar(conn, cfg, u.empresa_id, campo_id, "ELIMINADO")


async def ordenar(motor, cfg, u: UsuarioActual, items: list[tuple[int, int]], ip) -> None:
    requerir_usuario_id(u)
    ids = [i for i, _ in items]
    if len(set(ids)) != len(ids):
        raise _error("orden", "CAMPO_REPETIDO", "Un campo aparece más de una vez.")
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.fijar_orden(conn, items) != len(items):
            raise _error("orden", "CAMPO_NO_EXISTE", "Algún campo no existe.")  # revierte todo
        await bitacora.registrar(
            conn,
            empresa_id=u.empresa_id,
            accion="CAMPO_MODIFICADO",
            entidad="campo_colaborador",
            usuario_id=requerir_usuario_id(u),
            ip=ip,
            detalle={"campos": ["orden"], "totales": {"campos": len(items)}},
        )
        await eventos.publicar(conn, cfg, u.empresa_id, None, "ORDENADO")
