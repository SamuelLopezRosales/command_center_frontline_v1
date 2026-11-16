"""Ayudantes de las pruebas de whatsapp: colas y contactos de mentira, datos y consultas."""

import json
import uuid
from typing import Any

import psycopg

LLAVE_CODIGOS = b"llave-hmac-de-prueba-0123456789-abcdefghij"
CELULAR = "5218112345678"


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


# ------------------------------------------------------------------ bot (T-212)

import hashlib  # noqa: E402
import re  # noqa: E402

from cc_whatsapp.clientes import Busqueda, RespuestaError  # noqa: E402


def huella_de(celular: str) -> str:
    """Hash de prueba del número (los últimos 10 dígitos)."""
    return hashlib.sha256(re.sub(r"\D", "", celular)[-10:].encode()).hexdigest()


class ColaboradoresFalso:
    """INT-COL-01 a 03 y 07. ``registrar`` da de alta un número; ``dato`` es el dato correcto."""

    def __init__(self):
        self.registrados: dict[str, Busqueda] = {}
        self.datos: dict[int, str] = {}
        self.desafios: dict[int, str] = {}
        self.verificaciones = 0

    def registrar(self, celular, colaborador_id, *, elegible=True, motivo=None, dato="1234",
                  desafio="NSS_ULTIMOS4"):  # fmt: skip
        self.registrados[huella_de(celular)] = Busqueda(
            True, huella_de(celular), colaborador_id, elegible, motivo
        )
        self.datos[colaborador_id] = dato
        self.desafios[colaborador_id] = desafio

    async def buscar_por_celular(self, empresa_id, celular):
        h = huella_de(celular)
        return self.registrados.get(h, Busqueda(False, h))

    async def desafio(self, empresa_id, colaborador_id):
        return self.desafios[colaborador_id]

    async def verificar(self, empresa_id, colaborador_id, dato):
        self.verificaciones += 1
        return self.datos[colaborador_id] == dato

    async def nombre(self, empresa_id, colaborador_id):
        return "Ana Pérez Ruiz"


class ConstanciasFalso:
    def __init__(self, plantillas=None):
        self.lista = plantillas if plantillas is not None else [
            {"id": 1, "nombre": "Constancia laboral", "descripcion": None, "version": 1}
        ]  # fmt: skip
        self._n = 0
        self.creadas: list[int] = []
        self.elegidas: list[tuple[int, int]] = []
        self.generadas: list[int] = []
        self.canceladas: list[int] = []
        self.abierta = False  # simula INT-CON-02 con 409 SOLICITUD_ABIERTA
        self.faltan: list[str] | None = None  # simula INT-CON-04 con 422

    async def plantillas(self, empresa_id):
        return list(self.lista)

    async def crear_solicitud(self, empresa_id, colaborador_id, conversacion_id, nombre):
        if self.abierta:
            raise RespuestaError(409, "SOLICITUD_ABIERTA")
        self._n += 1
        self.creadas.append(self._n)
        return self._n

    async def elegir_plantilla(self, empresa_id, solicitud_id, plantilla_id):
        self.elegidas.append((solicitud_id, plantilla_id))

    async def generar(self, empresa_id, solicitud_id):
        if self.faltan:
            raise RespuestaError(422, "CAMPOS_FALTANTES", {"campos": self.faltan})
        self.generadas.append(solicitud_id)

    async def cancelar(self, empresa_id, solicitud_id):
        self.canceladas.append(solicitud_id)


class AlertasFalsas:
    def __init__(self):
        self.avisos: list[tuple[str, dict]] = []

    async def avisar(self, empresa_id, tipo, datos):
        self.avisos.append((tipo, datos))


def salidas_bot(datos) -> list[dict]:
    """Mensajes que el bot dejó para ``wa-salida``, en orden."""
    return eventos(datos, "mensaje_salida")


def textos_bot(datos) -> list[str]:
    return [m["texto"] or "[interactivo]" for m in salidas_bot(datos)]


def ultimo_codigo(datos) -> str:
    """Código de 6 dígitos del último mensaje de verificación enviado."""
    for m in reversed(salidas_bot(datos)):
        encontrado = re.search(r"\b(\d{6})\b", m["texto"] or "")
        if encontrado:
            return encontrado.group(1)
    raise AssertionError("el bot no envió ningún código")


# ------------------------------------------------------------------ cifrado y chat (T-218)


class KmsFalso:
    """KMS de mentira: la DEK "cifrada" es la clara XOR una máscara, ligada al contexto."""

    def __init__(self, servicio: str = "whatsapp"):
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


def crear_notificacion_enviada(datos, colaborador_id: int, *, estado="ENVIADO", hace="1 hour"):
    """Mensaje de notificación ya enviado al colaborador (lo que deja el ``enviador``)."""
    sql(
        datos,
        "INSERT INTO whatsapp.mensaje_whatsapp (empresa_id, colaborador_id, direccion, tipo, "
        "plantilla_meta, clave_idempotencia, estado, origen_tipo, origen_id, id_mensaje_proveedor, "
        "fecha_hora) VALUES (%s, %s, 'SALIENTE', 'PLANTILLA', 'aviso', %s, %s, 'NOTIFICACION', 7, "
        "%s, now() - %s::interval)",
        (datos["empresa"], colaborador_id, str(uuid.uuid4()), estado, f"wamid.{uuid.uuid4().hex}",
         hace),
    )  # fmt: skip


# ------------------------------------------------------------------ API del chat (T-218)

import time  # noqa: E402

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

EMISOR = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_PRUEBA"
CLIENTE = "cliente-spa"
LLAVE_JWT = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def cab(sub: str, empresa_id: int, usuario_id: int | None, rol: str = "RH") -> dict[str, str]:
    ahora = int(time.time())
    claims = {
        "sub": sub, "iss": EMISOR, "client_id": CLIENTE, "token_use": "access", "iat": ahora,
        "exp": ahora + 900, "jti": uuid.uuid4().hex, "empresa_id": str(empresa_id), "rol": rol,
    }  # fmt: skip
    if usuario_id is not None:
        claims["usuario_id"] = str(usuario_id)
    return {"Authorization": "Bearer " + jwt.encode(claims, LLAVE_JWT, algorithm="RS256")}


def crear_usuario(datos, empresa_id: int, nombre: str = "Ana RH") -> int:
    return sql(
        datos,
        "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (empresa_id, nombre, f"{uuid.uuid4().hex[:8]}@rh.test", uuid.uuid4().hex),
    )[0][0]
