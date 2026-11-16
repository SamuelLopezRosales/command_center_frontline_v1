"""Interfaces internas de ``colaboradores`` (INT-COL-01 a 05, 07 y 08; design.md §3.3, §7.2).

Las usan ``whatsapp`` (búsqueda por celular, desafío, verificación y resumen para el chat),
``constancias`` (datos de la constancia y de la organización) y los emisores de mensajes
(``contactos:resolver``, la puerta única de elegibilidad, CC-REQ-157).

- Ningún dato sensible sale si no se pidió: la verificación compara en tiempo constante y nunca
  devuelve el dato; ``datos-constancia`` descifra solo las variables pedidas.
- Cuando se descifra un dato sensible se registra ``CONSULTA_SENSIBLE`` con origen ``SISTEMA``
  y los códigos, sin valores (CC-REQ-153, 156).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from cc_common import bitacora
from cc_common.crypto import iguales
from cc_common.db import transaccion
from cc_common.errores import ErrorCampo, ErrorNoEncontrado, ErrorValidacion
from sqlalchemy import text

from cc_colaboradores.repos import catalogos as repo_catalogos
from cc_colaboradores.repos import colaborador as repo
from cc_colaboradores.repos import valor_campo as repo_valor
from cc_colaboradores.servicios import elegibilidad, variables

DESAFIO_NSS = "NSS_ULTIMOS4"
DESAFIO_FECHA = "FECHA_INGRESO_DDMM"
LIMITE_LOTE = 500


def normalizar_celular(crudo: str) -> str | None:
    """A 10 dígitos: acepta espacios, guiones, ``+52`` y el ``521`` de WhatsApp para México."""
    digitos = re.sub(r"\D", "", crudo or "")
    if len(digitos) == 13 and digitos.startswith("521"):
        digitos = digitos[3:]
    elif len(digitos) == 12 and digitos.startswith("52"):
        digitos = digitos[2:]
    return digitos if len(digitos) == 10 else None


async def _sensible(conn, empresa_id: int, colaborador_id: int, codigos: list[str]) -> None:
    if codigos:
        await bitacora.registrar(
            conn,
            empresa_id=empresa_id,
            accion="CONSULTA_SENSIBLE",
            entidad="colaborador",
            entidad_id=colaborador_id,
            colaborador_id=colaborador_id,
            origen="SISTEMA",
            detalle={"codigos_internos": sorted(codigos)},
        )


async def _fila(conn, colaborador_id: int) -> dict[str, Any]:
    fila = await repo.obtener(conn, colaborador_id)
    if fila is None:
        raise ErrorNoEncontrado()
    return fila


# ------------------------------------------------------------------ INT-COL-01


async def buscar_por_celular(motor, cif, empresa_id: int, celular: str) -> dict[str, Any]:
    """Devuelve el hash aun si el número no existe, para registrar el intento (CC-REQ-072)."""
    normal = normalizar_celular(celular)
    if normal is None:
        digitos = re.sub(r"\D", "", celular or "")
        return {"encontrado": False, "celular_hash": cif.hash_numero_invalido(digitos).hex()}
    huella = cif.hash_celular(normal)
    async with transaccion(motor, empresa_id) as conn:
        cid = await repo.por_hash_celular(conn, huella)
        fila = await repo.obtener(conn, cid) if cid else None
    salida: dict[str, Any] = {"encontrado": fila is not None, "celular_hash": huella.hex()}
    if fila:
        e = elegibilidad.evaluar(fila, "VERIFICACION")
        salida.update(
            colaborador_id=fila["id"],
            estatus=fila["estatus"],
            consentimiento_vigente=elegibilidad.consentimiento_vigente(fila),
            elegible=e.elegible,
            motivo=e.motivo,
        )
    return salida


# ------------------------------------------------------------------ INT-COL-02 y 03


def _definicion_nss(definiciones):
    return next((d for d in definiciones if d.clave == "nss" and d.activo), None)


async def _tipo_desafio(conn, colaborador_id: int, definiciones) -> tuple[str, Any]:
    d = _definicion_nss(definiciones)
    if d is not None:
        r = await conn.execute(
            text(
                "SELECT 1 FROM colaboradores.valor_campo "
                "WHERE colaborador_id = :c AND campo_id = :d"
            ),
            {"c": colaborador_id, "d": d.id},
        )
        if r.first():
            return DESAFIO_NSS, d
    return DESAFIO_FECHA, None


async def desafio(motor, campos_cli, empresa_id: int, colaborador_id: int) -> str:
    definiciones = await campos_cli.definiciones(empresa_id)
    async with transaccion(motor, empresa_id) as conn:
        await _fila(conn, colaborador_id)
        tipo, _ = await _tipo_desafio(conn, colaborador_id, definiciones)
    return tipo


def _normalizar_fecha_ddmm(dato: str) -> str:
    digitos = re.sub(r"\D", "", dato or "")
    return digitos.zfill(4) if len(digitos) in (3, 4) else digitos


async def verificar(
    motor, cif, campos_cli, empresa_id: int, colaborador_id: int, dato: str
) -> bool:
    definiciones = await campos_cli.definiciones(empresa_id)
    async with transaccion(motor, empresa_id) as conn, cif.transaccion(conn, empresa_id):
        fila = await _fila(conn, colaborador_id)
        tipo, d = await _tipo_desafio(conn, colaborador_id, definiciones)
        if tipo == DESAFIO_NSS:
            valores, descifrados = await repo_valor.leer(
                conn,
                cif,
                empresa_id=empresa_id,
                colaborador_id=colaborador_id,
                definiciones=[d],
                incluir_sensibles=True,
                solo={d.codigo_interno},
            )
            esperado = str(valores.get(d.codigo_interno, ""))[-4:]
            recibido = re.sub(r"\D", "", dato or "")
            await _sensible(conn, empresa_id, colaborador_id, descifrados)
        else:
            f = fila["fecha_ingreso"]
            esperado = f"{f.day:02d}{f.month:02d}"
            recibido = _normalizar_fecha_ddmm(dato)
    # Se compara siempre, aun con longitudes distintas, en tiempo constante.
    return bool(esperado) and iguales(recibido.encode(), esperado.encode())


# ------------------------------------------------------------------ INT-COL-04


async def datos_constancia(
    motor, cif, campos_cli, empresa_id: int, colaborador_id: int, pedidas: list[str]
) -> tuple[dict[str, str], list[str]]:
    definiciones = await campos_cli.definiciones(empresa_id)
    desconocidas = sorted(set(pedidas) - variables.conocidas(definiciones))
    if desconocidas:
        raise ErrorValidacion(
            "VARIABLE_DESCONOCIDA",
            "Hay variables que no existen.",
            errores=[ErrorCampo("variables", "VARIABLE_DESCONOCIDA", v) for v in desconocidas],
        )
    async with transaccion(motor, empresa_id) as conn, cif.transaccion(conn, empresa_id):
        fila = await _fila(conn, colaborador_id)
        org = await repo_catalogos.organizacion(conn, fila["organizacion_id"]) or {}
        valores, faltantes, descifrados = await variables.resolver(
            conn,
            cif,
            empresa_id=empresa_id,
            fila=fila,
            organizacion=org,
            definiciones=definiciones,
            variables=list(dict.fromkeys(pedidas)),
        )
        await _sensible(conn, empresa_id, colaborador_id, descifrados)
    return valores, faltantes


# ------------------------------------------------------------------ INT-COL-05


@dataclass
class Contacto:
    id: int
    elegible: bool
    motivo: str | None = None
    celular: str | None = None
    correo: str | None = None
    valores: dict[str, str] = field(default_factory=dict)
    faltantes: list[str] = field(default_factory=list)


def _efectivas(token: str, por_clave: dict, por_codigo: dict) -> tuple[str, str | None]:
    """``(clave, campo)`` de una variable pedida. Una variable de colaborador de una notificación
    guarda el ``codigo_interno`` del campo dinámico (``CAMP-0003``); aquí se resuelve por ``clave``.
    La clave tiene prioridad; ``campo`` es la definición dinámica implicada (si la hay)."""
    if token in por_clave or token not in por_codigo:
        return token, token if token in por_clave else None
    clave = por_codigo[token].clave
    return clave, clave


def _sensibles_pedidas(pedidas: list[str], definiciones) -> list[str]:
    """Variables pedidas que descifrarían un campo sensible (directa o por ``registro_patronal`` y
    ``horario``, que se apoyan en el campo del mismo nombre y en ``turno``)."""
    por_clave = {d.clave: d for d in definiciones}
    por_codigo = {d.codigo_interno: d for d in definiciones}
    salida = []
    for token in pedidas:
        clave, campo = _efectivas(token, por_clave, por_codigo)
        implicados = {campo} if campo else set()
        if clave == "horario":
            implicados.add("turno")
        if clave == "registro_patronal":
            implicados.add("registro_patronal")
        if any(por_clave[c].es_sensible for c in implicados if c in por_clave):
            salida.append(token)
    return salida


async def resolver_contactos(
    motor,
    cif,
    campos_cli,
    empresa_id: int,
    ids: list[int],
    proposito: str,
    pedidas: list[str] | None,
    *,
    solo_elegibilidad: bool = False,
) -> list[Contacto]:
    """Regla única de elegibilidad. El celular se entrega solo a un elegible y por WhatsApp; el
    correo, solo con el propósito ``CORREO`` (respaldo de notificaciones).

    **Variables de plantilla** (T-217, INT-COL-05 ampliado). ``variables`` pide valores por
    elegible; salen en ``valores`` con la misma llave con la que se pidieron y lo que no tenga valor
    queda en ``faltantes``. Se aceptan las variables fijas y de organización, y los campos
    dinámicos por su ``clave`` **o** por su ``codigo_interno`` (así los guarda ``notificaciones`` en
    ``variables_json``: ``{"1": {"origen": "COLABORADOR", "campo": "CAMP-0003"}}``). Un campo
    **sensible** nunca sale por aquí (422 ``VARIABLE_SENSIBLE``): para eso existe INT-COL-04, que sí
    lo registra en la bitácora. Esta operación no registra valores ni en bitácora ni en logs.

    ``solo_elegibilidad`` devuelve solo ``elegible`` y ``motivo`` (sin celular, correo ni
    valores): para quien solo necesita saber a quién se puede escribir (NOT-22)."""
    if proposito not in elegibilidad.PROPOSITOS:
        raise ErrorValidacion(
            errores=[ErrorCampo("proposito", "VALOR_NO_PERMITIDO", "Propósito no válido.")]
        )
    if len(ids) > LIMITE_LOTE:
        raise ErrorValidacion(
            errores=[ErrorCampo("ids", "DEMASIADO_LARGO", "Máximo 500 por llamada.")]
        )
    definiciones = await campos_cli.definiciones(empresa_id)
    pedidas = [] if solo_elegibilidad else list(dict.fromkeys(pedidas or []))
    por_clave = {d.clave: d for d in definiciones}
    por_codigo = {d.codigo_interno: d for d in definiciones}
    conocidas = variables.conocidas(definiciones)
    desconocidas = sorted(v for v in pedidas if v not in conocidas and v not in por_codigo)
    if desconocidas:
        raise ErrorValidacion(
            "VARIABLE_DESCONOCIDA",
            "Hay variables que no existen.",
            errores=[ErrorCampo("variables", "VARIABLE_DESCONOCIDA", v) for v in desconocidas],
        )
    sensibles = _sensibles_pedidas(pedidas, definiciones)
    if sensibles:
        raise ErrorValidacion(
            "VARIABLE_SENSIBLE",
            "Un campo sensible no se puede pedir por esta interfaz.",
            errores=[ErrorCampo("variables", "VARIABLE_SENSIBLE", v) for v in sensibles],
        )
    claves = {v: _efectivas(v, por_clave, por_codigo)[0] for v in pedidas}
    correo_def = next((d for d in definiciones if d.clave == "correo"), None)
    salida: list[Contacto] = []
    async with transaccion(motor, empresa_id) as conn, cif.transaccion(conn, empresa_id):
        orgs: dict[int, dict] = {}
        for cid in dict.fromkeys(ids):
            fila = await repo.obtener(conn, cid)
            if fila is None:
                salida.append(Contacto(cid, False, "NO_ENCONTRADO"))
                continue
            e = elegibilidad.evaluar(fila, proposito)
            if not e.elegible:
                salida.append(Contacto(cid, False, e.motivo))
                continue
            c = Contacto(cid, True)
            if solo_elegibilidad:
                salida.append(c)
                continue
            if proposito == "CORREO":
                correo = None
                if correo_def is not None:
                    valores, _ = await repo_valor.leer(
                        conn,
                        cif,
                        empresa_id=empresa_id,
                        colaborador_id=cid,
                        definiciones=[correo_def],
                        incluir_sensibles=True,
                        solo={correo_def.codigo_interno},
                    )
                    correo = valores.get(correo_def.codigo_interno)
                if not correo:
                    salida.append(Contacto(cid, False, "SIN_CORREO"))
                    continue
                c.correo = str(correo)
            else:
                c.celular = cif.descifrar(
                    fila["celular_cifrado"],
                    empresa_id=empresa_id,
                    tabla=repo.TABLA,
                    columna=repo.COLUMNA_CELULAR,
                    registro=cid,
                )
            if pedidas:
                org_id = fila["organizacion_id"]
                if org_id not in orgs:
                    orgs[org_id] = await repo_catalogos.organizacion(conn, org_id) or {}
                por_clave_valor, _, descifrados = await variables.resolver(
                    conn,
                    cif,
                    empresa_id=empresa_id,
                    fila=fila,
                    organizacion=orgs[org_id],
                    definiciones=definiciones,
                    variables=list(dict.fromkeys(claves.values())),
                )
                await _sensible(conn, empresa_id, cid, descifrados)  # vacío: no hay sensibles
                for v in pedidas:
                    if claves[v] in por_clave_valor:
                        c.valores[v] = por_clave_valor[claves[v]]
                    else:
                        c.faltantes.append(v)
            salida.append(c)
    return salida


# ------------------------------------------------------------------ INT-COL-07 y 08


async def resumen(motor, empresa_id: int, colaborador_id: int) -> dict[str, Any]:
    async with transaccion(motor, empresa_id) as conn:
        f = await _fila(conn, colaborador_id)
    return {
        "id": f["id"],
        "numero_empleado": f["numero_empleado"],
        "nombre_completo": f"{f['nombres']} {f['apellido_paterno']} {f['apellido_materno']}",
        "puesto": f["puesto"],
        "estatus": f["estatus"],
        "organizacion": {
            "id": f["organizacion_id"],
            "clave": f["organizacion_clave"],
            "razon_social": f["organizacion_razon_social"],
        },
        "planta": {"id": f["planta_id"], "nombre": f["planta_nombre"]},
        "celular_ultimos4": f["celular_ultimos4"],
        "consentimiento_vigente": elegibilidad.consentimiento_vigente(f),
    }


async def organizacion(motor, empresa_id: int, organizacion_id: int) -> dict[str, Any]:
    async with transaccion(motor, empresa_id) as conn:
        org = await repo_catalogos.organizacion(conn, organizacion_id)
    if org is None:
        raise ErrorNoEncontrado()
    return org


# ------------------------------------------------------------------ INT-COL-09 y 10 (T-206)


async def faltantes_contar(
    motor, campos_cli, empresa_id: int, codigos: list[str]
) -> dict[str, int]:
    """Cuántos colaboradores ``ACTIVO`` no tienen valor en cada campo (CC-REQ-013, 067).

    Un código que la caché de definiciones aún no conoce (campo recién creado) se vuelve a
    pedir una vez a `campos` antes de rechazarlo con 422."""
    definiciones = {d.codigo_interno: d for d in await campos_cli.definiciones(empresa_id)}
    if any(c not in definiciones for c in codigos):
        campos_cli.invalidar(empresa_id)
        definiciones = {d.codigo_interno: d for d in await campos_cli.definiciones(empresa_id)}
    desconocidos = [c for c in codigos if c not in definiciones]
    if desconocidos:
        raise ErrorValidacion(
            "CAMPO_DESCONOCIDO",
            "Algún campo no existe.",
            errores=[ErrorCampo("codigos_internos", "CAMPO_DESCONOCIDO", "El campo no existe.")],
        )
    ids = {c: definiciones[c].id for c in codigos}
    async with transaccion(motor, empresa_id) as conn:
        r = await conn.execute(
            text(
                "SELECT i.campo_id, count(c.id) FROM unnest(CAST(:ids AS bigint[])) AS i(campo_id) "
                "LEFT JOIN colaboradores.colaborador c ON c.estatus = 'ACTIVO' "
                "AND NOT EXISTS (SELECT 1 FROM colaboradores.valor_campo v "
                "                WHERE v.colaborador_id = c.id AND v.campo_id = i.campo_id) "
                "GROUP BY i.campo_id"
            ),
            {"ids": list(ids.values())},
        )
        por_id = {int(campo): int(total) for campo, total in r.all()}
    return {codigo: por_id.get(campo_id, 0) for codigo, campo_id in ids.items()}


async def campo_con_valores(motor, empresa_id: int, campo_id: int) -> bool:
    """¿Algún colaborador de la empresa tiene valor en el campo? No consulta las definiciones:
    un campo recién creado o de otra empresa simplemente no tiene valores."""
    async with transaccion(motor, empresa_id) as conn:
        r = await conn.execute(
            text("SELECT EXISTS (SELECT 1 FROM colaboradores.valor_campo WHERE campo_id = :c)"),
            {"c": campo_id},
        )
        return bool(r.scalar_one())
