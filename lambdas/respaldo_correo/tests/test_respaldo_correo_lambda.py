"""T-114: Lambda ``respaldo-correo`` con PostgreSQL real (RLS), dobles de SES/SNS y SES en LocalStack."""

import json
import urllib.request
import uuid
from datetime import timedelta

import pytest
from notif_comun.config import ConfigNotifLambdas
from notif_comun.contactos import ContactosNoDisponible, StubContactos
from notif_comun.metricas import CONTADORES
from notif_comun.pruebas import (
    AHORA,
    NOCHE,
    CorreoFalso,
    SnsFalso,
    evento_scheduler,
    evento_sqs,
    registro_sqs,
)
from notif_comun.scheduler import RESPALDO, StubScheduler
from respaldo_correo.handler import PIE, manejar

pytestmark = pytest.mark.docker

TEMA = "arn:aws:sns:us-east-1:000000000000:alertas-rh"
HACE_25H = AHORA - timedelta(hours=25)


def correo_de(i):
    return f"colab{i}@ejemplo.test"


def contacto(i):
    return {
        "elegible": True,
        "correo": correo_de(i),
        "valores": {"nombre_completo": f"Persona {i}", "puesto": "SECRETO"},
    }


class Ctx:
    def __init__(self, mundo, ahora=AHORA, contactos=None):
        self.mundo = mundo
        self.correo = CorreoFalso()
        self.sns = SnsFalso()
        self.scheduler = StubScheduler()
        self.contactos = contactos or StubContactos(por_defecto=contacto)
        self.ahora = ahora
        self.cfg = ConfigNotifLambdas(
            alertas_topic_arn=TEMA, ses_asunto="Aviso de RH", ambiente="test"
        )

    def correr(self, evento, **kw):
        return manejar(
            evento,
            abrir=self.mundo.abrir,
            cfg=self.cfg,
            contactos=self.contactos,
            correo=kw.get("correo", self.correo),
            sns=kw.get("sns", self.sns),
            scheduler=self.scheduler,
            reloj=lambda: self.ahora,
        )

    def mensaje(self, nid, empresa):
        return evento_scheduler({"notificacion_id": nid, "empresa_id": empresa})

    @property
    def destinos(self):
        return sorted(e["destino"] for e in self.correo.enviados)


def notificacion(mundo, **kw):
    kw.setdefault("estado", "COMPLETADA")
    kw.setdefault("respaldo", True)
    kw.setdefault("encolado_en", HACE_25H)
    kw.setdefault("estado_envio", "ENVIADO")
    return mundo.notificacion(**kw)


def poner(mundo, nid, estados):
    """Reparte estados entre los destinatarios (en orden de id)."""
    ids = [r[0] for r in mundo.destinatarios(nid, "id")]
    for did, est in zip(ids, estados, strict=True):
        mundo.sql(
            "UPDATE notificaciones.notificacion_destinatario SET estado_envio = %s WHERE id = %s",
            (est, did),
        )
    return ids


# --- envío ---------------------------------------------------------------------------------------


def test_toma_enviado_y_fallido_sin_entregado_y_envia_el_correo(mundo):
    nid = notificacion(mundo, destinatarios=4)
    ids = poner(mundo, nid, ["ENVIADO", "FALLIDO", "ENTREGADO", "LEIDO"])
    c = Ctx(mundo)
    assert c.correr(c.mensaje(nid, mundo.a)) == {"batchItemFailures": []}
    cols = [r[0] for r in mundo.sql("SELECT colaborador_id FROM notificaciones.notificacion_destinatario "
                                    "WHERE id = ANY(%s) ORDER BY id", (ids[:2],))]  # fmt: skip
    assert c.destinos == sorted(correo_de(i) for i in cols)
    filas = mundo.destinatarios(nid, "estado_envio, canal_usado, respaldo_enviado_en IS NOT NULL")
    assert filas == [("ENVIADO", "CORREO", True), ("FALLIDO", "CORREO", True),
                     ("ENTREGADO", None, False), ("LEIDO", None, False)]  # fmt: skip
    assert CONTADORES["respaldos_enviados"] == 2
    # solicitud a colaboradores: propósito CORREO y solo las variables de la plantilla
    assert c.contactos.llamadas == [(mundo.a, 2, "CORREO", ("nombre_completo",))]


