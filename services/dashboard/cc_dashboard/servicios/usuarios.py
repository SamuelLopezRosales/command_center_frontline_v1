"""Listado y desactivación de usuarios (DSH-08, DSH-09; design.md §3.2, §11.2; CC-REQ-010).

Reglas de desactivación:
- Un usuario no puede desactivarse a sí mismo ni dejar a la empresa sin usuarios activos (409).
- La base de datos y Cognito se mantienen coherentes: se llama a Cognito dentro de la transacción,
  antes de confirmarla. Si Cognito falla, la transacción se revierte y ``activo`` no cambia.
  Si falla la confirmación después de que Cognito respondió, repetir la operación es seguro,
  porque deshabilitar a un usuario ya deshabilitado no tiene efecto.
- Repetir la desactivación de un usuario ya inactivo no hace nada (idempotente).
"""

from __future__ import annotations

from typing import Any

from cc_common import bitacora
from cc_common.auth import UsuarioActual
from cc_common.db import transaccion
from cc_common.errores import ErrorConflicto, ErrorNoEncontrado

from cc_dashboard.repos import usuarios as repo
from cc_dashboard.servicios.sesion import _usuario_vigente


async def listar(motor: Any, actual: UsuarioActual) -> list[repo.FilaUsuarioLista]:
    async with transaccion(motor, actual.empresa_id) as conn:
        fila = await _usuario_vigente(conn, actual)
        await repo.tocar_actividad(conn, fila.id)
        return await repo.listar(conn)


async def desactivar(
    motor: Any, cognito: Any, actual: UsuarioActual, usuario_id: int, ip: str | None
) -> None:
    async with transaccion(motor, actual.empresa_id) as conn:
        yo = await _usuario_vigente(conn, actual)
        await repo.tocar_actividad(conn, yo.id)
        activos = await repo.bloquear_activos(conn)
        objetivo = await repo.por_id(conn, usuario_id)
        if objetivo is None:  # no existe o es de otra empresa (RLS)
            raise ErrorNoEncontrado("USUARIO_NO_ENCONTRADO", "El usuario no existe.")
        if objetivo.id == yo.id:
            raise ErrorConflicto("NO_PUEDE_DESACTIVARSE", "No puedes desactivar tu propia cuenta.")
        if not objetivo.activo:
            return
        if len(activos) <= 1:
            raise ErrorConflicto(
                "ULTIMO_USUARIO_ACTIVO", "La empresa debe conservar al menos un usuario activo."
            )
        await repo.marcar_inactivo(conn, objetivo.id)
        await bitacora.registrar(
            conn,
            empresa_id=actual.empresa_id,
            accion="USUARIO_DESACTIVADO",
            entidad="usuario",
            entidad_id=objetivo.id,
            usuario_id=yo.id,
            ip=ip,
        )
        await cognito.deshabilitar_y_cerrar_sesiones(objetivo.cognito_sub)
