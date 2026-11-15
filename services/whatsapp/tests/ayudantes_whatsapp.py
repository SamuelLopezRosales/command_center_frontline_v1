"""Ayudantes de las pruebas de whatsapp: colas y contactos de mentira, datos y consultas."""

import json
import uuid
from typing import Any

import psycopg


class ColaFalsa:
    """Registra ``send_message`` y ``change_message_visibility``."""

    def __init__(self, fallar: bool = False):
        self.enviados: list[dict[str, Any]] = []
        self.visibilidad: list[tuple[str, int]] = []
        self.fallar = fallar

    def send_message(self, **kw):
        if self.fallar:
            raise RuntimeError("SQS caído")
        self.enviados.append(kw)

    def change_message_visibility(self, **kw):
        self.visibilidad.append((kw["ReceiptHandle"], kw["VisibilityTimeout"]))

    def cuerpos(self, cola: str) -> list[dict]:
        return [json.loads(e["MessageBody"]) for e in self.enviados if e["QueueUrl"] == cola]


class ContactosFalso:
    """INT-COL-05: ``contactos[id] = {"elegible", "motivo", "celular"}``."""

    def __init__(self, contactos: dict[int, dict] | None = None):
        self.contactos = contactos or {}
        self.llamadas: list[tuple[int, int, str]] = []

    def resolver(self, empresa_id: int, colaborador_id: int, proposito: str) -> dict:
        self.llamadas.append((empresa_id, colaborador_id, proposito))
        return {"id": colaborador_id, **self.contactos.get(colaborador_id, {"elegible": False})}


def sql(datos, consulta: str, params=()):
    with psycopg.connect(datos["url_admin"], autocommit=True) as c:
        cur = c.execute(consulta, params)
        return cur.fetchall() if cur.description else []


def crear_colaborador(datos) -> int:
    e = datos["empresa"]
    org = sql(
        datos,
        "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
        "VALUES (%s, %s, 'Org') ON CONFLICT (empresa_id, clave) DO UPDATE SET razon_social = 'Org' "
        "RETURNING id",
        (e, "ORG1"),
    )[0][0]
    planta = sql(
        datos,
        "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Norte') "
        "ON CONFLICT (empresa_id, lower(nombre)) DO UPDATE SET nombre = 'Norte' RETURNING id",
        (e,),
    )[0][0]
    return sql(
        datos,
        "INSERT INTO colaboradores.colaborador (empresa_id, organizacion_id, planta_id, "
        "numero_empleado, nombres, apellido_paterno, apellido_materno, celular_cifrado, "
        "celular_hash, celular_ultimos4, fecha_ingreso, puesto, tipo_empleado) "
        "VALUES (%s, %s, %s, %s, 'Ana', 'Pérez', 'Ruiz', '\\x00', "
        "decode(md5(%s) || md5(%s), 'hex'), '0000', '2020-01-01', 'Op', 'OPERATIVO') RETURNING id",
        (e, org, planta, f"E-{uuid.uuid4().hex[:8]}".upper(), uuid.uuid4().hex, uuid.uuid4().hex),
    )[0][0]


def crear_conversacion(datos, colaborador_id: int, *, hace: str | None = "1 hour") -> int:
    """Conversación con el último mensaje entrante ``hace`` ese intervalo (``None``: nunca)."""
    return sql(
        datos,
        "INSERT INTO whatsapp.conversacion_whatsapp (empresa_id, colaborador_id, estado, "
        "celular_hash, origen, ultimo_mensaje_entrante_at) "
        "VALUES (%s, %s, 'ACTIVA', decode(md5(%s) || md5(%s), 'hex'), 'CONSTANCIA', "
        + ("now() - %s::interval" if hace else "%s::timestamptz")
        + ") RETURNING id",
        (datos["empresa"], colaborador_id, uuid.uuid4().hex, uuid.uuid4().hex, hace),
    )[0][0]


def crear_mensaje(datos, colaborador_id: int, *, proveedor: str, estado="ENVIADO") -> str:
    """Mensaje saliente ya enviado. Devuelve su ``clave_idempotencia``."""
    clave = str(uuid.uuid4())
    sql(
        datos,
        "INSERT INTO whatsapp.mensaje_whatsapp (empresa_id, colaborador_id, direccion, tipo, "
        "clave_idempotencia, estado, origen_tipo, origen_id, id_mensaje_proveedor) "
        "VALUES (%s, %s, 'SALIENTE', 'TEXTO', %s, %s, 'CONSTANCIA', 7, %s)",
        (datos["empresa"], colaborador_id, clave, estado, proveedor),
    )
    return clave


def eventos(datos, tipo: str) -> list[dict]:
    return [
        f[0]
        for f in sql(
            datos, "SELECT payload FROM whatsapp.outbox WHERE tipo = %s ORDER BY id", (tipo,)
        )
    ]


def mensaje(datos, clave: str) -> tuple:
    return sql(
        datos,
        "SELECT estado, error_codigo, id_mensaje_proveedor, intentos, tipo, plantilla_meta "
        "FROM whatsapp.mensaje_whatsapp WHERE clave_idempotencia = %s",
        (clave,),
    )[0]


def registro_sqs(cuerpo: dict, n: int = 1, receptor: int = 1, grupo: str | None = None) -> dict:
    """Registro de un evento SQS (``Records``)."""
    atributos = {"ApproximateReceiveCount": str(receptor)}
    if grupo:
        atributos["MessageGroupId"] = grupo
    return {
        "messageId": f"m{n}",
        "receiptHandle": f"rh{n}",
        "body": json.dumps(cuerpo),
        "attributes": atributos,
    }
