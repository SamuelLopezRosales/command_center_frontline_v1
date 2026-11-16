"""Solicitudes de constancia (INT-CON-01 a INT-CON-06; design.md §2.2, §3.5; CC-REQ-070 a 075).

`whatsapp` crea la solicitud al iniciar la conversación (INT-CON-02), fija la plantilla elegida
(INT-CON-03) y pide generarla (INT-CON-04). Generar **valida** que todas las variables tengan
valor; si faltan datos, la solicitud queda FALLIDA con ``CAMPOS_FALTANTES`` y no se genera nada. Si
todo está completo, se escribe en el ``outbox`` el mensaje a ``cola-pdf`` y responde 202: el PDF lo
hace el ``worker-pdf``.
"""

from __future__ import annotations

from typing import Any

from cc_common import outbox
from cc_common.db import transaccion
from cc_common.errores import (
    ErrorConflicto,
    ErrorNoEncontrado,
    ErrorValidacion,
)
from sqlalchemy.exc import IntegrityError

from cc_constancias import contenido as esquema
from cc_constancias.errores import desde_integridad
from cc_constancias.render.resolutor_variables import resolver
from cc_constancias.repos import solicitudes as repo

MARCADOR = "-"  # valor de relleno de las variables del sistema al validar


def _estado_invalido(estado: str) -> ErrorConflicto:
    return ErrorConflicto(
        "ESTADO_INVALIDO",
        "La solicitud ya no admite esta operación.",
        detalle={"estado_actual": estado, "estado_esperado": "RECIBIDA"},
    )


async def plantillas(motor, empresa_id: int) -> list[dict[str, Any]]:
    async with transaccion(motor, empresa_id) as conn:
        return await repo.plantillas_activas(conn)


async def crear(
    motor, empresa_id: int, *, colaborador_id: int, conversacion_id: int | None, nombre: str
) -> dict[str, Any]:
    try:
        async with transaccion(motor, empresa_id) as conn:
            return await repo.crear(
                conn,
                empresa_id=empresa_id,
                colaborador_id=colaborador_id,
                conversacion_id=conversacion_id,
                nombre=nombre,
            )
    except IntegrityError as exc:
        raise desde_integridad(exc) from exc


async def fijar_plantilla(motor, empresa_id: int, solicitud_id: int, plantilla_id: int) -> dict:
    async with transaccion(motor, empresa_id) as conn:
        s = await repo.obtener(conn, solicitud_id, bloquear=True)
        if s is None:
            raise ErrorNoEncontrado()
        if s["estado"] != "RECIBIDA":
            raise _estado_invalido(s["estado"])
        p = await repo.plantilla_para_solicitud(conn, plantilla_id)
        if p is None:
            raise ErrorConflicto(
                "PLANTILLA_NO_DISPONIBLE", "La plantilla no está activa o no tiene versión."
            )
        await repo.fijar_version(conn, solicitud_id, p["version_id"])
        return await repo.obtener(conn, solicitud_id) or s


async def registrar_fallo(
    conn,
    cfg,
    *,
    empresa_id: int,
    solicitud: dict[str, Any],
    motivo: str,
    desde: tuple[str, ...],
    campos: list[str] | None = None,
) -> bool:
    """Pasa la solicitud a FALLIDA y emite ``constancia.fallida`` (EventBridge; la regla hacia SNS
    avisa a RH). ``campos`` lleva los nombres de variable faltantes (nunca valores; design.md §5.6,
    CC-REQ-076). Devuelve ``False`` si la solicitud ya no estaba en un estado de origen."""
    if not await repo.cambiar_estado(conn, solicitud["id"], "FALLIDA", motivo=motivo, desde=desde):
        return False
    await outbox.escribir(
        conn,
        "constancias",
        destino_tipo="EVENTBRIDGE",
        destino=cfg.bus_eventos,
        tipo="constancia.fallida",
        payload={
            "empresa_id": empresa_id,
            "solicitud_id": solicitud["id"],
            "colaborador_id": solicitud["colaborador_id"],
            "motivo": motivo,
            **({"campos": sorted(campos)} if campos else {}),
        },
        empresa_id=empresa_id,
    )
    return True