def test_el_correo_solo_lleva_las_variables_de_la_plantilla(mundo):
    nid = notificacion(mundo, destinatarios=1)
    c = Ctx(mundo)
    c.correr(c.mensaje(nid, mundo.a))
    [e] = c.correo.enviados
    assert e["asunto"] == "Aviso de RH"
    assert e["texto"].startswith("Hola Persona ") and "20 nov 2026" in e["texto"]
    assert e["texto"].endswith(PIE)
    assert "SECRETO" not in e["texto"]  # un valor no pedido nunca entra (ni aunque llegara)
    assert set(e["etiquetas"]) == {"notificacion_id", "destinatario_id", "empresa_id"}


def test_el_correo_de_una_plantilla_con_nombre_sustituye_por_nombre(mundo):
    plantilla = mundo.crear_plantilla(
        mundo.a, "aviso_llegada", "Hola {{guest_name}}, te esperamos en {{lugar}}."
    )
    nid = notificacion(
        mundo,
        destinatarios=1,
        plantilla=plantilla,
        variables={
            "lugar": {"origen": "FIJO", "valor": "Recepción"},
            "guest_name": {"origen": "COLABORADOR", "campo": "nombre_completo"},
        },
    )
    c = Ctx(mundo)
    c.correr(c.mensaje(nid, mundo.a))
    [e] = c.correo.enviados
    assert e["texto"].startswith("Hola Persona ") and ", te esperamos en Recepción." in e["texto"]
    assert "{{" not in e["texto"] and "SECRETO" not in e["texto"]
    assert c.contactos.llamadas == [(mundo.a, 1, "CORREO", ("nombre_completo",))]


def test_no_envia_antes_de_24_horas(mundo):
    nid = notificacion(mundo, destinatarios=2, encolado_en=AHORA - timedelta(hours=23))
    c = Ctx(mundo)
    c.correr(c.mensaje(nid, mundo.a))
    assert c.correo.enviados == [] and c.contactos.llamadas == []


def test_repetir_el_mensaje_no_reenvia(mundo):
    nid = notificacion(mundo, destinatarios=3)
    c = Ctx(mundo)
    c.correr(c.mensaje(nid, mundo.a))
    c.correr(c.mensaje(nid, mundo.a))
    c.correr(c.mensaje(nid, mundo.a))
    assert len(c.correo.enviados) == 3


def test_varios_bloques(mundo):
    nid = notificacion(mundo, destinatarios=120)
    c = Ctx(mundo)
    c.correr(c.mensaje(nid, mundo.a))
    assert len(c.correo.enviados) == 120 == len(set(c.destinos))
    assert [n for (_, n, _, _) in c.contactos.llamadas] == [50, 50, 20]


@pytest.mark.parametrize("estado", ["CANCELADA", "BORRADOR", "PROGRAMADA"])
def test_estados_sin_respaldo(mundo, estado):
    nid = notificacion(
        mundo, destinatarios=2, estado=estado, programada_para=AHORA + timedelta(days=1)
    )
    c = Ctx(mundo)
    c.correr(c.mensaje(nid, mundo.a))
    assert c.correo.enviados == [] and CONTADORES["respaldos_ignorados"] == 1


def test_notificacion_sin_la_opcion_de_respaldo_se_ignora(mundo):
    nid = notificacion(mundo, destinatarios=2, respaldo=False)
    c = Ctx(mundo)
    c.correr(c.mensaje(nid, mundo.a))
    assert c.correo.enviados == []


# --- sin correo ----------------------------------------------------------------------------------


