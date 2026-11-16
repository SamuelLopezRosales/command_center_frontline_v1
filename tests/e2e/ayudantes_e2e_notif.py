"""Mundo de la prueba de extremo a extremo de las notificaciones (T-218, T-117).

``construir_mundo_notificaciones`` parte del mundo de la constancia (``ayudantes_e2e.construir_mundo``:
PostgreSQL con RLS, LocalStack, `campos`, `colaboradores`, el bot, el ``worker_entrada`` y las Lambdas
``webhook_meta``, ``enviador`` y ``estados_entrega``) y agrega las piezas REALES de las notificaciones:

- el servicio `notificaciones` (ASGI, token interno hacia `colaboradores` real) con la API de plantillas
  de Meta simulada (``simulador_meta``) y un ``StubScheduler`` en lugar de EventBridge Scheduler;
- el servicio `whatsapp` (chat de RH, WAP-01 a 05) con su cifrador y la plantilla leída de
  `notificaciones` por INT-NOT-01;
- las Lambdas ``despachador`` y ``respaldo_correo`` (la segunda con SES de LocalStack), con
  `colaboradores` real por HTTP interno (puente síncrono);
- el relay del outbox de `notificaciones` y el consumidor de ``ev-notificaciones``
  (``wa.plantilla_estado``, ``wa.mensaje_estado`` y ``wa.respuesta_recibida``).

Cada pieza se ejecuta con el bombeo de ``Mundo.bombear`` (sin tareas de fondo). Los relojes de las
piezas con horario (servicio `notificaciones` y Lambdas) son fijos y se mueven con ``RelojFijo``; el
resto usa el reloj real y la base (``now()``), que se mueve con SQL.
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg
from ayudantes_e2e import (
    EMISOR,
    SECRETO_INTERNO,
    KmsFalso,
    Mundo,
    PuenteSincrono,
    _cliente,
    cerrar_mundo,
    construir_mundo,
    emitir,
)

PLANTILLA_TEXTO = "Hola {{1}}, tu cita es el {{2}}."
PLANTILLA_EJEMPLOS = ["Ana", "20 de noviembre"]
VARIABLES = {
    "1": {"origen": "COLABORADOR", "campo": "nombre_completo"},
    "2": {"origen": "FIJO", "valor": "20 de noviembre"},
}
CELULARES = {
    "ana": "8111110001",
    "beto": "8111110002",
    "carla": "8111110003",
    "dario": "8111110004",
    "elena": "8111110005",
}
CORREOS = {"ana": "ana.notif@ejemplo.test", "beto": "beto.notif@ejemplo.test",
           "carla": "carla.notif@ejemplo.test"}  # fmt: skip
BASE_NOT = "/api/v1/notificaciones"
BASE_PLANTILLAS = "/api/v1/plantillas-mensaje"
BASE_CHAT = "/api/v1/conversaciones"


class RelojFijo:
    def __init__(self, ahora: datetime) -> None:
        self.ahora = ahora

    def __call__(self) -> datetime:
        return self.ahora


# martes 17/11/2026 12:00 en Ciudad de México (dentro del horario de 08:00 a 20:00)
MEDIODIA_CDMX = datetime(2026, 11, 17, 18, 0, tzinfo=UTC)
PROGRAMADA_PARA = datetime(2026, 11, 17, 20, 0, tzinfo=UTC)  # 14:00 CDMX


def wa_id(celular: str) -> str:
    return "521" + celular


class MundoNotificaciones(Mundo):
    """El mundo de la constancia más las piezas de las notificaciones."""

    def __init__(self) -> None:
        super().__init__()
        self.consumidos_not = 0
        self.relato: list[tuple[str, str]] = []
        self.colaboradores: dict[str, int] = {}
        self.colaboradores_b: dict[str, int] = {}
        self._vistos_meta = 0

    # ------------------------------------------------------------------ bombeo

    def _pasos(self) -> list[tuple[str, Any]]:
        return [
            ("relay-outbox whatsapp", self._relay_wa),
            ("worker-whatsapp-entrada", self._worker_entrada),
            ("relay-outbox constancias", self._relay_con),
            ("relay-outbox notificaciones", self._relay_not),
            ("lambda despachador", self._despachador),
            ("lambda respaldo-correo", self._respaldo),
            ("lambda enviador", self._enviador),
            ("lambda estados-entrega", self._estados),
            ("worker-pdf", self._worker_pdf),
            ("consumidor ev-constancias", self._consumidor),
            ("consumidor ev-notificaciones", self._consumidor_not),
        ]

    async def _relay_not(self) -> int:
        return await self._publicar(
            self.motores["svc_notificaciones"], "notificaciones", self.pub_not
        )

    async def _despachador(self) -> int:
        from despachador.handler import manejar

        msgs = self.aws.recibir(self.aws.despacho, maximo=1, visibilidad=120)
        for m in msgs:
            r = await asyncio.to_thread(
                manejar,
                {"Records": [self.aws.registro_lambda(m)]},
                abrir=self.abrir_not,
                cfg=self.cfg_lam,
                sqs=self.aws.sqs,
                scheduler=self.sched_lam,
                contactos=self.contactos_lam,
                restante_ms=lambda: 280_000,
                reloj=self.reloj_lam,
            )
            if not r["batchItemFailures"]:
                self.aws.borrar(self.aws.despacho, m)
        return len(msgs)

    async def _respaldo(self) -> int:
        from respaldo_correo.handler import manejar

        msgs = self.aws.recibir(self.aws.respaldo, maximo=1, visibilidad=120)
        for m in msgs:
            r = await asyncio.to_thread(
                manejar,
                {"Records": [self.aws.registro_lambda(m)]},
                abrir=self.abrir_not,
                cfg=self.cfg_lam,
                contactos=self.contactos_lam,
                correo=self.correo,
                sns=self.aws.sns,
                scheduler=self.sched_lam,
                reloj=self.reloj_lam,
            )
            if not r["batchItemFailures"]:
                self.aws.borrar(self.aws.respaldo, m)
        return len(msgs)

    async def _consumidor_not(self) -> int:
        from cc_common.tareas import cuerpo_de_evento
        from cc_notificaciones.consumidores import manejar_evento

        esperados = sum(
            n
            for k, n in self.publicados.items()
            if k
            in (
                "EVENTBRIDGE:wa.mensaje_estado",
                "EVENTBRIDGE:wa.plantilla_estado",
                "EVENTBRIDGE:wa.respuesta_recibida",
            )
        )
        espera = 3 if self.consumidos_not < esperados else 0  # EventBridge reparte en segundo plano
        msgs = self.aws.recibir(self.aws.ev_notificaciones, espera=espera)
        for m in msgs:
            evento = cuerpo_de_evento(json.loads(m["Body"]))
            try:
                await manejar_evento(self.motores["svc_notificaciones"], evento)
            except Exception:  # noqa: BLE001, S112 - sin borrar: SQS reentrega
                continue
            self.consumidos_not += 1
            self.aws.borrar(self.aws.ev_notificaciones, m)
        return len(msgs)

    # ------------------------------------------------------------------ transcripción

    def paso(self, titulo: str, detalle: str = "") -> None:
        self.relato.append((titulo, detalle))

    def _registrar_salidas(self) -> None:
        for e in self.sim.enviados[self._vistos_meta :]:
            quien = f"Meta -> ...{e['to'][-4:]}"
            if e["type"] == "template":
                t = e["template"]
                params = [p["text"] for c in t.get("components", []) for p in c["parameters"]]
                # el primer parámetro es el nombre del colaborador: no va a la transcripción
                texto = f"[plantilla {t['name']}] <nombre>, " + ", ".join(params[1:])
            else:
                texto = (
                    self._enmascarar(e["text"]["body"]) if e["type"] == "text" else f"[{e['type']}]"
                )
            self.transcripcion.append((quien, texto))
        self._vistos_meta = len(self.sim.enviados)

    # ------------------------------------------------------------------ llamadas de RH

    @property
    def rh_a(self) -> dict[str, str]:
        return self.a.rh

    @property
    def rh_b(self) -> dict[str, str]:
        return self.b.rh

    def rh_otro(self, empresa, usuario_id: int, sub: str) -> dict[str, str]:
        return emitir(sub, empresa.id, usuario_id)

    async def plantilla_aprobada(self, nombre: str, emp=None) -> int:
        """Borrador -> EN_REVISION (API de Meta simulada) -> aprobación de Meta -> webhook ->
        ``estados-entrega`` -> ``wa.plantilla_estado`` -> consumidor de `notificaciones`."""
        emp = emp or self.a
        r = await self.http_not.post(
            BASE_PLANTILLAS,
            json={"nombre": nombre, "categoria": "UTILITY", "idioma": "es_MX",
                  "texto_con_variables": PLANTILLA_TEXTO, "ejemplos": PLANTILLA_EJEMPLOS},
            headers=emp.rh,
        )  # fmt: skip
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        assert r.json()["estado_meta"] == "BORRADOR"
        r = await self.http_not.post(f"{BASE_PLANTILLAS}/{pid}/enviar-revision", headers=emp.rh)
        assert r.status_code == 202 and r.json()["estado_meta"] == "EN_REVISION", r.text
        assert self.sim.plantillas[nombre]["status"] == "PENDING"
        self.sim.aprobar(nombre)
        resp = self.webhook(self.sim.cambio_de_plantilla(nombre, "APPROVED"))
        assert resp["statusCode"] == 200
        await self.bombear(f"Meta aprueba la plantilla {nombre}")
        r = await self.http_not.get(f"{BASE_PLANTILLAS}/{pid}", headers=emp.rh)
        assert r.json()["estado_meta"] == "APROBADA", r.text
        return pid

    async def crear_notificacion(self, plantilla_id: int, *, emp=None, planta=None,
                                 respaldo=True, titulo="Aviso de cita") -> int:  # fmt: skip
        emp = emp or self.a
        planta = planta or self.planta_notif
        r = await self.http_not.post(
            BASE_NOT,
            json={
                "titulo": titulo,
                "modo": "CRITERIOS",
                "criterios": {"op": "Y", "items": [{"campo": "planta_id", "operador": "es",
                                                    "valor": planta}]},
                "plantilla_mensaje_id": plantilla_id,
                "variables": VARIABLES,
                "respaldo_correo": respaldo,
            },
            headers=emp.rh,
        )  # fmt: skip
        assert r.status_code == 201, r.text
        return r.json()["id"]

    async def revisar(self, nid: int, emp=None) -> dict:
        r = await self.http_not.post(f"{BASE_NOT}/{nid}/revisar", headers=(emp or self.a).rh)
        assert r.status_code == 200, r.text
        return r.json()

    async def confirmar(self, nid: int, emp=None, **cuerpo) -> httpx.Response:
        return await self.http_not.post(
            f"{BASE_NOT}/{nid}/confirmar", json=cuerpo or {"modo_envio": "AHORA"},
            headers=(emp or self.a).rh,
        )  # fmt: skip

    async def notificacion(self, nid: int, emp=None) -> dict:
        r = await self.http_not.get(f"{BASE_NOT}/{nid}", headers=(emp or self.a).rh)
        assert r.status_code == 200, r.text
        return r.json()

    def estado_notificacion(self, nid: int) -> str:
        return self.sql("SELECT estado FROM notificaciones.notificacion WHERE id = %s", (nid,))[0][
            0
        ]

    def destinatarios(self, nid: int) -> dict[str, tuple]:
        """``{nombre_corto: (estado_envio, motivo_exclusion, motivo_fallo, canal_usado)}``."""
        filas = self.sql(
            "SELECT colaborador_id, estado_envio, motivo_exclusion, motivo_fallo, canal_usado "
            "FROM notificaciones.notificacion_destinatario WHERE notificacion_id = %s",
            (nid,),
        )
        por_id = {v: k for k, v in self.colaboradores.items()}
        por_id.update({v: "b_" + k for k, v in self.colaboradores_b.items()})
        return {por_id[f[0]]: f[1:] for f in filas}

    # ------------------------------------------------------------------ lo que hace el tiempo

    async def disparar_schedule(self, nombre: str, *, ahora: datetime) -> dict:
        """EventBridge Scheduler entrega el cuerpo del schedule a ``notif-despacho``."""
        s = self.scheduler_not.schedules[nombre]
        self.reloj_lam.ahora = ahora
        self.aws.sqs.send_message(QueueUrl=self.aws.despacho, MessageBody=json.dumps(s.cuerpo))
        return s.cuerpo

    async def disparar_respaldo(self, nid: int, *, ahora: datetime) -> None:
        s = self.sched_lam.schedules[f"cc-notif-respaldo-{nid}"]
        self.reloj_lam.ahora = ahora
        self.aws.sqs.send_message(QueueUrl=self.aws.respaldo, MessageBody=json.dumps(s.cuerpo))

    def correos_enviados(self) -> list[dict]:
        """Correos que recibió SES de LocalStack con el origen de ESTA prueba."""
        with urllib.request.urlopen(f"{self.url_localstack}/_aws/ses") as r:  # noqa: S310
            todos = json.loads(r.read())["messages"]
        return [m for m in todos if m["Source"] == self.ses_origen]

    def cerrar_ventana(self, conversacion_id: int, horas: int = 30) -> None:
        self.sql(
            "UPDATE whatsapp.conversacion_whatsapp SET ultimo_mensaje_entrante_at = "
            "now() - make_interval(hours => %s) WHERE id = %s",
            (horas, conversacion_id),
        )

    def meta_a(self, nombre: str, tipo: str | None = None) -> list[dict]:
        """Lo que Meta entregó al colaborador (por su nombre corto)."""
        destino = "52" + CELULARES[nombre]
        return [
            e for e in self.sim.enviados
            if e["to"] == destino and (tipo is None or e["type"] == tipo)
        ]  # fmt: skip


async def construir_mundo_notificaciones(bd, localstack: str) -> MundoNotificaciones:
    from cc_common.db import crear_motor
    from cc_common.outbox import publicador_aws
    from cc_notificaciones.clientes import ColaboradoresHttp as ColaboradoresHttpNot
    from cc_notificaciones.clientes import StubCampos
    from cc_notificaciones.config import ConfigNotificaciones
    from cc_notificaciones.main import crear_app as crear_app_not
    from cc_notificaciones.meta import CredencialesMeta, MetaPlantillasHttp
    from cc_notificaciones.scheduler import StubScheduler as StubSchedulerNot
    from cc_whatsapp.cifrado import Cifrador as CifradorWa
    from cc_whatsapp.clientes import ColaboradoresHttp as ColaboradoresHttpWa
    from cc_whatsapp.clientes import NotificacionesHttp
    from cc_whatsapp.main import crear_app as crear_app_wa
    from notif_comun.config import ConfigNotifLambdas
    from notif_comun.contactos import ContactosHttp
    from notif_comun.scheduler import StubScheduler as StubSchedulerLam
    from respaldo_correo.correo import CorreoSes

    w: MundoNotificaciones = await construir_mundo(  # type: ignore[assignment]
        bd, localstack, con_empresa_b=True, campo_correo=True, clase=MundoNotificaciones
    )
    w.url_localstack = localstack
    bucle = asyncio.get_running_loop()
    aws = w.aws

    # ---- colas y reglas de EventBridge hacia ev-notificaciones
    def cola(nombre: str) -> str:
        return aws.sqs.create_queue(QueueName=f"{nombre}-{aws.sufijo}")["QueueUrl"]

    aws.despacho = cola("notif-despacho")
    aws.respaldo = cola("notif-respaldo")
    aws.ev_notificaciones = cola("ev-notificaciones")
    for evento in ("wa.mensaje_estado", "wa.plantilla_estado", "wa.respuesta_recibida"):
        regla = "r-" + evento.replace(".", "-").replace("_", "-")
        aws.events.put_rule(
            Name=regla, EventBusName=aws.bus, EventPattern=json.dumps({"detail-type": [evento]})
        )
        aws.events.put_targets(
            Rule=regla, EventBusName=aws.bus,
            Targets=[{"Id": "t-not", "Arn": aws._arn(aws.ev_notificaciones)}],
        )  # fmt: skip

    # ---- servicio notificaciones (campos de mentira: solo se usa planta_id; colaboradores real)
    w.motores["svc_notificaciones"] = crear_motor(bd.url_rol("svc_notificaciones"))
    w.reloj_not = RelojFijo(MEDIODIA_CDMX)
    w.scheduler_not = StubSchedulerNot()
    w.sim_meta_credenciales = CredencialesMeta(w.sim.access_token, w.sim.waba_id)

    async def credenciales():
        return w.sim_meta_credenciales

    cfg_not = ConfigNotificaciones(
        cognito_emisor=EMISOR, cognito_client_id="cliente-spa", cola_despacho_url=aws.despacho,
        bus_eventos=aws.bus, cola_eventos_url=aws.ev_notificaciones,
    )  # fmt: skip
    w.cfg_not = cfg_not
    w.app_not = crear_app_not(
        cfg_not, motor=w.motores["svc_notificaciones"], verificador=w.verificador,
        campos=StubCampos({w.a.id: [], w.b.id: []}),
        colaboradores=ColaboradoresHttpNot(w.interno(w.app_col, "notificaciones")),
        meta=MetaPlantillasHttp(credenciales, transporte=w.sim.transporte()),
        scheduler=w.scheduler_not, reloj=w.reloj_not, secreto_interno=lambda: SECRETO_INTERNO,
    )  # fmt: skip
    w.http_not = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=w.app_not), base_url="http://not"
    )
    w.pub_not = publicador_aws(aws.sqs, aws.events, fuente="cc.notificaciones")

    # ---- servicio whatsapp (chat de RH) y cifrado del contenido de las respuestas del bot
    w.cifrador_wa = CifradorWa(KmsFalso("whatsapp"), "llave-de-prueba")
    w.ctx_a.cifrador = w.cifrador_wa
    w.reloj_wa = RelojFijo(datetime.now(UTC))  # el chat usa el reloj real (la base mueve el tiempo)
    w.app_wa = crear_app_wa(
        w.cfg_wa, motor=w.motor_wa, verificador=w.verificador, cifrador=w.cifrador_wa,
        colaboradores=ColaboradoresHttpWa(w.interno(w.app_col, "whatsapp")),
        notificaciones=NotificacionesHttp(w.interno(w.app_not, "whatsapp")),
        secreto_interno=lambda: SECRETO_INTERNO,
    )  # fmt: skip
    w.http_wa = httpx.AsyncClient(transport=httpx.ASGITransport(app=w.app_wa), base_url="http://wa")

    # ---- Lambdas despachador y respaldo-correo
    w.ses_origen = f"rh-{aws.sufijo}@command-center.test"
    ses = _cliente("ses", localstack)
    ses.verify_email_identity(EmailAddress=w.ses_origen)
    w.correo = CorreoSes(ses, w.ses_origen)
    w.cfg_lam = ConfigNotifLambdas(
        cola_salida_url=aws.salida, cola_despacho_url=aws.despacho, cola_respaldo_url=aws.respaldo,
        alertas_topic_arn=aws.topico, ses_origen=w.ses_origen, ses_asunto="Aviso de RH",
        ambiente="test",
    )  # fmt: skip
    w.reloj_lam = RelojFijo(MEDIODIA_CDMX)
    w.sched_lam = StubSchedulerLam()
    url_not = bd.url_rol("svc_notificaciones", asincrona=False)
    w.abrir_not = lambda: psycopg.connect(url_not)
    w.contactos_lam = ContactosHttp(
        "http://col", lambda: SECRETO_INTERNO, servicio="notificaciones",
        cliente=httpx.Client(transport=PuenteSincrono(w.app_col, bucle)),
    )  # fmt: skip

    await _sembrar_colaboradores(w)
    return w


async def cerrar_mundo_notificaciones(w: MundoNotificaciones) -> None:
    await w.http_not.aclose()
    await w.http_wa.aclose()
    w.contactos_lam._http.close()
    await cerrar_mundo(w)


# --------------------------------------------------------------------------- datos


async def _alta(w: Mundo, emp, nombre: str, celular: str, *, planta: int, consentimiento=True,
                correo: str | None = None) -> int:  # fmt: skip
    r = await w.http_col.post(
        "/api/v1/colaboradores",
        json={
            "numero_empleado": f"N-{emp.id}-{celular[-4:]}", "nombres": nombre.capitalize(),
            "apellido_paterno": "Notif", "apellido_materno": "Luna", "celular": celular,
            "organizacion_id": emp.organizacion_id, "planta_id": planta,
            "fecha_ingreso": "2021-05-10", "puesto": "Operador", "tipo_empleado": "OPERATIVO",
            "campos": {"CAMP-0002": correo} if correo else {}, "consentimiento": consentimiento,
        },
        headers=emp.rh,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _sembrar_colaboradores(w: MundoNotificaciones) -> None:
    """Planta nueva por empresa con: Ana, Beto y Carla (consentimiento y correo), Darío (sin
    consentimiento) y Elena (en baja). La empresa B tiene su propia Ana en su planta."""
    w.planta_notif = w.sql(
        "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Sur') RETURNING id",
        (w.a.id,),
    )[0][0]
    pb = w.sql(
        "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Sur B') RETURNING id",
        (w.b.id,),
    )[0][0]
    w.planta_notif_b = pb
    for n in ("ana", "beto", "carla"):
        w.colaboradores[n] = await _alta(
            w, w.a, n, CELULARES[n], planta=w.planta_notif, correo=CORREOS[n]
        )
    w.colaboradores["dario"] = await _alta(
        w, w.a, "dario", CELULARES["dario"], planta=w.planta_notif, consentimiento=False
    )
    w.colaboradores["elena"] = await _alta(
        w, w.a, "elena", CELULARES["elena"], planta=w.planta_notif
    )
    r = await w.http_col.post(
        f"/api/v1/colaboradores/{w.colaboradores['elena']}/baja",
        json={"fecha_baja": "2026-11-01"}, headers=w.a.rh,
    )  # fmt: skip
    assert r.status_code == 200, r.text
    # empresa B: su propia Ana (otro celular) con consentimiento y correo
    w.colaboradores_b["ana"] = await _alta(
        w, w.b, "ana", "8199990001", planta=pb, correo="ana.b@ejemplo.test"
    )


def _unico() -> str:
    return uuid.uuid4().hex[:6]


def mas_horas(dt: datetime, horas: float) -> datetime:
    return dt + timedelta(hours=horas)
