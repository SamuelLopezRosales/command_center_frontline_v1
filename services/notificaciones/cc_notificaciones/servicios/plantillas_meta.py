"""Importar plantillas ya aprobadas en Meta (``GET /plantillas-mensaje/meta`` y
``POST /plantillas-mensaje/importar``; design.md §3.6, §7.5; CC-REQ-117).

Qué se importa
--------------
El modelo local maneja **un cuerpo de texto** con variables posicionales ``{{1}}..{{n}}``
consecutivas **o** con nombre (``{{guest_name}}``, ``parameter_format`` ``NAMED`` de Meta); el
formato se infiere del texto (``cc_common.plantillas_meta``). Una plantilla de Meta es *compatible*
solo si:

- su estado en Meta es ``APPROVED``;
- su nombre cumple ``^[a-z0-9_]+$``, su categoría es UTILITY, MARKETING o AUTHENTICATION y su
  idioma tiene el formato de Meta (``es_MX``, ``en``, ``en_US``...). **Cualquier idioma sirve**: la
  fila guarda el idioma y el enviador y el chat de RH mandan el de la plantilla;
- **encabezado**: ninguno, o de texto **sin variables** (Meta lo agrega solo al enviar). Los de
  imagen, video, documento y ubicación, y los de texto con variable, exigirían mandar datos en cada
  mensaje y no se soportan todavía;
- **botones**: ninguno, o todos **estáticos** (respuesta rápida, número de teléfono, URL sin
  variable). No se soportan los de URL con variable, copiar código, OTP, Flow, catálogo ni
  multiproducto (llevan parámetros al enviar);
- sin ``CAROUSEL`` ni otro componente que no sea ``HEADER``, ``BODY``, ``FOOTER`` o ``BUTTONS``;
- tiene un ``BODY`` de texto cuyas variables son todas numeradas y consecutivas desde 1, o todas con
  nombre (minúsculas, dígitos y guion bajo, que empieza con letra). Mezclarlas, o que el
  ``parameter_format`` declarado no coincida con el texto, la vuelve incompatible.

Se evalúan **todas** las reglas: ``motivos`` trae cada problema (el primero es el de
``codigo_incompatible``). Un ``FOOTER`` de texto fijo se tolera, igual que el encabezado de texto
fijo y los botones estáticos: Meta los agrega al enviar y se reportan como advertencia.

Cómo se importa
---------------
El servidor identifica cada plantilla por **nombre e idioma** y vuelve a consultar a Meta; los
datos de la fila (nombre, categoría, texto, idioma, ``id_plantilla_meta``, ejemplos) salen de Meta,
nunca de lo que mande el cliente. Cada elemento va en su propia transacción: no es "todo o nada".
Es idempotente (``YA_EXISTIA`` si ya hay una fila con el mismo ``id_plantilla_meta``) y tolera
concurrencia (``ON CONFLICT (empresa_id, nombre) DO NOTHING``).

Limitación conocida: la restricción única local es ``(empresa_id, nombre)``, y Meta permite el
mismo nombre en varios idiomas. Se importa el primero que se pida; si el nombre ya existe
localmente con otro id o idioma, el elemento se **omite** (``NOMBRE_EN_USO``): no se puede enviar el
mismo nombre en otro idioma. No se cambió la restricción ni se hizo migración.

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
from cc_common import plantillas_meta as pm
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
IDIOMA_VALIDO = re.compile(r"[a-z]{2,3}(_[A-Z]{2})?")

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

_NO_SOPORTADO = "Command Center aún no lo soporta."
MOTIVOS = {
    "IDIOMA_INVALIDO": "El código de idioma no tiene el formato de Meta (por ejemplo es_MX o en).",
    "ENCABEZADO_IMAGEN": "Encabezado de imagen: requiere adjuntar la imagen al enviar; aún no "
    "soportado.",
    "ENCABEZADO_VIDEO": "Encabezado de video: requiere adjuntar el video al enviar; aún no "
    "soportado.",
    "ENCABEZADO_DOCUMENTO": "Encabezado de documento: requiere adjuntar el archivo al enviar; aún "
    "no soportado.",
    "ENCABEZADO_UBICACION": "Encabezado de ubicación: requiere enviar la ubicación en cada "
    "mensaje; aún no soportado.",
    "ENCABEZADO_TEXTO_CON_VARIABLE": "El encabezado de texto lleva una variable: solo se admiten "
    "encabezados de texto fijo.",
    "ENCABEZADO_NO_SOPORTADO": "Tiene un encabezado de un tipo que Command Center no maneja.",
    "BOTON_URL_CON_VARIABLE": "Tiene un botón de URL con variable: solo se admiten botones "
    "estáticos.",
    "BOTON_COPIAR_CODIGO": "Tiene un botón de copiar código: requiere enviar el código en cada "
    "mensaje; aún no soportado.",
    "BOTON_OTP": "Tiene un botón de código de un solo uso (OTP): " + _NO_SOPORTADO,
    "BOTON_FLOW": "Tiene un botón de Flow: " + _NO_SOPORTADO,
    "BOTON_CATALOGO": "Tiene un botón de catálogo: " + _NO_SOPORTADO,
    "BOTON_MPM": "Tiene un botón de varios productos (MPM): " + _NO_SOPORTADO,
    "BOTON_SPM": "Tiene un botón de producto (SPM): " + _NO_SOPORTADO,
    "BOTON_NO_SOPORTADO": "Tiene un botón de un tipo que Command Center no maneja.",
    "TIENE_CARRUSEL": "Es un carrusel: solo se admiten plantillas con cuerpo de texto.",
    "COMPONENTE_NO_SOPORTADO": "Tiene componentes que Command Center no maneja: solo se admiten "
    "encabezado de texto, cuerpo de texto, pie y botones estáticos.",
    "VARIABLES_MEZCLADAS": "Mezcla variables numeradas ({{1}}) con variables con nombre.",
    "NOMBRE_VARIABLE_INVALIDO": "El nombre de una variable no cumple el formato (solo minúsculas, "
    "números y guion bajo, y empieza con una letra).",
    "VARIABLES_FORMATO_INCONSISTENTE": "El formato de variables declarado en Meta no coincide con "
    "el del texto.",
    "VARIABLES_NO_CONSECUTIVAS": "Las variables no son consecutivas desde {{1}}.",
    "VARIABLES_INVALIDAS": "El texto tiene variables o llaves con un formato no válido.",
    "DEMASIADAS_VARIABLES": "Tiene más variables de las que admite Command Center.",
    "SIN_CUERPO_TEXTO": "No tiene un cuerpo de texto.",
    "TEXTO_DEMASIADO_LARGO": "El texto del cuerpo es más largo de lo que admite Command Center.",
    "NOMBRE_INVALIDO": "El nombre no cumple el formato (solo minúsculas, números y guion bajo).",
    "CATEGORIA_NO_SOPORTADA": "La categoría no es Utilidad, Marketing ni Autenticación.",
    "FOOTER_NO_SOPORTADO": "El pie de página trae variables o no es texto.",
}

# Botón de Meta -> código de incompatibilidad (los que no están aquí y no son estáticos).
_BOTONES_ESTATICOS = ("QUICK_REPLY", "PHONE_NUMBER", "URL")
_BOTONES_NO_SOPORTADOS = {
    "COPY_CODE": "BOTON_COPIAR_CODIGO",
    "OTP": "BOTON_OTP",
    "FLOW": "BOTON_FLOW",
    "CATALOG": "BOTON_CATALOGO",
    "MPM": "BOTON_MPM",
    "SPM": "BOTON_SPM",
}
_ENCABEZADOS_MEDIA = {
    "IMAGE": "ENCABEZADO_IMAGEN",
    "VIDEO": "ENCABEZADO_VIDEO",
    "DOCUMENT": "ENCABEZADO_DOCUMENTO",
    "LOCATION": "ENCABEZADO_UBICACION",
}

ADVERTENCIA_PIE = (
    "Tiene pie de página fijo: Meta lo agrega al mensaje al enviar, pero Command Center no lo "
    "muestra en la vista previa."
)
ADVERTENCIA_ENCABEZADO = (
    "Tiene un encabezado de texto fijo: Meta lo agrega al mensaje al enviar, pero Command Center "
    "no lo muestra en la vista previa."
)
ADVERTENCIA_BOTONES = (
    "Tiene botones fijos: Meta los agrega al mensaje al enviar, pero Command Center no los "
    "muestra en la vista previa."
)
ADVERTENCIA_RESPUESTA_RAPIDA = (
    "Tiene botones de respuesta rápida: las respuestas llegan al webhook que tenga configurado la "
    "cuenta en Meta (puede ser el de otro proyecto), no a Command Center, mientras no se "
    "registre el de Command Center."
)


@dataclass(frozen=True)
class Evaluacion:
    texto: str
    num_variables: int
    compatible: bool
    motivos: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (código, motivo)
    advertencias: tuple[str, ...] = field(default_factory=tuple)
    ejemplos: tuple[str, ...] = field(default_factory=tuple)
    formato: str = pm.POSICIONAL  # POSICIONAL | NOMBRADO
    variables: tuple[str, ...] = field(default_factory=tuple)  # "1", "2"... o los nombres
    botones: tuple[dict[str, str], ...] = field(default_factory=tuple)  # {tipo, texto}
    encabezado: dict[str, str | None] | None = None  # {tipo, formato, texto}

    @property
    def codigo_incompatible(self) -> str | None:
        return self.motivos[0][0] if self.motivos else None

    @property
    def motivo_incompatible(self) -> str | None:
        return self.motivos[0][1] if self.motivos else None


def _limpios(fila: list[str]) -> tuple[str, ...]:
    limpios = tuple(e.strip()[: servicio_plantillas.MAX_EJEMPLO] for e in fila)
    return limpios if all(limpios) and not any("\n" in e for e in limpios) else ()


def _ejemplos(cuerpo: dict[str, Any], v: pm.Variables) -> tuple[str, ...]:
    """Los ejemplos del cuerpo, en el orden de las variables, si calzan con ellas: posicional,
    ``example.body_text[0]``; con nombre, ``example.body_text_named_params`` (``param_name`` y
    ``example``, en cualquier orden)."""
    ejemplo = cuerpo.get("example")
    if not isinstance(ejemplo, dict):
        return ()
    if v.nombrado:
        crudos = ejemplo.get("body_text_named_params")
        if not isinstance(crudos, list):
            return ()
        por_nombre = {
            e.get("param_name"): e.get("example")
            for e in crudos
            if isinstance(e, dict) and isinstance(e.get("param_name"), str)
        }
        fila = [por_nombre.get(n) for n in v.nombres]
        if len(por_nombre) != v.cantidad or not all(isinstance(e, str) for e in fila):
            return ()
        return _limpios(fila)  # type: ignore[arg-type]
    filas = ejemplo.get("body_text")
    fila = filas[0] if isinstance(filas, list) and filas and isinstance(filas[0], list) else None
    if not fila or len(fila) != v.cantidad or not all(isinstance(e, str) for e in fila):
        return ()
    return _limpios(fila)


def _tipo_componente(c: dict[str, Any]) -> str:
    return str(c.get("type", "")).upper()


def _evaluar_encabezado(
    componentes: list[dict[str, Any]], motivos: list[tuple[str, str]], advertencias: list[str]
) -> dict[str, str | None] | None:
    """El encabezado como se informa a la pantalla y, si no se soporta, el motivo exacto."""
    encabezados = [c for c in componentes if _tipo_componente(c) == "HEADER"]
    if not encabezados:
        return None
    primero: dict[str, str | None] | None = None
    for h in encabezados:
        formato = str(h.get("format") or "").upper()
        texto = h.get("text") if isinstance(h.get("text"), str) else None
        if formato == "TEXT":
            info: dict[str, str | None] = {"tipo": "TEXTO", "formato": "TEXT", "texto": texto}
            if texto is None or "{{" in texto:
                motivos.append(
                    ("ENCABEZADO_TEXTO_CON_VARIABLE", MOTIVOS["ENCABEZADO_TEXTO_CON_VARIABLE"])
                )
            elif ADVERTENCIA_ENCABEZADO not in advertencias:
                advertencias.append(ADVERTENCIA_ENCABEZADO)
        elif formato in _ENCABEZADOS_MEDIA:
            codigo = _ENCABEZADOS_MEDIA[formato]
            tipo = "UBICACION" if formato == "LOCATION" else "MEDIA"
            info = {"tipo": tipo, "formato": formato, "texto": None}
            motivos.append((codigo, MOTIVOS[codigo]))
        else:
            info = {"tipo": "OTRO", "formato": formato or None, "texto": None}
            motivos.append(("ENCABEZADO_NO_SOPORTADO", MOTIVOS["ENCABEZADO_NO_SOPORTADO"]))
        primero = primero or info
    return primero


def _evaluar_botones(
    componentes: list[dict[str, Any]], motivos: list[tuple[str, str]], advertencias: list[str]
) -> tuple[dict[str, str], ...]:
    botones: list[dict[str, str]] = []
    for c in componentes:
        if _tipo_componente(c) != "BUTTONS":
            continue
        crudos = c.get("buttons")
        for b in crudos if isinstance(crudos, list) else []:
            if not isinstance(b, dict):
                continue
            tipo = str(b.get("type") or "").upper()
            texto = b.get("text") if isinstance(b.get("text"), str) else ""
            botones.append({"tipo": tipo or "DESCONOCIDO", "texto": texto})
            if tipo == "URL":
                url = b.get("url")
                if not isinstance(url, str) or "{{" in url:
                    motivos.append(("BOTON_URL_CON_VARIABLE", MOTIVOS["BOTON_URL_CON_VARIABLE"]))
            elif tipo in _BOTONES_NO_SOPORTADOS:
                codigo = _BOTONES_NO_SOPORTADOS[tipo]
                motivos.append((codigo, MOTIVOS[codigo]))
            elif tipo not in _BOTONES_ESTATICOS:
                motivos.append(("BOTON_NO_SOPORTADO", MOTIVOS["BOTON_NO_SOPORTADO"]))
    if botones:
        if ADVERTENCIA_BOTONES not in advertencias:
            advertencias.append(ADVERTENCIA_BOTONES)
        if any(b["tipo"] == "QUICK_REPLY" for b in botones):
            advertencias.append(ADVERTENCIA_RESPUESTA_RAPIDA)
    return tuple(botones)


def evaluar(t: PlantillaListada) -> Evaluacion:
    """Decide si la plantilla de Meta se puede usar tal cual en Command Center, con **todos** los
    motivos de incompatibilidad (en el orden de las reglas) y, también en una incompatible, el
    formato y las variables del texto, los botones y el encabezado cuando se pueden leer."""
    componentes = [c for c in t.componentes if isinstance(c, dict)]
    tipos = [_tipo_componente(c) for c in componentes]
    cuerpos = [c for c in componentes if _tipo_componente(c) == "BODY"]
    texto_crudo = cuerpos[0].get("text") if cuerpos else None
    texto = texto_crudo if isinstance(texto_crudo, str) else ""
    n = len({m.group(1).strip() for m in pm.TOKEN.finditer(texto)})
    motivos: list[tuple[str, str]] = []
    advertencias: list[str] = []

    def malo(codigo: str, motivo: str | None = None) -> None:
        motivos.append((codigo, motivo or MOTIVOS[codigo]))

    if t.estado != "APPROVED":
        estado = ESTADOS_EN_ESPANOL.get(t.estado, t.estado.lower() or "desconocido")
        malo(
            "ESTADO_NO_APROBADO",
            f"Está {estado} en Meta: solo se importan las plantillas aprobadas.",
        )
    if not NOMBRE_VALIDO.fullmatch(t.nombre):
        malo("NOMBRE_INVALIDO")
    if t.categoria not in CATEGORIAS:
        malo("CATEGORIA_NO_SOPORTADA")
    if not IDIOMA_VALIDO.fullmatch(t.idioma):
        malo("IDIOMA_INVALIDO")

    encabezado = _evaluar_encabezado(componentes, motivos, advertencias)
    botones = _evaluar_botones(componentes, motivos, advertencias)
    if "CAROUSEL" in tipos:
        malo("TIENE_CARRUSEL")
    if any(tipo not in ("HEADER", "BODY", "FOOTER", "BUTTONS", "CAROUSEL") for tipo in tipos):
        malo("COMPONENTE_NO_SOPORTADO")
    if tipos.count("BODY") != 1 or not texto.strip():
        malo("SIN_CUERPO_TEXTO")
    for pie in (c for c in componentes if _tipo_componente(c) == "FOOTER"):
        if not isinstance(pie.get("text"), str) or "{{" in pie["text"]:
            malo("FOOTER_NO_SOPORTADO")
        elif ADVERTENCIA_PIE not in advertencias:
            advertencias.append(ADVERTENCIA_PIE)

    variables: pm.Variables | None = None
    if texto.strip():
        if len(texto) > servicio_plantillas.MAX_TEXTO:
            malo("TEXTO_DEMASIADO_LARGO")
        try:
            variables = pm.analizar(texto, maximo=servicio_plantillas.MAX_VARIABLES)
        except pm.ErrorVariables as exc:
            codigo = exc.codigo
            if codigo not in (
                "VARIABLES_NO_CONSECUTIVAS",
                "DEMASIADAS_VARIABLES",
                "VARIABLES_MEZCLADAS",
                "NOMBRE_VARIABLE_INVALIDO",
            ):
                codigo = "VARIABLES_INVALIDAS"
            malo(codigo)
        if variables is not None:
            declarado = (t.formato_parametros or "").upper()
            if (
                variables.cantidad
                and declarado in ("POSITIONAL", "NAMED")
                and (declarado == "NAMED") != variables.nombrado
            ):
                malo("VARIABLES_FORMATO_INCONSISTENTE")

    por_codigo: dict[str, str] = {}
    for codigo, motivo in motivos:
        por_codigo.setdefault(codigo, motivo)
    unicos = tuple(por_codigo.items())
    if variables is None:  # el texto no se pudo interpretar: no se informan variables
        try:
            variables = pm.analizar(texto, maximo=10_000) if texto.strip() else None
        except pm.ErrorVariables:
            variables = None
    ejemplos = _ejemplos(cuerpos[0], variables) if variables and cuerpos and not unicos else ()
    return Evaluacion(
        texto=texto,
        num_variables=variables.cantidad if variables else n,
        compatible=not unicos,
        motivos=unicos,
        advertencias=tuple(advertencias),
        ejemplos=ejemplos,
        formato=variables.formato if variables else pm.POSICIONAL,
        variables=variables.nombres if variables else (),
        botones=botones,
        encabezado=encabezado,
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


async def listar_de_meta(motor, meta, u: UsuarioActual) -> dict[str, Any]:
    """Las plantillas de la cuenta de Meta con su compatibilidad y si ya están asociadas."""
    listado = await _listar_meta(meta)  # sin conexión a la base mientras se espera a Meta
    async with transaccion(motor, u.empresa_id) as conn:
        locales = await repo.identificadores(conn)
    ids_locales = {f["id_plantilla_meta"] for f in locales if f["id_plantilla_meta"]}
    nombres_locales = {f["nombre"] for f in locales}
    items = []
    for t in sorted(listado.items, key=lambda x: (x.nombre, x.idioma)):
        ev = evaluar(t)
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
                "formato_variables": ev.formato,
                "variables": list(ev.variables),
                "compatible": ev.compatible,
                "codigo_incompatible": ev.codigo_incompatible,
                "motivo_incompatible": ev.motivo_incompatible,
                "motivos_incompatibles": [{"codigo": c, "motivo": m} for c, m in ev.motivos],
                "botones": list(ev.botones),
                "encabezado": ev.encabezado,
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
) -> dict[str, Any]:
    if t is None:
        return _resultado(
            nombre,
            idioma,
            OMITIDA,
            "Meta no tiene una plantilla con ese nombre e idioma.",
            codigo="NO_ENCONTRADA_EN_META",
        )
    ev = evaluar(t)
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
    motor, meta, u: UsuarioActual, pedidas: list[tuple[str, str]]
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
        resultados.append(await _importar_una(motor, meta, u, usuario_id, t, nombre, idioma))
    return resultados
