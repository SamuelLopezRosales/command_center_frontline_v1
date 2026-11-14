"""Sesión, usuario actual e invitaciones (DSH-06, DSH-07, DSH-10; design.md §3.2, §11.2).

Reglas:
- El usuario del token debe existir en ``identidad.usuario`` y estar activo.
- El inicio de sesión se registra en la bitácora una sola vez por ``jti`` (idempotente) y con
  la IP del visitante.
- El código de invitación tiene 128 bits, se muestra una sola vez y solo se guarda su SHA-256.
  Caduca a las 72 horas (D-02, CC-REQ-008).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cc_common import bitacora
from cc_common.auth import UsuarioActual
from cc_common.db import transaccion
from cc_common.errores import ErrorNoAutenticado, ErrorProhibido
from cc_common.permisos import ROL_PERMISOS

from cc_dashboard.repos import usuarios as repo


@dataclass(frozen=True)
class Perfil:
    id: int
    empresa_id: int
    nombre: str
    correo: str
    rol: str
    permisos: list[str]


@dataclass(frozen=True)
class InvitacionCreada:
    id: int
    codigo: str
    fecha_expira: datetime


def _hash_codigo(codigo: str) -> bytes:
    return hashlib.sha256(codigo.encode()).digest()


async def _usuario_vigente(conn: Any, actual: UsuarioActual) -> repo.FilaUsuario:
    fila = await repo.por_sub(conn, actual.sub)
    if fila is None or fila.empresa_id != actual.empresa_id:
        raise ErrorProhibido(
            "USUARIO_NO_REGISTRADO", "El usuario no está registrado en el sistema."
        )
    if not fila.activo:
        raise ErrorNoAutenticado("USUARIO_INACTIVO", "El usuario está desactivado.")
    return fila


async def perfil(motor: Any, actual: UsuarioActual) -> Perfil:
    async with transaccion(motor, actual.empresa_id) as conn:
        fila = await _usuario_vigente(conn, actual)
        await repo.tocar_actividad(conn, fila.id)
    return Perfil(
        id=fila.id,
        empresa_id=fila.empresa_id,
        nombre=fila.nombre,
        correo=fila.correo,
        rol=fila.rol,
        permisos=sorted(p.value for p in ROL_PERMISOS.get(fila.rol, frozenset())),
    )


async def iniciar_sesion(motor: Any, actual: UsuarioActual, ip: str | None) -> bool:
    """Registra LOGIN una vez por token. Devuelve True si se registró ahora."""
    async with transaccion(motor, actual.empresa_id) as conn:
        fila = await _usuario_vigente(conn, actual)
        await repo.tocar_actividad(conn, fila.id)
        if actual.jti and await repo.login_ya_registrado(conn, actual.empresa_id, actual.jti):
            return False
        await bitacora.registrar(
            conn,
            empresa_id=actual.empresa_id,
            accion="LOGIN",
            entidad="usuario",
            entidad_id=fila.id,
            usuario_id=fila.id,
            ip=ip,
            detalle={"jti": actual.jti} if actual.jti else {},
        )
    return True


async def crear_invitacion(
    motor: Any, actual: UsuarioActual, correo_destino: str | None, horas: int = 72
) -> InvitacionCreada:
    codigo = secrets.token_urlsafe(16)  # 128 bits
    async with transaccion(motor, actual.empresa_id) as conn:
        fila = await _usuario_vigente(conn, actual)
        inv_id, expira = await repo.crear_invitacion(
            conn,
            empresa_id=actual.empresa_id,
            codigo_hash=_hash_codigo(codigo),
            horas=horas,
            creada_por=fila.id,
            correo_destino=correo_destino,
        )
        await bitacora.registrar(
            conn,
            empresa_id=actual.empresa_id,
            accion="INVITACION_CREADA",
            entidad="invitacion_registro",
            entidad_id=inv_id,
            usuario_id=fila.id,
        )
    return InvitacionCreada(id=inv_id, codigo=codigo, fecha_expira=expira)
