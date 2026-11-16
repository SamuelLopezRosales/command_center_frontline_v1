"""Audiencias guardadas (NOT-01 a NOT-06; design.md §3.6, §6.1; CC-REQ-100, 101).

- Los criterios se validan contra INT-CAM-01 (``cc_common.criterios_audiencia``): solo campos
  fijos de la lista cerrada y campos activos y no sensibles, operadores de la lista cerrada, hasta
  20 criterios. `colaboradores` los valida de nuevo al evaluarlos.
- El nombre es único entre las activas (409 ``AUDIENCIA_NOMBRE_DUPLICADO``, por el índice).
- DELETE desactiva. Reactivar (PATCH ``activa``) vuelve a exigir nombre único.
- No se registra en la bitácora: el catálogo de acciones de auditoría (design.md §2.7) no incluye
  audiencias; los envíos sí quedan con criterios y totales (``NOTIFICACION_ENVIO``, T-216).
"""

from __future__ import annotations

from typing import Any

from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.criterios_audiencia import validar
from cc_common.db import transaccion
from cc_common.errores import ErrorCampo, ErrorNoEncontrado, ErrorValidacion
from cc_common.paginacion import (
    LIMITE_CURSOR_MAX,
    CursorInvalido,
    PaginaCursor,
    acotar,
    codificar_cursor,
    decodificar_cursor,
)
from sqlalchemy.exc import IntegrityError

from cc_notificaciones.errores import desde_integridad
from cc_notificaciones.repos import audiencias as repo


async def validar_criterios(campos_cli, empresa_id: int, criterios: Any) -> None:
    validar(criterios, await campos_cli.definiciones(empresa_id))


async def crear(
    motor, campos_cli, u: UsuarioActual, nombre: str, criterios: dict[str, Any]
) -> dict[str, Any]:
    usuario_id = requerir_usuario_id(u)
    await validar_criterios(campos_cli, u.empresa_id, criterios)
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            return await repo.crear(
                conn,
                empresa_id=u.empresa_id,
                nombre=nombre,
                criterios=criterios,
                usuario_id=usuario_id,
            )
    except IntegrityError as exc:
        raise desde_integridad(exc) from exc


async def listar(
    motor, u: UsuarioActual, estado: str, cursor: str | None, limite: int | None
) -> PaginaCursor[dict[str, Any]]:
    tope = acotar(limite, LIMITE_CURSOR_MAX)
    despues = None
    if cursor:
        try:
            (valor,) = decodificar_cursor(cursor)
            despues = int(valor)
        except (CursorInvalido, ValueError, TypeError) as exc:
            raise ErrorValidacion(
                errores=[ErrorCampo("cursor", "CURSOR_INVALIDO", "El cursor no es válido.")]
            ) from exc
    async with transaccion(motor, u.empresa_id) as conn:
        filas = await repo.listar(conn, estado=estado, despues_de=despues, limite=tope + 1)
    pagina = filas[:tope]
    siguiente = codificar_cursor((pagina[-1]["id"],)) if len(filas) > tope else None
    return PaginaCursor(pagina, siguiente)


async def detalle(motor, u: UsuarioActual, audiencia_id: int) -> dict[str, Any]:
    async with transaccion(motor, u.empresa_id) as conn:
        fila = await repo.obtener(conn, audiencia_id)
    if fila is None:
        raise ErrorNoEncontrado()
    return fila


async def actualizar(
    motor, campos_cli, u: UsuarioActual, audiencia_id: int, cambios: dict[str, Any]
) -> dict[str, Any]:
    if "criterios" in cambios:
        await validar_criterios(campos_cli, u.empresa_id, cambios["criterios"])
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            actual = await repo.obtener(conn, audiencia_id, bloquear=True)
            if actual is None:
                raise ErrorNoEncontrado()
            nuevos: dict[str, Any] = {}
            if "nombre" in cambios:
                nuevos["nombre"] = cambios["nombre"]
            if "criterios" in cambios:
                nuevos["criterios_json"] = cambios["criterios"]
            if "activa" in cambios:
                nuevos["activa"] = cambios["activa"]
            if not nuevos:
                return actual
            return await repo.actualizar(conn, audiencia_id, nuevos)
    except IntegrityError as exc:
        raise desde_integridad(exc) from exc


async def desactivar(motor, u: UsuarioActual, audiencia_id: int) -> None:
    async with transaccion(motor, u.empresa_id) as conn:
        actual = await repo.obtener(conn, audiencia_id, bloquear=True)
        if actual is None:
            raise ErrorNoEncontrado()
        if actual["activa"]:
            await repo.actualizar(conn, audiencia_id, {"activa": False})


async def previsualizar(
    campos_cli, colaboradores_cli, u: UsuarioActual, criterios: dict[str, Any], zona: str
) -> int:
    """NOT-06: solo el total (``solo_conteo``). Sin colaboradores devuelve 0, no un error."""
    await validar_criterios(campos_cli, u.empresa_id, criterios)
    r = await colaboradores_cli.evaluar_audiencia(
        u.empresa_id, criterios, solo_conteo=True, zona_horaria=zona
    )
    return r.total
