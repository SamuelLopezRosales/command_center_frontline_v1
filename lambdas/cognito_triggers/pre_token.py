"""``cognito-pre-token`` (LAM-09, versión 2 del evento): agrega ``empresa_id`` y ``rol``.

- Usuario no registrado en la base: no agrega nada. La API lo rechaza (USUARIO_NO_REGISTRADO).
- Usuario inactivo: no se emiten tokens, en ningún tipo de inicio (CC-REQ-010).
- Inactividad (CC-REQ-004): al **renovar** tokens, se rechaza si ``ultima_actividad`` tiene más
  de 30 minutos. En un inicio de sesión interactivo no se aplica: la persona volvió a
  autenticarse con contraseña y MFA, y ``POST /sesion/iniciar`` (DSH-06) actualiza la actividad.
  Aplicarla también ahí dejaría fuera para siempre a quien no entra por más de 30 minutos.
- ``empresa_id`` y ``rol`` salen siempre de la base, nunca del cliente (design.md §11.1).
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

    _, empresa_id, rol, activo, ultima = fila
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

    respuesta = event.setdefault("response", {}) or {}
    event["response"] = respuesta
    detalles = respuesta.setdefault("claimsAndScopeOverrideDetails", {})
    acceso = detalles.setdefault("accessTokenGeneration", {})
    acceso.setdefault("claimsToAddOrOverride", {}).update(
        {"empresa_id": str(empresa_id), "rol": rol}
    )
    return event
