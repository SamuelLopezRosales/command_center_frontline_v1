"""T-111: Lambda ``despachador`` con PostgreSQL real (RLS) y dobles de SQS, Scheduler y colaboradores."""

import json
from datetime import timedelta

import pytest
from despachador.handler import manejar, mensaje_uuid
from notif_comun.contactos import ContactosNoDisponible, StubContactos
from notif_comun.metricas import CONTADORES
from notif_comun.pruebas import AHORA, NOCHE, ColaSqsFalsa, evento_scheduler, evento_sqs
from notif_comun.scheduler import DESPACHO, RESPALDO, StubScheduler

pytestmark = pytest.mark.docker

SALIDA = "wa-salida.fifo"
DESPACHO_URL = "notif-despacho"


class Ctx:
    def __init__(self, mundo, ahora=AHORA, restante=lambda: 280_000, por_defecto=None):
        self.mundo = mundo
        self.sqs = ColaSqsFalsa()
        self.scheduler = StubScheduler()
        self.contactos = StubContactos(
            por_defecto=por_defecto
            or (lambda i: {"elegible": True, "valores": {"nombre_completo": f"Nombre {i}"}})
        )
        self.ahora = ahora
        self.restante = restante
        from notif_comun.config import ConfigNotifLambdas

        self.cfg = ConfigNotifLambdas(
            cola_salida_url=SALIDA, cola_despacho_url=DESPACHO_URL, ambiente="test"
        )

    def correr(self, evento):
        return manejar(
            evento,
            abrir=self.mundo.abrir,
            cfg=self.cfg,
            sqs=self.sqs,
            scheduler=self.scheduler,
            contactos=self.contactos,
            restante_ms=lambda: self.restante(),
            reloj=lambda: self.ahora,
        )

    def inicio(self, nid, empresa, tipo="INICIO"):
        return evento_scheduler({"notificacion_id": nid, "tipo": tipo, "empresa_id": empresa})

    @property
    def salida(self):
        return self.sqs.cuerpos(SALIDA)


def programada(mundo, empresa=None, **kw):
    kw.setdefault("programada_para", AHORA - timedelta(minutes=1))
    return mundo.notificacion(empresa, estado="PROGRAMADA", modo_envio="PROGRAMAR", **kw)


def test_programada_pasa_a_enviando_y_publica_con_uuid_determinista(mundo):
    nid = programada(mundo, destinatarios=3)
    c = Ctx(mundo)
    assert c.correr(c.inicio(nid, mundo.a)) == {"batchItemFailures": []}
    assert mundo.estado(nid) == "ENVIANDO"
    assert len(c.salida) == 3
    ids = [r[0] for r in mundo.sql("SELECT id FROM notificaciones.notificacion_destinatario "
                                   "WHERE notificacion_id = %s ORDER BY id", (nid,))]  # fmt: skip
    esperados = {mensaje_uuid(nid, i) for i in ids}
    assert {m["mensaje_uuid"] for m in c.salida} == esperados
    m = c.salida[0]
    assert m["origen_tipo"] == "NOTIFICACION" and m["origen_id"] == nid
    assert m["tipo"] == "PLANTILLA" and m["plantilla"] == "aviso_uniformes"
    assert m["max_intentos"] == 3 and m["proposito"] == "NOTIFICACION"
    assert m["empresa_id"] == mundo.a and m["variables"][1] == "20 nov 2026"
    assert m["variables"][0].startswith("Nombre ")
    # grupo FIFO por colaborador y deduplicación por mensaje_uuid
    reg = c.sqs.mensajes[SALIDA][0]
    assert reg["MessageGroupId"] == str(m["colaborador_id"])
    assert reg["MessageDeduplicationId"] == m["mensaje_uuid"]
    assert mundo.contar(nid, "estado_envio = 'PENDIENTE' AND encolado_en IS NOT NULL") == 3
    assert mundo.sql("SELECT fecha_envio FROM notificaciones.notificacion WHERE id = %s", (nid,))[
        0
    ][0]
    assert CONTADORES["destinatarios_encolados"] == 3 and CONTADORES["despachos"] == 1
    # solo variables resueltas por `colaboradores`: una sola llamada, propósito NOTIFICACION
    assert c.contactos.llamadas == [(mundo.a, 3, "NOTIFICACION", ("nombre_completo",))]


