"""Esquema JSON del contenido de una plantilla (design.md §5.1; CC-REQ-060, 061, 062, 064).

El contenido es una estructura cerrada, no HTML: bloques (``logotipo`` y ``parrafo``), y dentro de
un párrafo nodos de texto, de variable y saltos de línea. Marcas permitidas: negrita, cursiva,
subrayado, tamaño (8 a 48 pt), color (``#RRGGBB``) y alineación. Toda clave que el esquema no
define se rechaza (``extra='forbid'``), y el texto no puede traer etiquetas HTML; el renderizador
escapa lo demás.

Aquí solo se valida la **estructura**: que las variables existan y estén activas lo revisa la
validación previa a la publicación (CON-09).

``serializar`` produce la forma canónica (claves ordenadas, sin espacios, sin valores nulos) que se
guarda en S3 y de la que sale el hash SHA-256: el mismo contenido siempre da el mismo hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Any, Literal

from cc_common.errores import ErrorCampo, ErrorValidacion
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    ValidationError,
    field_validator,
)

ESQUEMA_VERSION = 1
MAX_BLOQUES = 200
MAX_NODOS = 500
MAX_TEXTO = 5000
PATRON_VARIABLE = r"^[a-z][a-z0-9_]{0,40}(\.[a-z][a-z0-9_]{0,40})?$"
PATRON_COLOR = r"^#[0-9A-Fa-f]{6}$"
_HTML = re.compile(r"<\s*/?\s*[A-Za-z!?]")

Alineacion = Literal["izquierda", "centro", "derecha", "justificado"]
Color = Annotated[str, Field(pattern=PATRON_COLOR)]
Tamano = Annotated[int, Field(ge=8, le=48)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Margenes(_Base):
    sup: float = Field(default=2.5, ge=1.0, le=5.0)
    inf: float = Field(default=2.5, ge=1.0, le=5.0)
    izq: float = Field(default=2.5, ge=1.0, le=5.0)
    der: float = Field(default=2.5, ge=1.0, le=5.0)


class Pagina(_Base):
    tamano: Literal["CARTA", "A4"] = "CARTA"
    margenes_cm: Margenes = Field(default_factory=Margenes)


class _Marcas(_Base):
    negrita: bool | None = None
    cursiva: bool | None = None
    subrayado: bool | None = None
    tamano_pt: Tamano | None = None
    color: Color | None = None


class NodoTexto(_Marcas):
    texto: Annotated[str, Field(min_length=1, max_length=MAX_TEXTO)]

    @field_validator("texto")
    @classmethod
    def _sin_html(cls, v: str) -> str:
        if _HTML.search(v):
            raise ValueError("HTML_NO_PERMITIDO")
        return v


class NodoVariable(_Marcas):
    var: Annotated[str, Field(pattern=PATRON_VARIABLE)]


class NodoSalto(_Base):
    salto: Literal[True]


def _etiqueta_nodo(v: Any) -> str | None:
    if isinstance(v, dict):
        for clave in ("texto", "var", "salto"):
            if clave in v:
                return clave
        return None
    return {NodoTexto: "texto", NodoVariable: "var", NodoSalto: "salto"}.get(type(v))


Nodo = Annotated[
    Annotated[NodoTexto, Tag("texto")]
    | Annotated[NodoVariable, Tag("var")]
    | Annotated[NodoSalto, Tag("salto")],
    Discriminator(_etiqueta_nodo),
]


class BloqueLogotipo(_Base):
    tipo: Literal["logotipo"]
    alineacion: Alineacion = "izquierda"
    ancho_cm: float = Field(default=5.0, ge=1.0, le=15.0)


class BloqueParrafo(_Base):
    tipo: Literal["parrafo"]
    alineacion: Alineacion = "izquierda"
    contenido: Annotated[list[Nodo], Field(max_length=MAX_NODOS)] = Field(default_factory=list)


Bloque = Annotated[BloqueLogotipo | BloqueParrafo, Field(discriminator="tipo")]


class ContenidoPlantilla(_Base):
    esquema: Literal[1]
    pagina: Pagina = Field(default_factory=Pagina)
    bloques: Annotated[list[Bloque], Field(max_length=MAX_BLOQUES)] = Field(default_factory=list)


# ------------------------------------------------------------------ uso del contenido


def variables_usadas(contenido: ContenidoPlantilla) -> list[str]:
    """Nombres de variable del contenido, sin repetir y en orden de aparición."""
    vistas: dict[str, None] = {}
    for b in contenido.bloques:
        if isinstance(b, BloqueParrafo):
            for n in b.contenido:
                if isinstance(n, NodoVariable):
                    vistas.setdefault(n.var)
    return list(vistas)


def usa_logotipo(contenido: ContenidoPlantilla) -> bool:
    return any(isinstance(b, BloqueLogotipo) for b in contenido.bloques)


def a_diccionario(contenido: ContenidoPlantilla) -> dict[str, Any]:
    return contenido.model_dump(mode="json", exclude_none=True)


def serializar(contenido: ContenidoPlantilla) -> bytes:
    """Forma canónica del contenido (la que se guarda y se hashea)."""
    return json.dumps(
        a_diccionario(contenido), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def hash_de(cuerpo: bytes) -> str:
    return hashlib.sha256(cuerpo).hexdigest()


# ------------------------------------------------------------------ lectura y errores

_ETIQUETAS = frozenset({"texto", "var", "salto", "logotipo", "parrafo"})
_HTML_CLAVES = frozenset({"html", "style", "estilo", "script", "css", "onclick", "onerror"})


def _ruta(loc: tuple[Any, ...]) -> str:
    """Ruta legible, sin las etiquetas internas de las uniones (``bloques.2.parrafo``)."""
    partes: list[str] = []
    anterior_entero = False
    for p in loc:
        if isinstance(p, str) and p in _ETIQUETAS and anterior_entero:
            anterior_entero = False
            continue
        partes.append(str(p))
        anterior_entero = isinstance(p, int)
    return ".".join(partes) or "contenido"


def _error(e: dict[str, Any]) -> ErrorCampo:
    """Un error de Pydantic sin ``input`` ni ``ctx``: nunca repite el valor recibido."""
    loc = tuple(e.get("loc", ()))
    campo = _ruta(loc)
    ultimo = str(loc[-1]) if loc else ""
    tipo = str(e.get("type", ""))
    msg = str(e.get("msg", ""))
    if tipo == "json_invalid":
        return ErrorCampo("contenido", "ESTRUCTURA_INVALIDA", "El contenido no es JSON válido.")
    if "HTML_NO_PERMITIDO" in msg or ultimo in _HTML_CLAVES:
        return ErrorCampo(campo, "HTML_NO_PERMITIDO", "No se admite HTML en la plantilla.")
    if tipo == "string_pattern_mismatch" and ultimo == "color":
        return ErrorCampo(campo, "COLOR_INVALIDO", "El color debe ser #RRGGBB.")
    if tipo == "string_pattern_mismatch" and ultimo == "var":
        return ErrorCampo(campo, "VARIABLE_INVALIDA", "El nombre de la variable no es válido.")
    if tipo in ("greater_than_equal", "less_than_equal") and ultimo == "tamano_pt":
        return ErrorCampo(campo, "TAMANO_FUERA_DE_RANGO", "El tamaño debe estar entre 8 y 48 pt.")
    if tipo in ("greater_than_equal", "less_than_equal") and loc[-2:-1] == ("margenes_cm",):
        return ErrorCampo(campo, "MARGEN_FUERA_DE_RANGO", "El margen debe estar entre 1 y 5 cm.")
    if tipo in ("greater_than_equal", "less_than_equal"):
        return ErrorCampo(campo, "VALOR_FUERA_DE_RANGO", "El valor está fuera de rango.")
    if tipo == "extra_forbidden":
        return ErrorCampo(campo, "CAMPO_NO_PERMITIDO", "Campo no permitido.")
    if tipo == "missing":
        return ErrorCampo(campo, "REQUERIDO", "El campo es obligatorio.")
    if tipo == "union_tag_invalid":
        etiqueta = (e.get("ctx") or {}).get("tag")
        if etiqueta in _HTML_CLAVES:
            return ErrorCampo(campo, "HTML_NO_PERMITIDO", "No se admite HTML en la plantilla.")
        return ErrorCampo(campo, "TIPO_NO_PERMITIDO", "Tipo de bloque no permitido.")
    if tipo in ("union_tag_not_found", "model_attributes_type", "model_type", "dict_type"):
        return ErrorCampo(campo, "ESTRUCTURA_INVALIDA", "La estructura no es válida.")
    if tipo == "string_too_short":
        return ErrorCampo(campo, "DEMASIADO_CORTO", "El valor no puede estar vacío.")
    if tipo in ("string_too_long", "too_long"):
        return ErrorCampo(campo, "DEMASIADO_LARGO", "El valor es demasiado largo.")
    if tipo == "literal_error":
        return ErrorCampo(campo, "VALOR_NO_PERMITIDO", "Valor no permitido.")
    return ErrorCampo(campo, "FORMATO_INVALIDO", "Formato inválido.")


def leer(cuerpo: bytes | str | dict[str, Any]) -> ContenidoPlantilla:
    """Valida el contenido y lo devuelve; lanza ``ErrorValidacion`` (422) con una entrada por
    problema y sin repetir valores."""
    try:
        if isinstance(cuerpo, dict):
            return ContenidoPlantilla.model_validate(cuerpo)
        return ContenidoPlantilla.model_validate_json(cuerpo)
    except ValidationError as exc:
        errores: list[ErrorCampo] = []
        for e in exc.errors():
            err = _error(dict(e))
            if err not in errores:
                errores.append(err)
        raise ErrorValidacion(
            "CONTENIDO_INVALIDO", "El contenido de la plantilla no es válido.", errores=errores[:50]
        ) from None
