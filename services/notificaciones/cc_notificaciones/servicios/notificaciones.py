"""CRUD de notificaciones, duplicar, destinatarios e indicadores (NOT-14 a 17, 21, 23 y 24;
design.md §3.6; CC-REQ-102, 103, 104, 119, 120, 121, 122).

**Cómo se define la audiencia** (decisión abierta de T-215; lo más conservador y coherente con
``cv1_09``, donde el selector ofrece "Por criterios", "Individual" y "Grupo guardado"):

=============  ==============================  =====================================================
``modo``       Campo del contrato              Qué se guarda
=============  ==============================  =====================================================
CRITERIOS      ``criterios`` (en línea)        ``criterios_snapshot_json`` = los criterios validados
GRUPO          ``audiencia_id`` (guardada)     ``audiencia_id``; NOT-18 toma sus criterios vivos y
                                               deja el snapshot al revisar
INDIVIDUAL     ``colaborador_id``              ``criterios_snapshot_json`` con el criterio estable
                                               ``{"campo": "colaborador_id", "operador": "es"}``
=============  ==============================  =====================================================

Así no hace falta una columna nueva ni un campo extra en INT-COL-06: el colaborador individual es
un criterio más (``colaborador_id`` es campo fijo de ``cc_common.criterios_audiencia``) y pasa por
el mismo embudo (consentimiento, estatus, celular válido). Se exige exactamente un campo según el
modo. Al crear un INDIVIDUAL se comprueba (conteo en INT-COL-06) que el colaborador exista en la
empresa: de lo contrario 422 ``COLABORADOR_NO_ENCONTRADO``.

Reglas:
- Solo plantillas APROBADAS: otra cosa, 422 ``PLANTILLA_META_NO_APROBADA``. El contrato no tiene
  texto libre ni ``canal`` (``extra=forbid``): solo plantilla aprobada más variables
  (``servicios/variables.py``). ``canal`` queda siempre ``PLANTILLA_META``.
- Edición solo en BORRADOR (otro estado: 409 ``ESTADO_INVALIDO``). Cambiar la audiencia invalida la
  revisión (borra renglones y totales): hay que revisar de nuevo.
- La zona horaria se guarda al crear (la que mande el cliente, validada, o ``CC_ZONA_HORARIA``).
- Duplicar (NOT-23) copia plantilla, variables, audiencia/criterios y respaldo de correo a un nuevo
  BORRADOR sin revisión ni destinatarios, y exige que la plantilla siga APROBADA.
- Destinatarios (NOT-21): celular enmascarado ``+52 •• •••• nnnn``; el celular completo no existe
  en este servicio.
- Indicadores (NOT-24): destinatarios de las notificaciones enviadas en el mes local de la empresa;
  porcentajes sobre las enviadas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.db import transaccion
from cc_common.errores import (
    ErrorCampo,
    ErrorConflicto,
    ErrorNoEncontrado,
    ErrorValidacion,
)
from cc_common.paginacion import (
    LIMITE_CURSOR_MAX,
    PaginaCursor,
    acotar,
    codificar_cursor,
)

from cc_notificaciones.repos import audiencias as repo_audiencias
from cc_notificaciones.repos import destinatarios as repo_dest
from cc_notificaciones.repos import notificaciones as repo
from cc_notificaciones.repos import plantillas as repo_plantillas
from cc_notificaciones.servicios import horario, variables
from cc_notificaciones.servicios.paginas import decodificar_id

MODOS = ("CRITERIOS", "INDIVIDUAL", "GRUPO")
CAMPOS_AUDIENCIA = ("criterios", "colaborador_id", "audiencia_id")
ESTADOS_DESTINATARIO = (
    "PENDIENTE",
    "EXCLUIDO",
    "ENVIADO",
    "ENTREGADO",
    "LEIDO",
    "RESPONDIO",
    "FALLIDO",
)
MAX_TITULO = 150


def criterio_individual(colaborador_id: int) -> dict[str, Any]:
    return {
        "op": "Y",
        "items": [{"campo": "colaborador_id", "operador": "es", "valor": colaborador_id}],
    }


def colaborador_de(criterios: dict[str, Any] | None) -> int | None:
    """El ``colaborador_id`` de un criterio individual (``None`` si no lo es)."""
    try:
        (hoja,) = criterios["items"]  # type: ignore[index]
        if hoja["campo"] == "colaborador_id" and hoja["operador"] == "es":
            return int(hoja["valor"])
    except (KeyError, TypeError, ValueError):
        return None
    return None


def mascara_celular(ultimos4: str | None) -> str | None:
    """``+52 •• •••• nnnn``: solo los últimos cuatro dígitos son visibles (CC-REQ-121)."""
    if not ultimos4:
        return None
    return f"+52 •• •••• {str(ultimos4).strip()}"


def _error_audiencia(codigo: str, mensaje: str, campo: str = "modo") -> ErrorValidacion:
    return ErrorValidacion(codigo, mensaje, errores=[ErrorCampo(campo, codigo, mensaje)])


def _estado_no_editable(actual: str) -> ErrorConflicto:
    return ErrorConflicto(
        "ESTADO_INVALIDO",
        "Solo se puede editar una notificación en borrador.",
        detalle={"estado_actual": actual, "estado_esperado": "BORRADOR"},
    )


def _titulo(titulo: str) -> str:
    t = titulo.strip()
    if not t or len(t) > MAX_TITULO:
        raise ErrorValidacion(
            errores=[
                ErrorCampo("titulo", "TITULO_INVALIDO", f"Use de 1 a {MAX_TITULO} caracteres.")
            ]
        )
    return t


async def _plantilla_aprobada(conn, plantilla_id: int) -> dict[str, Any]:
    p = await repo_plantillas.obtener(conn, plantilla_id)
    if p is None:
        raise ErrorValidacion(
            "PLANTILLA_NO_ENCONTRADA",
            "La plantilla no existe.",
            errores=[ErrorCampo("plantilla_mensaje_id", "PLANTILLA_NO_ENCONTRADA", "No existe.")],
        )
    if p["estado_meta"] != "APROBADA":
        raise ErrorValidacion(
            "PLANTILLA_META_NO_APROBADA",
            "Solo se pueden usar plantillas aprobadas por Meta.",
            errores=[
                ErrorCampo(
                    "plantilla_mensaje_id",
                    "PLANTILLA_META_NO_APROBADA",
                    "La plantilla debe estar aprobada.",
                )
            ],
        )
    return p


async def _validar_variables(campos_cli, empresa_id: int, vars_: Any, texto: str) -> None:
    definiciones = None
    if variables.usa_campos_dinamicos(vars_):
        definiciones = await campos_cli.definiciones(empresa_id)
    variables.validar(vars_, texto, definiciones)


async def _resolver_audiencia(
    motor,
    campos_cli,
    col_cli,
    u: UsuarioActual,
    cfg,
    *,
    modo: str,
    criterios: Any,
    colaborador_id: int | None,
    audiencia_id: int | None,
) -> tuple[int | None, dict[str, Any] | None]:
    """``(audiencia_id, criterios_snapshot)`` según el modo; exige exactamente un campo."""
    dados = {
        "criterios": criterios is not None,
        "colaborador_id": colaborador_id is not None,
        "audiencia_id": audiencia_id is not None,
    }
    esperado = {"CRITERIOS": "criterios", "INDIVIDUAL": "colaborador_id", "GRUPO": "audiencia_id"}
    if modo not in esperado:
        raise _error_audiencia("MODO_INVALIDO", "El modo no es válido.")
    campo = esperado[modo]
    if not dados[campo]:
        raise _error_audiencia("AUDIENCIA_REQUERIDA", "Falta definir a quién se le escribe.", campo)
    sobrantes = [c for c in CAMPOS_AUDIENCIA if c != campo and dados[c]]
    if sobrantes:
        raise ErrorValidacion(
            "AUDIENCIA_AMBIGUA",
            "Indique solo la audiencia del modo elegido.",
            errores=[
                ErrorCampo(c, "AUDIENCIA_AMBIGUA", "No aplica al modo elegido.") for c in sobrantes
            ],
        )
    if modo == "CRITERIOS":
        from cc_common.criterios_audiencia import validar

        validar(criterios, await campos_cli.definiciones(u.empresa_id))
        return None, criterios
    if modo == "GRUPO":
        async with transaccion(motor, u.empresa_id) as conn:
            a = await repo_audiencias.obtener(conn, audiencia_id)  # type: ignore[arg-type]
        if a is None:
            raise _error_audiencia("AUDIENCIA_NO_ENCONTRADA", "La audiencia no existe.", campo)
        if not a["activa"]:
            raise _error_audiencia("AUDIENCIA_INACTIVA", "La audiencia está desactivada.", campo)
        return audiencia_id, None
    crit = criterio_individual(colaborador_id)  # type: ignore[arg-type]
    r = await col_cli.evaluar_audiencia(
        u.empresa_id, crit, solo_conteo=True, zona_horaria=cfg.zona_horaria
    )
    if r.total == 0:
        raise _error_audiencia(
            "COLABORADOR_NO_ENCONTRADO", "El colaborador no existe.", "colaborador_id"
        )
    return None, crit


async def crear(
    motor, cfg, campos_cli, col_cli, u: UsuarioActual, d: dict[str, Any]
) -> dict[str, Any]:
    usuario_id = requerir_usuario_id(u)
    titulo = _titulo(d["titulo"])
    zona = d.get("zona_horaria") or cfg.zona_horaria
    horario.zona(zona)
    async with transaccion(motor, u.empresa_id) as conn:
        plantilla = await _plantilla_aprobada(conn, d["plantilla_mensaje_id"])
    await _validar_variables(
        campos_cli, u.empresa_id, d["variables"], plantilla["texto_con_variables"]
    )
    audiencia_id, criterios = await _resolver_audiencia(
        motor,
        campos_cli,
        col_cli,
        u,
        cfg,
        modo=d["modo"],
        criterios=d.get("criterios"),
        colaborador_id=d.get("colaborador_id"),
        audiencia_id=d.get("audiencia_id"),
    )
    async with transaccion(motor, u.empresa_id) as conn:
        nid = await repo.crear(
            conn,
            empresa_id=u.empresa_id,
            usuario_id=usuario_id,
            titulo=titulo,
            modo=d["modo"],
            audiencia_id=audiencia_id,
            criterios=criterios,
            plantilla_id=plantilla["id"],
            variables=d["variables"],
            respaldo_correo=bool(d.get("respaldo_correo", False)),
            zona_horaria=zona,
        )
        return await repo.obtener(conn, nid)  # type: ignore[return-value]


async def listar(
    motor,
    u: UsuarioActual,
    *,
    pestana: str,
    estado: str | None,
    cursor: str | None,
    limite: int | None,
) -> tuple[PaginaCursor[dict[str, Any]], dict[str, int]]:
    tope = acotar(limite, LIMITE_CURSOR_MAX)
    despues = decodificar_id(cursor)
    estados = (estado,) if estado else repo.PESTANAS[pestana]
    async with transaccion(motor, u.empresa_id) as conn:
        filas = await repo.listar(conn, estados=estados, despues_de=despues, limite=tope + 1)
        conteos = await repo.conteo_pestanas(conn)
    pagina = filas[:tope]
    siguiente = codificar_cursor((pagina[-1]["id"],)) if len(filas) > tope else None
    return PaginaCursor(pagina, siguiente), conteos


async def detalle(motor, u: UsuarioActual, notificacion_id: int) -> dict[str, Any]:
    async with transaccion(motor, u.empresa_id) as conn:
        n = await repo.obtener(conn, notificacion_id)
    if n is None:
        raise ErrorNoEncontrado()
    return n


async def actualizar(
    motor, cfg, campos_cli, col_cli, u: UsuarioActual, notificacion_id: int, cambios: dict[str, Any]
) -> dict[str, Any]:
    """NOT-17. ``cambios`` solo trae lo que mandó el cliente (``exclude_unset``)."""
    async with transaccion(motor, u.empresa_id) as conn:
        actual = await repo.obtener(conn, notificacion_id)
    if actual is None:
        raise ErrorNoEncontrado()
    if actual["estado"] != "BORRADOR":
        raise _estado_no_editable(actual["estado"])

    nuevos: dict[str, Any] = {}
    if "titulo" in cambios:
        nuevos["titulo"] = _titulo(cambios["titulo"])
    if "respaldo_correo" in cambios:
        nuevos["respaldo_correo"] = bool(cambios["respaldo_correo"])
    if "zona_horaria" in cambios:
        horario.zona(cambios["zona_horaria"])
        nuevos["zona_horaria"] = cambios["zona_horaria"]

    plantilla_id = cambios.get("plantilla_mensaje_id", actual["plantilla_mensaje_id"])
    if "plantilla_mensaje_id" in cambios or "variables" in cambios:
        async with transaccion(motor, u.empresa_id) as conn:
            plantilla = await _plantilla_aprobada(conn, plantilla_id)
        vars_ = cambios.get("variables", actual["variables_json"] or {})
        await _validar_variables(campos_cli, u.empresa_id, vars_, plantilla["texto_con_variables"])
        nuevos["plantilla_mensaje_id"] = plantilla_id
        nuevos["variables_json"] = vars_

    cambia_audiencia = any(k in cambios for k in ("modo", *CAMPOS_AUDIENCIA))
    if cambia_audiencia:
        modo = cambios.get("modo", actual["modo"])
        audiencia_id, criterios = await _resolver_audiencia(
            motor,
            campos_cli,
            col_cli,
            u,
            cfg,
            modo=modo,
            criterios=cambios.get("criterios"),
            colaborador_id=cambios.get("colaborador_id"),
            audiencia_id=cambios.get("audiencia_id"),
        )
        nuevos.update(modo=modo, audiencia_id=audiencia_id, criterios_snapshot_json=criterios)

    async with transaccion(motor, u.empresa_id) as conn:
        n = await repo.obtener(conn, notificacion_id, bloquear=True)
        if n is None:
            raise ErrorNoEncontrado()
        if n["estado"] != "BORRADOR":
            raise _estado_no_editable(n["estado"])
        if nuevos:
            await repo.actualizar(conn, notificacion_id, nuevos)
            if cambia_audiencia:
                await repo.invalidar_revision(conn, notificacion_id)
        return await repo.obtener(conn, notificacion_id)  # type: ignore[return-value]


async def duplicar(motor, u: UsuarioActual, notificacion_id: int) -> dict[str, Any]:
    """NOT-23."""
    usuario_id = requerir_usuario_id(u)
    async with transaccion(motor, u.empresa_id) as conn:
        origen = await repo.obtener(conn, notificacion_id)
        if origen is None:
            raise ErrorNoEncontrado()
        await _plantilla_aprobada(conn, origen["plantilla_mensaje_id"])
        sufijo = " (copia)"
        titulo = origen["titulo"][: MAX_TITULO - len(sufijo)] + sufijo
        nid = await repo.duplicar(
            conn, origen, empresa_id=u.empresa_id, usuario_id=usuario_id, titulo=titulo
        )
        return await repo.obtener(conn, nid)  # type: ignore[return-value]


async def destinatarios(
    motor,
    u: UsuarioActual,
    notificacion_id: int,
    *,
    estado: str | None,
    cursor: str | None,
    limite: int | None,
) -> PaginaCursor[dict[str, Any]]:
    """NOT-21."""
    tope = acotar(limite, LIMITE_CURSOR_MAX, por_defecto=50)
    despues = decodificar_id(cursor)
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.obtener(conn, notificacion_id) is None:
            raise ErrorNoEncontrado()
        filas = await repo_dest.listar_destinatarios(
            conn, notificacion_id, estado=estado, despues_de=despues, limite=tope + 1
        )
    pagina = filas[:tope]
    siguiente = codificar_cursor((pagina[-1]["id"],)) if len(filas) > tope else None
    return PaginaCursor(pagina, siguiente)


async def indicadores(motor, cfg, u: UsuarioActual, ahora: datetime) -> dict[str, Any]:
    """NOT-24: indicadores del mes local y conteo de pestañas."""
    inicio, fin = horario.inicio_de_mes(ahora, cfg.zona_horaria)
    async with transaccion(motor, u.empresa_id) as conn:
        c = await repo.indicadores_mes(conn, inicio, fin)
        pestanas = await repo.conteo_pestanas(conn)

    def pct(parte: int) -> float:
        return round(100 * parte / c["enviadas"], 1) if c["enviadas"] else 0.0

    return {
        "mes": inicio.strftime("%Y-%m"),
        "enviadas": c["enviadas"],
        "entregadas": c["entregadas"],
        "leidas": c["leidas"],
        "fallidas": c["fallidas"],
        "porcentaje_entregadas": pct(c["entregadas"]),
        "porcentaje_leidas": pct(c["leidas"]),
        "conteos": pestanas,
    }
