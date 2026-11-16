"""Formato y validación de los criterios de audiencia (design.md §6.1; CC-REQ-100, 101).

Módulo puro y compartido: lo usan `notificaciones` (valida al guardar y al revisar, contra
INT-CAM-01) y `colaboradores` (valida otra vez y compila a SQL, INT-COL-06). Así la lista cerrada
de campos y operadores vive en un solo lugar. No toca la base de datos ni el SQL.

Formato (árbol de un nivel de grupos, máximo 20 criterios en total)::

    {"op": "Y", "items": [
      {"campo": "planta_id", "operador": "es", "valor": 3},
      {"op": "O", "items": [
        {"campo": "CAMP-0002", "operador": "es", "valor": "VENTAS"},
        {"campo": "antiguedad_anios", "operador": ">=", "valor": 5}]}]}

Decisiones donde el diseño no es explícito (se eligió lo más conservador):
- La raíz es siempre un grupo; un grupo contiene criterios y, solo la raíz, otros grupos
  (profundidad máxima 2). Un grupo sin elementos es inválido y la audiencia exige al menos un
  criterio (una audiencia vacía seleccionaría a toda la empresa por descuido).
- Campos fijos: ``colaborador_id``, ``organizacion_id`` y ``planta_id`` (enteros; ``es``,
  ``no_es``, ``en``; ``colaborador_id`` es el criterio estable del modo INDIVIDUAL),
  ``tipo_empleado`` y ``estatus`` (valores cerrados; ``es``, ``no_es``, ``en``) y
  ``antiguedad_anios`` (años completos enteros de 0 a 80; operadores de NUMERO).
- LISTA: el valor es el ``valor`` de una opción **activa** del campo (no su id); se resuelve a id.
- ``no_es`` en LISTA y TEXTO incluye a quien no tiene valor (lo aplica el compilador).
- SI_NO acepta un booleano JSON. NUMERO acepta números JSON (no cadenas ni booleanos). FECHA
  acepta ``AAAA-MM-DD``. TEXTO compara sin distinguir mayúsculas, de hasta 200 caracteres.
- Los mensajes de error nunca incluyen el valor recibido.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from cc_common.errores import ErrorCampo, ErrorValidacion

MAX_CRITERIOS = 20
MAX_VALORES_EN = 50
MAX_TEXTO = 200
ANTIGUEDAD_MAX = 80
NUMERO_MAX = Decimal("99999999999999")  # cabe en numeric(18, 4)

OPERADORES_POR_TIPO: dict[str, tuple[str, ...]] = {
    "LISTA": ("es", "no_es", "en"),
    "TEXTO": ("es", "no_es", "contiene"),
    "NUMERO": ("=", "<", "<=", ">", ">=", "entre"),
    "FECHA": ("antes", "despues", "entre"),
    "SI_NO": ("es",),
}
OPERADORES_CONJUNTO = ("es", "no_es", "en")

# Campo fijo -> tipo de criterio. ``ID`` y ``ENUM`` usan los operadores de conjunto.
FIJOS: dict[str, str] = {
    "colaborador_id": "ID",  # modo INDIVIDUAL de una notificación (T-216)
    "organizacion_id": "ID",
    "planta_id": "ID",
    "tipo_empleado": "ENUM",
    "estatus": "ENUM",
    "antiguedad_anios": "ANTIGUEDAD",
}
VALORES_ENUM: dict[str, tuple[str, ...]] = {
    "tipo_empleado": ("ADMINISTRATIVO", "OPERATIVO"),
    "estatus": ("ACTIVO", "BAJA"),
}
COMBINADORES = ("Y", "O")


@dataclass(frozen=True)
class Hoja:
    """Criterio validado. ``campo`` es el campo fijo o el código interno; ``campo_id`` solo para
    campos dinámicos. ``valor`` ya está normalizado: ``int``, ``str``, ``Decimal``, ``date``,
    ``bool``, lista de ``int`` o ``str`` (operador ``en``) o tupla de dos valores (``entre``);
    en LISTA son ids de opción."""

    campo: str
    tipo: str  # ID, ENUM, ANTIGUEDAD, TEXTO, NUMERO, FECHA, LISTA, SI_NO
    operador: str
    valor: Any
    campo_id: int | None = None


@dataclass(frozen=True)
class Grupo:
    op: str
    items: tuple[Hoja | Grupo, ...]


class _Errores:
    def __init__(self) -> None:
        self.lista: list[ErrorCampo] = []

    def agregar(self, ruta: str, codigo: str, mensaje: str) -> None:
        self.lista.append(ErrorCampo(ruta, codigo, mensaje))


def contar_hojas(nodo: Hoja | Grupo) -> int:
    if isinstance(nodo, Hoja):
        return 1
    return sum(contar_hojas(i) for i in nodo.items)


def validar(criterios: Any, definiciones: list[Any], *, ruta: str = "criterios") -> Grupo:
    """Valida el árbol contra las definiciones de campos (INT-CAM-01) y lo normaliza.

    Solo los campos activos y no sensibles son utilizables. Lanza ``ErrorValidacion`` con un
    ``ErrorCampo`` por problema encontrado (``criterios.items.0.operador``...).
    """
    por_codigo = {d.codigo_interno: d for d in definiciones if d.activo and not d.es_sensible}
    sensibles = {d.codigo_interno for d in definiciones if d.activo and d.es_sensible}
    errores = _Errores()
    total = [0]
    raiz = _grupo(criterios, ruta, 1, por_codigo, sensibles, errores, total)
    if total[0] == 0 and not errores.lista:
        errores.agregar(ruta, "SIN_CRITERIOS", "Agregue al menos un criterio.")
    if total[0] > MAX_CRITERIOS:
        errores.agregar(ruta, "DEMASIADOS_CRITERIOS", f"El máximo es de {MAX_CRITERIOS} criterios.")
    if errores.lista or raiz is None:
        raise ErrorValidacion(errores=errores.lista)
    return raiz


def _grupo(
    nodo: Any,
    ruta: str,
    nivel: int,
    por_codigo: dict[str, Any],
    sensibles: set[str],
    errores: _Errores,
    total: list[int],
) -> Grupo | None:
    if not isinstance(nodo, dict) or set(nodo) != {"op", "items"}:
        errores.agregar(ruta, "ESTRUCTURA_INVALIDA", "Se esperaba un grupo con op e items.")
        return None
    if nodo["op"] not in COMBINADORES:
        errores.agregar(f"{ruta}.op", "COMBINADOR_INVALIDO", "El combinador debe ser Y u O.")
    items = nodo["items"]
    if not isinstance(items, list) or not items:
        errores.agregar(f"{ruta}.items", "ESTRUCTURA_INVALIDA", "El grupo no puede estar vacío.")
        return None
    if len(items) > MAX_CRITERIOS * 2:  # corta antes de recorrer una carga abusiva
        errores.agregar(f"{ruta}.items", "DEMASIADOS_CRITERIOS", "Demasiados criterios.")
        return None
    hijos: list[Hoja | Grupo] = []
    for i, item in enumerate(items):
        r = f"{ruta}.items.{i}"
        if isinstance(item, dict) and "items" in item:
            if nivel >= 2:
                errores.agregar(r, "PROFUNDIDAD_EXCEDIDA", "Solo se admite un nivel de grupos.")
                continue
            sub = _grupo(item, r, nivel + 1, por_codigo, sensibles, errores, total)
            if sub is not None:
                hijos.append(sub)
        else:
            total[0] += 1
            if total[0] > MAX_CRITERIOS:
                continue  # el error global se agrega una vez en ``validar``
            hoja = _hoja(item, r, por_codigo, sensibles, errores)
            if hoja is not None:
                hijos.append(hoja)
    if nodo["op"] not in COMBINADORES:
        return None
    return Grupo(nodo["op"], tuple(hijos))


def _hoja(
    nodo: Any, ruta: str, por_codigo: dict[str, Any], sensibles: set[str], errores: _Errores
) -> Hoja | None:
    if not isinstance(nodo, dict) or set(nodo) != {"campo", "operador", "valor"}:
        errores.agregar(ruta, "ESTRUCTURA_INVALIDA", "Se esperaba campo, operador y valor.")
        return None
    campo, operador, valor = nodo["campo"], nodo["operador"], nodo["valor"]
    if not isinstance(campo, str) or not isinstance(operador, str) or len(campo) > 64:
        errores.agregar(ruta, "ESTRUCTURA_INVALIDA", "Campo u operador inválidos.")
        return None
    campo_id: int | None = None
    opciones: dict[str, int] = {}
    if campo in FIJOS:
        tipo = FIJOS[campo]
        permitidos = OPERADORES_POR_TIPO["NUMERO"] if tipo == "ANTIGUEDAD" else OPERADORES_CONJUNTO
    elif campo in por_codigo:
        d = por_codigo[campo]
        tipo, campo_id = d.tipo_dato, d.id
        permitidos = OPERADORES_POR_TIPO.get(tipo, ())
        if tipo == "LISTA":
            opciones = {o.valor: o.id for o in d.opciones if o.activo}
    elif campo in sensibles:
        errores.agregar(
            f"{ruta}.campo", "CAMPO_SENSIBLE_NO_FILTRABLE", "Un campo sensible no se puede usar."
        )
        return None
    else:
        errores.agregar(f"{ruta}.campo", "CAMPO_DESCONOCIDO", "El campo no existe o está inactivo.")
        return None
    if operador not in permitidos:
        errores.agregar(
            f"{ruta}.operador", "OPERADOR_NO_PERMITIDO", "El operador no aplica a este campo."
        )
        return None
    try:
        normal = _valor(campo, tipo, operador, valor, opciones)
    except _ValorInvalido as exc:
        errores.agregar(f"{ruta}.valor", exc.codigo, exc.mensaje)
        return None
    return Hoja(campo, tipo, operador, normal, campo_id)


class _ValorInvalido(Exception):  # noqa: N818 - uso interno
    def __init__(self, mensaje: str = "El valor no es válido.", codigo: str = "VALOR_INVALIDO"):
        super().__init__(codigo)
        self.codigo = codigo
        self.mensaje = mensaje


def _valor(campo: str, tipo: str, operador: str, valor: Any, opciones: dict[str, int]) -> Any:
    if operador == "en":
        if not isinstance(valor, list) or not 1 <= len(valor) <= MAX_VALORES_EN:
            raise _ValorInvalido(f"Se esperaba una lista de 1 a {MAX_VALORES_EN} valores.")
        return [_escalar(campo, tipo, v, opciones) for v in valor]
    if operador == "entre":
        if not isinstance(valor, list) or len(valor) != 2:
            raise _ValorInvalido("Se esperaban dos valores (desde y hasta).")
        a, b = (_escalar(campo, tipo, v, opciones) for v in valor)
        if a > b:
            raise _ValorInvalido("El primer valor no puede ser mayor que el segundo.")
        return (a, b)
    return _escalar(campo, tipo, valor, opciones)


def _escalar(campo: str, tipo: str, v: Any, opciones: dict[str, int]) -> Any:  # noqa: PLR0911
    if tipo == "ID":
        if isinstance(v, bool) or not isinstance(v, int) or not 0 < v < 2**62:
            raise _ValorInvalido("Se esperaba un identificador entero positivo.")
        return v
    if tipo == "ENUM":
        if not isinstance(v, str) or v not in VALORES_ENUM[campo]:
            raise _ValorInvalido("El valor no está permitido para este campo.")
        return v
    if tipo == "ANTIGUEDAD":
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= ANTIGUEDAD_MAX:
            raise _ValorInvalido(f"Se esperaban años enteros de 0 a {ANTIGUEDAD_MAX}.")
        return v
    if tipo == "TEXTO":
        if not isinstance(v, str) or not 1 <= len(v.strip()) <= MAX_TEXTO:
            raise _ValorInvalido(f"Se esperaba un texto de 1 a {MAX_TEXTO} caracteres.")
        return v.strip()
    if tipo == "NUMERO":
        if isinstance(v, bool) or not isinstance(v, int | float):
            raise _ValorInvalido("Se esperaba un número.")
        try:
            numero = Decimal(str(v))
        except InvalidOperation as exc:  # pragma: no cover - str(float) siempre es válido
            raise _ValorInvalido("Se esperaba un número.") from exc
        if not numero.is_finite() or abs(numero) > NUMERO_MAX:
            raise _ValorInvalido("El número está fuera de rango.")
        return numero
    if tipo == "FECHA":
        if not isinstance(v, str) or len(v) != 10:
            raise _ValorInvalido("Se esperaba una fecha AAAA-MM-DD.")
        try:
            return date.fromisoformat(v)
        except ValueError as exc:
            raise _ValorInvalido("Se esperaba una fecha AAAA-MM-DD.") from exc
    if tipo == "SI_NO":
        if not isinstance(v, bool):
            raise _ValorInvalido("Se esperaba verdadero o falso.")
        return v
    if tipo == "LISTA":
        if not isinstance(v, str) or v not in opciones:
            raise _ValorInvalido("La opción no existe o está inactiva.", "OPCION_DESCONOCIDA")
        return opciones[v]
    raise _ValorInvalido()  # tipo de campo desconocido: nunca se acepta
