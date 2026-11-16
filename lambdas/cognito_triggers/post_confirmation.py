"""``cognito-post-confirmation`` (LAM-08): crea el usuario tras confirmar el correo.

En una sola transacción: crea ``identidad.usuario`` (empresa de la invitación, rol RH), marca la
invitación como usada y registra ``USUARIO_REGISTRADO`` en la bitácora. Si algo falla, no queda
nada a medias. Es idempotente: Cognito puede reintentar el trigger (design.md §4.6;
CC-REQ-007, 008).

El código viaja en el atributo ``custom:codigo_invitacion`` (registro en ``progreso.md``). Al
terminar se sustituye por un valor inerte para no conservar el código en Cognito.
"""

from __future__ import annotations

import logging
from typing import Any

from cognito_triggers import comun

log = logging.getLogger("cognito_triggers")


def _registrar(conn: Any, sub: str, correo: str, nombre: str, codigo: str) -> bool:
    """Devuelve True si creó el usuario y False si ya existía (reintento)."""
    if conn.execute("SELECT 1 FROM identidad.usuario_por_sub(%s)", (sub,)).fetchone():
        return False
    inv = conn.execute(
        "SELECT invitacion_id, empresa_id, correo_destino FROM identidad.validar_invitacion(%s)",
        (comun.hash_codigo(codigo),),
    ).fetchone()
    if inv is None:
        raise comun.rechazar("codigo_no_valido")
    invitacion_id, empresa_id, correo_exigido = inv
    if correo_exigido and correo_exigido.strip().lower() != correo:
        raise comun.rechazar("correo_distinto")

    comun.fijar_empresa(conn, empresa_id)
    usuario_id = conn.execute(
        "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub, rol) "
        "VALUES (%s, %s, %s, %s, 'RH') RETURNING id",
        (empresa_id, nombre, correo, sub),
    ).fetchone()[0]
    usada = conn.execute(
        "UPDATE identidad.invitacion_registro SET usada_por_usuario_id = %s, fecha_uso = now() "
        "WHERE id = %s AND usada_por_usuario_id IS NULL",
        (usuario_id, invitacion_id),
    )
    if usada.rowcount != 1:  # otra confirmación se adelantó con el mismo código
        raise comun.rechazar("codigo_ya_usado")
    conn.execute(
        "INSERT INTO auditoria.bitacora "
        "(empresa_id, usuario_id, accion, entidad, entidad_id, origen) "
        "VALUES (%s, %s, 'USUARIO_REGISTRADO', 'usuario', %s, 'USUARIO')",
        (empresa_id, usuario_id, usuario_id),
    )
    return True


def _registrar_abierto(conn: Any, sub: str, correo: str, nombre: str) -> bool:
    """Registro sin invitación: la empresa es la única empresa activa. Idempotente."""
    if conn.execute("SELECT 1 FROM identidad.usuario_por_sub(%s)", (sub,)).fetchone():
        return False
    if not comun.dominio_permitido(correo):
        raise comun.rechazar("dominio_no_permitido")
    empresa_id = conn.execute("SELECT identidad.empresa_unica()").fetchone()[0]
    if empresa_id is None:
        raise comun.rechazar("sin_empresa_unica")
    comun.fijar_empresa(conn, empresa_id)
    usuario_id = conn.execute(
        "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub, rol) "
        "VALUES (%s, %s, %s, %s, 'RH') RETURNING id",
        (empresa_id, nombre, correo, sub),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO auditoria.bitacora "
        "(empresa_id, usuario_id, accion, entidad, entidad_id, origen) "
        "VALUES (%s, %s, 'USUARIO_REGISTRADO', 'usuario', %s, 'USUARIO')",
        (empresa_id, usuario_id, usuario_id),
    )
    return True


def _invalidar_codigo(event: dict[str, Any]) -> None:
    try:
        comun.cliente_cognito().admin_update_user_attributes(
            UserPoolId=event["userPoolId"],
            Username=event["userName"],
            UserAttributes=[{"Name": comun.ATRIBUTO_CODIGO, "Value": "usado"}],
        )
    except Exception:
        # El usuario ya quedó registrado y el código ya no sirve (está marcado como usado).
        log.warning("no se pudo invalidar el atributo del código", exc_info=True)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    # Se dispara también al confirmar un cambio de contraseña: ahí no hay nada que registrar.
    if event.get("triggerSource") != "PostConfirmation_ConfirmSignUp":
        return event

    atributos = event.get("request", {}).get("userAttributes", {}) or {}
    sub = atributos.get("sub")
    correo = (atributos.get("email") or "").strip().lower()
    nombre = (atributos.get("name") or "").strip() or correo
    if comun.registro_abierto():
        if not sub or not correo:
            raise comun.rechazar("datos_incompletos")
        with comun.abrir_conexion() as conn, conn.transaction():
            _registrar_abierto(conn, sub, correo, nombre)
        return event

    codigo = (atributos.get(comun.ATRIBUTO_CODIGO) or "").strip()
    if not sub or not correo or not codigo or len(codigo) > comun.CODIGO_LONGITUD_MAX:
        raise comun.rechazar("datos_incompletos")

    with comun.abrir_conexion() as conn, conn.transaction():
        creado = _registrar(conn, sub, correo, nombre, codigo)
    if creado:
        _invalidar_codigo(event)
    return event
