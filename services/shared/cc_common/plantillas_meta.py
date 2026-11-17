"""Variables de las plantillas de mensaje de Meta: formato posicional o con nombre.

Módulo compartido (servicio de notificaciones, servicio de WhatsApp, Lambdas ``despachador``,
``respaldo_correo`` y ``enviador``). Solo usa la biblioteca estándar: se puede empaquetar en las
Lambdas sin dependencias.

Una plantilla de Meta (``parameter_format``) usa **un** formato de variables en el cuerpo:

- ``POSICIONAL``: ``{{1}}``, ``{{2}}``... consecutivas desde 1 (una puede repetirse en el texto).
- ``NOMBRADO``: ``{{guest_name}}``... nombres en minúsculas, dígitos y guion bajo que empiezan con
  letra (``^[a-z][a-z0-9_]*$``). Un mismo nombre puede aparecer varias veces y cuenta una sola
  variable. Meta exige enviar **todos** los nombres y el orden no importa.

El formato **se infiere del texto** (no hay columna en la base de datos): si todos los marcadores
son números es posicional; si todos son nombres es nombrado; mezclarlos no es válido. Un texto sin
marcadores es posicional con cero variables.

``nombres`` va siempre en orden de **primera aparición** en el texto. En el formato posicional son
``["1", "2", ...]`` (cadenas), de modo que ``variables_json`` (cuyas claves son cadenas) se maneja
igual con los dos formatos.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

POSICIONAL = "POSICIONAL"
NOMBRADO = "NOMBRADO"

MAX_VARIABLES = 20
MAX_LONGITUD_NOMBRE = 50

TOKEN = re.compile(r"\{\{([^{}]*)\}\}")
_POSICION = re.compile(r"[1-9][0-9]{0,1}")
_NOMBRE = re.compile(r"[a-z][a-z0-9_]*")
_NUMERICO = re.compile(r"[0-9]+")
_FORMA_NOMBRE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ErrorVariables(ValueError):
    """El texto no tiene variables válidas. ``codigo`` es estable (se traduce a un 422 o a un motivo
    de incompatibilidad al importar); ``mensaje`` está en español y nunca incluye el texto."""

    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.mensaje = mensaje


@dataclass(frozen=True)
class Variables:
    formato: str  # POSICIONAL | NOMBRADO
    nombres: tuple[str, ...]  # en orden de primera aparición; posicional: "1", "2"...

    @property
    def cantidad(self) -> int:
        return len(self.nombres)

    @property
    def nombrado(self) -> bool:
        return self.formato == NOMBRADO


def _tokens(texto: str) -> list[str]:
    encontrados = [m.group(1) for m in TOKEN.finditer(texto)]
    resto = TOKEN.sub("", texto)
    if "{{" in resto or "}}" in resto:
        raise ErrorVariables("VARIABLE_INVALIDA", "Hay llaves sin cerrar.")
    return encontrados


def analizar(texto: str, *, maximo: int = MAX_VARIABLES) -> Variables:
    """Formato y variables del texto. Lanza ``ErrorVariables`` con ``codigo``:

    ``VARIABLE_INVALIDA`` (llaves sin cerrar o un marcador que no es número ni nombre válido),
    ``VARIABLES_MEZCLADAS`` (posicionales y con nombre juntas), ``VARIABLES_NO_CONSECUTIVAS``
    (posicionales que no van de 1 a n), ``NOMBRE_VARIABLE_INVALIDO`` (un nombre fuera de
    ``^[a-z][a-z0-9_]*$`` o demasiado largo) y ``DEMASIADAS_VARIABLES``."""
    tokens = _tokens(texto)
    if not tokens:
        return Variables(POSICIONAL, ())
    numericos = [t for t in tokens if _NUMERICO.fullmatch(t)]
    if numericos and len(numericos) != len(tokens):
        raise ErrorVariables(
            "VARIABLES_MEZCLADAS",
            "No se pueden mezclar variables numeradas ({{1}}) con variables con nombre.",
        )
    if numericos:
        if not all(_POSICION.fullmatch(t) for t in numericos):
            raise ErrorVariables("VARIABLE_INVALIDA", "Use variables como {{1}}, {{2}}.")
        distintas = sorted({int(t) for t in numericos})
        if distintas != list(range(1, len(distintas) + 1)):
            raise ErrorVariables(
                "VARIABLES_NO_CONSECUTIVAS",
                "Las variables deben ser consecutivas desde {{1}}.",
            )
        formato, nombres = POSICIONAL, tuple(str(i) for i in distintas)
    else:
        for t in tokens:
            if not _FORMA_NOMBRE.fullmatch(t):
                raise ErrorVariables("VARIABLE_INVALIDA", "Use variables como {{1}} o {{nombre}}.")
            if not _NOMBRE.fullmatch(t):
                raise ErrorVariables(
                    "NOMBRE_VARIABLE_INVALIDO",
                    "El nombre de una variable lleva minúsculas, números y guion bajo, y empieza "
                    "con una letra.",
                )
            if len(t) > MAX_LONGITUD_NOMBRE:
                raise ErrorVariables(
                    "NOMBRE_VARIABLE_INVALIDO",
                    f"El nombre de una variable admite hasta {MAX_LONGITUD_NOMBRE} caracteres.",
                )
        formato, nombres = NOMBRADO, tuple(dict.fromkeys(tokens))
    if len(nombres) > maximo:
        raise ErrorVariables("DEMASIADAS_VARIABLES", f"El máximo es de {maximo} variables.")
    return Variables(formato, nombres)


def nombres_para_envio(texto: str) -> list[str] | None:
    """``parameter_name`` de cada variable (en orden de aparición) si la plantilla es nombrada;
    ``None`` si es posicional o si el texto no se puede interpretar. Nunca lanza."""
    try:
        v = analizar(texto, maximo=10_000)
    except ErrorVariables:
        return None
    return list(v.nombres) if v.nombrado else None


def sustituir(texto: str, valores: Mapping[str, str]) -> str:
    """Reemplaza cada marcador por ``valores[nombre]`` (en posicional, la clave es ``"1"``...). Un
    marcador sin valor se deja como está. No interpreta los valores como marcadores."""

    def uno(m: re.Match[str]) -> str:
        return valores.get(m.group(1), m.group(0))

    return TOKEN.sub(uno, texto)


def valores_por_nombre(
    texto: str, variables: list[str] | tuple[str, ...], *, nombres: list[str] | None = None
) -> dict[str, str]:
    """Empareja la lista de valores con las variables del texto, en orden de aparición (posicional:
    ``{"1": v[0], ...}``). ``nombres`` (si viene) manda sobre lo que se deduzca del texto."""
    if nombres is None:
        nombres = list(analizar(texto, maximo=10_000).nombres)
    return {n: variables[i] for i, n in enumerate(nombres) if i < len(variables)}
