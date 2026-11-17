"""Ayudantes de las pruebas de ``despachador``, ``conciliador`` y ``respaldo-correo``.

No se empaqueta con las Lambdas. Trae dobles de SQS, SNS y SES, y ``Mundo``: una base migrada con
dos empresas, la plantilla y las notificaciones de prueba, y la conexión como ``svc_notificaciones``
(con RLS). ``conciliacion.sql`` se aplica aquí hasta que forme parte de la migración del servicio.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

SQL_CONCILIACION = Path(__file__).parent / "sql" / "conciliacion.sql"
# Martes 17/11/2026 12:00 en Ciudad de México (18:00 UTC): dentro de horario.
AHORA = datetime(2026, 11, 17, 18, 0, tzinfo=UTC)
# Martes 17/11/2026 22:00 en Ciudad de México (04:00 UTC del 18): fuera de horario.
NOCHE = datetime(2026, 11, 18, 4, 0, tzinfo=UTC)


class ColaSqsFalsa:
    """Doble de SQS que valida lo que SQS validaría: lotes de hasta 10, ``Id`` únicos por lote."""

    def __init__(self) -> None:
        self.mensajes: dict[str, list[dict[str, Any]]] = {}
        self.llamadas_lote = 0
        self.tamanos_lote: list[int] = []
        self.fallar_envio = False
        self.fallar_lote_numero: int | None = None  # n-ésima llamada a send_message_batch
        self.fallar_ids: set[str] = set()  # ``Id`` que se reportan en ``Failed``

    def send_message(self, **kw):
        if self.fallar_envio:
            raise RuntimeError("SQS caído")
        self.mensajes.setdefault(kw["QueueUrl"], []).append(kw)
        return {"MessageId": "x"}

    def send_message_batch(self, QueueUrl, Entries):  # noqa: N803 - firma de boto3
        self.llamadas_lote += 1
        assert 1 <= len(Entries) <= 10, "SendMessageBatch admite de 1 a 10 mensajes"
        ids = [e["Id"] for e in Entries]
        assert len(set(ids)) == len(ids), "Id repetido dentro del lote"
        self.tamanos_lote.append(len(Entries))
        if self.fallar_lote_numero == self.llamadas_lote:
            raise RuntimeError("SQS caído")
        ok, fallidos = [], []
        for e in Entries:
            if e["Id"] in self.fallar_ids:
                fallidos.append({"Id": e["Id"], "SenderFault": False, "Code": "InternalError"})
            else:
                self.mensajes.setdefault(QueueUrl, []).append({"QueueUrl": QueueUrl, **e})
                ok.append({"Id": e["Id"]})
        return {"Successful": ok, "Failed": fallidos}

    def cuerpos(self, cola: str) -> list[dict[str, Any]]:
        return [json.loads(m["MessageBody"]) for m in self.mensajes.get(cola, [])]


class SnsFalso:
    def __init__(self) -> None:
        self.publicados: list[dict[str, Any]] = []
        self.error: Exception | None = None

    def publish(self, **kw):
        if self.error:
            raise self.error
        self.publicados.append(kw)
        return {"MessageId": "x"}

    def cuerpos(self) -> list[dict[str, Any]]:
        return [json.loads(p["Message"]) for p in self.publicados]


class CorreoFalso:
    """Doble de ``EnviarCorreo``: registra los correos (``rechazar``, ``transitorio_en``)."""

    def __init__(self) -> None:
        self.enviados: list[dict[str, Any]] = []
        self.rechazar: set[str] = set()
        self.transitorio_en: set[str] = set()

    def enviar(self, *, destino, asunto, texto, etiquetas):
        from respaldo_correo.correo import CorreoRechazado, CorreoTransitorio

        if destino in self.transitorio_en:
            raise CorreoTransitorio("Throttling")
        if destino in self.rechazar:
            raise CorreoRechazado("MessageRejected")
        self.enviados.append(
            {"destino": destino, "asunto": asunto, "texto": texto, "etiquetas": etiquetas}
        )
        return f"id-{len(self.enviados)}"


def registro_sqs(cuerpo: dict[str, Any], n: int = 1) -> dict[str, Any]:
    """Un registro del evento de SQS (``Records``) con ese cuerpo."""
    return {
        "messageId": f"m{n}",
        "receiptHandle": f"r{n}",
        "body": json.dumps(cuerpo),
        "attributes": {"ApproximateReceiveCount": "1"},
    }


def evento_sqs(*cuerpos: dict[str, Any]) -> dict[str, Any]:
    return {"Records": [registro_sqs(c, i) for i, c in enumerate(cuerpos, 1)]}


def evento_scheduler(cuerpo: dict[str, Any]) -> dict[str, Any]:
    """EventBridge Scheduler -> SQS entrega el ``Input`` del schedule como cuerpo del mensaje."""
    return evento_sqs(cuerpo)


class Mundo:
    """Base migrada con las empresas ``a`` y ``b`` (un usuario RH cada una)."""

    def __init__(self, bd_migrada) -> None:
        self.bd = bd_migrada
        self.admin = bd_migrada.url_admin
        self.url = bd_migrada.url_rol("svc_notificaciones", asincrona=False)
        with psycopg.connect(self.admin, autocommit=True) as c:
            c.execute(SQL_CONCILIACION.read_text(encoding="utf-8"))
            self.a = self._empresa(c, "A", "a")
            self.b = self._empresa(c, "B", "b")
        self.usuario = {}
        with psycopg.connect(self.admin, autocommit=True) as c:
            for emp, tag in ((self.a, "a"), (self.b, "b")):
                self.usuario[emp] = c.execute(
                    "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
                    "VALUES (%s, 'RH', %s, %s) RETURNING id",
                    (emp, f"rh@{tag}.com", f"sub-{tag}"),
                ).fetchone()[0]
        self.plantilla = {
            emp: self.sql(
                "INSERT INTO notificaciones.plantilla_mensaje (empresa_id, creada_por_usuario_id, "
                "nombre, categoria, texto_con_variables, estado_meta, id_plantilla_meta) "
                "VALUES (%s, %s, 'aviso_uniformes', 'UTILITY', "
                "'Hola {{1}}, tu entrega es el {{2}}.', 'APROBADA', 'meta-1') RETURNING id",
                (emp, self.usuario[emp]),
            )[0][0]
            for emp in (self.a, self.b)
        }

    @staticmethod
    def _empresa(c, nombre: str, _tag: str) -> int:
        return c.execute(
            "INSERT INTO identidad.empresa (razon_social) VALUES (%s) RETURNING id", (nombre,)
        ).fetchone()[0]

    def crear_plantilla(
        self, empresa: int, nombre: str, texto: str, idioma: str = "es_MX", estado="APROBADA"
    ) -> int:
        """Otra plantilla de la empresa (con variables numeradas o con nombre, en otro idioma)."""
        return self.sql(
            "INSERT INTO notificaciones.plantilla_mensaje (empresa_id, creada_por_usuario_id, "
            "nombre, categoria, idioma, texto_con_variables, estado_meta, id_plantilla_meta) "
            "VALUES (%s, %s, %s, 'UTILITY', %s, %s, %s, %s) RETURNING id",
            (empresa, self.usuario[empresa], nombre, idioma, texto, estado, f"meta-{nombre}"),
        )[0][0]

    def abrir(self) -> psycopg.Connection:
        """Conexión como ``svc_notificaciones`` (con RLS), como la abre la Lambda."""
        return psycopg.connect(self.url)

    def sql(self, consulta: str, params=()):
        """Consulta como administrador (sin RLS) para preparar y comprobar la base."""
        with psycopg.connect(self.admin, autocommit=True) as c:
            cur = c.execute(consulta, params)
            return cur.fetchall() if cur.description else []

    def notificacion(
        self,
        empresa: int | None = None,
        *,
        estado: str = "ENVIANDO",
        destinatarios: int = 3,
        programada_para: datetime | None = None,
        zona: str = "America/Mexico_City",
        respaldo: bool = False,
        fuera_horario: bool = False,
        modo_envio: str = "AHORA",
        variables: dict[str, Any] | None = None,
        schedule: str | None = None,
        primer_colaborador: int = 1000,
        encolado_en: datetime | None = None,
        estado_envio: str = "PENDIENTE",
        plantilla: int | None = None,
    ) -> int:
        empresa = empresa or self.a
        variables = (
            variables
            if variables is not None
            else {
                "1": {"origen": "COLABORADOR", "campo": "nombre_completo"},
                "2": {"origen": "FIJO", "valor": "20 nov 2026"},
            }
        )
        nid = self.sql(
            "INSERT INTO notificaciones.notificacion (empresa_id, usuario_id, "
            "plantilla_mensaje_id, "
            "variables_json, respaldo_correo, programada_para, zona_horaria, estado, titulo, modo, "
            "revisada_en, confirmada_fuera_horario, schedule_nombre, modo_envio) "
            "VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, 'Aviso', 'CRITERIOS', now(), "
            "%s, %s, %s) "
            "RETURNING id",
            (
                empresa,
                self.usuario[empresa],
                plantilla or self.plantilla[empresa],
                json.dumps(variables),
                respaldo,
                programada_para,
                zona,
                estado,
                fuera_horario,
                schedule,
                modo_envio,
            ),
        )[0][0]
        if destinatarios:
            self.sql(
                "INSERT INTO notificaciones.notificacion_destinatario (empresa_id, "
                "notificacion_id, "
                "colaborador_id, estado_envio, colaborador_nombre, encolado_en) "
                "SELECT %s, %s, %s + g, %s, 'Nombre ' || g, %s FROM generate_series(1, %s) g",
                (empresa, nid, primer_colaborador, estado_envio, encolado_en, destinatarios),
            )
        return nid

    def estado(self, nid: int) -> str:
        return self.sql("SELECT estado FROM notificaciones.notificacion WHERE id = %s", (nid,))[0][
            0
        ]

    def destinatarios(self, nid: int, columnas: str = "estado_envio") -> list[tuple]:
        return self.sql(
            f"SELECT {columnas} FROM notificaciones.notificacion_destinatario "  # noqa: S608
            "WHERE notificacion_id = %s ORDER BY id",
            (nid,),
        )

    def contar(self, nid: int, condicion: str) -> int:
        return self.sql(
            "SELECT count(*) FROM notificaciones.notificacion_destinatario "  # noqa: S608
            f"WHERE notificacion_id = %s AND {condicion}",
            (nid,),
        )[0][0]
