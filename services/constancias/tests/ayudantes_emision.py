"""Ayudantes de T-209: KMS de prueba, plantillas listas para emitir y solicitudes."""

import os
import uuid

from ayudantes_constancias import SECRETO_INTERNO, publicar_version, sql
from cc_constancias.almacenamiento import clave_borrador
from cc_constancias.contenido import hash_de

CONTENIDO_EMISION = {
    "esquema": 1,
    "bloques": [
        {
            "tipo": "parrafo",
            "contenido": [
                {"texto": "Constancia de "},
                {"var": "nombre_completo"},
                {"texto": " con NSS "},
                {"var": "nss"},
            ],
        }
    ],
}


class KmsFalso:
    """La DEK "cifrada" es la clara XOR una máscara, ligada al contexto de cifrado."""

    def __init__(self):
        self._mascara = os.urandom(32)

    def _etiqueta(self, contexto: dict) -> bytes:
        return repr(sorted(contexto.items())).encode()

    def generate_data_key(self, **kw):
        assert kw["EncryptionContext"]["servicio"] == "constancias"
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


def interno(servicio: str, empresa_id: int | None) -> dict[str, str]:
    from cc_common.internal_client import emitir_token_interno

    h = {"Authorization": f"Bearer {emitir_token_interno(SECRETO_INTERNO, servicio)}"}
    if empresa_id is not None:
        h["X-Empresa-Id"] = str(empresa_id)
    return h


def plantilla_activa(datos, almacen, contenido=None, nombre="Constancia", activa=True) -> int:
    """Plantilla con su versión 1 publicada (y activa, si se pide)."""
    pid = sql(
        datos,
        "INSERT INTO constancias.plantilla_constancia (empresa_id, nombre) VALUES (%s, %s) "
        "RETURNING id",
        (datos["a"], nombre),
    )[0][0]
    publicar_version(datos, almacen, pid, 1, contenido or CONTENIDO_EMISION)
    if activa:
        sql(
            datos, "UPDATE constancias.plantilla_constancia SET activa = true WHERE id = %s", (pid,)
        )
    return pid


def poner_borrador(datos, almacen, plantilla_id: int, contenido: dict) -> None:
    from cc_constancias import contenido as esquema

    cuerpo = esquema.serializar(esquema.leer(contenido))
    clave = clave_borrador(datos["a"], plantilla_id)
    almacen._s3.put_object(Bucket=almacen._bucket, Key=clave, Body=cuerpo)
    sql(
        datos,
        "INSERT INTO constancias.borrador_plantilla (plantilla_id, empresa_id, contenido_s3_key, "
        "hash_sha256, actualizado_por_usuario_id) VALUES (%s, %s, %s, %s, %s)",
        (plantilla_id, datos["a"], clave, hash_de(cuerpo), datos["ua"]),
    )


def version_id(datos, plantilla_id: int) -> int:
    return sql(
        datos,
        "SELECT id FROM constancias.version_plantilla WHERE plantilla_id = %s AND numero = 1",
        (plantilla_id,),
    )[0][0]


def conversacion(datos, colaborador_id: int) -> int:
    return sql(
        datos,
        "INSERT INTO whatsapp.conversacion_whatsapp (empresa_id, colaborador_id, estado, "
        "celular_hash, origen) VALUES (%s, %s, 'ACTIVA', decode(md5(%s) || md5(%s), 'hex'), "
        "'CONSTANCIA') RETURNING id",
        (datos["a"], colaborador_id, uuid.uuid4().hex, uuid.uuid4().hex),
    )[0][0]


def solicitud(
    datos, colaborador_id: int, plantilla_id: int | None = None, estado="RECIBIDA"
) -> int:
    version = version_id(datos, plantilla_id) if plantilla_id else None
    return sql(
        datos,
        "INSERT INTO constancias.solicitud_constancia (empresa_id, colaborador_id, "
        "version_plantilla_id, estado, colaborador_nombre) "
        "VALUES (%s, %s, %s, %s, 'Ana Pérez Ruiz') RETURNING id",
        (datos["a"], colaborador_id, version, estado),
    )[0][0]


def salidas(datos, tipo: str) -> list[dict]:
    """Mensajes del ``outbox`` de constancias de un tipo."""
    filas = sql(
        datos, "SELECT payload FROM constancias.outbox WHERE tipo = %s ORDER BY id", (tipo,)
    )
    return [f[0] for f in filas]
