"""Conexión con Meta: lectura, guardado parcial, token de verificación y prueba de conexión.

Reglas:
- Los valores secretos solo existen en el secreto de Secrets Manager (``AlmacenMeta``). No pasan
  por la base de datos, los logs ni las respuestas; la bitácora lleva solo los **nombres** de los
  campos.
- **Carrera de escritura.** Guardar es lectura, mezcla y ``PutSecretValue`` (Secrets Manager no
  tiene escritura condicional). Para que dos guardados simultáneos, incluso en tareas distintas de
  Fargate, no se pisen, el ciclo completo corre bajo ``pg_advisory_xact_lock`` dentro de la misma
  transacción que escribe la bitácora: la bitácora se inserta primero y el secreto se escribe al
  final, de modo que si Secrets Manager falla se revierte todo. Queda una ventana mínima (la
  confirmación de la transacción tras escribir el secreto) que, con una sola persona
  administrando, se acepta.
- Después de guardar se invalida el caché de credenciales de este proceso; los demás procesos y las
  Lambdas toman el cambio al vencer su caché de 5 minutos.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.bitacora import registrar
from cc_common.db import transaccion
from cc_common.errores import ErrorCampo, ErrorValidacion
from sqlalchemy import text

from cc_notificaciones import sonda_meta
from cc_notificaciones.integracion_meta import (
    AlmacenMeta,
    MetaGuardada,
    mezclar,
    ultimos4,
)

# Clave del candado de asesoría de PostgreSQL (bigint arbitrario y fijo para este secreto).
CANDADO_META = 7_340_120_001
ENTIDAD = "integracion_meta"
ETIQUETAS = {
    "waba_id": "WABA ID",
    "phone_number_id": "Phone Number ID",
    "access_token": "Access token",
    "app_secret": "App Secret",  # pragma: allowlist secret
    "verify_token": "Verify token",
}


def estado_publico(g: MetaGuardada, version_defecto: str) -> dict[str, Any]:
    """Lo que devuelve el GET: nunca un valor secreto; solo los últimos 4 si miden 12 o más."""
    return {
        "configurada": g.configurada,
        "waba_id": g.waba_id,
        "phone_number_id": g.phone_number_id,
        "api_version": g.api_version or version_defecto,
        "access_token": {
            "configurado": bool(g.access_token),
            "ultimos4": ultimos4(g.access_token),
        },
        "app_secret": {"configurado": bool(g.app_secret), "ultimos4": ultimos4(g.app_secret)},
        "verify_token": {"configurado": bool(g.verify_token)},
        "actualizado_en": g.actualizado_en,
        "actualizado_por_usuario_id": g.actualizado_por_usuario_id,
    }


async def obtener(almacen: AlmacenMeta, version_defecto: str) -> dict[str, Any]:
    datos = await asyncio.to_thread(almacen.leer)
    return estado_publico(MetaGuardada.de_json(datos), version_defecto)


async def _bloquear(conn) -> None:
    await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CANDADO_META})


async def guardar(
    motor,
    almacen: AlmacenMeta,
    u: UsuarioActual,
    cambios: dict[str, str],
    *,
    version_defecto: str,
    ahora: datetime | None = None,
    al_guardar: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Cambia solo los campos de ``cambios`` y conserva el resto (bitácora ``META_CONFIGURADA``)."""
    usuario_id = requerir_usuario_id(u)
    ahora = ahora or datetime.now(UTC)
    async with transaccion(motor, u.empresa_id) as conn:
        await _bloquear(conn)
        actual = await asyncio.to_thread(almacen.leer)
        nuevo, cambiados = mezclar(actual, cambios, usuario_id=usuario_id, ahora=ahora)
        if cambiados:
            await registrar(
                conn,
                empresa_id=u.empresa_id,
                usuario_id=usuario_id,
                accion="META_CONFIGURADA",
                entidad=ENTIDAD,
                detalle={"campos": sorted(cambiados)},
            )
            await asyncio.to_thread(almacen.escribir, nuevo)
    if cambiados and al_guardar is not None:
        al_guardar()
    return estado_publico(MetaGuardada.de_json(nuevo), version_defecto)


def generar_verify_token() -> str:
    """43 caracteres de ``[A-Za-z0-9_-]`` con 256 bits de entropía."""
    return secrets.token_urlsafe(32)


async def generar_token_verificacion(
    motor,
    almacen: AlmacenMeta,
    u: UsuarioActual,
    *,
    version_defecto: str,
    ahora: datetime | None = None,
    al_guardar: Callable[[], None] | None = None,
) -> str:
    """Crea y guarda un token nuevo; es la única vez que se devuelve (``META_CONFIGURADA``)."""
    nuevo = generar_verify_token()
    await guardar(
        motor,
        almacen,
        u,
        {"verify_token": nuevo},
        version_defecto=version_defecto,
        ahora=ahora,
        al_guardar=al_guardar,
    )
    return nuevo


async def probar(
    motor,
    almacen: AlmacenMeta,
    u: UsuarioActual,
    *,
    base: str,
    version_defecto: str,
    timeout_s: float,
    transporte: httpx.AsyncBaseTransport | None = None,
) -> sonda_meta.ResultadoPrueba:
    """Consulta la Graph API con lo guardado. ``META_NO_CONFIGURADA`` (422) si falta algo."""
    usuario_id = requerir_usuario_id(u)
    g = MetaGuardada.de_json(await asyncio.to_thread(almacen.leer))
    faltan = [c for c in ("waba_id", "phone_number_id", "access_token") if not getattr(g, c)]
    if faltan:
        raise ErrorValidacion(
            "META_NO_CONFIGURADA",
            "Faltan credenciales de Meta: guárdelas antes de probar la conexión.",
            errores=[
                ErrorCampo(c, "REQUERIDO", f"Falta guardar el campo {ETIQUETAS[c]}.")
                for c in faltan
            ],
        )
    resultado = await sonda_meta.probar(
        base=base,
        version=g.api_version or version_defecto,
        phone_number_id=g.phone_number_id or "",
        waba_id=g.waba_id or "",
        access_token=g.access_token or "",
        timeout_s=timeout_s,
        transporte=transporte,
    )
    detalle: dict[str, Any] = {"estado_nuevo": "OK" if resultado.ok else "FALLO"}
    if resultado.fallidas:
        detalle["campos"] = resultado.fallidas
    async with transaccion(motor, u.empresa_id) as conn:
        await registrar(
            conn,
            empresa_id=u.empresa_id,
            usuario_id=usuario_id,
            accion="META_PROBADA",
            entidad=ENTIDAD,
            detalle=detalle,
        )
    return resultado
