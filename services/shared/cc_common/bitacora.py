"""Registro en la bitácora de auditoría (design.md §2.7; CC-REQ-154, 155, 156, 162).

La bitácora es de solo inserción. ``detalle`` admite únicamente claves de una lista
permitida: identificadores, nombres de campos, criterios y totales; nunca valores
personales. La base de datos aplica la misma lista con una restricción ``CHECK`` (T-027).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

CLAVES_DETALLE = frozenset(
    {
        "campos",  # nombres de campos cambiados, sin valores
        "codigos_internos",
        "criterios",
        "totales",
        "estado_anterior",
        "estado_nuevo",
        "motivo",
        "folio",
        "plantilla_id",
        "version",
        "notificacion_id",
        "carga_id",
        "conversacion_id",
        "solicitud_id",
        "jti",
        "confirmada_fuera_horario",
        "proposito",
        "celular_hash",
    }
)

ACCIONES = frozenset(
    {
        "LOGIN",
        "USUARIO_REGISTRADO",
        "USUARIO_DESACTIVADO",
        "INVITACION_CREADA",
        "ALTA",
        "MODIFICACION",
        "BAJA",
        "REACTIVACION",
        "CONSULTA_DETALLE",
        "CONSULTA_SENSIBLE",
        "CAMPO_CREADO",
        "CAMPO_MODIFICADO",
        "CAMPO_ELIMINADO",
        "CARGA_INICIADA",
        "CARGA_TERMINADA",
        "CARGA_CANCELADA",
        "CATALOGO_MODIFICADO",
        "PLANTILLA_CREADA",
        "PLANTILLA_MODIFICADA",
        "PLANTILLA_PUBLICADA",
        "PLANTILLA_ELIMINADA",
        "CONSTANCIA_GENERADA",
        "CONSTANCIA_ENTREGADA",
        "CONSTANCIA_DESCARGADA",
        "CONSTANCIA_REENVIADA",
        "NOTIFICACION_ENVIO",
        "NOTIFICACION_CANCELADA",
        "MENSAJE_CHAT",
        "INTENTO_WHATSAPP",
        "META_CONFIGURADA",
        "META_PROBADA",
        "PLANTILLA_MENSAJE_IMPORTADA",
    }
)

SQL_INSERTAR = text(
    """
    INSERT INTO auditoria.bitacora
      (empresa_id, usuario_id, colaborador_id, accion, entidad, entidad_id, ip, origen, detalle)
    VALUES
      (:empresa_id, :usuario_id, :colaborador_id, :accion, :entidad, :entidad_id,
       CAST(:ip AS inet), :origen, CAST(:detalle AS jsonb))
    """
)
# Sin RETURNING: RETURNING exige SELECT sobre la tabla y los roles de servicio solo tienen INSERT
# en la bitácora (solo dashboard la lee; design.md §2.6). Hallazgo de T-201.


class DetalleNoPermitido(ValueError):
    pass


def validar_detalle(detalle: Mapping[str, Any]) -> dict[str, Any]:
    prohibidas = set(detalle) - CLAVES_DETALLE
    if prohibidas:
        raise DetalleNoPermitido(f"claves de detalle no permitidas: {sorted(prohibidas)}")
    return dict(detalle)


async def registrar(
    conn: AsyncConnection,
    *,
    empresa_id: int,
    accion: str,
    entidad: str,
    entidad_id: int | None = None,
    usuario_id: int | None = None,
    colaborador_id: int | None = None,
    ip: str | None = None,
    origen: Literal["USUARIO", "SISTEMA"] = "USUARIO",
    detalle: Mapping[str, Any] | None = None,
) -> None:
    """Inserta un registro en la misma transacción que la operación de negocio."""
    if accion not in ACCIONES:
        raise ValueError(f"acción de bitácora desconocida: {accion}")
    datos = validar_detalle(detalle or {})
    await conn.execute(
        SQL_INSERTAR,
        {
            "empresa_id": empresa_id,
            "usuario_id": usuario_id,
            "colaborador_id": colaborador_id,
            "accion": accion,
            "entidad": entidad,
            "entidad_id": entidad_id,
            "ip": ip,
            "origen": origen,
            "detalle": json.dumps(datos, ensure_ascii=False, default=str),
        },
    )
