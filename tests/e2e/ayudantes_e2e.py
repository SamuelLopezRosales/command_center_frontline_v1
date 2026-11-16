"""Ayudantes de la prueba de extremo a extremo de la constancia por WhatsApp (T-214).

``construir_mundo`` conecta las piezas REALES del producto, todas en proceso:

- Servicios FastAPI (``campos``, ``colaboradores``, ``constancias``, ``dashboard``) como apps ASGI
  que se llaman entre sí con el cliente HTTP interno (token de 60 s) sobre ``ASGITransport``.
- El bot (``cc_whatsapp.bot.conversacion.procesar``) y el ``worker_entrada`` leyendo
  ``wa-entrada.fifo`` de LocalStack.
- Las Lambdas ``webhook_meta``, ``enviador`` y ``estados_entrega`` con eventos construidos a mano
  (firma HMAC válida) y la API de Meta simulada con ``httpx.MockTransport``.
- El ``worker_pdf`` de constancias (el renderizador se inyecta: WeasyPrint no carga en Windows).
- Los relays del outbox (``publicar_pendientes`` + ``publicador_aws``), SQS, EventBridge y SNS de
  LocalStack, y el consumidor de eventos de constancias.

Nada de esto usa tareas de fondo: ``Mundo.bombear`` ejecuta cada pieza una vez, en orden, hasta
que ya no hay trabajo.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import boto3
import httpx
import jwt
import psycopg
from botocore.config import Config
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

DEBUG = bool(os.environ.get("E2E_DEBUG"))
RAIZ = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- simulador de Meta


def _simulador_meta():
    try:
        return importlib.import_module("simulador_meta")
    except ImportError:
        ruta = RAIZ / "services" / "whatsapp" / "tests" / "simulador_meta" / "__init__.py"
        espec = importlib.util.spec_from_file_location(
            "simulador_meta", ruta, submodule_search_locations=[str(ruta.parent)]
        )
        modulo = importlib.util.module_from_spec(espec)
        sys.modules["simulador_meta"] = modulo
        espec.loader.exec_module(modulo)
        return modulo


SIM = _simulador_meta()

# --------------------------------------------------------------------------- constantes

EMISOR = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_PRUEBA"
CLIENTE = "cliente-spa"
LLAVE_JWT = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SECRETO_INTERNO = "secreto-interno-de-prueba-0123456789-abcdef"  # pragma: allowlist secret
LLAVE_HMAC_CELULAR = b"h" * 32
LLAVE_CODIGOS = b"llave-hmac-de-codigos-de-prueba-0123456789"
LLAVE_KMS = "alias/cc-e2e-datos"

CELULAR_A = "8112345678"  # lo que se da de alta (10 dígitos)
WA_ID_A = "52" + "1" + CELULAR_A  # como lo manda Meta: 521 + 10 dígitos
CELULAR_B = "5587654321"
WA_ID_B = "521" + CELULAR_B
NSS_A = "12345678901"
NSS_B = "99887766554"
AVISO_PRIVACIDAD = "https://cc.e2e.test/privacidad"
DOMINIO = "cc.e2e.test"

CONTENIDO_PLANTILLA = {
    "esquema": 1,
    "bloques": [
        {
            "tipo": "parrafo",
            "contenido": [
                {"texto": "Constancia "},
                {"var": "folio"},
                {"texto": " de "},
                {"var": "nombre_completo"},
                {"texto": " con NSS "},
                {"var": "nss"},
            ],
        }
    ],
}


def emitir(sub: str, empresa_id: int, usuario_id: int, rol: str = "RH") -> dict[str, str]:
    ahora = int(time.time())
    token = jwt.encode(
        {
            "sub": sub,
            "iss": EMISOR,
            "client_id": CLIENTE,
            "token_use": "access",
            "iat": ahora,
            "exp": ahora + 900,
            "jti": uuid.uuid4().hex,
            "empresa_id": str(empresa_id),
            "rol": rol,
            "usuario_id": str(usuario_id),
        },
        LLAVE_JWT,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


class KmsFalso:
    """La DEK "cifrada" es la clara XOR una máscara, ligada al contexto de cifrado."""

    def __init__(self, servicio: str):
        import os

        self._mascara = os.urandom(32)
        self._servicio = servicio

    def _etiqueta(self, contexto: dict) -> bytes:
        return repr(sorted(contexto.items())).encode()

    def generate_data_key(self, **kw):
        import os

        assert kw["EncryptionContext"]["servicio"] == self._servicio
        claro = os.urandom(32)
        envuelta = bytes(a ^ b for a, b in zip(claro, self._mascara, strict=True))
        return {
            "Plaintext": claro,
            "CiphertextBlob": envuelta + self._etiqueta(kw["EncryptionContext"]),
        }

    def decrypt(self, **kw):
        blob = kw["CiphertextBlob"]
        if not blob.endswith(self._etiqueta(kw["EncryptionContext"])):
            raise RuntimeError("InvalidCiphertextException")
        return {"Plaintext": bytes(a ^ b for a, b in zip(blob[:32], self._mascara, strict=True))}


class FalsoPdf:
    """Renderizador inyectado (WeasyPrint no carga en Windows). ``fallos`` falla las primeras
    ``fallos`` llamadas (``None``: siempre)."""

    def __init__(self, fallos: int | None = 0):
        self.fallos = fallos
        self.llamadas = 0
        self.htmls: list[str] = []

    def __call__(self, html: str) -> bytes:
        self.llamadas += 1
        if self.fallos is None or self.fallos > 0:
            if self.fallos is not None:
                self.fallos -= 1
            raise RuntimeError("falla inyectada del renderizador")
        self.htmls.append(html)
        return b"%PDF-1.7 falso " + html.encode()


# --------------------------------------------------------------------------- puente sync -> ASGI


class PuenteSincrono(httpx.BaseTransport):
    """Deja que un ``httpx.Client`` síncrono (el de ``ContactosHttp`` del enviador, que corre en un
    hilo) llame a una app ASGI que vive en el ciclo de eventos principal."""

    def __init__(self, app, bucle: asyncio.AbstractEventLoop):
        self._t = httpx.ASGITransport(app=app)
        self._bucle = bucle

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        async def llamar() -> httpx.Response:
            r = await self._t.handle_async_request(request)
            await r.aread()
            return httpx.Response(r.status_code, headers=r.headers, content=r.content)

        return asyncio.run_coroutine_threadsafe(llamar(), self._bucle).result(30)


class SqsAcelerado:
    """Envuelve el cliente SQS del enviador: la espera creciente de los reintentos (30 y 120 s) se
    sustituye por 0 para que la prueba no espere; se conserva lo que el enviador pidió."""

    def __init__(self, sqs):
        self._sqs = sqs
        self.pedidos: list[int] = []

    def change_message_visibility(self, **kw):
        self.pedidos.append(kw["VisibilityTimeout"])
        self._sqs.change_message_visibility(
            QueueUrl=kw["QueueUrl"], ReceiptHandle=kw["ReceiptHandle"], VisibilityTimeout=0
        )


# --------------------------------------------------------------------------- recursos AWS


def _cliente(servicio: str, url: str, **extra):
    return boto3.client(
        servicio,
        endpoint_url=url,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",  # pragma: allowlist secret
        **extra,
    )


@dataclass
class AwsLocal:
    """Colas, bus, tema y buckets de UNA prueba (nombres únicos: las pruebas no se pisan)."""

    sqs: Any
    events: Any
    sns: Any
    s3: Any
    sufijo: str
    entrada: str = ""
    salida: str = ""
    estados: str = ""
    pdf: str = ""
    ev_constancias: str = ""
    alertas: str = ""
    bus: str = ""
    topico: str = ""
    bucket_plantillas: str = ""
    bucket_constancias: str = ""

    @classmethod
    def crear(cls, url: str) -> AwsLocal:
        s = uuid.uuid4().hex[:8]
        a = cls(
            sqs=_cliente("sqs", url),
            events=_cliente("events", url),
            sns=_cliente("sns", url),
            s3=_cliente(
                "s3", url, config=Config(signature_version="s3v4", s3={"addressing_style": "path"})
            ),
            sufijo=s,
        )

        def cola(nombre: str, fifo: bool = False) -> str:
            attrs = {"FifoQueue": "true"} if fifo else {}
            suf = ".fifo" if fifo else ""
            return a.sqs.create_queue(QueueName=f"{nombre}-{s}{suf}", Attributes=attrs)["QueueUrl"]

        a.entrada = cola("wa-entrada", True)
        a.salida = cola("wa-salida", True)
        a.estados = cola("wa-estados")
        a.pdf = cola("cola-pdf")
        a.ev_constancias = cola("ev-constancias")
        a.alertas = cola("alertas-rh")
        a.bus = f"cc-e2e-{s}"
        a.events.create_event_bus(Name=a.bus)
        for evento, destino in (
            ("wa.mensaje_estado", a.ev_constancias),
            ("constancia.fallida", a.alertas),
        ):
            regla = "r-" + evento.replace(".", "-").replace("_", "-")
            a.events.put_rule(
                Name=regla, EventBusName=a.bus, EventPattern=json.dumps({"detail-type": [evento]})
            )
            a.events.put_targets(
                Rule=regla,
                EventBusName=a.bus,
                Targets=[{"Id": "t", "Arn": a._arn(destino)}],
            )
        a.topico = a.sns.create_topic(Name=f"alertas-rh-{s}")["TopicArn"]
        a.sns.subscribe(TopicArn=a.topico, Protocol="sqs", Endpoint=a._arn(a.alertas))
        a.bucket_plantillas = f"cc-plantillas-{s}"
        a.s3.create_bucket(Bucket=a.bucket_plantillas)
        a.bucket_constancias = f"cc-constancias-{s}"
        a.s3.create_bucket(Bucket=a.bucket_constancias, ObjectLockEnabledForBucket=True)
        return a

    def _arn(self, url: str) -> str:
        return self.sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])[
            "Attributes"
        ]["QueueArn"]

    def recibir(self, url: str, *, maximo=10, espera=0, visibilidad=0) -> list[dict]:
        return self.sqs.receive_message(
            QueueUrl=url,
            MaxNumberOfMessages=maximo,
            WaitTimeSeconds=espera,
            VisibilityTimeout=visibilidad,
            AttributeNames=["All"],
        ).get("Messages", [])

    def borrar(self, url: str, m: dict) -> None:
        self.sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])

    def registro_lambda(self, m: dict) -> dict:
        """Mensaje de SQS como lo entrega el origen de eventos de Lambda."""
        return {
            "messageId": m["MessageId"],
            "receiptHandle": m["ReceiptHandle"],
            "body": m["Body"],
            "attributes": m.get("Attributes", {}),
        }


# --------------------------------------------------------------------------- datos de empresa


@dataclass
class Empresa:
    id: int
    usuario_id: int
    sub: str
    organizacion_id: int = 0
    planta_id: int = 0
    plantillas: dict[str, int] = field(default_factory=dict)
    colaborador_id: int = 0
    wa_id: str = ""
    celular: str = ""
    nss: str = ""

    @property
    def rh(self) -> dict[str, str]:
        return emitir(self.sub, self.id, self.usuario_id)


def _clientes_pg(url_admin: str):
    return psycopg.connect(url_admin, autocommit=True)


def sql(url_admin: str, consulta: str, params=()) -> list[tuple]:
    with _clientes_pg(url_admin) as c:
        cur = c.execute(consulta, params)
        return cur.fetchall() if cur.description else []


# --------------------------------------------------------------------------- el mundo


def texto_de(mensaje_meta: dict) -> str:
    """Lo que el colaborador ve de un mensaje enviado por la API de Meta."""
    tipo = mensaje_meta["type"]
    if tipo == "text":
        return mensaje_meta["text"]["body"]
    if tipo == "interactive":
        i = mensaje_meta["interactive"]
        filas = [f["title"] for s in i["action"]["sections"] for f in s["rows"]]
        return f"[lista] {i['body']['text']} ({i['action']['button']}): " + " | ".join(filas)
    if tipo == "template":
        t = mensaje_meta["template"]
        params = [p["text"] for c in t.get("components", []) for p in c["parameters"]]
        return f"[plantilla {t['name']}] " + " ".join(params)
    return f"[{tipo}]"


class Mundo:
    """Todas las piezas conectadas. Se arma con ``construir_mundo``."""

    # ------------------------------------------------------------------ armado

    def __init__(self):
        self.pasos: list[tuple[str, int]] = []  # (pieza, trabajo) de cada vuelta del bombeo
        self.publicados: dict[str, int] = {}
        self.consumidos_eventos = 0
        self.alertas: list[dict] = []
        self.transcripcion: list[tuple[str, str]] = []
        self._vistos = 0
        self._n = 0
        self.tiempos: list[tuple[str, float]] = []
        self.fallo_envio = None
        self.reintentos_pedidos: list[int] = []

    # ------------------------------------------------------------------ webhook y bombeo

    def _wamid(self) -> str:
        self._n += 1
        return f"wamid.IN{self.aws.sufijo}{self._n}"

    def webhook(self, payload: dict, *, firma_valida: bool = True) -> dict:
        from webhook_meta.handler import manejar

        evento = self.sim.evento_post(payload, firma_valida=firma_valida)
        return manejar(evento, sqs=self.aws.sqs, secretos=self.sim.secretos, cfg=self.cfg_wa)

    async def decir(self, texto: str, *, wa_id: str | None = None, bombear: bool = True):
        """El colaborador escribe: webhook firmado -> SQS -> worker -> bot -> ... (bombeo)."""
        wa = wa_id or self.a.wa_id
        r = self.webhook(self.sim.mensaje_entrante(wa, texto, wamid=self._wamid()))
        assert r["statusCode"] == 200, r
        self.transcripcion.append(("COLABORADOR", self._enmascarar(texto)))
        if bombear:
            await self.bombear(f"colaborador escribe: {self._enmascarar(texto)}")

    async def elegir(self, opcion_id: str, *, wa_id: str | None = None):
        wa = wa_id or self.a.wa_id
        r = self.webhook(self.sim.respuesta_interactiva(wa, opcion_id, wamid=self._wamid()))
        assert r["statusCode"] == 200, r
        self.transcripcion.append(("COLABORADOR", f"[elige la opción {opcion_id}]"))
        await self.bombear(f"colaborador elige {opcion_id}")

    async def estado_meta(self, wamid: str, estado: str, *, destinatario=None, error=None):
        """Meta avisa el estado de un mensaje (webhook firmado -> wa-estados) y se bombea."""
        dest = destinatario or self.a.wa_id
        r = self.webhook(self.sim.estado(wamid, estado, dest, error=error))
        assert r["statusCode"] == 200, r
        await self.bombear(f"Meta reporta {estado}")

    async def bombear(self, etiqueta: str = "bombeo", *, maximo: int = 60) -> None:
        """Ejecuta relays, worker de entrada, Lambdas, worker-pdf y consumidor, una vez cada uno y
        en orden, hasta que ninguno tenga trabajo."""
        t0 = time.perf_counter()
        for _ in range(maximo):
            hecho = 0
            for nombre, paso in self._pasos():
                n = await paso()
                if n and DEBUG:
                    print("PASO", nombre, n, dict(self.publicados), self.consumidos_eventos)
                if n:
                    self.pasos.append((nombre, n))
                hecho += n
            if not hecho:
                break
        else:
            raise AssertionError("el bombeo no terminó: hay trabajo que nunca se agota")
        self.tiempos.append((etiqueta, time.perf_counter() - t0))
        self._registrar_salidas()

    def _pasos(self) -> list[tuple[str, Any]]:
        """Piezas del bombeo, en orden. ``MundoNotificaciones`` agrega las suyas."""
        return [
            ("relay-outbox whatsapp", self._relay_wa),
            ("worker-whatsapp-entrada", self._worker_entrada),
            ("relay-outbox constancias", self._relay_con),
            ("lambda enviador", self._enviador),
            ("lambda estados-entrega", self._estados),
            ("worker-pdf", self._worker_pdf),
            ("consumidor ev-constancias", self._consumidor),
        ]

    def _registrar_salidas(self) -> None:
        for e in self.sim.enviados[self._vistos :]:
            self.transcripcion.append((f"BOT -> ...{e['to'][-4:]}", self._enmascarar(texto_de(e))))
        self._vistos = len(self.sim.enviados)

    # ------------------------------------------------------------------ pasos del bombeo

    async def _publicar(self, motor, esquema: str, publicador_base) -> int:
        from cc_common.outbox import publicar_pendientes

        async def publicador(m):
            await publicador_base(m)
            clave = f"{m.destino_tipo}:{m.tipo}"
            self.publicados[clave] = self.publicados.get(clave, 0) + 1

        return await publicar_pendientes(motor, esquema, publicador)

    async def _relay_wa(self) -> int:
        return await self._publicar(self.motor_wa, "whatsapp", self.pub_wa)

    async def _relay_con(self) -> int:
        return await self._publicar(self.motor_con, "constancias", self.pub_con)

    async def _worker_entrada(self) -> int:
        from cc_whatsapp.workers.worker_entrada import atender_lote

        return await atender_lote(
            self.aws.sqs, self.aws.entrada, self.ctx_a, espera_s=0, visibilidad_s=30
        )

    async def _enviador(self) -> int:
        from enviador.handler import manejar

        msgs = self.aws.recibir(self.aws.salida, visibilidad=120)
        if not msgs:
            return 0
        sqs = SqsAcelerado(self.aws.sqs)
        r = await asyncio.to_thread(
            manejar,
            {"Records": [self.aws.registro_lambda(m) for m in msgs]},
            abrir=self.abrir_wa,
            cfg=self.cfg_wa,
            meta=self.meta,
            contactos=self.contactos,
            sqs=sqs,
        )
        self.reintentos_pedidos += sqs.pedidos
        fallidos = {f["itemIdentifier"] for f in r["batchItemFailures"]}
        for m in msgs:
            if m["MessageId"] not in fallidos:
                self.aws.borrar(self.aws.salida, m)
        return len(msgs)

    async def _estados(self) -> int:
        from estados_entrega.handler import manejar

        msgs = self.aws.recibir(self.aws.estados)
        if not msgs:
            return 0
        r = await asyncio.to_thread(
            manejar,
            {"Records": [self.aws.registro_lambda(m) for m in msgs]},
            abrir=self.abrir_wa,
            cfg=self.cfg_wa,
        )
        fallidos = {f["itemIdentifier"] for f in r["batchItemFailures"]}
        for m in msgs:
            if m["MessageId"] not in fallidos:
                self.aws.borrar(self.aws.estados, m)
        return len(msgs)

    async def _worker_pdf(self) -> int:
        from cc_constancias.workers.worker_pdf import atender

        msgs = self.aws.recibir(self.aws.pdf, maximo=1)
        for m in msgs:
            cuerpo = json.loads(m["Body"])
            try:
                await atender(
                    self.motor_con,
                    self.cfg_con,
                    recepciones=int(m["Attributes"]["ApproximateReceiveCount"]),
                    empresa_id=int(cuerpo["empresa_id"]),
                    solicitud_id=int(cuerpo["solicitud_id"]),
                    almacen=self.almacen_plantillas,
                    almacen_constancias=self.almacen_constancias,
                    cifrador=self.cifrador_con,
                    campos=self.campos_con,
                    colaboradores=self.colaboradores_con,
                    cargador_logotipo=None,
                    generar_pdf=self.pdf,
                )
            except Exception:  # noqa: BLE001, S112 - sin borrar: SQS reentrega
                continue
            self.aws.borrar(self.aws.pdf, m)
        return len(msgs)

    async def _consumidor(self) -> int:
        from cc_common.tareas import cuerpo_de_evento
        from cc_constancias.consumidores import manejar_evento

        esperados = self.publicados.get("EVENTBRIDGE:wa.mensaje_estado", 0)
        espera = (
            3 if self.consumidos_eventos < esperados else 0
        )  # EventBridge reparte en segundo plano
        msgs = self.aws.recibir(self.aws.ev_constancias, espera=espera)
        for m in msgs:
            evento = cuerpo_de_evento(json.loads(m["Body"]))
            try:
                await manejar_evento(
                    self.motor_con,
                    self.almacen_plantillas,
                    self.campos_con,
                    self.colaboradores_con,
                    evento,
                    self.cfg_con,
                )
            except Exception:  # noqa: BLE001, S112
                continue
            self.consumidos_eventos += 1
            self.aws.borrar(self.aws.ev_constancias, m)
        return len(msgs)

    # ------------------------------------------------------------------ alertas a RH

    async def alertas_rh(self, *, esperar: int = 0, tipo: str | None = None) -> list[dict]:
        """Avisos recibidos en la cola de alertas de RH (SNS del bot y EventBridge de constancias).
        ``esperar``: cuántos avisos del ``tipo`` se esperan (espera hasta 6 s a que lleguen)."""
        limite = time.monotonic() + 6
        while True:
            for m in self.aws.recibir(self.aws.alertas, espera=1 if esperar else 0):
                cuerpo = json.loads(m["Body"])
                if "detail-type" in cuerpo:  # EventBridge -> cola
                    detalle = cuerpo["detail"]
                    detalle = json.loads(detalle) if isinstance(detalle, str) else detalle
                    self.alertas.append(
                        {"origen": "EVENTBRIDGE", **detalle, "tipo": cuerpo["detail-type"]}
                    )
                else:  # SNS -> cola
                    self.alertas.append({"origen": "SNS", **json.loads(cuerpo["Message"])})
                self.aws.borrar(self.aws.alertas, m)
            propias = [a for a in self.alertas if tipo is None or a["tipo"] == tipo]
            if len(propias) >= esperar or time.monotonic() > limite:
                return propias

    # ------------------------------------------------------------------ lectura

    def sql(self, consulta: str, params=()) -> list[tuple]:
        return sql(self.bd.url_admin, consulta, params)

    def recibidos(self, wa_id: str | None = None) -> list[dict]:
        """Mensajes que Meta entregó al colaborador (lo que envió el enviador)."""
        destino = "52" + (wa_id or self.a.wa_id)[-10:]
        return [e for e in self.sim.enviados if e["to"] == destino]

    def textos(self, wa_id: str | None = None) -> list[str]:
        return [texto_de(e) for e in self.recibidos(wa_id)]

    def codigo_recibido(self, wa_id: str | None = None) -> str:
        """El código de 6 dígitos del último mensaje de verificación (lo que el colaborador lee)."""
        for t in reversed(self.textos(wa_id)):
            m = re.search(r"verificación es (\d{6})", t)
            if m:
                return m.group(1)
        raise AssertionError("el colaborador no recibió ningún código")

    def enlace_recibido(self) -> str:
        for t in reversed(self.textos()):
            m = re.search(r"https://\S+/d/[A-Za-z0-9_-]{43}", t)
            if m:
                return m.group(0)
        raise AssertionError("el colaborador no recibió ningún enlace")

    def wamid_del_enlace(self) -> str:
        """``wamid`` (de Meta) del último mensaje que llevó un enlace de descarga."""
        for e in reversed(self.sim.enviados):
            if "/d/" in json.dumps(e):
                return e["wamid"]
        raise AssertionError("Meta no recibió ningún enlace")

    def estado_solicitud(self, empresa_id: int | None = None) -> list[tuple]:
        return self.sql(
            "SELECT id, estado, motivo_fallo FROM constancias.solicitud_constancia "
            "WHERE empresa_id = %s ORDER BY id",
            (empresa_id or self.a.id,),
        )

    def estado_constancia(self, empresa_id: int | None = None) -> list[tuple]:
        return self.sql(
            "SELECT id, folio, estado_entrega, fecha_entrega IS NOT NULL, solicitud_id "
            "FROM constancias.constancia_generada WHERE empresa_id = %s ORDER BY id",
            (empresa_id or self.a.id,),
        )

    def mensajes(self, origen: str = "CONSTANCIA", empresa_id: int | None = None) -> list[tuple]:
        return self.sql(
            "SELECT id, estado, error_codigo, tipo, intentos, id_mensaje_proveedor "
            "FROM whatsapp.mensaje_whatsapp WHERE empresa_id = %s AND origen_tipo = %s "
            "AND direccion = 'SALIENTE' ORDER BY id",
            (empresa_id or self.a.id, origen),
        )

    # ------------------------------------------------------------------ huellas y secretos

    def _enmascarar(self, texto: str) -> str:
        """Transcripción sin secretos: código, token del enlace y números."""
        t = re.sub(r"(?<!\d)\d{6}(?!\d)", "***", texto)
        t = re.sub(r"^\*\*\* \S+$", "*** ****", t)  # código + dato adicional del colaborador
        t = re.sub(r"/d/[A-Za-z0-9_-]{43}", "/d/***", t)
        t = re.sub(r"(?<!\d)52?1?\d{10}(?!\d)", lambda m: "…" + m.group(0)[-4:], t)
        return t

    def volcado_de_la_base(
        self,
        esquemas=("whatsapp", "constancias", "colaboradores", "auditoria", "campos", "identidad"),
    ) -> str:
        """Toda la base como texto (``row_to_json``), para buscar valores que no deben estar."""
        partes: list[str] = []
        with _clientes_pg(self.bd.url_admin) as c:
            tablas = c.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE'",
                (list(esquemas),),
            ).fetchall()
            for esquema, tabla in tablas:
                filas = c.execute(
                    f'SELECT row_to_json(t)::text FROM "{esquema}"."{tabla}" t'
                ).fetchall()  # noqa: S608
                partes += [f"{esquema}.{tabla}: {f[0]}" for f in filas]
        return "\n".join(partes)


async def construir_mundo(bd, localstack: str, *, pdf: FalsoPdf | None = None, max_intentos_pdf=3,
                          con_empresa_b: bool = False, plantillas: int = 1,
                          clase: type[Mundo] = Mundo, campo_correo: bool = False) -> Mundo:  # fmt: skip
    """Arma el mundo completo sobre una base migrada y los recursos de LocalStack."""
    from cc_campos.clientes import StubConstancias
    from cc_campos.config import ConfigCampos
    from cc_campos.main import crear_app as crear_app_campos
    from cc_colaboradores.campos_cliente import CacheCampos
    from cc_colaboradores.campos_cliente import CamposHttp as CamposHttpCol
    from cc_colaboradores.cifrado import Cifrador as CifradorCol
    from cc_colaboradores.config import ConfigColaboradores
    from cc_colaboradores.main import crear_app as crear_app_col
    from cc_common.auth import VerificadorToken
    from cc_common.db import crear_motor
    from cc_common.internal_client import ClienteInterno
    from cc_common.outbox import publicador_aws
    from cc_constancias.almacenamiento import AlmacenConstancias, AlmacenS3
    from cc_constancias.cifrado import Cifrador as CifradorCon
    from cc_constancias.clientes import CamposHttp as CamposHttpCon
    from cc_constancias.clientes import ColaboradoresHttp as ColaboradoresHttpCon
    from cc_constancias.config import ConfigConstancias
    from cc_constancias.main import crear_app as crear_app_con
    from cc_constancias.servicios.firma_cloudfront import FirmadorCloudFront
    from cc_dashboard.config import ConfigDashboard
    from cc_dashboard.main import crear_app as crear_app_dash
    from cc_whatsapp.bot.contexto import Contexto
    from cc_whatsapp.clientes import ColaboradoresHttp as ColaboradoresHttpWa
    from cc_whatsapp.clientes import ConstanciasHttp
    from cc_whatsapp.config import ConfigWhatsapp
    from cc_whatsapp.contactos import ContactosHttp
    from cc_whatsapp.meta import ClienteMeta
    from cc_whatsapp.servicios.alertas import AlertasSns

    w = clase()
    w.bd = bd
    w.pdf = pdf or FalsoPdf()
    w.aws = AwsLocal.crear(localstack)
    w.sim = SIM.SimuladorMeta()
    w.sim._n = (
        uuid.uuid4().int % 10**9
    )  # wamids únicos entre pruebas (la base se comparte por prueba)
    bucle = asyncio.get_running_loop()

    # ---- empresas, usuarios y campo NSS (SQL de administrador: es la "siembra")
    def sembrar(nombre: str, sub: str, celular: str, wa_id: str, nss: str) -> Empresa:
        with _clientes_pg(bd.url_admin) as c:
            e = c.execute(
                "INSERT INTO identidad.empresa (razon_social) VALUES (%s) RETURNING id", (nombre,)
            ).fetchone()[0]
            u = c.execute(
                "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (e, f"RH {nombre}", f"rh@{nombre.lower()}.test", sub),
            ).fetchone()[0]
            c.execute(
                "INSERT INTO campos.campo_colaborador (empresa_id, nombre_campo, clave, "
                "codigo_interno, tipo_dato, orden, es_sensible) "
                "VALUES (%s, 'NSS', 'nss', 'CAMP-0001', 'TEXTO', 1, true)",
                (e,),
            )
            if campo_correo:  # el respaldo por correo lee el campo ``correo`` (INT-COL-05)
                c.execute(
                    "INSERT INTO campos.campo_colaborador (empresa_id, nombre_campo, clave, "
                    "codigo_interno, tipo_dato, orden, es_sensible) "
                    "VALUES (%s, 'Correo', 'correo', 'CAMP-0002', 'TEXTO', 2, true)",
                    (e,),
                )
            org = c.execute(
                "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
                "VALUES (%s, 'ORG1', 'Org') RETURNING id",
                (e,),
            ).fetchone()[0]
            pla = c.execute(
                "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Norte') "
                "RETURNING id",
                (e,),
            ).fetchone()[0]
        return Empresa(e, u, sub, org, pla, wa_id=wa_id, celular=celular, nss=nss)

    w.a = sembrar("EmpresaA", "sub-a", CELULAR_A, WA_ID_A, NSS_A)
    w.b = sembrar("EmpresaB", "sub-b", CELULAR_B, WA_ID_B, NSS_B) if con_empresa_b else None

    # ---- motores por rol (RLS vigente)
    def motor(rol: str):
        return crear_motor(bd.url_rol(rol))

    w.motores = {
        r: motor(r)
        for r in (
            "svc_campos",
            "svc_colaboradores",
            "svc_constancias",
            "svc_whatsapp",
            "svc_dashboard",
        )
    }
    w.motor_wa = w.motores["svc_whatsapp"]
    w.motor_con = w.motores["svc_constancias"]
    verificador = VerificadorToken(
        EMISOR, CLIENTE, resolver_llave=lambda _t: LLAVE_JWT.public_key()
    )

    def interno(app, servicio: str, base="http://interno") -> ClienteInterno:
        return ClienteInterno(
            base, servicio=servicio, secreto=lambda: SECRETO_INTERNO,
            transporte=httpx.ASGITransport(app=app), reintentos=0,
        )  # fmt: skip

    # ---- campos
    app_campos = crear_app_campos(
        ConfigCampos(cognito_emisor=EMISOR, cognito_client_id=CLIENTE),
        motor=w.motores["svc_campos"], verificador=verificador, colaboradores=None,
        constancias=StubConstancias(), secreto_interno=lambda: SECRETO_INTERNO,
    )  # fmt: skip
    # ---- colaboradores (su cliente de INT-CAM-01 apunta al campos real)
    kms_col = KmsFalso("colaboradores")
    cifrador_col = CifradorCol(kms_col, LLAVE_KMS, LLAVE_HMAC_CELULAR)
    app_col = crear_app_col(
        ConfigColaboradores(cognito_emisor=EMISOR, cognito_client_id=CLIENTE),
        motor=w.motores["svc_colaboradores"], verificador=verificador, cifrador=cifrador_col,
        campos=CacheCampos(CamposHttpCol(interno(app_campos, "colaboradores"))),
        secreto_interno=lambda: SECRETO_INTERNO,
    )  # fmt: skip
    # ---- constancias (campos y colaboradores reales por HTTP interno)
    w.almacen_plantillas = AlmacenS3(w.aws.bucket_plantillas, w.aws.s3)
    w.almacen_constancias = AlmacenConstancias(w.aws.bucket_constancias, w.aws.s3, retencion_dias=1)
    w.cfg_con = ConfigConstancias(
        cognito_emisor=EMISOR, cognito_client_id=CLIENTE, dominio=DOMINIO,
        cola_pdf_url=w.aws.pdf, cola_wa_salida_url=w.aws.salida, bus_eventos=w.aws.bus,
        max_intentos_pdf=max_intentos_pdf, retencion_constancias_dias=1,
    )  # fmt: skip
    w.campos_con = CamposHttpCon(interno(app_campos, "constancias"))
    w.colaboradores_con = ColaboradoresHttpCon(interno(app_col, "constancias"))
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa

    pem = _rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    w.cifrador_con = CifradorCon(KmsFalso("constancias"), "llave-de-prueba")
    app_con = crear_app_con(
        w.cfg_con, motor=w.motor_con, verificador=verificador, almacen=w.almacen_plantillas,
        campos=w.campos_con, colaboradores=w.colaboradores_con,
        almacen_constancias=w.almacen_constancias,
        firmador=FirmadorCloudFront("cdn.e2e.test", "KPAR1", pem),
        secreto_interno=lambda: SECRETO_INTERNO,
    )  # fmt: skip
    # ---- dashboard
    app_dash = crear_app_dash(
        ConfigDashboard(cognito_emisor=EMISOR, cognito_client_id=CLIENTE),
        motor=w.motores["svc_dashboard"], verificador=verificador,
    )  # fmt: skip

    w.http_con = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_con), base_url="http://con"
    )
    w.http_col = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_col), base_url="http://col"
    )
    w.http_dash = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_dash), base_url="http://dash"
    )
    w.app_col, w.app_con, w.app_campos = app_col, app_con, app_campos
    w.verificador, w.interno = verificador, interno

    # ---- whatsapp: configuración, bot, clientes del bot, Lambdas
    def cfg_wa(empresa: Empresa) -> ConfigWhatsapp:
        return ConfigWhatsapp(
            empresa_id=empresa.id, meta_phone_number_id=w.sim.phone_number_id,
            cola_entrada_url=w.aws.entrada, cola_estados_url=w.aws.estados,
            cola_salida_url=w.aws.salida, bus_eventos=w.aws.bus,
            aviso_privacidad_url=AVISO_PRIVACIDAD, plantilla_constancia_lista="constancia_lista",
        )  # fmt: skip

    w.cfg_wa = cfg_wa(w.a)
    alertas = AlertasSns(w.aws.sns, w.aws.topico)

    def contexto(empresa: Empresa) -> Contexto:
        return Contexto(
            cfg=cfg_wa(empresa), motor=w.motor_wa,
            colaboradores=ColaboradoresHttpWa(interno(app_col, "whatsapp")),
            constancias=ConstanciasHttp(interno(app_con, "whatsapp")),
            alertas=alertas, llave_codigos=LLAVE_CODIGOS,
        )  # fmt: skip

    w.ctx_a = contexto(w.a)
    w.ctx_b = contexto(w.b) if w.b else None
    w.fallo_envio = None  # callable(cuerpo_enviado) -> (status, codigo) | None

    def responder_meta(peticion: httpx.Request) -> httpx.Response:
        if w.fallo_envio is not None:
            error = w.fallo_envio(json.loads(peticion.content))
            if error:
                return httpx.Response(
                    error[0], json={"error": {"code": error[1], "message": "simulado"}}
                )
        return w.sim._responder(peticion)

    w.meta = ClienteMeta(
        base=w.cfg_wa.meta_api_base, version=w.cfg_wa.meta_api_version,
        phone_number_id=w.sim.phone_number_id, token=w.sim.access_token,
        cliente=httpx.Client(transport=httpx.MockTransport(responder_meta)),
    )  # fmt: skip
    w.contactos = ContactosHttp(
        "http://col", lambda: SECRETO_INTERNO,
        cliente=httpx.Client(transport=PuenteSincrono(app_col, bucle)),
    )  # fmt: skip
    url_wa = bd.url_rol("svc_whatsapp", asincrona=False)
    w.abrir_wa = lambda: psycopg.connect(url_wa)
    w.pub_wa = publicador_aws(w.aws.sqs, w.aws.events, fuente="cc.whatsapp")
    w.pub_con = publicador_aws(w.aws.sqs, w.aws.events, fuente="cc.constancias")

    # ---- datos: colaboradores por la API real y plantillas publicadas
    for emp in (w.a, w.b):
        if emp is not None:
            await _alta_colaborador(w, emp)
            for n in range(plantillas):
                _plantilla_activa(w, emp, "Constancia laboral" if n == 0 else f"Constancia {n + 1}")
    return w


async def _alta_colaborador(w: Mundo, emp: Empresa, *, con_nss: bool = True) -> int:
    r = await w.http_col.post(
        "/api/v1/colaboradores",
        json={
            "numero_empleado": f"E-{emp.id}", "nombres": "Ana", "apellido_paterno": "Pérez",
            "apellido_materno": "Luna", "celular": emp.celular,
            "organizacion_id": emp.organizacion_id, "planta_id": emp.planta_id,
            "fecha_ingreso": "2020-03-15", "puesto": "Analista", "tipo_empleado": "ADMINISTRATIVO",
            "campos": {"CAMP-0001": emp.nss} if con_nss else {}, "consentimiento": True,
        },
        headers=emp.rh,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    emp.colaborador_id = r.json()["id"]
    return emp.colaborador_id


def _plantilla_activa(w: Mundo, emp: Empresa, nombre: str) -> int:
    from cc_constancias import contenido as esquema
    from cc_constancias.almacenamiento import clave_version

    pid = sql(
        w.bd.url_admin,
        "INSERT INTO constancias.plantilla_constancia (empresa_id, nombre) VALUES (%s, %s) "
        "RETURNING id",
        (emp.id, nombre),
    )[0][0]
    cuerpo = esquema.serializar(esquema.leer(CONTENIDO_PLANTILLA))
    clave = clave_version(emp.id, pid, 1)
    w.aws.s3.put_object(Bucket=w.aws.bucket_plantillas, Key=clave, Body=cuerpo)
    sql(
        w.bd.url_admin,
        "INSERT INTO constancias.version_plantilla (empresa_id, plantilla_id, numero, "
        "contenido_s3_key, hash_sha256, creada_por_usuario_id) VALUES (%s, %s, 1, %s, %s, %s)",
        (emp.id, pid, clave, esquema.hash_de(cuerpo), emp.usuario_id),
    )
    sql(
        w.bd.url_admin,
        "UPDATE constancias.plantilla_constancia SET activa = true WHERE id = %s",
        (pid,),
    )
    emp.plantillas[nombre] = pid
    return pid


async def cerrar_mundo(w: Mundo) -> None:
    for c in (w.http_con, w.http_col, w.http_dash):
        await c.aclose()
    for m in w.motores.values():
        await m.dispose()
    w.contactos._http.close()
