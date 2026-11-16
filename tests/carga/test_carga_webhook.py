"""T-142: respuesta del webhook de Meta (candidato de §15.3: menos de 1 s, CC-NFR-002).

Mide el handler real (``lambdas/webhook_meta``) en proceso: verifica la firma HMAC, extrae el
mensaje y lo encola. Variantes: SQS en memoria y una cola FIFO real de LocalStack. NO incluye el
arranque en frío de la Lambda, ni API Gateway, ni la red hasta Meta: eso solo se mide en AWS con
``tests/carga/webhook_k6.js``. No necesita PostgreSQL.
"""

import time
import uuid

import boto3
import pytest
from ayudantes_medicion import p95, registrar
from ayudantes_whatsapp import ColaFalsa
from cc_whatsapp.config import ConfigWhatsapp
from simulador_meta import SimuladorMeta
from webhook_meta.handler import manejar

pytestmark = pytest.mark.carga

WA_ID = "5218112345678"
N = 300


def _medir(sim, cfg, sqs, eventos):
    tiempos = []
    for e in eventos:
        t0 = time.perf_counter()
        r = manejar(e, sqs=sqs, secretos=sim.secretos, cfg=cfg)
        tiempos.append(time.perf_counter() - t0)
        assert r["statusCode"] == 200
    return tiempos


def test_webhook_con_sqs_en_memoria():
    sim = SimuladorMeta()
    cfg = ConfigWhatsapp(
        meta_phone_number_id="PN-PRUEBA",
        cola_entrada_url="wa-entrada.fifo",
        cola_estados_url="wa-estados",
    )
    eventos = [
        sim.evento_post(sim.mensaje_entrante(WA_ID, "Hola", wamid=f"wamid.C{i}")) for i in range(N)
    ]
    t = _medir(sim, cfg, ColaFalsa(), eventos)
    registrar("webhook mensaje firmado (SQS en memoria)", f"{p95(t) * 1000:.2f}", "ms p95", n=N)
    assert p95(t) < 1.0


def test_webhook_con_sqs_fifo_real(localstack):
    sqs = boto3.client(
        "sqs",
        region_name="us-east-1",
        endpoint_url=localstack,
        aws_access_key_id="test",
        aws_secret_access_key="test",  # pragma: allowlist secret
    )
    sufijo = uuid.uuid4().hex[:8]
    fifo = sqs.create_queue(
        QueueName=f"carga-wa-entrada-{sufijo}.fifo",
        Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "false"},
    )["QueueUrl"]
    estados = sqs.create_queue(QueueName=f"carga-wa-estados-{sufijo}")["QueueUrl"]
    try:
        sim = SimuladorMeta()
        cfg = ConfigWhatsapp(
            meta_phone_number_id="PN-PRUEBA", cola_entrada_url=fifo, cola_estados_url=estados
        )
        entrantes = [
            sim.evento_post(sim.mensaje_entrante(WA_ID, "Hola", wamid=f"wamid.R{sufijo}{i}"))
            for i in range(N)
        ]
        de_estado = [
            sim.evento_post(sim.estado(f"wamid.S{sufijo}{i}", "delivered")) for i in range(N)
        ]
        t = _medir(sim, cfg, sqs, entrantes)
        registrar(
            "webhook mensaje firmado (SQS FIFO de LocalStack)",
            f"{p95(t) * 1000:.1f}",
            "ms p95",
            n=N,
        )
        assert p95(t) < 1.0
        t = _medir(sim, cfg, sqs, de_estado)
        registrar(
            "webhook estado de entrega (SQS estandar de LocalStack)",
            f"{p95(t) * 1000:.1f}",
            "ms p95",
            n=N,
        )
        assert p95(t) < 1.0
    finally:
        sqs.delete_queue(QueueUrl=fifo)
        sqs.delete_queue(QueueUrl=estados)