def test_sin_correo_marca_fallido_con_motivo_y_alerta_a_rh_sin_datos_personales(mundo):
    nid = notificacion(mundo, destinatarios=4)
    ids = poner(mundo, nid, ["ENVIADO", "ENVIADO", "FALLIDO", "ENVIADO"])
    cols = [r[0] for r in mundo.destinatarios(nid, "colaborador_id")]
    mundo.sql(
        "UPDATE notificaciones.notificacion_destinatario SET motivo_fallo = 'NUMERO_INVALIDO' WHERE id = %s",
        (ids[2],),
    )
    c = Ctx(
        mundo,
        contactos=StubContactos(
            {
                cols[0]: {"elegible": False, "motivo": "SIN_CORREO"},
                cols[1]: {"elegible": True, "correo": None, "valores": {}},  # elegible sin correo
                cols[2]: {"elegible": False, "motivo": "ESTATUS_BAJA"},
                cols[3]: contacto(cols[3]),
            }
        ),
    )
    c.correr(c.mensaje(nid, mundo.a))
    assert c.destinos == [correo_de(cols[3])]
    filas = mundo.destinatarios(
        nid, "estado_envio, motivo_fallo, canal_usado, respaldo_enviado_en IS NOT NULL"
    )
    assert filas == [
        ("FALLIDO", "SIN_CORREO", None, True),
        ("FALLIDO", "SIN_CORREO", None, True),
        ("FALLIDO", "NUMERO_INVALIDO", None, True),  # conserva el motivo original de WhatsApp
        ("ENVIADO", None, "CORREO", True),
    ]  # fmt: skip
    [alerta] = c.sns.cuerpos()
    assert alerta == {"tipo": "RESPALDO_SIN_CORREO", "notificacion_id": nid, "empresa_id": mundo.a,
                      "cantidad": 3, "motivos": {"SIN_CORREO": 2, "ESTATUS_BAJA": 1}}  # fmt: skip
    assert c.sns.publicados[0]["TopicArn"] == TEMA
    crudo = json.dumps(c.sns.publicados)
    assert "@" not in crudo and "Persona" not in crudo and "Nombre" not in crudo
    assert CONTADORES["sin_correo"] == 3
    # repetir no vuelve a alertar ni a enviar
    c.correr(c.mensaje(nid, mundo.a))
    assert len(c.sns.publicados) == 1 and len(c.correo.enviados) == 1


def test_no_elegible_por_baja_o_sin_consentimiento_no_recibe_correo(mundo):
    nid = notificacion(mundo, destinatarios=2)
    cols = [r[0] for r in mundo.destinatarios(nid, "colaborador_id")]
    c = Ctx(mundo, contactos=StubContactos({cols[0]: {"elegible": False, "motivo": "SIN_CONSENTIMIENTO"},
                                            cols[1]: {"elegible": False, "motivo": "ESTATUS_BAJA"}}))  # fmt: skip
    c.correr(c.mensaje(nid, mundo.a))
    assert c.correo.enviados == []
    assert {r[0] for r in mundo.destinatarios(nid, "motivo_fallo")} == {
        "SIN_CONSENTIMIENTO",
        "ESTATUS_BAJA",
    }


def test_si_falla_el_aviso_a_rh_no_se_envia_ni_se_marca_nada(mundo):
    nid = notificacion(mundo, destinatarios=2)
    cols = [r[0] for r in mundo.destinatarios(nid, "colaborador_id")]
    c = Ctx(mundo, contactos=StubContactos({cols[0]: {"elegible": False, "motivo": "SIN_CORREO"},
                                            cols[1]: contacto(cols[1])}))  # fmt: skip
    c.sns.error = RuntimeError("SNS caído")
    r = c.correr(c.mensaje(nid, mundo.a))
    assert r == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert c.correo.enviados == [] and mundo.contar(nid, "respaldo_enviado_en IS NOT NULL") == 0
    c.sns.error = None
    assert c.correr(c.mensaje(nid, mundo.a)) == {"batchItemFailures": []}
    assert len(c.correo.enviados) == 1 and len(c.sns.publicados) == 1


