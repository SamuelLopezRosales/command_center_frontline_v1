"""Importar plantillas ya aprobadas en Meta (``GET /plantillas-mensaje/meta`` y
``POST /plantillas-mensaje/importar``; design.md §3.6, §7.5; CC-REQ-117).

Qué se importa
--------------
El modelo local maneja **un cuerpo de texto con variables posicionales** ``{{1}}..{{n}}``
consecutivas. Una plantilla de Meta es *compatible* solo si:

- su estado en Meta es ``APPROVED``;
- su nombre cumple ``^[a-z0-9_]+$`` y su categoría es UTILITY, MARKETING o AUTHENTICATION;
- está en el idioma con el que el sistema **envía** (``CC_PLANTILLA_IDIOMA_ENVIO``, ``es_MX``): el
  enviador y el chat de RH mandan siempre ese idioma y no el de la fila (hallazgo documentado);
- no trae ``HEADER`` (de ningún tipo), ``BUTTONS``, ``CAROUSEL`` ni otro componente;
- tiene un ``BODY`` de texto, sin variables con nombre (``parameter_format`` POSITIONAL o ausente)
  y con variables consecutivas desde 1.

Un ``FOOTER`` de texto se tolera: Meta lo agrega solo al enviar; se reporta como advertencia.

Cómo se importa
---------------
El servidor identifica cada plantilla por **nombre e idioma** y vuelve a consultar a Meta; los
datos de la fila (nombre, categoría, texto, idioma, ``id_plantilla_meta``, ejemplos) salen de Meta,
nunca de lo que mande el cliente. Cada elemento va en su propia transacción: no es "todo o nada".
Es idempotente (``YA_EXISTIA`` si ya hay una fila con el mismo ``id_plantilla_meta``) y tolera
concurrencia (``ON CONFLICT (empresa_id, nombre) DO NOTHING``).

Limitación conocida: la restricción única local es ``(empresa_id, nombre)``, y Meta permite el
mismo nombre en varios idiomas. Si el nombre ya existe localmente con otro id o idioma, el elemento
se **omite** (``NOMBRE_EN_USO``). No se cambió la restricción ni se hizo migración.

Los errores de Meta nunca llegan como 500 ni con el texto de Meta: se traducen con las categorías de
``sonda_meta`` a un 502 ``ERROR_PROVEEDOR_META`` con mensaje en español; sin credenciales es un 422
``META_NO_CONFIGURADA``. Nada registra texto de plantillas.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.bitacora import registrar
from cc_common.db import transaccion
from cc_common.errores import ErrorProveedor, ErrorValidacion

from cc_notificaciones import sonda_meta
from cc_notificaciones.meta import ErrorMeta, ListadoMeta, PlantillaListada
from cc_notificaciones.repos import plantillas as repo
from cc_notificaciones.servicios import plantillas as servicio_plantillas

log = logging.getLogger("cc.notificaciones.plantillas_meta")

ACCION_IMPORTADA = "PLANTILLA_MENSAJE_IMPORTADA"
ENTIDAD = "plantilla_mensaje"
CATEGORIAS = ("UTILITY", "MARKETING", "AUTHENTICATION")
MAX_IMPORTAR = 50
NOMBRE_VALIDO = re.compile(r"[a-z0-9_]{1,512}")
TOKEN = re.compile(r"\{\{([^{}]*)\}\}")
VARIABLE_NOMBRADA = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Códigos de resultado de un elemento importado.
IMPORTADA = "IMPORTADA"
YA_EXISTIA = "YA_EXISTIA"
OMITIDA = "OMITIDA"

ESTADOS_EN_ESPANOL = {
    "PENDING": "en revisión",
    "IN_APPEAL": "en apelación",
    "REJECTED": "rechazada",
    "PAUSED": "pausada",
    "DISABLED": "deshabilitada",
    "FLAGGED": "marcada por baja calidad",
    "PENDING_DELETION": "pendiente de eliminar",
    "DELETED": "eliminada",
    "LIMIT_EXCEEDED": "con el límite excedido",
}

MOTIVOS = {
    "TIENE_ENCABEZADO": "Tiene encabezado (imagen, video, documento o texto): solo se admiten "
    "plantillas con cuerpo de texto.",
    "TIENE_BOTONES": "Tiene botones: solo se admiten plantillas con cuerpo de texto.",
    "TIENE_CARRUSEL": "Es un carrusel: solo se admiten plantillas con cuerpo de texto.",
    "COMPONENTE_NO_SOPORTADO": "Tiene componentes que Command Center no maneja: solo se admiten "
    "plantillas con cuerpo de texto.",
    "VARIABLES_CON_NOMBRE": "Usa variables con nombre; solo se admiten variables numeradas "
    "({{1}}, {{2}}…).",
    "VARIABLES_NO_CONSECUTIVAS": "Las variables no son consecutivas desde {{1}}.",
    "VARIABLES_INVALIDAS": "El texto tiene variables o llaves con un formato no válido.",
    "DEMASIADAS_VARIABLES": "Tiene más variables de las que admite Command Center.",
    "SIN_CUERPO_TEXTO": "No tiene un cuerpo de texto.",
    "TEXTO_DEMASIADO_LARGO": "El texto del cuerpo es más largo de lo que admite Command Center.",
    "NOMBRE_INVALIDO": "El nombre no cumple el formato (solo minúsculas, números y guion bajo).",
    "CATEGORIA_NO_SOPORTADA": "La categoría no es Utilidad, Marketing ni Autenticación.",
    "FOOTER_NO_SOPORTADO": "El pie de página trae variables o no es texto.",
}

ADVERTENCIA_PIE = (
    "Tiene pie de página fijo: Meta lo agrega al mensaje al enviar, pero Command Center no lo "
    "muestra en la vista previa."
)


@dataclass(frozen=True)
class Evaluacion:
    texto: str
    num_variables: int
    compatible: bool
    codigo_incompatible: str | None = None
    motivo_incompatible: str | None = None
    advertencias: tuple[str, ...] = field(default_factory=tuple)
    ejemplos: tuple[str, ...] = field(default_factory=tuple)


def _no_compatible(
    texto: str, n: int, codigo: str, motivo: str | None = None, advertencias=()
) -> Evaluacion:
    return Evaluacion(
        texto,
        n,
        False,
        codigo,
        motivo or MOTIVOS[codigo],
        tuple(advertencias),
    )


def _ejemplos(cuerpo: dict[str, Any], n: int) -> tuple[str, ...]:
    """Los ejemplos del cuerpo (``example.body_text[0]``) si calzan con las variables."""
    ejemplo = cuerpo.get("example")
    filas = ejemplo.get("body_text") if isinstance(ejemplo, dict) else None
    fila = filas[0] if isinstance(filas, list) and filas and isinstance(filas[0], list) else None
    if not fila or len(fila) != n or not all(isinstance(e, str) for e in fila):
        return ()
    limpios = tuple(e.strip()[: servicio_plantillas.MAX_EJEMPLO] for e in fila)
    return limpios if all(limpios) and not any("\n" in e for e in limpios) else ()


def evaluar(t: PlantillaListada, *, idioma_envio: str) -> Evaluacion:
    """Decide si la plantilla de Meta se puede usar tal cual en Command Center."""
    cuerpos = [c for c in t.componentes if str(c.get("type", "")).upper() == "BODY"]
    texto_crudo = cuerpos[0].get("text") if cuerpos else None
    texto = texto_crudo if isinstance(texto_crudo, str) else ""
    tokens = [m.group(1).strip() for m in TOKEN.finditer(texto)]
    n = len(set(tokens))

    if t.estado != "APPROVED":
        estado = ESTADOS_EN_ESPANOL.get(t.estado, t.estado.lower() or "desconocido")
        return _no_compatible(
            texto,
            n,
            "ESTADO_NO_APROBADO",
            f"Está {estado} en Meta: solo se importan las plantillas aprobadas.",
        )
    if not NOMBRE_VALIDO.fullmatch(t.nombre):
        return _no_compatible(texto, n, "NOMBRE_INVALIDO")
    if t.categoria not in CATEGORIAS:
        return _no_compatible(texto, n, "CATEGORIA_NO_SOPORTADA")
    if t.idioma != idioma_envio:
        return _no_compatible(
            texto,
            n,
            "IDIOMA_NO_ENVIABLE",
            f"Está en el idioma {t.idioma}: el sistema envía las plantillas en {idioma_envio} y "
            "Meta rechazaría el envío.",
        )

    tipos = [str(c.get("type", "")).upper() for c in t.componentes]
    for tipo, codigo in (
        ("HEADER", "TIENE_ENCABEZADO"),
        ("BUTTONS", "TIENE_BOTONES"),
        ("CAROUSEL", "TIENE_CARRUSEL"),
    ):
        if tipo in tipos:
            return _no_compatible(texto, n, codigo)
    if any(tipo not in ("BODY", "FOOTER") for tipo in tipos):
        return _no_compatible(texto, n, "COMPONENTE_NO_SOPORTADO")
    if tipos.count("BODY") != 1 or not texto.strip():
        return _no_compatible(texto, n, "SIN_CUERPO_TEXTO")

    advertencias: list[str] = []
    for pie in (c for c in t.componentes if str(c.get("type", "")).upper() == "FOOTER"):
        if not isinstance(pie.get("text"), str) or "{{" in pie["text"]:
            return _no_compatible(texto, n, "FOOTER_NO_SOPORTADO")
        advertencias.append(ADVERTENCIA_PIE)

    if (t.formato_parametros or "POSITIONAL").upper() != "POSITIONAL" or any(
        VARIABLE_NOMBRADA.fullmatch(x) for x in tokens
    ):
        return _no_compatible(texto, n, "VARIABLES_CON_NOMBRE", advertencias=advertencias)
    if len(texto) > servicio_plantillas.MAX_TEXTO:
        return _no_compatible(texto, n, "TEXTO_DEMASIADO_LARGO", advertencias=advertencias)
    try:
        n = servicio_plantillas.cantidad_variables(texto)
    except ErrorValidacion as exc:
        codigo = exc.errores[0].codigo if exc.errores else "VARIABLES_INVALIDAS"
        if codigo not in ("VARIABLES_NO_CONSECUTIVAS", "DEMASIADAS_VARIABLES"):
            codigo = "VARIABLES_INVALIDAS"
        return _no_compatible(texto, n, codigo, advertencias=advertencias)
    return Evaluacion(
        texto, n, True, advertencias=tuple(advertencias), ejemplos=_ejemplos(cuerpos[0], n)
    )


# ------------------------------------------------------------------ errores de Meta


def _categoria_error(exc: ErrorMeta) -> str:
    causa = exc.__cause__
    if isinstance(causa, httpx.TimeoutException):
        return sonda_meta.TIEMPO
    if isinstance(causa, httpx.HTTPError):
        return sonda_meta.RED
    if exc.estado_http is None:
        return sonda_meta.OTRO
    cuerpo: dict[str, Any] = {}
    if exc.codigo is not None and exc.codigo.isdigit():
        cuerpo = {"error": {"code": int(exc.codigo)}}
    return sonda_meta.clasificar(exc.estado_http, cuerpo)


def traducir_error_meta(exc: ErrorMeta) -> Exception:
    """422 ``META_NO_CONFIGURADA`` sin credenciales; si no, 502 ``ERROR_PROVEEDOR_META`` con un
    mensaje fijo en español (nunca el texto de Meta ni el de la excepción)."""
    if exc.motivo == "META_SIN_CREDENCIALES":
        return ErrorValidacion(
            "META_NO_CONFIGURADA",
            "Faltan credenciales de Meta: guárdelas en Conexión con Meta antes de continuar.",
        )
    categoria = _categoria_error(exc)
    log.warning("falló la consulta de plantillas a Meta: %s (%s)", exc.motivo, categoria)
    if categoria == sonda_meta.NO_EXISTE:
        mensaje = sonda_meta.NO_EXISTE_WABA
    elif categoria == sonda_meta.OTRO:
        mensaje = "Meta devolvió una respuesta inesperada."
        if exc.estado_http:
            mensaje = f"Meta devolvió una respuesta inesperada (HTTP {exc.estado_http})."
    else:
        mensaje = sonda_meta.MENSAJES[categoria]
    return ErrorProveedor("ERROR_PROVEEDOR_META", mensaje)


async def _listar_meta(meta) -> ListadoMeta:
    try:
        return await meta.listar()
    except ErrorMeta as exc:
        raise traducir_error_meta(exc) from exc


# ------------------------------------------------------------------ listado


async def listar_de_meta(motor, meta, u: UsuarioActual, *, idioma_envio: str) -> dict[str, Any]:
    """Las plantillas de la cuenta de Meta con su compatibilidad y si ya están asociadas."""
    listado = await _listar_meta(meta)  # sin conexión a la base mientras se espera a Meta
    async with transaccion(motor, u.empresa_id) as conn:
        locales = await repo.identificadores(conn)
    ids_locales = {f["id_plantilla_meta"] for f in locales if f["id_plantilla_meta"]}
    nombres_locales = {f["nombre"] for f in locales}
    items = []
    for t in sorted(listado.items, key=lambda x: (x.nombre, x.idioma)):
        ev = evaluar(t, idioma_envio=idioma_envio)
        ya = t.id in ids_locales
        items.append(
            {
                "nombre": t.nombre,
                "idioma": t.idioma,
                "categoria": t.categoria,
                "estado_meta": t.estado,
                "id_plantilla_meta": t.id,
                "texto": ev.texto,
                "num_variables": ev.num_variables,
                "compatible": ev.compatible,
                "codigo_incompatible": ev.codigo_incompatible,
                "motivo_incompatible": ev.motivo_incompatible,
                "advertencias": list(ev.advertencias),
                "ya_importada": ya,
                "nombre_en_uso": (not ya) and t.nombre in nombres_locales,
            }
        )
    return {"items": items, "truncado": listado.truncado}


# ------------------------------------------------------------------ importación


def _resultado(
    nombre: str,
    idioma: str,
    resultado: str,
    motivo: str | None = None,
    *,
    codigo: str | None = None,
    plantilla_id: int | None = None,
) -> dict[str, Any]:
    return {
        "nombre": nombre,
        "idioma": idioma,
        "resultado": resultado,
        "motivo": motivo,
        "codigo": codigo,
        "plantilla_id": plantilla_id,
    }


async def _importar_una(
    motor,
    meta,
    u: UsuarioActual,
    usuario_id: int,
    t: PlantillaListada | None,
    nombre: str,
    idioma: str,
    *,
    idioma_envio: str,
) -> dict[str, Any]:
    if t is None:
        return _resultado(
            nombre,
            idioma,
            OMITIDA,
            "Meta no tiene una plantilla con ese nombre e idioma.",
            codigo="NO_ENCONTRADA_EN_META",
        )
    ev = evaluar(t, idioma_envio=idioma_envio)
    if not ev.compatible:
        return _resultado(
            nombre, idioma, OMITIDA, ev.motivo_incompatible, codigo=ev.codigo_incompatible
        )
    async with transaccion(motor, u.empresa_id) as conn:
        existente = await repo.buscar_por_id_meta(conn, t.id)
        if existente is not None:
            return _resultado(nombre, idioma, YA_EXISTIA, plantilla_id=existente)
        nuevo = await repo.importar_aprobada(
            conn,
            empresa_id=u.empresa_id,
            usuario_id=usuario_id,
            nombre=t.nombre,
            categoria=t.categoria,
            idioma=t.idioma,
            texto=ev.texto,
            ejemplos=list(ev.ejemplos),
            id_meta=t.id,
        )
        if nuevo is None:  # el nombre ya estaba (otra importación simultánea o una local)
            fila = await repo.buscar_por_nombre(conn, t.nombre)
            if fila is not None and fila["id_plantilla_meta"] == t.id:
                return _resultado(nombre, idioma, YA_EXISTIA, plantilla_id=fila["id"])
            return _resultado(
                nombre,
                idioma,
                OMITIDA,
                "Ya existe una plantilla local con ese nombre y otro identificador o idioma en "
                "Meta. Renómbrela o elimínela antes de importar.",
                codigo="NOMBRE_EN_USO",
            )
        await registrar(
            conn,
            empresa_id=u.empresa_id,
            usuario_id=usuario_id,
            accion=ACCION_IMPORTADA,
            entidad=ENTIDAD,
            entidad_id=nuevo,
            detalle={"plantilla_id": nuevo, "estado_nuevo": "APROBADA"},
        )
    log.info("plantilla %s importada desde Meta", nuevo)
    return _resultado(nombre, idioma, IMPORTADA, plantilla_id=nuevo)


async def importar(
    motor, meta, u: UsuarioActual, pedidas: list[tuple[str, str]], *, idioma_envio: str
) -> list[dict[str, Any]]:
    """Importa cada ``(nombre, idioma)``: una transacción por elemento y un resultado por elemento.
    Un fallo de Meta al consultar el catálogo detiene todo antes de escribir (502 o 422)."""
    usuario_id = requerir_usuario_id(u)
    listado = await _listar_meta(meta)
    indice = {(t.nombre, t.idioma): t for t in listado.items}
    resultados = []
    for nombre, idioma in pedidas:
        t = indice.get((nombre, idioma))
        if t is None and listado.truncado:  # el catálogo se recortó: se pregunta por esa
            try:
                t = await meta.obtener(nombre=nombre, idioma=idioma)
            except ErrorMeta as exc:
                error = traducir_error_meta(exc)
                resultados.append(
                    _resultado(nombre, idioma, OMITIDA, error.mensaje_publico, codigo="ERROR_META")
                )
                continue
        resultados.append(
            await _importar_una(
                motor, meta, u, usuario_id, t, nombre, idioma, idioma_envio=idioma_envio
            )
        )
    return resultados
