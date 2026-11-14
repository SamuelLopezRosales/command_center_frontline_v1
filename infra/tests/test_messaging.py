"""T-041: aserciones del stack CcMessaging."""

import json

import pytest
from aws_cdk.assertions import Template

from infra.app import construir_stacks, crear_app
from infra.stacks.messaging import COLAS, RUTAS_EVENTOS

PERMITIDA = "034362033822"


@pytest.fixture(scope="module")
def plantilla() -> Template:
    app, amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    return Template.from_stack(construir_stacks(app, amb, destino)["messaging"])


def _colas(plantilla) -> dict[str, dict]:
    return {
        r["Properties"]["QueueName"]: r["Properties"]
        for r in plantilla.find_resources("AWS::SQS::Queue").values()
    }


def test_diez_colas_con_su_dlq(plantilla):
    colas = _colas(plantilla)
    assert len(colas) == 20
    for d in COLAS:
        sufijo = ".fifo" if d.fifo else ""
        assert f"cc-test-{d.nombre}{sufijo}" in colas
        assert f"cc-test-{d.nombre}-dlq{sufijo}" in colas


@pytest.mark.parametrize("d", COLAS, ids=lambda d: d.nombre)
def test_cola_visibilidad_recepciones_y_retencion(plantilla, d):
    sufijo = ".fifo" if d.fifo else ""
    colas = _colas(plantilla)
    p = colas[f"cc-test-{d.nombre}{sufijo}"]
    assert p["VisibilityTimeout"] == d.visibilidad_s
    assert p["MessageRetentionPeriod"] == 4 * 86400
    assert p["RedrivePolicy"]["maxReceiveCount"] == d.max_recepciones
    assert p.get("FifoQueue", False) is d.fifo
    dlq = colas[f"cc-test-{d.nombre}-dlq{sufijo}"]
    assert dlq["MessageRetentionPeriod"] == 14 * 86400
    assert dlq.get("FifoQueue", False) is d.fifo
    assert "RedrivePolicy" not in dlq  # una DLQ no tiene otra DLQ


def test_valores_de_la_tabla_4_1(plantilla):
    esperado = {
        "cola-pdf": (180, 3),
        "cola-cargas": (900, 2),
        "wa-entrada": (60, 5),
        "wa-salida": (180, 3),
        "wa-estados": (180, 5),
        "notif-despacho": (1800, 3),
        "notif-respaldo": (360, 3),
        "ev-colaboradores": (120, 5),
        "ev-constancias": (120, 5),
        "ev-notificaciones": (120, 5),
    }
    assert {d.nombre: (d.visibilidad_s, d.max_recepciones) for d in COLAS} == esperado