def test_enviar_ahora_ya_enviando_se_despacha(mundo):
    nid = mundo.notificacion(estado="ENVIANDO", destinatarios=2)
    c = Ctx(mundo)
    c.correr(c.inicio(nid, mundo.a))
    assert len(c.salida) == 2 and mundo.estado(nid) == "ENVIANDO"


def test_repetir_la_invocacion_no_duplica(mundo):
    nid = programada(mundo, destinatarios=25)
    c = Ctx(mundo)
    for _ in range(3):
        assert c.correr(c.inicio(nid, mundo.a)) == {"batchItemFailures": []}
    uuids = [m["mensaje_uuid"] for m in c.salida]
    assert len(uuids) == 25 == len(set(uuids))


def test_lotes_de_10_y_bloques_de_500(mundo):
    nid = programada(mundo, destinatarios=1234)
    c = Ctx(mundo)
    c.correr(c.inicio(nid, mundo.a))
    assert [n for (_, n, _, _) in c.contactos.llamadas] == [500, 500, 234]
    assert max(c.sqs.tamanos_lote) == 10 and sum(c.sqs.tamanos_lote) == 1234
    assert len({m["mensaje_uuid"] for m in c.salida}) == 1234


def test_diez_mil_destinatarios_sin_duplicar(mundo):
    nid = programada(mundo, destinatarios=10_000)
    c = Ctx(mundo)
    assert c.correr(c.inicio(nid, mundo.a)) == {"batchItemFailures": []}
    uuids = [m["mensaje_uuid"] for m in c.salida]
    assert len(uuids) == 10_000 == len(set(uuids))
    assert len({m["colaborador_id"] for m in c.salida}) == 10_000
    assert c.sqs.llamadas_lote == 1000  # 10,000 / 10
    assert mundo.contar(nid, "encolado_en IS NULL") == 0
    # una segunda invocación no publica nada más
    c.correr(c.inicio(nid, mundo.a, "CONTINUAR"))
    assert len(c.salida) == 10_000


def test_continuar_retoma_tras_el_limite_de_tiempo(mundo):
    nid = programada(mundo, destinatarios=1200)
    llamadas = {"n": 0}

    def restante():
        llamadas["n"] += 1
        return 280_000 if llamadas["n"] <= 2 else 10_000  # corta tras dos bloques

    c = Ctx(mundo, restante=restante)
    c.correr(c.inicio(nid, mundo.a))
    assert len(c.salida) == 1000
    [cont] = c.sqs.cuerpos(DESPACHO_URL)
    assert cont["tipo"] == "CONTINUAR" and cont["notificacion_id"] == nid
    assert cont["empresa_id"] == mundo.a and cont["evento_id"]
    assert (
        mundo.sql("SELECT fecha_envio FROM notificaciones.notificacion WHERE id = %s", (nid,))[0][0]
        is None
    )
    assert CONTADORES["despachos_continuados"] == 1
    # la invocación CONTINUAR (con tiempo) termina el trabajo sin repetir lo publicado
    c.restante = lambda: 280_000
    c.correr(evento_sqs(cont))
    uuids = [m["mensaje_uuid"] for m in c.salida]
    assert len(uuids) == 1200 == len(set(uuids))
    assert mundo.sql("SELECT fecha_envio FROM notificaciones.notificacion WHERE id = %s", (nid,))[
        0
    ][0]


@pytest.mark.parametrize("estado", ["CANCELADA", "BORRADOR", "COMPLETADA", "CON_FALLAS"])
def test_estados_que_no_despachan(mundo, estado):
    nid = mundo.notificacion(estado=estado, destinatarios=3, programada_para=None)
    c = Ctx(mundo)
    assert c.correr(c.inicio(nid, mundo.a)) == {"batchItemFailures": []}
    assert c.salida == [] and mundo.estado(nid) == estado
    assert mundo.contar(nid, "encolado_en IS NOT NULL") == 0
    assert CONTADORES["despachos_ignorados"] == 1


def test_cancelada_durante_el_despacho_detiene_los_bloques(mundo):
    nid = programada(mundo, destinatarios=1500)
    c = Ctx(mundo)
    vistas = {"n": 0}

    def restante():
        vistas["n"] += 1
        if vistas["n"] == 2:  # RH cancela entre el primer y el segundo bloque
            mundo.sql(
                "UPDATE notificaciones.notificacion SET estado = 'CANCELADA' WHERE id = %s", (nid,)
            )
        return 280_000

    c.restante = restante
    c.correr(c.inicio(nid, mundo.a))
    assert len(c.salida) == 500
    assert mundo.estado(nid) == "CANCELADA" and CONTADORES["despachos_interrumpidos"] == 1


