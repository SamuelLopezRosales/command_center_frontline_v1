"""Chat de RH (WAP-01 a WAP-05; design.md §3.7, §7.3; CC-REQ-104, 115, 116).

- **Ventana de 24 horas** (``VentanaService``): texto libre solo con la ventana abierta (el último
  mensaje entrante del colaborador tiene menos de 24 horas); cerrada, 409 ``VENTANA_24H_CERRADA`` y
  solo se acepta una plantilla aprobada (WAP-04).
- **Contenido cifrado** (``cifrado.py``): lo que RH escribe se guarda en ``contenido_cifrado``
  (AES-GCM, AAD con la ``clave_idempotencia`` y la empresa) y se descifra solo al leer el hilo
  (WAP-02). Nada del contenido llega a logs ni a la bitácora.
- **Envío**: la fila queda ``ENCOLADO`` y el ``MensajeSalida`` (origen ``CHAT``) se escribe en el
  ``outbox`` en la misma transacción; el relay lo publica en ``wa-salida.fifo`` y el ``enviador``
  decide (de nuevo) la ventana, la elegibilidad del colaborador y el envío. Si el colaborador ya no
  es elegible el mensaje queda ``FALLIDO`` con su motivo.
- **Texto en el ``outbox``**: el mensaje de salida lleva el texto en claro (el ``enviador`` no
  descifra: no tiene KMS) igual que los demás mensajes de salida; viaja por SQS (TLS y cifrado en
  reposo) y no se registra en logs. Limitación conocida, ver ``progreso.md``.
- **Asignación**: ``whatsapp.usuario_asignable`` (migración 0003) comprueba que el usuario exista y
  sea de la misma empresa sin dar al servicio lectura de ``identidad``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from cc_common import bitacora, outbox
from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.crypto import ErrorCifrado
from cc_common.db import transaccion
from cc_common.errores import ErrorCampo, ErrorConflicto, ErrorNoEncontrado, ErrorValidacion
from cc_common.paginacion import CursorInvalido, codificar_cursor, decodificar_cursor

from cc_whatsapp.repos import chat as repo
from cc_whatsapp.servicios.ventana_service import VentanaService

log = logging.getLogger("cc.chat")

LIMITE_CONVERSACIONES = 100
LIMITE_MENSAJES = 200
_VARIABLE = re.compile(r"\{\{(\d+)\}\}")


def _ahora() -> datetime:
    return datetime.now(UTC)


def _cursor(valor: str | None) -> tuple[datetime, int] | None:
    if not valor:
        return None
    try:
        fecha, ident = decodificar_cursor(valor)
        if not isinstance(fecha, datetime):
            raise CursorInvalido("cursor inválido")
        return fecha, int(ident)
    except (CursorInvalido, ValueError, TypeError) as exc:
        raise ErrorValidacion(
            errores=[ErrorCampo("cursor", "CURSOR_INVALIDO", "El cursor no es válido.")]
        ) from exc


def _item(c: dict[str, Any], nombre: str | None, ventana: VentanaService, ahora: datetime):
    ultimo = c["ultimo_mensaje_entrante_at"]
    return {
        "id": c["id"],
        "colaborador_id": c["colaborador_id"],
        "colaborador_nombre": nombre,
        "estado": c["estado"],
        "origen": c["origen"],
        "verificada": c["verificada"],
        "ventana_abierta": ventana.abierta(ultimo, ahora),
        "ultimo_mensaje_entrante_at": ultimo,
        "fecha_ultimo_mensaje": c["fecha_ultimo_mensaje"],
        "asignada_a_usuario_id": c["asignada_a_usuario_id"],
        "fecha_asignacion": c["fecha_asignacion"],
        "ultima_notificacion_id": c["ultima_notificacion_id"],
    }


async def _nombres(colaboradores, empresa_id: int, ids: set[int]) -> dict[int, str | None]:
    """INT-COL-07 por colaborador, en paralelo. Si `colaboradores` falla, el nombre queda vacío:
    el listado no depende de él."""
    sem = asyncio.Semaphore(8)

    async def uno(i: int) -> tuple[int, str | None]:
        async with sem:
            try:
                return i, await colaboradores.nombre(empresa_id, i)
            except Exception:  # noqa: BLE001
                log.warning("no se pudo leer el nombre de un colaborador")
                return i, None

    return dict(await asyncio.gather(*(uno(i) for i in ids)))


# ------------------------------------------------------------------ WAP-01


async def listar(
    motor,
    colaboradores,
    ventana: VentanaService,
    u: UsuarioActual,
    *,
    notificacion_id: int | None,
    asignada_a: int | None,
    estado: str | None,
    cursor: str | None,
    limite: int | None,
    reloj: Callable[[], datetime] = _ahora,
) -> dict[str, Any]:
    n = max(1, min(limite or 30, LIMITE_CONVERSACIONES))
    async with transaccion(motor, u.empresa_id) as conn:
        filas = await repo.listar(
            conn, notificacion_id=notificacion_id, asignada_a=asignada_a, estado=estado,
            cursor=_cursor(cursor), limite=n + 1,
        )  # fmt: skip
    siguiente = None
    if len(filas) > n:
        filas = filas[:n]
        ultima = filas[-1]
        siguiente = codificar_cursor((ultima["fecha_ultimo_mensaje"], ultima["id"]))
    nombres = await _nombres(colaboradores, u.empresa_id, {f["colaborador_id"] for f in filas})
    ahora = reloj()
    return {
        "items": [_item(f, nombres.get(f["colaborador_id"]), ventana, ahora) for f in filas],
        "siguiente": siguiente,
    }


# ------------------------------------------------------------------ WAP-02


async def _conversacion(conn, conversacion_id: int) -> dict[str, Any]:
    c = await repo.obtener(conn, conversacion_id)
    if c is None:
        raise ErrorNoEncontrado()
    return c


async def mensajes(
    motor,
    cifrador,
    u: UsuarioActual,
    conversacion_id: int,
    *,
    cursor: str | None,
    limite: int | None,
) -> dict[str, Any]:
    n = max(1, min(limite or 50, LIMITE_MENSAJES))
    async with transaccion(motor, u.empresa_id) as conn:
        conv = await _conversacion(conn, conversacion_id)
        filas = await repo.mensajes(conn, conv, cursor=_cursor(cursor), limite=n + 1)
        siguiente = None
        if len(filas) > n:
            filas = filas[:n]
            siguiente = codificar_cursor((filas[-1]["fecha_hora"], filas[-1]["id"]))
        items = []
        async with cifrador.transaccion(conn, u.empresa_id):
            for f in filas:
                contenido = None
                if f["contenido_cifrado"] is not None:
                    try:
                        contenido = cifrador.descifrar(
                            f["contenido_cifrado"], empresa_id=u.empresa_id,
                            clave=f["clave_idempotencia"],
                        )  # fmt: skip
                    except ErrorCifrado:
                        log.warning("no se pudo descifrar un mensaje del chat")
                items.append(
                    {
                        "id": f["id"],
                        "direccion": f["direccion"],
                        "tipo": f["tipo"],
                        "plantilla": f["plantilla_meta"],
                        "contenido": contenido,
                        "estado": f["estado"],
                        "error_codigo": f["error_codigo"],
                        "origen_tipo": f["origen_tipo"],
                        "enviado_por_usuario_id": f["enviado_por_usuario_id"],
                        "fecha_hora": f["fecha_hora"],
                    }
                )
    return {"items": items, "siguiente": siguiente}


# ------------------------------------------------------------------ WAP-03 y WAP-04


async def _encolar(
    conn, cfg, cifrador, u: UsuarioActual, conv: dict[str, Any], *, tipo: str, contenido: str,
    plantilla: str | None, cuerpo_extra: dict[str, Any], ip: str | None,
    detalle: dict[str, Any],
) -> int:  # fmt: skip
    usuario_id = requerir_usuario_id(u)
    clave = uuid.uuid4()
    async with cifrador.transaccion(conn, u.empresa_id):
        blob = cifrador.cifrar(contenido, empresa_id=u.empresa_id, clave=clave)
    mensaje_id = await repo.insertar_saliente(
        conn, empresa_id=u.empresa_id, conversacion_id=conv["id"],
        colaborador_id=conv["colaborador_id"], clave=clave, tipo=tipo, plantilla=plantilla,
        contenido_cifrado=blob, usuario_id=usuario_id,
    )  # fmt: skip
    await repo.tocar_saliente(conn, conv["id"])
    cuerpo = {
        "mensaje_uuid": str(clave),
        "origen_tipo": "CHAT",
        "origen_id": conv["id"],
        "colaborador_id": conv["colaborador_id"],
        "conversacion_id": conv["id"],
        "empresa_id": u.empresa_id,
        "tipo": tipo,
        "proposito": "CHAT",
        "max_intentos": 3,
        **cuerpo_extra,
    }
    await outbox.escribir(
        conn, "whatsapp", destino_tipo="SQS", destino=cfg.cola_salida_url, tipo="mensaje_salida",
        payload=cuerpo, empresa_id=u.empresa_id, grupo=str(conv["colaborador_id"]),
        deduplicacion=str(clave),
    )  # fmt: skip
    await bitacora.registrar(
        conn, empresa_id=u.empresa_id, accion="MENSAJE_CHAT", entidad="conversacion_whatsapp",
        entidad_id=conv["id"], colaborador_id=conv["colaborador_id"], usuario_id=usuario_id,
        ip=ip, detalle={"conversacion_id": conv["id"], **detalle},
    )  # fmt: skip
    return mensaje_id


async def enviar_texto(
    motor, cfg, cifrador, ventana: VentanaService, u: UsuarioActual, conversacion_id: int,
    texto: str, ip: str | None, reloj: Callable[[], datetime] = _ahora,
) -> int:  # fmt: skip
    async with transaccion(motor, u.empresa_id) as conn:
        conv = await _conversacion(conn, conversacion_id)
        if not ventana.abierta(conv["ultimo_mensaje_entrante_at"], reloj()):
            raise ErrorConflicto(
                "VENTANA_24H_CERRADA",
                "La ventana de 24 horas está cerrada: solo puede enviar una plantilla aprobada.",
            )
        return await _encolar(
            conn, cfg, cifrador, u, conv, tipo="TEXTO", contenido=texto, plantilla=None,
            cuerpo_extra={"texto": texto}, ip=ip, detalle={"proposito": "TEXTO"},
        )  # fmt: skip


def armar(texto: str, variables: list[str]) -> str:
    """Rellena ``{{n}}`` con las variables (``{{1}}`` es la primera)."""
    return _VARIABLE.sub(lambda m: variables[int(m.group(1)) - 1], texto)


async def enviar_plantilla(
    motor, cfg, cifrador, notificaciones, u: UsuarioActual, conversacion_id: int,
    plantilla_mensaje_id: int, variables: list[str], ip: str | None,
) -> int:  # fmt: skip
    # La plantilla se consulta antes de abrir la transacción: no se retiene una conexión mientras
    # `notificaciones` responde.
    async with transaccion(motor, u.empresa_id) as conn:
        await _conversacion(conn, conversacion_id)
    p = await notificaciones.plantilla(u.empresa_id, plantilla_mensaje_id)
    if p is None:
        raise ErrorValidacion(
            "PLANTILLA_NO_ENCONTRADA",
            errores=[
                ErrorCampo("plantilla_mensaje_id", "NO_ENCONTRADA", "La plantilla no existe.")
            ],
        )
    if p["estado_meta"] != "APROBADA":
        raise ErrorValidacion(
            "PLANTILLA_NO_APROBADA",
            errores=[
                ErrorCampo(
                    "plantilla_mensaje_id", "NO_APROBADA",
                    "Solo se envían plantillas aprobadas por Meta.",
                )
            ],
        )  # fmt: skip
    numeros = {int(n) for n in _VARIABLE.findall(p["texto_con_variables"])}
    esperadas = max(numeros, default=0)
    if numeros != set(range(1, esperadas + 1)) or len(variables) != esperadas:
        raise ErrorValidacion(
            "VARIABLES_INVALIDAS",
            errores=[
                ErrorCampo(
                    "variables", "CANTIDAD_INCORRECTA",
                    f"La plantilla lleva {esperadas} variable(s).",
                )
            ],
        )  # fmt: skip
    async with transaccion(motor, u.empresa_id) as conn:
        conv = await _conversacion(conn, conversacion_id)
        return await _encolar(
            conn, cfg, cifrador, u, conv, tipo="PLANTILLA",
            contenido=armar(p["texto_con_variables"], variables), plantilla=p["nombre"],
            cuerpo_extra={"plantilla": p["nombre"], "variables": variables}, ip=ip,
            detalle={"plantilla_id": plantilla_mensaje_id, "proposito": "PLANTILLA"},
        )  # fmt: skip


# ------------------------------------------------------------------ WAP-05


async def asignar(
    motor, colaboradores, ventana: VentanaService, u: UsuarioActual, conversacion_id: int,
    usuario_id: int, ip: str | None, reloj: Callable[[], datetime] = _ahora,
) -> dict[str, Any]:  # fmt: skip
    actor = requerir_usuario_id(u)
    async with transaccion(motor, u.empresa_id) as conn:
        conv = await _conversacion(conn, conversacion_id)
        if not await repo.usuario_asignable(conn, u.empresa_id, usuario_id):
            raise ErrorValidacion(
                "USUARIO_NO_ENCONTRADO",
                errores=[ErrorCampo("usuario_id", "NO_ENCONTRADO", "El usuario no existe.")],
            )
        await repo.asignar(conn, conversacion_id, usuario_id)
        await bitacora.registrar(
            conn, empresa_id=u.empresa_id, accion="MODIFICACION", entidad="conversacion_whatsapp",
            entidad_id=conversacion_id, colaborador_id=conv["colaborador_id"], usuario_id=actor,
            ip=ip,
            detalle={"campos": ["asignada_a_usuario_id"], "conversacion_id": conversacion_id},
        )  # fmt: skip
        conv = await _conversacion(conn, conversacion_id)
    nombres = await _nombres(colaboradores, u.empresa_id, {conv["colaborador_id"]})
    return _item(conv, nombres.get(conv["colaborador_id"]), ventana, reloj())


__all__ = ["armar", "asignar", "enviar_plantilla", "enviar_texto", "listar", "mensajes"]