# --- horario ---------------------------------------------------------------------------------------


def test_fuera_de_horario_espera_al_siguiente_inicio(mundo):
    nid = notificacion(mundo, destinatarios=2)
    c = Ctx(mundo, ahora=NOCHE)  # 22:00 en Ciudad de México
    assert c.correr(c.mensaje(nid, mundo.a)) == {"batchItemFailures": []}
    assert c.correo.enviados == [] and mundo.contar(nid, "respaldo_enviado_en IS NOT NULL") == 0
    [s] = c.scheduler.schedules.values()
    assert s.nombre == f"cc-notif-respaldo-{nid}-d20261118" and s.destino == RESPALDO
    assert s.expresion == "at(2026-11-18T08:00:00)" and s.zona == "America/Mexico_City"
    assert s.cuerpo == {"notificacion_id": nid, "empresa_id": mundo.a}
    assert CONTADORES["respaldos_diferidos"] == 1
    c.ahora = NOCHE + timedelta(hours=10)  # al llegar el inicio, envía
    c.correr(c.mensaje(nid, mundo.a))
    assert len(c.correo.enviados) == 2


# --- errores de SES y de colaboradores ---------------------------------------------------------------


def test_error_transitorio_de_ses_reintenta_sin_duplicar(mundo):
    nid = notificacion(mundo, destinatarios=3)
    cols = [r[0] for r in mundo.destinatarios(nid, "colaborador_id")]
    c = Ctx(mundo)
    c.correo.transitorio_en = {correo_de(cols[1])}
    r = c.correr(c.mensaje(nid, mundo.a))
    assert r == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert c.destinos == [correo_de(cols[0])]  # el primero salió y quedó confirmado
    assert mundo.contar(nid, "respaldo_enviado_en IS NOT NULL") == 1
    c.correo.transitorio_en = set()
    assert c.correr(c.mensaje(nid, mundo.a)) == {"batchItemFailures": []}
    assert c.destinos == sorted(correo_de(i) for i in cols)  # cada uno, una sola vez


def test_rechazo_permanente_de_ses_marca_fallido(mundo):
    nid = notificacion(mundo, destinatarios=2)
    cols = [r[0] for r in mundo.destinatarios(nid, "colaborador_id")]
    c = Ctx(mundo)
    c.correo.rechazar = {correo_de(cols[0])}
    assert c.correr(c.mensaje(nid, mundo.a)) == {"batchItemFailures": []}
    assert mundo.destinatarios(nid, "estado_envio, motivo_fallo, canal_usado") == [
        ("FALLIDO", "CORREO_RECHAZADO", None), ("ENVIADO", None, "CORREO"),
    ]  # fmt: skip
    assert CONTADORES["correos_rechazados"] == 1


def test_colaboradores_caido_reintenta_sin_marcar(mundo):
    nid = notificacion(mundo, destinatarios=2)
    c = Ctx(mundo)
    c.contactos.error = ContactosNoDisponible()
    assert c.correr(c.mensaje(nid, mundo.a)) == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert mundo.contar(nid, "respaldo_enviado_en IS NOT NULL") == 0 and c.correo.enviados == []


# --- aislamiento y mensajes ------------------------------------------------------------------------


def test_aislamiento_por_empresa(mundo):
    na = notificacion(mundo, empresa=mundo.a, destinatarios=2)
    nb = notificacion(mundo, empresa=mundo.b, destinatarios=3, primer_colaborador=7000)
    c = Ctx(mundo)
    c.correr(c.mensaje(na, mundo.b))  # empresa equivocada: no ve la notificación
    assert c.correo.enviados == [] and CONTADORES["respaldos_ignorados"] == 1
    c.correr(c.mensaje(na, mundo.a))
    assert len(c.correo.enviados) == 2 and mundo.contar(nb, "respaldo_enviado_en IS NOT NULL") == 0
    c.correr(c.mensaje(nb, mundo.b))
    assert len(c.correo.enviados) == 5
    assert {x[0] for x in c.contactos.llamadas} == {mundo.a, mundo.b}