def test_todas_cifradas_con_kms_y_exigen_tls(plantilla):
    for p in _colas(plantilla).values():
        assert "KmsMasterKeyId" in p
    politicas = plantilla.find_resources("AWS::SQS::QueuePolicy")
    assert len(politicas) == 20
    for pol in politicas.values():
        assert any(
            s["Effect"] == "Deny" and s["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
            for s in pol["Properties"]["PolicyDocument"]["Statement"]
        )


def test_colas_fifo_son_wa_entrada_y_wa_salida(plantilla):
    fifo = {n for n, p in _colas(plantilla).items() if p.get("FifoQueue")}
    assert fifo == {
        "cc-test-wa-entrada.fifo",
        "cc-test-wa-salida.fifo",
        "cc-test-wa-entrada-dlq.fifo",
        "cc-test-wa-salida-dlq.fifo",
    }


def test_bus_con_archivo_de_7_dias(plantilla):
    (bus,) = plantilla.find_resources("AWS::Events::EventBus").values()
    assert bus["Properties"]["Name"] == "cc-test-eventos"
    (archivo,) = plantilla.find_resources("AWS::Events::Archive").values()
    assert archivo["Properties"]["RetentionDays"] == 7


def test_reglas_del_bus_hacia_las_colas_ev(plantilla):
    reglas = plantilla.find_resources("AWS::Events::Rule")
    assert len(reglas) == len(RUTAS_EVENTOS) == 5
    por_evento = {}
    for r in reglas.values():
        p = r["Properties"]
        (evento,) = p["EventPattern"]["detail-type"]
        assert "EventBusName" in p
        por_evento[evento] = len(p["Targets"])
    assert por_evento == {e: len(d) for e, d in RUTAS_EVENTOS.items()}
    # Cada destino es una cola ev-*.
    for destinos in RUTAS_EVENTOS.values():
        assert all(d.startswith("ev-") for d in destinos)


def test_rutas_de_eventos_segun_el_diseno():
    assert RUTAS_EVENTOS == {
        "campo.actualizado": ("ev-colaboradores", "ev-constancias"),
        "wa.mensaje_estado": ("ev-constancias", "ev-notificaciones"),
        "wa.respuesta_recibida": ("ev-notificaciones",),
        "wa.plantilla_estado": ("ev-notificaciones",),
        "wa.numero_invalido": ("ev-colaboradores",),
    }


def test_grupo_de_scheduler_y_rol_de_destino(plantilla):
    (grupo,) = plantilla.find_resources("AWS::Scheduler::ScheduleGroup").values()
    assert grupo["Properties"]["Name"] == "cc-test-envios"
    (rol,) = plantilla.find_resources("AWS::IAM::Role").values()
    assert rol["Properties"]["RoleName"] == "cc-test-scheduler-destino"
    confianza = rol["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]
    assert confianza["Principal"] == {"Service": "scheduler.amazonaws.com"}
    # Protección contra el "suplente confuso": cuenta y grupo de schedules.
    assert confianza["Condition"]["StringEquals"]["aws:SourceAccount"] == PERMITIDA
    assert "schedule/cc-test-envios/*" in json.dumps(confianza["Condition"]["ArnLike"])


def test_rol_de_scheduler_solo_escribe_en_las_dos_colas_de_envio(plantilla):
    (pol,) = plantilla.find_resources("AWS::IAM::Policy").values()
    sentencias = pol["Properties"]["PolicyDocument"]["Statement"]
    texto = json.dumps(sentencias)
    assert "sqs:SendMessage" in texto
    for s in sentencias:
        assert s["Resource"] != "*"
    recursos = json.dumps([s["Resource"] for s in sentencias if "sqs:SendMessage" in str(s)])
    assert "Colanotifdespacho" in recursos and "Colanotifrespaldo" in recursos
    assert "Colawasalida" not in recursos and "Colacolapdf" not in recursos


def test_tema_alertas_cifrado_y_con_tls(plantilla):
    (tema,) = plantilla.find_resources("AWS::SNS::Topic").values()
    assert tema["Properties"]["TopicName"] == "cc-test-alertas-rh"
    assert "KmsMasterKeyId" in tema["Properties"]
    (politica,) = plantilla.find_resources("AWS::SNS::TopicPolicy").values()
    assert any(
        s["Effect"] == "Deny" and s["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
        for s in politica["Properties"]["PolicyDocument"]["Statement"]
    )


def test_ses_identidad_por_correo_y_eventos_de_rebote_y_queja(plantilla):
    (ident,) = plantilla.find_resources("AWS::SES::EmailIdentity").values()
    assert ident["Properties"]["EmailIdentity"] == "samuel.lopez@honne.com"
    assert "DkimSigningAttributes" not in ident["Properties"]  # el dominio queda para PQ-22
    (conj,) = plantilla.find_resources("AWS::SES::ConfigurationSet").values()
    assert conj["Properties"]["DeliveryOptions"]["TlsPolicy"] == "REQUIRE"
    (dest,) = plantilla.find_resources("AWS::SES::ConfigurationSetEventDestination").values()
    cfg = dest["Properties"]["EventDestination"]
    assert set(cfg["MatchingEventTypes"]) == {"bounce", "complaint"}
    assert "SnsDestination" in cfg


def test_ses_solo_publica_en_el_tema_desde_su_conjunto_de_configuracion(plantilla):
    (politica,) = plantilla.find_resources("AWS::SNS::TopicPolicy").values()
    permitidas = [
        s for s in politica["Properties"]["PolicyDocument"]["Statement"] if s["Effect"] == "Allow"
    ]
    assert len(permitidas) == 1
    assert permitidas[0]["Principal"] == {"Service": "ses.amazonaws.com"}
    assert permitidas[0]["Condition"]["StringEquals"]["AWS:SourceAccount"] == PERMITIDA


def test_las_colas_se_borran_con_cdk_destroy_en_test(plantilla):
    for r in plantilla.find_resources("AWS::SQS::Queue").values():
        assert r["DeletionPolicy"] == "Delete"


def test_sin_credenciales(plantilla):
    assert "AKIA" not in json.dumps(plantilla.to_json())