def test_programada_adelantada_se_ignora(mundo):
    nid = mundo.notificacion(estado="PROGRAMADA", modo_envio="PROGRAMAR",
                             programada_para=AHORA + timedelta(hours=1))  # fmt: skip
    c = Ctx(mundo)
    c.correr(c.inicio(nid, mundo.a))
    assert c.salida == [] and mundo.estado(nid) == "PROGRAMADA"
    assert CONTADORES["despachos_adelantados"] == 1


def test_fuera_de_horario_reprograma_al_siguiente_inicio(mundo):
    nid = programada(mundo, destinatarios=3, schedule=f"cc-notif-{0}", programada_para=NOCHE)
    mundo.sql("UPDATE notificaciones.notificacion SET schedule_nombre = %s WHERE id = %s",
              (f"cc-notif-{nid}", nid))  # fmt: skip
    c = Ctx(mundo, ahora=NOCHE)  # 22:00 en Ciudad de México
    c.correr(c.inicio(nid, mundo.a))
    assert c.salida == []
    assert mundo.estado(nid) == "PROGRAMADA"
    [(nombre, expresion, zona, cuerpo, destino)] = [
        (s.nombre, s.expresion, s.zona, s.cuerpo, s.destino) for s in c.scheduler.schedules.values()
    ]
    assert nombre == f"cc-notif-{nid}-1" and destino == DESPACHO
    assert expresion == "at(2026-11-18T08:00:00)" and zona == "America/Mexico_City"
    assert cuerpo == {"notificacion_id": nid, "tipo": "INICIO", "empresa_id": mundo.a}
    fila = mundo.sql("SELECT programada_para, schedule_nombre FROM notificaciones.notificacion "
                     "WHERE id = %s", (nid,))[0]  # fmt: skip
    assert fila[0].isoformat() == "2026-11-18T14:00:00+00:00" and fila[1] == nombre
    assert CONTADORES["fuera_de_horario_reprogramados"] == 1
    # al llegar el nuevo inicio, despacha
    c.ahora = fila[0]
    c.correr(c.inicio(nid, mundo.a))
    assert len(c.salida) == 3 and mundo.estado(nid) == "ENVIANDO"


def test_fuera_de_horario_confirmado_si_despacha(mundo):
    nid = mundo.notificacion(estado="ENVIANDO", destinatarios=2, fuera_horario=True)
    c = Ctx(mundo, ahora=NOCHE)
    c.correr(c.inicio(nid, mundo.a))
    assert len(c.salida) == 2 and c.scheduler.schedules == {}


def test_enviar_ahora_sin_confirmacion_fuera_de_horario_se_difiere(mundo):
    nid = mundo.notificacion(estado="ENVIANDO", destinatarios=2, schedule=None)
    c = Ctx(mundo, ahora=NOCHE)
    c.correr(c.inicio(nid, mundo.a))
    assert c.salida == [] and mundo.estado(nid) == "PROGRAMADA"
    assert f"cc-notif-{nid}-1" in c.scheduler.schedules


def test_el_limite_de_las_20_es_inclusivo(mundo):
    nid = programada(mundo, destinatarios=1)
    c = Ctx(mundo, ahora=AHORA.replace(day=18, hour=2, minute=0))  # 20:00:00 en CDMX
    c.correr(c.inicio(nid, mundo.a))
    assert len(c.salida) == 1


def test_respaldo_programa_el_schedule_a_24_horas_al_terminar(mundo):
    nid = programada(mundo, destinatarios=2, respaldo=True)
    c = Ctx(mundo)
    c.correr(c.inicio(nid, mundo.a))
    [s] = c.scheduler.schedules.values()
    assert s.nombre == f"cc-notif-respaldo-{nid}" and s.destino == RESPALDO
    assert s.expresion == "at(2026-11-18T12:00:00)" and s.zona == "America/Mexico_City"
    assert s.cuerpo == {"notificacion_id": nid, "empresa_id": mundo.a}
    # repetir no crea otro schedule (mismo nombre) ni toca fecha_envio
    antes = mundo.sql("SELECT fecha_envio FROM notificaciones.notificacion WHERE id = %s", (nid,))[
        0
    ][0]
    c.ahora = AHORA + timedelta(hours=2)
    c.correr(c.inicio(nid, mundo.a, "CONTINUAR"))
    assert len(c.scheduler.schedules) == 1
    assert (
        mundo.sql("SELECT fecha_envio FROM notificaciones.notificacion WHERE id = %s", (nid,))[0][0]
        == antes
    )