@pytest.mark.parametrize("cuerpo", [{"notificacion_id": 5}, {"empresa_id": 1}, {"x": 1}, [1]])
def test_mensajes_invalidos_se_descartan(mundo, cuerpo):
    c = Ctx(mundo)
    assert c.correr(evento_sqs(cuerpo)) == {"batchItemFailures": []}
    assert CONTADORES["mensajes_invalidos"] == 1


# --- rebotes y quejas (SES -> SNS -> notif-respaldo) -----------------------------------------------------


def evento_ses(tipo, nid, did, eid, **extra):
    return {
        "eventType": tipo,
        "mail": {"messageId": "m", "tags": {"notificacion_id": [str(nid)],
                                            "destinatario_id": [str(did)], "empresa_id": [str(eid)]}},
        **extra,
    }  # fmt: skip


def con_sobre_sns(ev):
    return {"Records": [registro_sqs({"Type": "Notification", "MessageId": "x",
                                      "Message": json.dumps(ev)})]}  # fmt: skip


def test_rebote_permanente_marca_fallido_y_alerta_una_vez(mundo):
    nid = notificacion(mundo, destinatarios=2)
    [d0, d1] = [r[0] for r in mundo.destinatarios(nid, "id")]
    mundo.sql(
        "UPDATE notificaciones.notificacion_destinatario SET canal_usado = 'CORREO' WHERE id = %s",
        (d0,),
    )
    ev = evento_ses("Bounce", nid, d0, mundo.a, bounce={"bounceType": "Permanent",
                                                        "bouncedRecipients": [{"emailAddress": "x@y.z"}]})  # fmt: skip
    c = Ctx(mundo)
    assert c.correr(con_sobre_sns(ev)) == {"batchItemFailures": []}
    assert mundo.destinatarios(nid, "estado_envio, motivo_fallo") == [
        ("FALLIDO", "CORREO_REBOTADO"),
        ("ENVIADO", None),
    ]
    [a] = c.sns.cuerpos()
    assert (
        a["tipo"] == "RESPALDO_REBOTE" and a["notificacion_id"] == nid and "@" not in json.dumps(a)
    )
    assert CONTADORES["rebotes"] == 1
    c.correr(con_sobre_sns(ev))  # repetido: no vuelve a alertar
    assert len(c.sns.publicados) == 1 and CONTADORES["rebotes"] == 2
    assert d1  # el otro destinatario no cambió


def test_rebote_transitorio_solo_cuenta_y_no_pisa_una_entrega(mundo):
    nid = notificacion(mundo, destinatarios=2)
    ids = poner(mundo, nid, ["ENVIADO", "ENTREGADO"])
    c = Ctx(mundo)
    c.correr(
        con_sobre_sns(
            evento_ses("Bounce", nid, ids[0], mundo.a, bounce={"bounceType": "Transient"})
        )
    )
    assert mundo.destinatarios(nid, "estado_envio") == [("ENVIADO",), ("ENTREGADO",)]
    c.correr(
        con_sobre_sns(
            evento_ses("Bounce", nid, ids[1], mundo.a, bounce={"bounceType": "Permanent"})
        )
    )
    assert mundo.destinatarios(nid, "estado_envio") == [("ENVIADO",), ("ENTREGADO",)]  # ya entregó
    assert c.sns.publicados == [] and CONTADORES["rebotes"] == 2


def test_queja_y_eventos_ajenos(mundo):
    nid = notificacion(mundo, destinatarios=1)
    [d] = [r[0] for r in mundo.destinatarios(nid, "id")]
    c = Ctx(mundo)
    c.correr(con_sobre_sns(evento_ses("Delivery", nid, d, mundo.a)))
    assert mundo.destinatarios(nid, "estado_envio") == [("ENVIADO",)]
    sin_etiquetas = {"eventType": "Bounce", "bounce": {"bounceType": "Permanent"}, "mail": {}}
    c.correr(con_sobre_sns(sin_etiquetas))
    assert CONTADORES["rebotes_sin_etiquetas"] == 1
    c.correr(con_sobre_sns(evento_ses("Complaint", nid, d, mundo.a)))
    assert mundo.destinatarios(nid, "estado_envio, motivo_fallo") == [("FALLIDO", "CORREO_QUEJA")]
    assert CONTADORES["quejas"] == 1


