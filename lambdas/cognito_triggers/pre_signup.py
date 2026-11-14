"""``cognito-pre-signup`` (LAM-07): valida la invitación antes de permitir el registro.

Rechaza, con un mensaje genérico, un registro sin código, con código inexistente, vencido o
usado, o con un correo distinto al que exige la invitación. Nunca confirma al usuario ni verifica
su correo: eso lo hace Cognito con el código enviado por correo (design.md §4.6; CC-REQ-007, 008).
"""

from __future__ import annotations

from typing import Any

from cognito_triggers import comun


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    # Solo el registro abierto desde la aplicación. Los usuarios creados por un administrador o
    # por un proveedor externo no pasan por una invitación, así que se rechazan.
    if event.get("triggerSource") != "PreSignUp_SignUp":
        raise comun.rechazar("origen_no_permitido")

    atributos = event.get("request", {}).get("userAttributes", {}) or {}
    codigo = (atributos.get(comun.ATRIBUTO_CODIGO) or "").strip()
    correo = (atributos.get("email") or "").strip().lower()
    if not codigo or len(codigo) > comun.CODIGO_LONGITUD_MAX:
        raise comun.rechazar("sin_codigo")
    if not correo:
        raise comun.rechazar("sin_correo")

    with comun.abrir_conexion() as conn:
        fila = conn.execute(
            "SELECT invitacion_id, empresa_id, correo_destino "
            "FROM identidad.validar_invitacion(%s)",
            (comun.hash_codigo(codigo),),
        ).fetchone()

    if fila is None:
        raise comun.rechazar("codigo_no_valido")  # inexistente, vencido o usado
    _, _, correo_exigido = fila
    if correo_exigido and correo_exigido.strip().lower() != correo:
        raise comun.rechazar("correo_distinto")

    event["response"] = {
        **(event.get("response") or {}),
        "autoConfirmUser": False,
        "autoVerifyEmail": False,
        "autoVerifyPhone": False,
    }
    return event