async def variables_de_version(almacen, motor, empresa_id: int, version_id: int):
    """``(version, contenido)`` leído de S3 y verificado contra su hash."""
    from cc_constancias.servicios.publicacion import leer_objeto

    async with transaccion(motor, empresa_id) as conn:
        v = await repo.version_por_id(conn, version_id)
    if v is None:
        raise ErrorNoEncontrado()
    _, contenido = await leer_objeto(almacen, v["contenido_s3_key"], v["hash_sha256"])
    return v, contenido


async def generar(
    motor, almacen, campos, colaboradores, cfg, empresa_id: int, solicitud_id: int
) -> None:
    async with transaccion(motor, empresa_id) as conn:
        s = await repo.obtener(conn, solicitud_id)
    if s is None:
        raise ErrorNoEncontrado()
    if s["estado"] != "RECIBIDA":
        raise _estado_invalido(s["estado"])
    if s["version_plantilla_id"] is None:
        raise ErrorConflicto("SIN_PLANTILLA", "La solicitud no tiene plantilla elegida.")

    _, contenido = await variables_de_version(almacen, motor, empresa_id, s["version_plantilla_id"])
    definiciones = await campos.definiciones(empresa_id)
    r = await resolver(
        colaboradores,
        empresa_id=empresa_id,
        colaborador_id=s["colaborador_id"],
        variables=esquema.variables_usadas(contenido),
        definiciones=definiciones,
        sistema={"folio": MARCADOR, "qr_verificacion": MARCADOR},
    )
    problemas = [*r.desconocidas, *r.faltantes]
    async with transaccion(motor, empresa_id) as conn:
        if problemas:
            await registrar_fallo(
                conn, cfg, empresa_id=empresa_id, solicitud=s, motivo="CAMPOS_FALTANTES",
                desde=("RECIBIDA",), campos=problemas,
            )  # fmt: skip
        else:
            await outbox.escribir(
                conn,
                "constancias",
                destino_tipo="SQS",
                destino=cfg.cola_pdf_url,
                tipo="generar_pdf",
                payload={"solicitud_id": solicitud_id, "empresa_id": empresa_id},
                empresa_id=empresa_id,
                deduplicacion=f"pdf-{solicitud_id}",
            )
    if problemas:  # después del commit: el estado FALLIDA debe quedar guardado
        raise ErrorValidacion(
            "CAMPOS_FALTANTES",
            "Faltan datos del colaborador para esta constancia.",
            detalle={"campos": problemas},
        )


async def cancelar(motor, empresa_id: int, solicitud_id: int) -> dict[str, Any]:
    async with transaccion(motor, empresa_id) as conn:
        s = await repo.obtener(conn, solicitud_id, bloquear=True)
        if s is None:
            raise ErrorNoEncontrado()
        if s["estado"] != "RECIBIDA":
            raise _estado_invalido(s["estado"])
        await repo.cambiar_estado(conn, solicitud_id, "CANCELADA", desde=("RECIBIDA",))
        return await repo.obtener(conn, solicitud_id) or s


async def contenidos_vigentes(motor, almacen, empresa_id: int) -> list[tuple[dict, list[str]]]:
    """Por plantilla no eliminada: ``(fila, variables)`` de su versión vigente y su borrador.
    Un objeto ilegible se omite (no debe impedir calcular el resto)."""
    async with transaccion(motor, empresa_id) as conn:
        filas = await repo.plantillas_con_contenido(conn)
    resultado: list[tuple[dict, list[str]]] = []
    for f in filas:
        usadas: dict[str, None] = {}
        for clave in (f["version_clave"], f["borrador_clave"]):
            if not clave:
                continue
            try:
                cuerpo = await almacen.leer(clave)
                if cuerpo is not None:
                    usadas.update(dict.fromkeys(esquema.variables_usadas(esquema.leer(cuerpo))))
            except Exception:  # noqa: BLE001, S112
                continue
        resultado.append((f, list(usadas)))
    return resultado


async def uso_de_variables(
    motor, almacen, empresa_id: int, variables: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """INT-CON-06: plantillas (versión vigente o borrador) que usan cada variable."""
    usos: dict[str, list[dict[str, Any]]] = {v: [] for v in variables}
    for f, usadas in await contenidos_vigentes(motor, almacen, empresa_id):
        for v in variables:
            if v in usadas:
                usos[v].append({"id": f["id"], "nombre": f["nombre"]})
    return usos
