"""Apoyo de las pruebas E2E (T-133): simula a Meta en el stack local (sin webhook ni Lambdas).

  uv run python frontend/tests/e2e/apoyo/wa.py enviar WA_ID [--texto TEXTO | --interactivo ID]
  uv run python frontend/tests/e2e/apoyo/wa.py salida WA_ID [--contiene TEXTO] [--desde ID] [--espera SEG]
  uv run python frontend/tests/e2e/apoyo/wa.py envejecer NUMERO_EMPLEADO [--horas 30]

``enviar`` escribe en ``wa-entrada.fifo`` de LocalStack el mensaje reducido que consume
``worker_entrada`` (``{"wamid", "wa_id", "texto", "interactivo_id"}``; grupo FIFO = SHA-256 del
``wa_id``), como lo haría la Lambda ``webhook-meta``.

``salida`` lee lo que el bot respondió: filas de ``whatsapp.outbox`` (el mensaje queda ahí aunque
no haya enviador que lo entregue). Solo para el stack local: usa el rol administrador de
desarrollo de ``scripts/local/constantes.py``. Imprime una línea JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid

import boto3
import psycopg

LOCALSTACK = "http://localhost:4566"
DB = dict(
    host="127.0.0.1",
    port=55432,
    dbname="command_center",
    user="cc_local",
    password="cc_local_solo_desarrollo",  # pragma: allowlist secret
)


def enviar(wa_id: str, texto: str | None, interactivo: str | None) -> dict:
    sqs = boto3.client(
        "sqs",
        endpoint_url=LOCALSTACK,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",  # pragma: allowlist secret
    )
    url = sqs.get_queue_url(QueueName="wa-entrada.fifo")["QueueUrl"]
    wamid = f"wamid.E2E{uuid.uuid4().hex}"
    cuerpo = {"wamid": wamid, "wa_id": wa_id, "texto": texto, "interactivo_id": interactivo}
    sqs.send_message(
        QueueUrl=url,
        MessageBody=json.dumps(cuerpo),
        MessageGroupId=hashlib.sha256(wa_id.encode()).hexdigest(),
        MessageDeduplicationId=wamid,
    )
    return {"wamid": wamid}


def salida(wa_id: str, contiene: str | None, desde: int, espera: float) -> dict:
    limite = time.monotonic() + espera
    while True:
        with psycopg.connect(**DB) as con:
            filas = con.execute(
                "SELECT id, payload FROM whatsapp.outbox WHERE id > %s AND payload->>'wa_id' = %s ORDER BY id",
                (desde, wa_id),
            ).fetchall()
        mensajes = [
            {
                "id": i,
                "texto": p.get("texto"),
                "interactivo": p.get("interactivo"),
                "proposito": p.get("proposito"),
            }
            for i, p in filas
        ]
        if (
            contiene is None
            and mensajes
            or contiene
            and any(contiene in (m["texto"] or json.dumps(m["interactivo"])) for m in mensajes)
        ):
            return {"mensajes": mensajes}
        if time.monotonic() >= limite:
            return {"mensajes": mensajes, "agotado": True}
        time.sleep(1)


def envejecer(numero_empleado: str, horas: int) -> dict:
    """Retrasa el último mensaje entrante de la conversación de ese colaborador (ventana de 24 h cerrada).

    Escribe directo en la base LOCAL, solo sobre la conversación del colaborador de la prueba."""
    with psycopg.connect(**DB) as con:
        n = con.execute(
            "UPDATE whatsapp.conversacion_whatsapp SET ultimo_mensaje_entrante_at = now() - make_interval(hours => %s)"
            " WHERE colaborador_id = (SELECT id FROM colaboradores.colaborador WHERE numero_empleado = %s)",
            (horas, numero_empleado),
        ).rowcount
    return {"actualizadas": n}


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enviar")
    e.add_argument("wa_id")
    e.add_argument("--texto")
    e.add_argument("--interactivo")
    s = sub.add_parser("salida")
    s.add_argument("wa_id")
    s.add_argument("--contiene")
    s.add_argument("--desde", type=int, default=0)
    s.add_argument("--espera", type=float, default=0)
    v = sub.add_parser("envejecer")
    v.add_argument("numero_empleado")
    v.add_argument("--horas", type=int, default=30)
    a = p.parse_args()
    if a.cmd == "enviar":
        r = enviar(a.wa_id, a.texto, a.interactivo)
    elif a.cmd == "salida":
        r = salida(a.wa_id, a.contiene, a.desde, a.espera)
    else:
        r = envejecer(a.numero_empleado, a.horas)
    sys.stdout.write(json.dumps(r) + "\n")


if __name__ == "__main__":
    main()
