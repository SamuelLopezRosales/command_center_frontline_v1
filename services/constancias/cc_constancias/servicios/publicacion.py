"""Validación, publicación, versiones y restauración (CON-09 a CON-13; CC-REQ-065 a 068).

- **Validar** revisa el borrador contra el catálogo de variables: una variable que no existe o cuyo
  campo está desactivado es un **error** y no deja publicar; las variables sensibles y los
  colaboradores sin valor en un campo son **advertencias** (CC-REQ-067).
- **Publicar** crea la versión siguiente con el contenido del borrador: JSON canónico en S3
  (``plantillas/{empresa}/{plantilla}/v{n}.json``), y en la base solo su ruta y su hash SHA-256. La
  primera publicación activa la plantilla. Una versión no se modifica nunca (trigger de la base).
- El número de versión sale de ``max(numero) + 1`` con la fila de la plantilla bloqueada: dos
  publicaciones simultáneas se ordenan y no repiten número.
- **Restaurar** crea la versión N+1 con el contenido de una anterior, que no cambia. Revalida las
  variables: si alguna dejó de existir o se desactivó, 422 (CC-REQ-068).

Las llamadas a otros servicios (definiciones de campos, conteos) se hacen **antes** de abrir la
transacción que bloquea la plantilla, para no retener el bloqueo mientras se espera la red.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from cc_common import bitacora
from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.db import transaccion
from cc_common.errores import (
    ErrorCampo,
    ErrorConflicto,
    ErrorInterno,
    ErrorNoEncontrado,
    ErrorValidacion,
)

from cc_constancias import contenido as esquema
from cc_constancias.almacenamiento import clave_version
from cc_constancias.errores import version_desactualizada
from cc_constancias.render.catalogo_variables import BASE_SUELDO, Catalogo
from cc_constancias.repos import plantillas as repo
from cc_constancias.repos import versiones as repo_versiones


@dataclass
class Hallazgo:
    codigo: str
    mensaje: str
    variables: list[str] = field(default_factory=list)
    total: int | None = None


@dataclass
class Analisis:
    errores: list[Hallazgo] = field(default_factory=list)
    advertencias: list[Hallazgo] = field(default_factory=list)
    sensibles: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ lectura del contenido


async def leer_objeto(
    almacen, clave: str, hash_esperado: str
) -> tuple[bytes, esquema.ContenidoPlantilla]:
    """Contenido de S3 verificado contra su hash. Una diferencia es un error de integridad."""
    cuerpo = await almacen.leer(clave)
    if cuerpo is None or esquema.hash_de(cuerpo) != hash_esperado:
        raise ErrorInterno("CONTENIDO_INCONSISTENTE", "No fue posible leer el contenido.")
    return cuerpo, esquema.leer(cuerpo)


async def _borrador(motor, u: UsuarioActual, plantilla_id: int) -> dict[str, Any]:
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.obtener(conn, plantilla_id) is None:
            raise ErrorNoEncontrado()
        fila = await repo.obtener_borrador(conn, plantilla_id)
    if fila is None:
        raise ErrorNoEncontrado("BORRADOR_NO_EXISTE", "La plantilla todavía no tiene borrador.")
    return fila


# ------------------------------------------------------------------ análisis


def _plural(n: int) -> str:
    return "colaborador" if n == 1 else "colaboradores"


async def analizar(
    contenido: esquema.ContenidoPlantilla,
    definiciones,
    colaboradores,
    empresa_id: int,
    *,
    con_conteos: bool,
) -> Analisis:
    usadas = esquema.variables_usadas(contenido)
    catalogo = Catalogo(definiciones)
    clasif = catalogo.clasificar(usadas)
    a = Analisis(sensibles=clasif["sensibles"])
    for v in clasif["inexistentes"]:
        a.errores.append(Hallazgo("VARIABLE_INEXISTENTE", "La variable no existe.", [v]))
    for v in clasif["inactivas"]:
        a.errores.append(
            Hallazgo("VARIABLE_INACTIVA", "El campo de esta variable está desactivado.", [v])
        )
    if a.sensibles:
        a.advertencias.append(
            Hallazgo(
                "VARIABLES_SENSIBLES",
                "La plantilla usa datos sensibles: aparecerán en las constancias.",
                a.sensibles,
            )
        )
    if con_conteos:
        a.advertencias += await _sin_valor(
            usadas, catalogo, definiciones, colaboradores, empresa_id
        )
    return a


async def _sin_valor(usadas, catalogo, definiciones, colaboradores, empresa_id) -> list[Hallazgo]:
    """Cuántos colaboradores activos no tienen valor en cada campo que la plantilla usa. Las
    derivadas de sueldo dependen de ``sueldo`` y ``periodicidad_sueldo``: se cuentan esos."""
    por_clave = {d.clave: d for d in definiciones}
    campos: list[str] = []  # claves de campo, sin repetir y en orden
    for v in usadas:
        if catalogo.estado(v) != "ACTIVA":
            continue
        origen = catalogo.obtener(v).origen  # type: ignore[union-attr]
        candidatas = list(BASE_SUELDO) if origen == "DERIVADA" else [v] if origen == "CAMPO" else []
        for c in candidatas:
            if c in por_clave and c not in campos:
                campos.append(c)
    if not campos:
        return []
    conteos = await colaboradores.faltantes_contar(
        empresa_id, [por_clave[c].codigo_interno for c in campos]
    )
    avisos = []
    for c in campos:
        n = int(conteos.get(por_clave[c].codigo_interno, 0))
        if n > 0:
            avisos.append(
                Hallazgo(
                    "COLABORADORES_SIN_VALOR",
                    f"{n} {_plural(n)} sin {por_clave[c].nombre_campo}.",
                    [c],
                    total=n,
                )
            )
    return avisos


def _errores_422(a: Analisis) -> ErrorValidacion:
    return ErrorValidacion(
        "PLANTILLA_VARIABLE_INVALIDA",
        "Hay variables que no existen o están desactivadas.",
        errores=[ErrorCampo(f"variables.{h.variables[0]}", h.codigo, h.mensaje) for h in a.errores],
    )


# ------------------------------------------------------------------ CON-09


async def validar(
    motor, almacen, campos, colaboradores, u: UsuarioActual, plantilla_id: int
) -> Analisis:
    fila = await _borrador(motor, u, plantilla_id)
    _, contenido = await leer_objeto(almacen, fila["contenido_s3_key"], fila["hash_sha256"])
    definiciones = await campos.definiciones(u.empresa_id)
    return await analizar(contenido, definiciones, colaboradores, u.empresa_id, con_conteos=True)


# ------------------------------------------------------------------ CON-10


async def _crear_version(
    motor,
    almacen,
    u: UsuarioActual,
    plantilla_id: int,
    cuerpo: bytes,
    hash_: str,
    ip: str | None,
    *,
    borrador_esperado: str | None,
) -> dict[str, Any]:
    usuario_id = requerir_usuario_id(u)
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.obtener(conn, plantilla_id, bloquear=True) is None:
            raise ErrorNoEncontrado()
        if borrador_esperado is not None:
            actual = await repo.obtener_borrador(conn, plantilla_id)
            if actual is None or actual["hash_sha256"] != borrador_esperado:
                raise version_desactualizada()  # el borrador cambió mientras se validaba
        numero = await repo_versiones.siguiente_numero(conn, plantilla_id)
        clave = clave_version(u.empresa_id, plantilla_id, numero)
        await almacen.escribir(clave, cuerpo)
        version = await repo_versiones.insertar(
            conn,
            empresa_id=u.empresa_id,
            plantilla_id=plantilla_id,
            numero=numero,
            clave=clave,
            hash_sha256=hash_,
            usuario_id=usuario_id,
        )
        if numero == 1:
            await repo_versiones.activar(conn, plantilla_id)  # la primera publicación la activa
        else:
            await repo.tocar(conn, plantilla_id)
        await bitacora.registrar(
            conn,
            empresa_id=u.empresa_id,
            accion="PLANTILLA_PUBLICADA",
            entidad="plantilla_constancia",
            entidad_id=plantilla_id,
            usuario_id=usuario_id,
            ip=ip,
            detalle={"plantilla_id": plantilla_id, "version": numero},
        )
        return {**version, "vigente": True}


async def publicar(
    motor,
    almacen,
    campos,
    colaboradores,
    u: UsuarioActual,
    plantilla_id: int,
    confirmar_sensibles: bool,
    ip: str | None,
) -> dict[str, Any]:
    requerir_usuario_id(u)
    fila = await _borrador(motor, u, plantilla_id)
    cuerpo, contenido = await leer_objeto(almacen, fila["contenido_s3_key"], fila["hash_sha256"])
    definiciones = await campos.definiciones(u.empresa_id)
    a = await analizar(contenido, definiciones, colaboradores, u.empresa_id, con_conteos=False)
    if a.errores:
        raise _errores_422(a)
    if a.sensibles and not confirmar_sensibles:
        raise ErrorConflicto(
            "PLANTILLA_SENSIBLES_REQUIERE_CONFIRMACION",
            "La plantilla usa datos sensibles; confirme la publicación.",
            detalle={"campos": a.sensibles},
        )
    return await _crear_version(
        motor, almacen, u, plantilla_id, cuerpo, fila["hash_sha256"], ip,
        borrador_esperado=fila["hash_sha256"],
    )  # fmt: skip


# ------------------------------------------------------------------ CON-11 y CON-12


async def listar_versiones(motor, u: UsuarioActual, plantilla_id: int) -> list[dict[str, Any]]:
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.obtener(conn, plantilla_id) is None:
            raise ErrorNoEncontrado()
        filas = await repo_versiones.listar(conn, plantilla_id)
    return [{**f, "vigente": i == 0} for i, f in enumerate(filas)]  # la primera es la más nueva


async def obtener_version(
    motor, almacen, u: UsuarioActual, plantilla_id: int, numero: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.obtener(conn, plantilla_id) is None:
            raise ErrorNoEncontrado()
        fila = await repo_versiones.obtener(conn, plantilla_id, numero)
        ultima = await repo.ultima_version(conn, plantilla_id)
    if fila is None:
        raise ErrorNoEncontrado()
    cuerpo = await almacen.leer(fila["contenido_s3_key"])
    if cuerpo is None or esquema.hash_de(cuerpo) != fila["hash_sha256"]:
        raise ErrorInterno("CONTENIDO_INCONSISTENTE", "No fue posible leer el contenido.")
    vigente = ultima is not None and ultima["numero"] == fila["numero"]
    return {**fila, "vigente": vigente}, json.loads(cuerpo)


# ------------------------------------------------------------------ CON-13


async def restaurar(
    motor,
    almacen,
    campos,
    colaboradores,
    u: UsuarioActual,
    plantilla_id: int,
    numero: int,
    ip: str | None,
) -> dict[str, Any]:
    requerir_usuario_id(u)
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.obtener(conn, plantilla_id) is None:
            raise ErrorNoEncontrado()
        origen = await repo_versiones.obtener(conn, plantilla_id, numero)
    if origen is None:
        raise ErrorNoEncontrado()
    cuerpo, contenido = await leer_objeto(
        almacen, origen["contenido_s3_key"], origen["hash_sha256"]
    )
    definiciones = await campos.definiciones(u.empresa_id)
    a = await analizar(contenido, definiciones, colaboradores, u.empresa_id, con_conteos=False)
    if a.errores:
        raise _errores_422(a)
    return await _crear_version(
        motor, almacen, u, plantilla_id, cuerpo, origen["hash_sha256"], ip, borrador_esperado=None
    )
