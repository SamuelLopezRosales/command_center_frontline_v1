"""Borrador de una plantilla (CON-07 y CON-08; CC-REQ-060, 061, 062, 064).

El borrador es el contenido que RH está editando y **no** está disponible para WhatsApp. Vive en S3
(``plantillas/{empresa}/{plantilla}/borrador.json``); la base guarda su ruta y su hash.

- Guardar valida solo la **estructura** (``contenido.leer``): que las variables existan y estén
  activas se revisa al validar y publicar. El límite es de 512 KB (413 antes de analizar).
- ``If-Match`` evita pisar ediciones: el ``ETag`` es el hash del contenido. Sobre un borrador que
  ya existe es obligatorio (428 si falta, 412 si no coincide); para crear el primero no se envía.
- Guardar el mismo contenido no escribe nada (idempotente). La fila de la plantilla se bloquea
  durante la operación, así que dos guardados simultáneos se ordenan y el segundo ve el hash nuevo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from cc_common import bitacora
from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.db import transaccion
from cc_common.errores import ErrorInterno, ErrorNoEncontrado

from cc_constancias import contenido as esquema
from cc_constancias.almacenamiento import clave_borrador
from cc_constancias.errores import (
    contenido_demasiado_grande,
    precondicion_requerida,
    version_desactualizada,
)
from cc_constancias.repos import plantillas as repo


@dataclass(frozen=True)
class Borrador:
    contenido: dict | None  # None al guardar: solo se devuelven hash y fecha
    hash: str
    fecha_modificacion: datetime

    @property
    def etag(self) -> str:
        return f'"{self.hash}"'


def etiqueta_valida(if_match: str, hash_actual: str) -> bool:
    """``If-Match`` puede venir con comillas y con el prefijo débil ``W/``."""
    candidato = if_match.strip().removeprefix("W/").strip('"')
    return candidato == hash_actual


async def obtener(motor, almacen, u: UsuarioActual, plantilla_id: int) -> Borrador:
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.obtener(conn, plantilla_id) is None:
            raise ErrorNoEncontrado()
        fila = await repo.obtener_borrador(conn, plantilla_id)
    if fila is None:
        raise ErrorNoEncontrado("BORRADOR_NO_EXISTE", "La plantilla todavía no tiene borrador.")
    cuerpo = await almacen.leer(fila["contenido_s3_key"])
    if cuerpo is None or esquema.hash_de(cuerpo) != fila["hash_sha256"]:
        # El objeto de S3 no coincide con lo registrado: no se entrega algo que no se pueda
        # garantizar. Es un error de integridad del almacenamiento, no del usuario.
        raise ErrorInterno("BORRADOR_INCONSISTENTE", "No fue posible leer el borrador.")
    return Borrador(json.loads(cuerpo), fila["hash_sha256"], fila["fecha_modificacion"])


def revisar_tamano(cuerpo: bytes, maximo: int) -> None:
    if len(cuerpo) > maximo:
        raise contenido_demasiado_grande(maximo)


async def guardar(
    motor,
    almacen,
    u: UsuarioActual,
    plantilla_id: int,
    cuerpo: bytes,
    if_match: str | None,
    maximo: int,
    ip: str | None,
) -> Borrador:
    usuario_id = requerir_usuario_id(u)
    revisar_tamano(cuerpo, maximo)
    contenido = esquema.leer(cuerpo)
    canonico = esquema.serializar(contenido)
    nuevo_hash = esquema.hash_de(canonico)
    revisar_tamano(canonico, maximo)
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.obtener(conn, plantilla_id, bloquear=True) is None:
            raise ErrorNoEncontrado()
        actual = await repo.obtener_borrador(conn, plantilla_id)
        if actual is None:
            if if_match:
                raise version_desactualizada()  # se leyó un borrador que ya no existe
        else:
            if not if_match:
                raise precondicion_requerida()
            if not etiqueta_valida(if_match, actual["hash_sha256"]):
                raise version_desactualizada()
            if actual["hash_sha256"] == nuevo_hash:
                return Borrador(None, nuevo_hash, actual["fecha_modificacion"])
        clave = clave_borrador(u.empresa_id, plantilla_id)
        await almacen.escribir(clave, canonico)
        fila = await repo.guardar_borrador(
            conn,
            empresa_id=u.empresa_id,
            plantilla_id=plantilla_id,
            clave=clave,
            hash_sha256=nuevo_hash,
            usuario_id=usuario_id,
        )
        await repo.tocar(conn, plantilla_id)
        await bitacora.registrar(
            conn,
            empresa_id=u.empresa_id,
            accion="PLANTILLA_MODIFICADA",
            entidad="plantilla_constancia",
            entidad_id=plantilla_id,
            usuario_id=usuario_id,
            ip=ip,
            detalle={"campos": ["borrador"]},
        )
        return Borrador(None, fila["hash_sha256"], fila["fecha_modificacion"])