def test_sin_respaldo_no_hay_schedule(mundo):
    nid = programada(mundo, destinatarios=2, respaldo=False)
    c = Ctx(mundo)
    c.correr(c.inicio(nid, mundo.a))
    assert c.scheduler.schedules == {}


def test_error_de_colaboradores_reintenta_y_no_marca_nada(mundo):
    nid = programada(mundo, destinatarios=4)
    c = Ctx(mundo)
    c.contactos.error = ContactosNoDisponible()
    r = c.correr(c.inicio(nid, mundo.a))
    assert r == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert mundo.contar(nid, "encolado_en IS NOT NULL") == 0 and c.salida == []
    c.contactos.error = None  # al reintentar, despacha
    assert c.correr(c.inicio(nid, mundo.a)) == {"batchItemFailures": []}
    assert len(c.salida) == 4


def test_publicacion_fallida_libera_el_lote_y_se_reintenta_sin_duplicar(mundo):
    nid = programada(mundo, destinatarios=12)
    ids = [r[0] for r in mundo.sql("SELECT id FROM notificaciones.notificacion_destinatario "
                                   "WHERE notificacion_id = %s ORDER BY id", (nid,))]  # fmt: skip
    c = Ctx(mundo)
    c.sqs.fallar_ids = {str(ids[3]), str(ids[11])}
    r = c.correr(c.inicio(nid, mundo.a))
    assert r == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert len(c.salida) == 10
    assert mundo.contar(nid, "encolado_en IS NULL") == 2  # liberados para el reintento
    assert (
        mundo.sql("SELECT fecha_envio FROM notificaciones.notificacion WHERE id = %s", (nid,))[0][0]
        is None
    )
    c.sqs.fallar_ids = set()
    assert c.correr(c.inicio(nid, mundo.a)) == {"batchItemFailures": []}
    uuids = [m["mensaje_uuid"] for m in c.salida]
    assert len(uuids) == 12 == len(set(uuids)) and set(uuids) == {mensaje_uuid(nid, i) for i in ids}


def test_sqs_caido_en_un_lote_libera_y_reintenta(mundo):
    nid = programada(mundo, destinatarios=5)
    c = Ctx(mundo)
    c.sqs.fallar_lote_numero = 1
    r = c.correr(c.inicio(nid, mundo.a))
    assert r["batchItemFailures"] and mundo.contar(nid, "encolado_en IS NULL") == 5
    c.sqs.fallar_lote_numero = None
    c.correr(c.inicio(nid, mundo.a))
    assert len(c.salida) == 5


def test_reintento_usa_otra_ronda_y_otro_uuid(mundo):
    nid = mundo.notificacion(estado="ENVIANDO", destinatarios=1)
    mundo.sql(
        "UPDATE notificaciones.notificacion_destinatario SET intentos = 1 WHERE notificacion_id = %s",
        (nid,),
    )
    [(did,)] = mundo.destinatarios(nid, "id")
    c = Ctx(mundo)
    c.correr(c.inicio(nid, mundo.a, "REINTENTO"))
    [m] = c.salida
    assert m["mensaje_uuid"] == mensaje_uuid(nid, did, 1) != mensaje_uuid(nid, did, 0)


def test_solo_toma_pendientes_sin_encolar(mundo):
    nid = mundo.notificacion(estado="ENVIANDO", destinatarios=4)
    ids = [r[0] for r in mundo.destinatarios(nid, "id")]
    mundo.sql(
        "UPDATE notificaciones.notificacion_destinatario SET estado_envio = 'ENVIADO' WHERE id = %s",
        (ids[0],),
    )
    mundo.sql(
        "UPDATE notificaciones.notificacion_destinatario SET encolado_en = now() WHERE id = %s",
        (ids[1],),
    )
    c = Ctx(mundo)
    c.correr(c.inicio(nid, mundo.a))
    assert {m["mensaje_uuid"] for m in c.salida} == {mensaje_uuid(nid, i) for i in ids[2:]}


