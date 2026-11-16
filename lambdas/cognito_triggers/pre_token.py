"""``cognito-pre-token`` (LAM-09, evento V2): agrega ``empresa_id``, ``rol`` y ``usuario_id``.

- Usuario no registrado en la base: no agrega nada. La API lo rechaza (USUARIO_NO_REGISTRADO).
- Usuario inactivo: no se emiten tokens, en ningún tipo de inicio (CC-REQ-010).
- Inactividad (CC-REQ-004): al **renovar** tokens, se rechaza si ``ultima_actividad`` tiene más
  de 30 minutos. En un inicio de sesión interactivo no se aplica: la persona volvió a
  autenticarse con contraseña y MFA, y ``POST /sesion/iniciar`` (DSH-06) actualiza la actividad.
  Aplicarla también ahí dejaría fuera para siempre a quien no entra por más de 30 minutos.
- ``empresa_id``, ``rol`` y ``usuario_id`` salen de la base, nunca del cliente (design.md §11.1).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from cognito_triggers import comun

log = logging.getLogger("cognito_triggers")

INACTIVIDAD_MAXIMA = timedelta(minutes=30)
ORIGEN_RENOVACION = "TokenGeneration_RefreshTokens"
MENSAJE = "No fue posible iniciar sesión."


class SesionNoPermitida(Exception):  # noqa: N818
    pass


def _dict(padre: dict[str, Any], clave: str) -> dict[str, Any]:
    """El diccionario `padre[clave]`; si falta o es `None`, lo crea y lo deja en `padre`."""
    valor = padre.get(clave)
    if not isinstance(valor, dict):
        valor = padre[clave] = {}
    return valor


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    sub = (event.get("request", {}).get("userAttributes", {}) or {}).get("sub")
    if not sub:
        return event

    with comun.abrir_conexion() as conn:
        fila = conn.execute(
            "SELECT usuario_id, empresa_id, rol, activo, ultima_actividad "
            "FROM identidad.usuario_por_sub(%s)",
            (sub,),
        ).fetchone()
    if fila is None:
        return event

    usuario_id, empresa_id, rol, activo, ultima = fila
    if not activo:
        log.warning("token rechazado", extra={"motivo": "usuario_inactivo"})
        raise SesionNoPermitida(MENSAJE)
    if (
        event.get("triggerSource") == ORIGEN_RENOVACION
        and ultima is not None
        and datetime.now(UTC) - ultima > INACTIVIDAD_MAXIMA
    ):
        log.warning("token rechazado", extra={"motivo": "inactividad"})
        raise SesionNoPermitida(MENSAJE)

    # Cognito envía las claves de la respuesta presentes pero en `null`: `setdefault` no las
    # reemplaza, así que cada nivel se asegura con `_dict` (falla vista al iniciar sesión en AWS).
    respuesta = _dict(event, "response")
    detalles = _dict(respuesta, "claimsAndScopeOverrideDetails")
    acceso = _dict(detalles, "accessTokenGeneration")
    # usuario_id: los servicios lo necesitan para la bitácora y sus llaves foráneas sin leer
    # identidad.usuario (D-03); decisión de Samuel del 14 de noviembre de 2026.
    _dict(acceso, "claimsToAddOrOverride").update(
        {"empresa_id": str(empresa_id), "rol": rol, "usuario_id": str(usuario_id)}
    )
    return event
