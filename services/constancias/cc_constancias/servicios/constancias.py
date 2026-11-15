"""Consulta, descarga y reenvío de constancias emitidas (CON-16 a CON-18; CC-REQ-087 a 089).

- **Descarga** (RH): solo si la entrega ya no está PENDIENTE; devuelve una URL firmada de CloudFront
  de 24 horas y registra ``CONSTANCIA_DESCARGADA`` con el usuario.
- **Reenvío**: solo con la entrega FALLIDA. Crea un token nuevo, escribe el mensaje de salida y deja
  la entrega otra vez PENDIENTE; registra ``CONSTANCIA_REENVIADA`` con el usuario.
"""

from __future__ import annotations

from typing import Any

from cc_common import bitacora
from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.db import transaccion
from cc_common.errores import ErrorConflicto, ErrorNoEncontrado

from cc_constancias.entrega.estrategia import Entrega, estrategia_por_modo
from cc_constancias.repos import solicitudes as repo
from cc_constancias.servicios import entrega as servicio_entrega

VIGENCIA_RH_S = 24 * 3600


async def detalle(motor, u: UsuarioActual, constancia_id: int) -> dict[str, Any]:
    async with transaccion(motor, u.empresa_id) as conn:
        c = await repo.detalle_constancia(conn, constancia_id)
    if c is None:
        raise ErrorNoEncontrado()
    return c


async def descarga(motor, firmador, u: UsuarioActual, constancia_id: int, ip: str | None):
    usuario_id = requerir_usuario_id(u)
    async with transaccion(motor, u.empresa_id) as conn:
        c = await repo.constancia_por_id(conn, constancia_id)
        if c is None:
            raise ErrorNoEncontrado()
        if c["estado_entrega"] == "PENDIENTE":
            raise ErrorConflicto(
                "CONSTANCIA_PENDIENTE", "La constancia todavía no se entrega al colaborador."
            )
        await bitacora.registrar(
            conn,
            empresa_id=u.empresa_id,
            accion="CONSTANCIA_DESCARGADA",
            entidad="constancia_generada",
            entidad_id=constancia_id,
            colaborador_id=c["colaborador_id"],
            usuario_id=usuario_id,
            ip=ip,
            detalle={"folio": c["folio"]},
        )
    return firmador.firmar(c["pdf_s3_key"], VIGENCIA_RH_S)


async def reenviar(motor, cfg, u: UsuarioActual, constancia_id: int, ip: str | None) -> None:
    usuario_id = requerir_usuario_id(u)
    estrategia = estrategia_por_modo(cfg.modo_entrega)
    async with transaccion(motor, u.empresa_id) as conn:
        c = await repo.constancia_por_id(conn, constancia_id)
        if c is None:
            raise ErrorNoEncontrado()
        if c["estado_entrega"] != "FALLIDA":
            raise ErrorConflicto(
                "ESTADO_INVALIDO",
                "Solo se reenvía una constancia cuya entrega falló.",
                detalle={"estado_actual": c["estado_entrega"], "estado_esperado": "FALLIDA"},
            )
        await servicio_entrega.preparar_entrega(
            conn,
            cfg,
            estrategia,
            Entrega(
                empresa_id=u.empresa_id,
                constancia_id=constancia_id,
                solicitud_id=c["solicitud_id"],
                colaborador_id=c["colaborador_id"],
                conversacion_id=c["conversacion_id"],
                folio=c["folio"],
                pdf_s3_key=c["pdf_s3_key"],
                reenvio=True,
            ),
            generado_por="RH_REENVIO",
            usuario_id=usuario_id,
        )
        await repo.marcar_entrega_pendiente(conn, constancia_id)
        await bitacora.registrar(
            conn,
            empresa_id=u.empresa_id,
            accion="CONSTANCIA_REENVIADA",
            entidad="constancia_generada",
            entidad_id=constancia_id,
            colaborador_id=c["colaborador_id"],
            usuario_id=usuario_id,
            ip=ip,
            detalle={"folio": c["folio"]},
        )
