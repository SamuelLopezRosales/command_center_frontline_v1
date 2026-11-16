"""T-142: despacho de 10,000 destinatarios (CC-NFR-003; §15.4: unas 1,000 llamadas por lotes).

Usa el despachador real (``lambdas/despachador``) con PostgreSQL de Testcontainers (RLS) y el doble
de contactos de ``colaboradores``. Dos variantes: (1) doble de SQS en memoria (mide el costo del
despachador y la base) y (2) una cola SQS FIFO real de LocalStack (suma las 1,000 llamadas
``send_message_batch``). Ninguna incluye Meta ni el ``enviador``: el límite real de envíos lo
marca el nivel de mensajería de la cuenta de WhatsApp (PQ-27).
"""

import json
import time
import uuid
from datetime import timedelta

import boto3
import pytest
from ayudantes_medicion import registrar
from despachador.handler import manejar
from notif_comun.config import ConfigNotifLambdas
from notif_comun.contactos import StubContactos
from notif_comun.metricas import CONTADORES
from notif_comun.pruebas import AHORA, ColaSqsFalsa, Mundo, evento_scheduler
from notif_comun.scheduler import StubScheduler

pytestmark = [pytest.mark.carga, pytest.mark.docker]

N = 10_000


@pytest.fixture
def mundo(bd_migrada):
    CONTADORES.clear()
    return Mundo(bd_migrada)


def _correr(mundo, nid, sqs, cola_url):
    cfg = ConfigNotifLambdas(
        cola_salida_url=cola_url, cola_despacho_url="notif-despacho", ambiente="test"
    )
    contactos = StubContactos(
        por_defecto=lambda i: {"elegible": True, "valores": {"nombre_completo": f"Nombre {i}"}}
    )
    evento = evento_scheduler({"notificacion_id": nid, "tipo": "INICIO", "empresa_id": mundo.a})
    t0 = time.perf_counter()
    r = manejar(
        evento,
        abrir=mundo.abrir,
        cfg=cfg,
        sqs=sqs,
        scheduler=StubScheduler(),
        contactos=contactos,
        restante_ms=lambda: 280_000,
        reloj=lambda: AHORA,
    )
    return r, time.perf_counter() - t0


def _programada(mundo):
    return mundo.notificacion(
        None,
        estado="PROGRAMADA",
        modo_envio="PROGRAMAR",
        destinatarios=N,
        programada_para=AHORA - timedelta(minutes=1),
    )


def test_despacho_de_10000_con_doble_de_sqs(mundo):
    nid = _programada(mundo)
    sqs = ColaSqsFalsa()
    r, segundos = _correr(mundo, nid, sqs, "wa-salida.fifo")
    assert r == {"batchItemFailures": []}
    salida = sqs.cuerpos("wa-salida.fifo")
    assert len(salida) == N == len({m["mensaje_uuid"] for m in salida})
    registrar("despacho 10,000 destinatarios (doble de SQS)", f"{segundos:.1f}", "s")
    assert mundo.contar(nid, "encolado_en IS NULL") == 0


def test_despacho_de_10000_con_sqs_fifo_real(mundo, localstack):
    sqs = boto3.client(
        "sqs",
        region_name="us-east-1",
        endpoint_url=localstack,
        aws_access_key_id="test",
        aws_secret_access_key="test",  # pragma: allowlist secret
    )
    url = sqs.create_queue(
        QueueName=f"carga-despacho-{uuid.uuid4().hex[:8]}.fifo",
        Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "false"},
    )["QueueUrl"]
    try:
        nid = _programada(mundo)
        r, segundos = _correr(mundo, nid, sqs, url)
        assert r == {"batchItemFailures": []}
        assert mundo.contar(nid, "encolado_en IS NULL") == 0
        registrar("despacho 10,000 destinatarios (SQS FIFO de LocalStack)", f"{segundos:.1f}", "s")
        # recibe todo lo publicado: 10,000 mensajes distintos (lotes de 10)
        vistos: set[str] = set()
        t0 = time.perf_counter()
        vacias = 0
        while len(vistos) < N and vacias < 5 and time.perf_counter() - t0 < 240:
            resp = sqs.receive_message(
                QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=1, VisibilityTimeout=600
            )
            mensajes = resp.get("Messages", [])
            vacias = 0 if mensajes else vacias + 1
            vistos.update(json.loads(m["Body"])["mensaje_uuid"] for m in mensajes)
        registrar("despacho 10,000: mensajes recibidos de la cola", len(vistos), "de 10000")
        assert len(vistos) == N
    finally:
        sqs.delete_queue(QueueUrl=url)
