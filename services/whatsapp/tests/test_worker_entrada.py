"""T-212 (T-099): ``worker-whatsapp-entrada`` con SQS FIFO en LocalStack, antiabuso y cierre por
inactividad."""

import asyncio
import json
import uuid

import boto3
import pytest
from ayudantes_whatsapp import CELULAR, huella_de, sql, textos_bot
from cc_whatsapp.bot import mensajes_es as M
from cc_whatsapp.bot.inactividad import cerrar_inactivas, depurar_contadores
from cc_whatsapp.normalizacion import grupo_de
from cc_whatsapp.workers.worker_entrada import atender_lote

pytestmark = pytest.mark.docker


@pytest.fixture
def cola(localstack):
    sqs = boto3.client(
        "sqs", endpoint_url=localstack, region_name="us-east-1",
        aws_access_key_id="test", aws_secret_access_key="test",
    )  # fmt: skip
    url = sqs.create_queue(
        QueueName=f"wa-entrada-{uuid.uuid4().hex[:8]}.fifo", Attributes={"FifoQueue": "true"}
    )["QueueUrl"]
    return sqs, url


def mandar(cola, wa_id, wamid, texto, dedup=None):
    sqs, url = cola
    cuerpo = {
        "wamid": wamid,
        "wa_id": wa_id,
        "tipo": "text",
        "texto": texto,
        "interactivo_id": None,
    }
    sqs.send_message(
        QueueUrl=url, MessageBody=json.dumps(cuerpo), MessageGroupId=grupo_de(wa_id),
        MessageDeduplicationId=dedup or wamid,
    )  # fmt: skip


async def leer_todo(cola, bot, vueltas=5):
    total = 0
    for _ in range(vueltas):
        total += await atender_lote(cola[0], cola[1], bot, espera_s=1)
    return total


async def test_consume_en_orden_por_numero_y_una_repeticion_no_duplica(bot, datos, cola):
    mandar(cola, CELULAR, "wamid.W1", "constancia")
    mandar(cola, CELULAR, "wamid.W2", "texto sin forma")
    mandar(cola, CELULAR, "wamid.W2", "texto sin forma", dedup="otra-entrega")  # misma wamid
    mandar(cola, CELULAR, "wamid.W3", "otro texto")
    assert await leer_todo(cola, bot) == 4  # el repetido también se consume (y se borra)
    textos = textos_bot(datos)
    assert textos[0].startswith("Antes de continuar") and "código de verificación" in textos[1]
    assert textos[2:] == [M.FORMATO_VERIFICACION, M.FORMATO_VERIFICACION]  # W2 una vez, W3 una vez
    assert sql(
        datos, "SELECT count(*) FROM whatsapp.mensaje_whatsapp WHERE direccion = 'ENTRANTE'"
    ) == [(3,)]


async def test_un_fallo_detiene_el_lote_y_el_mensaje_se_reintenta_sin_perder_el_orden(
    bot, datos, cola, monkeypatch
):
    mandar(cola, CELULAR, "wamid.F1", "constancia")
    mandar(cola, CELULAR, "wamid.F2", "sin forma")
    original = bot.colaboradores.buscar_por_celular
    llamadas = {"n": 0}

    async def inestable(empresa_id, celular):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise RuntimeError("colaboradores caído")
        return await original(empresa_id, celular)

    monkeypatch.setattr(bot.colaboradores, "buscar_por_celular", inestable)
    assert await atender_lote(cola[0], cola[1], bot, espera_s=1, visibilidad_s=1) == 0
    assert textos_bot(datos) == []  # F1 falló, F2 no se adelantó y nada quedó a medias
    await asyncio.sleep(2)  # vence la visibilidad: SQS entrega de nuevo, en orden
    assert await leer_todo(cola, bot, vueltas=4) == 2
    textos = textos_bot(datos)
    assert textos[0].startswith("Antes de continuar") and textos[-1] == M.FORMATO_VERIFICACION


# ------------------------------------------------------------------ cierre por inactividad


def conv_con(datos, *, estado, hace: str, solicitud=None, bloqueada_hasta=None, verificada=True):
    return sql(
        datos,
        "INSERT INTO whatsapp.conversacion_whatsapp (empresa_id, colaborador_id, estado, verificada, "
        "celular_hash, origen, solicitud_constancia_id, fecha_ultimo_mensaje, bloqueada_hasta) "
        "VALUES (%s, %s, %s, %s, decode(%s, 'hex'), 'CONSTANCIA', %s, now() - %s::interval, %s) "
        "RETURNING id",
        (datos["empresa"], datos["colaborador"], estado, verificada,
         huella_de(f"55{uuid.uuid4().int % 10**8:08d}"), solicitud, hace, bloqueada_hasta),
    )[0][0]  # fmt: skip


def estado_de(datos, conv_id):
    return sql(datos, "SELECT estado, solicitud_constancia_id FROM whatsapp.conversacion_whatsapp "
               "WHERE id = %s", (conv_id,))[0]  # fmt: skip


async def test_treinta_minutos_sin_mensajes_cierran_y_cancelan_la_solicitud_sin_confirmar(
    bot, datos
):
    inactiva = conv_con(datos, estado="ACTIVA", hace="31 minutes", solicitud=41)
    verificando = conv_con(datos, estado="VERIFICANDO", hace="45 minutes", verificada=False)
    reciente = conv_con(datos, estado="ACTIVA", hace="10 minutes", solicitud=42)
    assert await cerrar_inactivas(bot) == 2
    assert estado_de(datos, inactiva) == ("CERRADA", None)
    assert estado_de(datos, verificando)[0] == "CERRADA"
    assert estado_de(datos, reciente) == ("ACTIVA", 42)  # sigue abierta, con su solicitud
    assert bot.constancias.canceladas == [41]


async def test_un_bloqueo_vencido_se_cierra_y_uno_vigente_no(bot, datos):
    vencido = conv_con(datos, estado="BLOQUEADA", hace="25 hours", bloqueada_hasta="2000-01-01")
    vigente = conv_con(datos, estado="BLOQUEADA", hace="1 hour",
                       bloqueada_hasta="2999-01-01")  # fmt: skip
    await cerrar_inactivas(bot)
    assert estado_de(datos, vencido)[0] == "CERRADA" and estado_de(datos, vigente)[0] == "BLOQUEADA"


async def test_si_constancias_no_responde_la_conversacion_se_cierra_en_la_siguiente_pasada(
    bot, datos
):
    conv = conv_con(datos, estado="ACTIVA", hace="40 minutes", solicitud=7)
    original = bot.constancias.cancelar

    async def caido(empresa_id, solicitud_id):
        raise RuntimeError("constancias caído")

    bot.constancias.cancelar = caido
    assert await cerrar_inactivas(bot) == 0
    assert estado_de(datos, conv) == ("ACTIVA", 7)  # nada a medias
    bot.constancias.cancelar = original
    assert await cerrar_inactivas(bot) == 1
    assert bot.constancias.canceladas == [7]


async def test_los_contadores_viejos_se_depuran(bot, datos):
    h = huella_de(CELULAR)
    sql(datos, "INSERT INTO whatsapp.uso_numero (empresa_id, celular_hash, tipo, ventana, total) VALUES "
        "(%s, decode(%s, 'hex'), 'MENSAJE', now() - interval '3 days', 5), "
        "(%s, decode(%s, 'hex'), 'MENSAJE', now(), 1)", (datos["empresa"], h, datos["empresa"], h))  # fmt: skip
    assert await depurar_contadores(bot) == 1
    assert sql(datos, "SELECT count(*) FROM whatsapp.uso_numero") == [(1,)]