def test_sin_variables_de_colaborador_no_consulta_colaboradores(mundo):
    nid = mundo.notificacion(estado="ENVIANDO", destinatarios=3,
                             variables={"1": {"origen": "FIJO", "valor": "x"},
                                        "2": {"origen": "FIJO", "valor": "y"}})  # fmt: skip
    c = Ctx(mundo)
    c.correr(c.inicio(nid, mundo.a))
    assert c.contactos.llamadas == [] and len(c.salida) == 3
    assert c.salida[0]["variables"] == ["x", "y"]


def test_aislamiento_por_empresa(mundo):
    na = programada(mundo, mundo.a, destinatarios=2)
    nb = programada(mundo, mundo.b, destinatarios=3, primer_colaborador=5000)
    c = Ctx(mundo)
    # un mensaje con la empresa equivocada no ve la notificación (RLS): se ignora
    c.correr(c.inicio(na, mundo.b))
    assert c.salida == [] and mundo.estado(na) == "PROGRAMADA"
    c.correr(c.inicio(na, mundo.a))
    c.correr(c.inicio(nb, mundo.b))
    por_empresa = {}
    for m in c.salida:
        por_empresa.setdefault(m["empresa_id"], set()).add(m["origen_id"])
    assert por_empresa == {mundo.a: {na}, mundo.b: {nb}}
    assert [x[1] for x in c.contactos.llamadas if x[0] == mundo.b] == [3]


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"notificacion_id": "7", "empresa_id": 1},
        {"notificacion_id": 7},
        {"notificacion_id": 7, "empresa_id": 1, "tipo": "OTRO"},
        [1, 2],
    ],
)
def test_mensajes_invalidos_se_descartan_sin_reintentar(mundo, cuerpo):
    c = Ctx(mundo)
    assert c.correr(evento_sqs(cuerpo)) == {"batchItemFailures": []}
    assert CONTADORES["mensajes_invalidos"] == 1 and c.salida == []


def test_cuerpo_que_no_es_json(mundo):
    c = Ctx(mundo)
    ev = {"Records": [{"messageId": "m1", "receiptHandle": "r", "body": "no-json"}]}
    assert c.correr(ev) == {"batchItemFailures": []} and CONTADORES["mensajes_invalidos"] == 1


def test_el_mensaje_del_outbox_con_evento_id_se_acepta(mundo):
    nid = mundo.notificacion(estado="ENVIANDO", destinatarios=2)
    c = Ctx(mundo)
    ev = evento_sqs({"evento_id": "e1", "tipo": "INICIO", "notificacion_id": nid,
                     "empresa_id": mundo.a})  # fmt: skip
    c.correr(ev)
    assert len(c.salida) == 2
    json.dumps(c.salida)  # los mensajes son serializables


# --- SQS FIFO real (LocalStack) ------------------------------------------------------------------


def test_publica_en_una_cola_fifo_real_y_la_deduplicacion_absorbe_una_liberacion(mundo, localstack):
    import uuid as _uuid

    import boto3

    sqs = boto3.client(
        "sqs",
        region_name="us-east-1",
        endpoint_url=localstack,
        aws_access_key_id="test",
        aws_secret_access_key="test",  # pragma: allowlist secret
    )
    url = sqs.create_queue(
        QueueName=f"wa-salida-prueba-{_uuid.uuid4().hex[:8]}.fifo",
        Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "false"},
    )["QueueUrl"]
    nid = programada(mundo, destinatarios=35)
    c = Ctx(mundo)
    c.cfg = c.cfg.model_copy(update={"cola_salida_url": url})
    c.sqs = sqs
    assert c.correr(c.inicio(nid, mundo.a)) == {"batchItemFailures": []}
    # simula que el conciliador liberó todo: se vuelve a publicar con los mismos uuid
    mundo.sql(
        "UPDATE notificaciones.notificacion_destinatario SET encolado_en = NULL "
        "WHERE notificacion_id = %s",
        (nid,),
    )
    assert c.correr(c.inicio(nid, mundo.a, "CONTINUAR")) == {"batchItemFailures": []}
    recibidos = []
    for _ in range(10):
        r = sqs.receive_message(
            QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=1, VisibilityTimeout=120
        )
        recibidos += [json.loads(m["Body"]) for m in r.get("Messages", [])]
        if not r.get("Messages") and len(recibidos) >= 35:
            break
    assert len(recibidos) == 35 == len({m["mensaje_uuid"] for m in recibidos})
    assert {m["empresa_id"] for m in recibidos} == {mundo.a}
