"""Plantillas de mensaje y su aprobación en Meta (NOT-07 a NOT-13; design.md §3.6, §7.5;
CC-REQ-117).

Reglas:
- Nombre en minúsculas, dígitos y guion bajo (regla de Meta; hasta 512 caracteres). Variables
  ``{{1}}``, ``{{2}}``... **consecutivas desde 1** (una puede repetirse en el texto); cada variable
  exige un ejemplo (Meta lo pide) y sin variables no hay ejemplos.
- Solo se edita en BORRADOR o RECHAZADA (otro estado: 409 ``ESTADO_INVALIDO``). Una plantilla que
  ya se envió a Meta (RECHAZADA con ``id_plantilla_meta``) conserva nombre, categoría e idioma:
  Meta no los deja cambiar al editar; solo el texto y los ejemplos. (La edición de una rechazada y
  su reenvío se confirman al vincular la cuenta, PQ-07.)
- ``enviar_a_revision`` (NOT-11) llama a Meta **con la fila bloqueada** (``FOR UPDATE``): dos envíos
  simultáneos no crean dos plantillas en Meta; el segundo ve EN_REVISION y recibe 409. Un fallo de
  Meta revierte todo y da 502 ``ERROR_PROVEEDOR_META``. Una rechazada que ya tiene id en Meta se
  reenvía actualizándola, no creándola otra vez.
- Aprobación o rechazo llegan por el evento ``wa.plantilla_estado`` (``aplicar_evento``) o por
  ``sincronizar`` (NOT-13), que consulta a Meta y respalda al evento. Solo se pasa de EN_REVISION a
  APROBADA o RECHAZADA (comparar y cambiar): un evento repetido, tardío o de otro estado de Meta
  (PAUSED, DISABLED...) no cambia nada. Se guarda el motivo del rechazo.
- Duplicar (NOT-12) crea un BORRADOR con nombre ``{nombre}_copia`` (o ``_copia_2``...).
- Nada de esto registra texto de plantillas ni de errores de Meta en logs: solo ids.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.db import transaccion
from cc_common.errores import (
    ErrorCampo,
    ErrorConflicto,
    ErrorNoEncontrado,
    ErrorProveedor,
    ErrorValidacion,
)
from cc_common.eventos import procesar_una_vez
from cc_common.paginacion import (
    LIMITE_CURSOR_MAX,
    PaginaCursor,
    acotar,
    codificar_cursor,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from cc_notificaciones.errores import desde_integridad
from cc_notificaciones.meta import ErrorMeta
from cc_notificaciones.repos import plantillas as repo
from cc_notificaciones.servicios.paginas import decodificar_id

log = logging.getLogger("cc.notificaciones.plantillas")

NOMBRE = re.compile(r"^[a-z0-9_]{1,512}$")
IDIOMA = re.compile(r"^[a-z]{2,3}(_[A-Z]{2})?$")
TOKEN = re.compile(r"\{\{[^{}]*\}\}")
VARIABLE = re.compile(r"^\{\{([1-9][0-9]{0,1})\}\}$")
MAX_TEXTO = 1024  # límite del cuerpo en Meta
MAX_VARIABLES = 20
MAX_EJEMPLO = 200
ESTADOS = ("BORRADOR", "EN_REVISION", "APROBADA", "RECHAZADA")
EDITABLES_ESTADOS = ("BORRADOR", "RECHAZADA")
# Estados de Meta (evento y consulta) que cierran la revisión.
ESTADO_DE_META = {"APPROVED": "APROBADA", "REJECTED": "RECHAZADA"}


def posiciones(texto: str) -> list[int]:
    """Números de variable del texto, en orden de aparición (una variable puede repetirse).
    Lanza ``ErrorValidacion`` si hay llaves que no forman una variable ``{{n}}``."""
    errores: list[ErrorCampo] = []
    encontradas: list[int] = []
    for t in TOKEN.findall(texto):
        m = VARIABLE.match(t)
        if m:
            encontradas.append(int(m.group(1)))
        else:
            errores.append(
                ErrorCampo(
                    "texto_con_variables", "VARIABLE_INVALIDA", "Use variables como {{1}}, {{2}}."
                )
            )
            break
    resto = TOKEN.sub("", texto)
    if not errores and ("{{" in resto or "}}" in resto):
        errores.append(
            ErrorCampo("texto_con_variables", "VARIABLE_INVALIDA", "Hay llaves sin cerrar.")
        )
    if not errores and encontradas:
        distintas = sorted(set(encontradas))
        if distintas != list(range(1, len(distintas) + 1)):
            errores.append(
                ErrorCampo(
                    "texto_con_variables",
                    "VARIABLES_NO_CONSECUTIVAS",
                    "Las variables deben ser consecutivas desde {{1}}.",
                )
            )
        elif len(distintas) > MAX_VARIABLES:
            errores.append(
                ErrorCampo(
                    "texto_con_variables",
                    "DEMASIADAS_VARIABLES",
                    f"El máximo es de {MAX_VARIABLES} variables.",
                )
            )
    if errores:
        raise ErrorValidacion(errores=errores)
    return encontradas


def cantidad_variables(texto: str) -> int:
    return len(set(posiciones(texto)))


def validar(*, nombre: str, categoria: str, idioma: str, texto: str, ejemplos: list[str]) -> int:
    """Valida los datos de una plantilla y devuelve cuántas variables tiene."""
    errores: list[ErrorCampo] = []
    if not NOMBRE.match(nombre):
        errores.append(
            ErrorCampo(
                "nombre",
                "NOMBRE_INVALIDO",
                "Use solo minúsculas, números y guion bajo (sin espacios ni acentos).",
            )
        )
    if not IDIOMA.match(idioma):
        errores.append(ErrorCampo("idioma", "IDIOMA_INVALIDO", "Use un código como es_MX."))
    if not texto.strip() or len(texto) > MAX_TEXTO:
        errores.append(
            ErrorCampo(
                "texto_con_variables",
                "TEXTO_INVALIDO",
                f"El texto debe tener de 1 a {MAX_TEXTO} caracteres.",
            )
        )
        raise ErrorValidacion(errores=errores)
    try:
        n = cantidad_variables(texto)
    except ErrorValidacion as exc:
        errores.extend(exc.errores)
        raise ErrorValidacion(errores=errores) from exc
    if len(ejemplos) != n:
        errores.append(
            ErrorCampo(
                "ejemplos",
                "EJEMPLOS_NO_COINCIDEN",
                "Indique un ejemplo por cada variable." if n else "Sin variables no hay ejemplos.",
            )
        )
    elif any(not e.strip() or len(e) > MAX_EJEMPLO or "\n" in e for e in ejemplos):
        errores.append(
            ErrorCampo(
                "ejemplos",
                "EJEMPLO_INVALIDO",
                f"Cada ejemplo lleva de 1 a {MAX_EJEMPLO} caracteres en una sola línea.",
            )
        )
    if errores:
        raise ErrorValidacion(errores=errores)
    return n


def _estado_no_editable(actual: str) -> ErrorConflicto:
    return ErrorConflicto(
        "ESTADO_INVALIDO",
        "Solo se puede editar o enviar una plantilla en borrador o rechazada.",
        detalle={"estado_actual": actual, "estado_esperado": "BORRADOR o RECHAZADA"},
    )


def _error_meta(exc: ErrorMeta) -> ErrorProveedor:
    log.warning("falló la API de plantillas de Meta: %s", exc.motivo)  # sin cuerpo de Meta
    return ErrorProveedor(
        "ERROR_PROVEEDOR_META", "Meta no pudo atender la solicitud. Intente de nuevo."
    )


async def crear(
    motor,
    u: UsuarioActual,
    *,
    nombre: str,
    categoria: str,
    idioma: str,
    texto: str,
    ejemplos: list[str],
) -> dict[str, Any]:
    usuario_id = requerir_usuario_id(u)
    validar(nombre=nombre, categoria=categoria, idioma=idioma, texto=texto, ejemplos=ejemplos)
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            return await repo.crear(
                conn,
                empresa_id=u.empresa_id,
                usuario_id=usuario_id,
                nombre=nombre,
                categoria=categoria,
                idioma=idioma,
                texto=texto,
                ejemplos=ejemplos,
            )
    except IntegrityError as exc:
        raise desde_integridad(exc) from exc


async def listar(
    motor, u: UsuarioActual, estado: str | None, cursor: str | None, limite: int | None
) -> PaginaCursor[dict[str, Any]]:
    tope = acotar(limite, LIMITE_CURSOR_MAX)
    despues = decodificar_id(cursor)
    async with transaccion(motor, u.empresa_id) as conn:
        filas = await repo.listar(conn, estado=estado, despues_de=despues, limite=tope + 1)
    pagina = filas[:tope]
    siguiente = codificar_cursor((pagina[-1]["id"],)) if len(filas) > tope else None
    return PaginaCursor(pagina, siguiente)


async def detalle(motor, u: UsuarioActual, plantilla_id: int) -> dict[str, Any]:
    async with transaccion(motor, u.empresa_id) as conn:
        p = await repo.obtener(conn, plantilla_id)
    if p is None:
        raise ErrorNoEncontrado()
    return p


async def actualizar(
    motor, u: UsuarioActual, plantilla_id: int, cambios: dict[str, Any]
) -> dict[str, Any]:
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            p = await repo.obtener(conn, plantilla_id, bloquear=True)
            if p is None:
                raise ErrorNoEncontrado()
            if p["estado_meta"] not in EDITABLES_ESTADOS:
                raise _estado_no_editable(p["estado_meta"])
            if p["id_plantilla_meta"]:
                bloqueados = [
                    k
                    for k in ("nombre", "categoria", "idioma")
                    if k in cambios and cambios[k] != p[k]
                ]
                if bloqueados:
                    raise ErrorValidacion(
                        "CAMPO_NO_EDITABLE",
                        "Meta no permite cambiar estos datos de una plantilla ya enviada.",
                        errores=[
                            ErrorCampo(k, "CAMPO_NO_EDITABLE", "No se puede cambiar.")
                            for k in bloqueados
                        ],
                    )
            nuevos = {
                "nombre": cambios.get("nombre", p["nombre"]),
                "categoria": cambios.get("categoria", p["categoria"]),
                "idioma": cambios.get("idioma", p["idioma"]),
                "texto_con_variables": cambios.get("texto_con_variables", p["texto_con_variables"]),
                "ejemplos_json": cambios.get("ejemplos", p["ejemplos_json"] or []),
            }
            validar(
                nombre=nuevos["nombre"],
                categoria=nuevos["categoria"],
                idioma=nuevos["idioma"],
                texto=nuevos["texto_con_variables"],
                ejemplos=nuevos["ejemplos_json"],
            )
            if all(nuevos[k] == p[k] for k in nuevos):
                return p
            return await repo.actualizar(conn, plantilla_id, nuevos)
    except IntegrityError as exc:
        raise desde_integridad(exc) from exc


async def enviar_a_revision(motor, meta, u: UsuarioActual, plantilla_id: int) -> dict[str, Any]:
    """NOT-11. Crea la plantilla en Meta (o actualiza la rechazada) y pasa a EN_REVISION."""
    async with transaccion(motor, u.empresa_id) as conn:
        p = await repo.obtener(conn, plantilla_id, bloquear=True)
        if p is None:
            raise ErrorNoEncontrado()
        if p["estado_meta"] not in EDITABLES_ESTADOS:
            raise _estado_no_editable(p["estado_meta"])
        ejemplos = p["ejemplos_json"] or []
        try:
            if p["id_plantilla_meta"]:
                await meta.actualizar(
                    p["id_plantilla_meta"], texto=p["texto_con_variables"], ejemplos=ejemplos
                )
                id_meta = p["id_plantilla_meta"]
            else:
                creada = await meta.crear(
                    nombre=p["nombre"],
                    categoria=p["categoria"],
                    idioma=p["idioma"],
                    texto=p["texto_con_variables"],
                    ejemplos=ejemplos,
                )
                id_meta = creada.id
        except ErrorMeta as exc:
            raise _error_meta(exc) from exc
        await repo.pasar_a_revision(conn, plantilla_id, id_meta=id_meta, esperado=p["estado_meta"])
        log.info("plantilla %s enviada a revisión", plantilla_id)
        return await repo.obtener(conn, plantilla_id)  # type: ignore[return-value]


async def duplicar(motor, u: UsuarioActual, plantilla_id: int) -> dict[str, Any]:
    """NOT-12. Un BORRADOR nuevo con el mismo texto y ejemplos; el nombre se vuelve único."""
    usuario_id = requerir_usuario_id(u)
    try:
        async with transaccion(motor, u.empresa_id) as conn:
            p = await repo.obtener(conn, plantilla_id)
            if p is None:
                raise ErrorNoEncontrado()
            base = p["nombre"][: 512 - 12]
            candidatos = [f"{base}_copia"] + [f"{base}_copia_{n}" for n in range(2, 52)]
            r = await conn.execute(
                text(
                    "SELECT nombre FROM notificaciones.plantilla_mensaje "
                    "WHERE nombre = ANY(CAST(:c AS text[]))"
                ),
                {"c": candidatos},
            )
            usados = {f[0] for f in r.all()}
            libre = next((c for c in candidatos if c not in usados), None)
            if libre is None:
                raise ErrorConflicto(
                    "PLANTILLA_NOMBRE_DUPLICADO",
                    errores=[ErrorCampo("nombre", "PLANTILLA_NOMBRE_DUPLICADO", "Ya existe.")],
                )
            return await repo.crear(
                conn,
                empresa_id=u.empresa_id,
                usuario_id=usuario_id,
                nombre=libre,
                categoria=p["categoria"],
                idioma=p["idioma"],
                texto=p["texto_con_variables"],
                ejemplos=p["ejemplos_json"] or [],
            )
    except IntegrityError as exc:  # carrera con otra copia al mismo tiempo
        raise desde_integridad(exc) from exc


def _motivo_de_rechazo(valor: Any) -> str:
    if isinstance(valor, str) and valor.strip() and valor.strip().upper() != "NONE":
        return valor.strip()[:500]
    return "SIN_MOTIVO"


async def sincronizar(motor, meta, u: UsuarioActual, plantilla_id: int) -> dict[str, Any]:
    """NOT-13. Consulta el estado en Meta y, si ya resolvió la revisión, lo aplica (respaldo del
    evento ``wa.plantilla_estado``). Sin resolución, no cambia nada."""
    async with transaccion(motor, u.empresa_id) as conn:
        p = await repo.obtener(conn, plantilla_id)
    if p is None:
        raise ErrorNoEncontrado()
    if p["estado_meta"] == "BORRADOR":
        raise ErrorConflicto(
            "ESTADO_INVALIDO",
            "La plantilla todavía no se envió a revisión.",
            detalle={"estado_actual": "BORRADOR", "estado_esperado": "EN_REVISION"},
        )
    if p["estado_meta"] != "EN_REVISION":
        return p  # ya resuelta: nada que respaldar
    try:
        r = await meta.consultar(nombre=p["nombre"], idioma=p["idioma"])
    except ErrorMeta as exc:
        raise _error_meta(exc) from exc
    nuevo = ESTADO_DE_META.get(r.estado) if r else None
    if nuevo is None:
        return p
    async with transaccion(motor, u.empresa_id) as conn:
        await repo.resolver_revision(
            conn,
            plantilla_id,
            nuevo=nuevo,
            motivo=_motivo_de_rechazo(r.motivo_rechazo) if nuevo == "RECHAZADA" else None,
        )
        return await repo.obtener(conn, plantilla_id)  # type: ignore[return-value]


async def aplicar_evento(motor, evento: dict[str, Any]) -> int:
    """Consumidor de ``wa.plantilla_estado`` (``{nombre, estado_meta, motivo_rechazo}``, sin
    empresa). Devuelve cuántas plantillas cambiaron. Idempotente: por ``evento_id`` cuando viene y,
    siempre, por comparar y cambiar desde EN_REVISION."""
    nombre = evento.get("nombre")
    nuevo = ESTADO_DE_META.get(str(evento.get("estado_meta") or "").upper())
    if nuevo is None or not isinstance(nombre, str) or not nombre:
        # Un estado que no cierra la revisión (PAUSED, DISABLED, FLAGGED...) no cambia el estado
        # local: una plantilla ya APROBADA seguiría "aprobada" aunque Meta la pause o la
        # deshabilite y sus envíos fallarían en Meta (ver docs/meta-configuracion.md). Se deja
        # constancia en el log solo con el estado (sin nombre ni texto).
        estado = re.sub(r"[^A-Z_]", "", str(evento.get("estado_meta") or "").upper())[:30]
        log.warning("evento de plantilla sin efecto (estado de Meta %s)", estado or "desconocido")
        return 0
    motivo = _motivo_de_rechazo(evento.get("motivo_rechazo")) if nuevo == "RECHAZADA" else None

    async def efecto(conn) -> int:
        cambiadas = 0
        for plantilla_id, empresa_id in await repo.en_revision_por_nombre(conn, nombre):
            await conn.execute(
                text("SELECT set_config('app.empresa_id', :e, true)"), {"e": str(empresa_id)}
            )
            if await repo.resolver_revision(conn, plantilla_id, nuevo=nuevo, motivo=motivo):
                cambiadas += 1
                log.info("plantilla %s resuelta como %s", plantilla_id, nuevo)
        return cambiadas

    evento_id = evento.get("evento_id")
    if evento_id:
        _, n = await procesar_una_vez(motor, "notificaciones", evento_id, efecto)
        return n or 0
    async with transaccion(motor, None) as conn:
        return await efecto(conn)
