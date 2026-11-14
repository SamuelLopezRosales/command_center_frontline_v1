"""Outbox transaccional y su relay (design.md §0.1 regla 4, §3.8, §8.1; CC-NFR-007).

Cada servicio escribe sus mensajes de cola y eventos en ``{esquema}.outbox`` dentro de la misma
transacción de negocio. Un relay los publica en SQS o EventBridge y marca ``publicado_en``.
Dos relays simultáneos no publican la misma fila gracias a ``FOR UPDATE SKIP LOCKED``.
La entrega es "al menos una vez": los consumidores deben ser idempotentes (``eventos.py``).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from cc_common.db import transaccion

_ESQUEMA = re.compile(r"^[a-z_]{1,40}$")
DestinoTipo = Literal["SQS", "EVENTBRIDGE"]

DDL_OUTBOX = """
CREATE TABLE IF NOT EXISTS {esquema}.outbox (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  evento_id     uuid NOT NULL UNIQUE,
  empresa_id    bigint,
  destino_tipo  text NOT NULL CHECK (destino_tipo IN ('SQS', 'EVENTBRIDGE')),
  destino       text NOT NULL,
  tipo          text NOT NULL,
  payload       jsonb NOT NULL,
  grupo         text,
  deduplicacion text,
  creado_en     timestamptz NOT NULL DEFAULT now(),
  publicado_en  timestamptz,
  intentos      int NOT NULL DEFAULT 0,
  ultimo_error  text
);
CREATE INDEX IF NOT EXISTS outbox_pendientes ON {esquema}.outbox (id) WHERE publicado_en IS NULL;
CREATE TABLE IF NOT EXISTS {esquema}.evento_procesado (
  evento_id     uuid PRIMARY KEY,
  procesado_en  timestamptz NOT NULL DEFAULT now()
);
"""


def esquema_valido(esquema: str) -> str:
    if not _ESQUEMA.match(esquema):
        raise ValueError("nombre de esquema inválido")
    return esquema


def ddl(esquema: str) -> str:
    """DDL de outbox y evento_procesado para un esquema (lo usan las migraciones)."""
    return DDL_OUTBOX.format(esquema=esquema_valido(esquema))


@dataclass(frozen=True)
class MensajeOutbox:
    id: int
    evento_id: uuid.UUID
    empresa_id: int | None
    destino_tipo: str
    destino: str
    tipo: str
    payload: dict[str, Any]
    grupo: str | None
    deduplicacion: str | None


async def escribir(
    conn: AsyncConnection,
    esquema: str,
    *,
    destino_tipo: DestinoTipo,
    destino: str,
    tipo: str,
    payload: Mapping[str, Any],
    empresa_id: int | None = None,
    grupo: str | None = None,
    deduplicacion: str | None = None,
    evento_id: uuid.UUID | None = None,
) -> uuid.UUID:
    eid = evento_id or uuid.uuid4()
    await conn.execute(
        text(
            f"""
            INSERT INTO {esquema_valido(esquema)}.outbox
              (evento_id, empresa_id, destino_tipo, destino, tipo, payload, grupo, deduplicacion)
            VALUES (:eid, :emp, :dt, :d, :t, CAST(:p AS jsonb), :g, :dd)
            """  # noqa: S608 - el esquema se valida con una expresión cerrada
        ),
        {
            "eid": eid,
            "emp": empresa_id,
            "dt": destino_tipo,
            "d": destino,
            "t": tipo,
            "p": json.dumps(dict(payload), ensure_ascii=False, default=str),
            "g": grupo,
            "dd": deduplicacion,
        },
    )
    return eid


Publicador = Callable[[MensajeOutbox], Awaitable[None]]


async def publicar_pendientes(
    motor: AsyncEngine, esquema: str, publicador: Publicador, *, lote: int = 50
) -> int:
    """Publica hasta ``lote`` mensajes pendientes. Devuelve cuántos se publicaron.

    Si una publicación falla, la fila queda pendiente con ``intentos + 1`` y el error (sin
    datos personales) para el siguiente ciclo; el resto del lote continúa.
    """
    e = esquema_valido(esquema)
    publicados = 0
    async with transaccion(motor, None) as conn:
        filas = (
            (
                await conn.execute(
                    text(
                        f"""
                    SELECT id, evento_id, empresa_id, destino_tipo, destino, tipo, payload,
                           grupo, deduplicacion
                    FROM {e}.outbox
                    WHERE publicado_en IS NULL
                    ORDER BY id
                    FOR UPDATE SKIP LOCKED
                    LIMIT :lote
                    """  # noqa: S608
                    ),
                    {"lote": lote},
                )
            )
            .mappings()
            .all()
        )
        for f in filas:
            msg = MensajeOutbox(**dict(f))
            try:
                await publicador(msg)
            except Exception as exc:  # noqa: BLE001
                await conn.execute(
                    text(
                        f"UPDATE {e}.outbox SET intentos = intentos + 1, "  # noqa: S608
                        "ultimo_error = :err WHERE id = :id"
                    ),
                    {"id": msg.id, "err": type(exc).__name__},
                )
                continue
            await conn.execute(
                text(f"UPDATE {e}.outbox SET publicado_en = now() WHERE id = :id"),  # noqa: S608
                {"id": msg.id},
            )
            publicados += 1
    return publicados


def publicador_aws(sqs: Any, eventbridge: Any, *, fuente: str) -> Publicador:
    """Publicador real con clientes boto3 (las llamadas son síncronas y cortas)."""

    async def _publicar(m: MensajeOutbox) -> None:
        cuerpo = json.dumps(
            {"evento_id": str(m.evento_id), "tipo": m.tipo, **m.payload},
            ensure_ascii=False,
            default=str,
        )
        if m.destino_tipo == "SQS":
            extra: dict[str, Any] = {}
            if m.destino.endswith(".fifo"):
                extra["MessageGroupId"] = m.grupo or "general"
                extra["MessageDeduplicationId"] = m.deduplicacion or str(m.evento_id)
            sqs.send_message(QueueUrl=m.destino, MessageBody=cuerpo, **extra)
        else:
            r = eventbridge.put_events(
                Entries=[
                    {
                        "Source": fuente,
                        "DetailType": m.tipo,
                        "Detail": cuerpo,
                        "EventBusName": m.destino,
                    }
                ]
            )
            if r.get("FailedEntryCount"):
                raise RuntimeError("EventBridge rechazó el evento")

    return _publicar