def test_rebote_de_otra_empresa_no_toca_nada(mundo):
    nid = notificacion(mundo, destinatarios=1)
    [d] = [r[0] for r in mundo.destinatarios(nid, "id")]
    c = Ctx(mundo)
    c.correr(
        con_sobre_sns(evento_ses("Bounce", nid, d, mundo.b, bounce={"bounceType": "Permanent"}))
    )
    assert mundo.destinatarios(nid, "estado_envio") == [("ENVIADO",)]


# --- SES y SNS reales en LocalStack ------------------------------------------------------------------


@pytest.fixture
def aws(localstack):
    import boto3

    kw = {
        "region_name": "us-east-1",
        "endpoint_url": localstack,
        "aws_access_key_id": "test",
        "aws_secret_access_key": "test",  # pragma: allowlist secret
    }
    ses = boto3.client("ses", **kw)
    try:
        ses.list_identities()
    except Exception:
        pytest.skip("LocalStack sin el servicio ses")
    return {"ses": ses, "sns": boto3.client("sns", **kw), "url": localstack}


def test_envio_real_por_ses_y_alerta_por_sns_en_localstack(mundo, aws):
    from respaldo_correo.correo import CorreoSes

    origen = f"rh-{uuid.uuid4().hex[:6]}@command-center.test"
    aws["ses"].verify_email_identity(EmailAddress=origen)
    tema = aws["sns"].create_topic(Name=f"alertas-rh-{uuid.uuid4().hex[:6]}")["TopicArn"]
    nid = notificacion(mundo, destinatarios=2)
    cols = [r[0] for r in mundo.destinatarios(nid, "colaborador_id")]
    c = Ctx(
        mundo,
        contactos=StubContactos(
            {cols[0]: contacto(cols[0]), cols[1]: {"elegible": False, "motivo": "SIN_CORREO"}}
        ),  # fmt: skip
    )
    c.cfg = ConfigNotifLambdas(alertas_topic_arn=tema, ambiente="test")
    c.correr(c.mensaje(nid, mundo.a), correo=CorreoSes(aws["ses"], origen), sns=aws["sns"])
    assert mundo.destinatarios(nid, "estado_envio, canal_usado, motivo_fallo") == [
        ("ENVIADO", "CORREO", None), ("FALLIDO", None, "SIN_CORREO"),
    ]  # fmt: skip
    with urllib.request.urlopen(f"{aws['url']}/_aws/ses") as r:  # noqa: S310
        enviados = [m for m in json.load(r)["messages"] if m["Source"] == origen]
    [m] = enviados
    assert m["Destination"]["ToAddresses"] == [correo_de(cols[0])]
    assert m["Subject"] == "Aviso de Recursos Humanos"
    assert (
        f"Persona {cols[0]}" in m["Body"]["text_part"] and "20 nov 2026" in m["Body"]["text_part"]
    )
    assert "SECRETO" not in m["Body"]["text_part"]


def test_ses_rechaza_un_origen_no_verificado_como_transitorio(mundo, aws):
    """Un origen sin verificar es un problema de configuración nuestro: el mensaje se reintenta (y
    termina en la DLQ con alarma); no se marca a nadie como FALLIDO."""
    from respaldo_correo.correo import CorreoSes

    nid = notificacion(mundo, destinatarios=1)
    c = Ctx(mundo)
    r = c.correr(
        c.mensaje(nid, mundo.a), correo=CorreoSes(aws["ses"], "no-verificado@command-center.test")
    )
    assert r == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert mundo.destinatarios(nid, "estado_envio, canal_usado") == [("ENVIADO", None)]
