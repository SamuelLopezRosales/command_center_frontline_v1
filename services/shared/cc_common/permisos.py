"""Catálogo de permisos y su asignación a roles (design.md §11.6; CC-NFR-017, CC-REQ-153).

En v1 existe un solo rol, RH, con todos los permisos (Ronda P2). Agregar roles solo cambia
``ROL_PERMISOS`` y el ``CHECK`` de ``usuario.rol``.
"""

from __future__ import annotations

from enum import StrEnum


class Permiso(StrEnum):
    DASHBOARD_VER = "dashboard:ver"
    BITACORA_VER = "bitacora:ver"
    USUARIOS_ADMINISTRAR = "usuarios:administrar"
    COLABORADORES_VER = "colaboradores:ver"
    COLABORADORES_EDITAR = "colaboradores:editar"
    COLABORADORES_VER_SENSIBLES = "colaboradores:ver_sensibles"
    CARGAS_EJECUTAR = "cargas:ejecutar"
    CAMPOS_ADMINISTRAR = "campos:administrar"
    CATALOGOS_ADMINISTRAR = "catalogos:administrar"
    PLANTILLAS_EDITAR = "plantillas:editar"
    PLANTILLAS_PUBLICAR = "plantillas:publicar"
    CONSTANCIAS_VER = "constancias:ver"
    CONSTANCIAS_REENVIAR = "constancias:reenviar"
    NOTIFICACIONES_EDITAR = "notificaciones:editar"
    NOTIFICACIONES_ENVIAR = "notificaciones:enviar"
    CHAT_RESPONDER = "chat:responder"


ROL_PERMISOS: dict[str, frozenset[Permiso]] = {
    "RH": frozenset(Permiso),
}


def tiene_permiso(rol: str, permiso: Permiso) -> bool:
    return permiso in ROL_PERMISOS.get(rol, frozenset())
