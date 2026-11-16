"""``AudienciaQueryService``: compila los criterios de una audiencia a SQL y los evalúa
(INT-COL-06; design.md §6.1; CC-REQ-100, 101, 105, 28).

Reglas de seguridad:
- El árbol se valida primero con ``cc_common.criterios_audiencia`` contra las definiciones de
  campos (INT-CAM-01): solo campos fijos de la lista cerrada y campos dinámicos **activos y no
  sensibles**; un campo fuera de la lista se rechaza con 422 antes de generar SQL.
- El SQL se arma con una tabla cerrada de fragmentos (``FRAGMENTOS``) y **todo valor viaja como
  parámetro enlazado** (``:p0``, ``:p1``...). Lo único que se concatena son esos nombres de
  parámetro y fragmentos constantes: ningún dato del cliente llega al texto de la consulta.
- Los campos dinámicos se consultan con ``EXISTS``/``NOT EXISTS`` sobre ``valor_campo`` y solo
  sobre las columnas tipadas (``valor_cifrado IS NULL``): nunca se descifra nada.

Semántica: ``no_es`` usa ``NOT EXISTS`` (incluye a quien no tiene valor) en campos dinámicos y
``<>`` en campos fijos (siempre tienen valor). La antigüedad son años completos al día de hoy en
la zona de la empresa: ``fecha_ingreso <= hoy - make_interval(years => n)``.

Embudo (una sola consulta, conteos acumulados): seleccionados, con consentimiento vigente,
activos y con celular válido. A cada colaborador no elegible se le da **un solo** motivo, el primero
que falla en el orden ``SIN_CONSENTIMIENTO``, ``ESTATUS_BAJA``, ``SIN_CELULAR_VALIDO``.
No hay caché: un cambio de planta (u otro dato) se refleja en la siguiente evaluación.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cc_common.criterios_audiencia import Grupo, Hoja, validar
from cc_common.db import transaccion
from cc_common.errores import ErrorCampo, ErrorValidacion
from cc_common.paginacion import CursorInvalido, codificar_cursor, decodificar_cursor
from sqlalchemy import text

from cc_colaboradores.servicios.elegibilidad import SQL_CONSENTIMIENTO_VIGENTE

LIMITE_MAXIMO = 1000
LIMITE_POR_DEFECTO = 500
MOTIVOS = ("SIN_CONSENTIMIENTO", "ESTATUS_BAJA", "SIN_CELULAR_VALIDO")

_HOY = "CAST((now() AT TIME ZONE CAST(:zona AS text)) AS date)"
_VALOR_ACTIVO = "v.valor_cifrado IS NULL"

# Fragmento por tipo de criterio y operador. ``{p}`` es el nombre del parámetro enlazado.
# Fijos: columna de ``colaborador`` (alias ``c``). Dinámicos: columna tipada de ``valor_campo``
# (alias ``v``). Todos son constantes del código.
FRAGMENTOS: dict[tuple[str, str], str] = {
    ("ID", "es"): "{col} = :{p}",
    ("ID", "no_es"): "{col} <> :{p}",
    ("ID", "en"): "{col} = ANY(:{p})",
    ("ENUM", "es"): "{col} = :{p}",
    ("ENUM", "no_es"): "{col} <> :{p}",
    ("ENUM", "en"): "{col} = ANY(:{p})",
    ("LISTA", "es"): "v.valor_opcion_id = :{p}",
    ("LISTA", "no_es"): "v.valor_opcion_id = :{p}",  # se niega con NOT EXISTS
    ("LISTA", "en"): "v.valor_opcion_id = ANY(:{p})",
    ("TEXTO", "es"): "lower(v.valor_texto) = lower(:{p})",
    ("TEXTO", "no_es"): "lower(v.valor_texto) = lower(:{p})",  # se niega con NOT EXISTS
    ("TEXTO", "contiene"): "lower(v.valor_texto) LIKE lower(:{p}) ESCAPE '\\'",
    ("NUMERO", "="): "v.valor_numero = :{p}",
    ("NUMERO", "<"): "v.valor_numero < :{p}",
    ("NUMERO", "<="): "v.valor_numero <= :{p}",
    ("NUMERO", ">"): "v.valor_numero > :{p}",
    ("NUMERO", ">="): "v.valor_numero >= :{p}",
    ("NUMERO", "entre"): "v.valor_numero BETWEEN :{p}a AND :{p}b",
    ("FECHA", "antes"): "v.valor_fecha < :{p}",
    ("FECHA", "despues"): "v.valor_fecha > :{p}",
    ("FECHA", "entre"): "v.valor_fecha BETWEEN :{p}a AND :{p}b",
    ("SI_NO", "es"): "v.valor_texto = :{p}",
}
_COLUMNAS_FIJAS = {
    "colaborador_id": "c.id",
    "organizacion_id": "c.organizacion_id",
    "planta_id": "c.planta_id",
    "tipo_empleado": "c.tipo_empleado",
    "estatus": "c.estatus",
}
_NEGADOS = {("LISTA", "no_es"), ("TEXTO", "no_es")}


@dataclass(frozen=True)
class Compilado:
    sql: str  # condición booleana sobre ``colaboradores.colaborador c``
    params: dict[str, Any] = field(default_factory=dict)


class _Compilador:
    def __init__(self) -> None:
        self.params: dict[str, Any] = {}
        self._n = 0

    def _nombre(self) -> str:
        self._n += 1
        return f"p{self._n}"

    def grupo(self, g: Grupo) -> str:
        union = " AND " if g.op == "Y" else " OR "
        return "(" + union.join(self.nodo(i) for i in g.items) + ")"

    def nodo(self, n: Hoja | Grupo) -> str:
        return self.grupo(n) if isinstance(n, Grupo) else self.hoja(n)

    def hoja(self, h: Hoja) -> str:
        if h.tipo == "ANTIGUEDAD":
            return self._antiguedad(h)
        p = self._nombre()
        if h.operador == "entre":
            self.params[f"{p}a"], self.params[f"{p}b"] = h.valor
        elif h.tipo == "TEXTO" and h.operador == "contiene":
            self.params[p] = "%" + _escapar_like(h.valor) + "%"
        elif h.tipo == "SI_NO":
            self.params[p] = "SI" if h.valor else "NO"
        else:
            self.params[p] = h.valor
        fragmento = FRAGMENTOS[(h.tipo, h.operador)].format(p=p, col=_COLUMNAS_FIJAS.get(h.campo))
        if h.campo in _COLUMNAS_FIJAS:
            return fragmento
        self.params[f"{p}_campo"] = h.campo_id
        negar = "NOT " if (h.tipo, h.operador) in _NEGADOS else ""
        return (
            f"{negar}EXISTS (SELECT 1 FROM colaboradores.valor_campo v "  # noqa: S608
            f"WHERE v.colaborador_id = c.id AND v.campo_id = :{p}_campo "
            f"AND {_VALOR_ACTIVO} AND {fragmento})"
        )

    def _anios(self, n: int) -> str:
        p = self._nombre()
        self.params[p] = n
        return f"({_HOY} - make_interval(years => :{p}))"

    def _antiguedad(self, h: Hoja) -> str:
        """Años completos ``a``: ``a >= n`` equivale a ``fecha_ingreso <= hoy - n años``."""
        op, v = h.operador, h.valor
        if op == "entre":
            desde, hasta = v
            return (
                f"(c.fecha_ingreso <= {self._anios(desde)} "
                f"AND c.fecha_ingreso > {self._anios(hasta + 1)})"
            )
        if op == ">=":
            return f"c.fecha_ingreso <= {self._anios(v)}"
        if op == ">":
            return f"c.fecha_ingreso <= {self._anios(v + 1)}"
        if op == "<":
            return f"c.fecha_ingreso > {self._anios(v)}"
        if op == "<=":
            return f"c.fecha_ingreso > {self._anios(v + 1)}"
        return f"(c.fecha_ingreso <= {self._anios(v)} AND c.fecha_ingreso > {self._anios(v + 1)})"


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def compilar(arbol: Grupo) -> Compilado:
    """Traduce un árbol ya validado. Es pura: no toca la base de datos."""
    c = _Compilador()
    return Compilado(c.grupo(arbol), c.params)


@dataclass(frozen=True)
class Embudo:
    seleccionados: int
    con_consentimiento: int
    activos: int
    celular_valido: int


@dataclass(frozen=True)
class ItemAudiencia:
    id: int
    nombre: str
    planta_nombre: str | None
    celular_ultimos4: str
    motivo_exclusion: str | None


@dataclass(frozen=True)
class ResultadoAudiencia:
    total: int
    embudo: Embudo
    items: list[ItemAudiencia]
    siguiente_cursor: str | None


class AudienciaQueryService:
    def __init__(self, motor: Any, campos: Any, zona_por_defecto: str = "America/Mexico_City"):
        self._motor = motor
        self._campos = campos
        self._zona = zona_por_defecto

    async def compilar(self, empresa_id: int, criterios: Any) -> Compilado:
        definiciones = await self._campos.definiciones(empresa_id)
        return compilar(validar(criterios, definiciones))

    async def evaluar(
        self,
        empresa_id: int,
        criterios: Any,
        *,
        solo_conteo: bool = False,
        cursor: str | None = None,
        limite: int = LIMITE_POR_DEFECTO,
        zona_horaria: str | None = None,
    ) -> ResultadoAudiencia:
        zona = _zona_valida(zona_horaria or self._zona)
        compilado = await self.compilar(empresa_id, criterios)
        params = {**compilado.params, "e": empresa_id, "zona": zona}
        donde = f"c.empresa_id = :e AND {compilado.sql}"
        limite = max(1, min(int(limite), LIMITE_MAXIMO))
        despues = _despues(cursor) if cursor and not solo_conteo else 0
        async with transaccion(self._motor, empresa_id) as conn:
            fila = (
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) AS seleccionados, "  # noqa: S608
                            "count(*) FILTER (WHERE t.vigente) AS con_consentimiento, "
                            "count(*) FILTER (WHERE t.vigente AND t.estatus = 'ACTIVO') "
                            "AS activos, "
                            "count(*) FILTER (WHERE t.vigente AND t.estatus = 'ACTIVO' "
                            "AND NOT t.celular_invalido) AS celular_valido "
                            "FROM (SELECT c.estatus, c.celular_invalido, "
                            f"{SQL_CONSENTIMIENTO_VIGENTE} AS vigente "
                            f"FROM colaboradores.colaborador c WHERE {donde}) t"
                        ),
                        params,
                    )
                )
                .mappings()
                .one()
            )
            embudo = Embudo(**{k: int(v) for k, v in fila.items()})
            if solo_conteo:
                return ResultadoAudiencia(embudo.seleccionados, embudo, [], None)
            filas = (
                (
                    await conn.execute(
                        text(
                            "SELECT c.id, c.nombres, c.apellido_paterno, c.apellido_materno, "  # noqa: S608
                            "p.nombre AS planta_nombre, c.celular_ultimos4, "
                            f"CASE WHEN NOT {SQL_CONSENTIMIENTO_VIGENTE} "
                            "THEN 'SIN_CONSENTIMIENTO' "
                            "WHEN c.estatus <> 'ACTIVO' THEN 'ESTATUS_BAJA' "
                            "WHEN c.celular_invalido THEN 'SIN_CELULAR_VALIDO' END "
                            "AS motivo_exclusion "
                            "FROM colaboradores.colaborador c "
                            "JOIN colaboradores.planta p ON p.id = c.planta_id "
                            f"WHERE {donde} AND c.id > :despues ORDER BY c.id LIMIT :lim"
                        ),
                        {**params, "despues": despues, "lim": limite + 1},
                    )
                )
                .mappings()
                .all()
            )
        hay_mas = len(filas) > limite
        filas = filas[:limite]
        items = [
            ItemAudiencia(
                id=f["id"],
                nombre=" ".join(
                    x for x in (f["nombres"], f["apellido_paterno"], f["apellido_materno"]) if x
                ),
                planta_nombre=f["planta_nombre"],
                celular_ultimos4=str(f["celular_ultimos4"]),
                motivo_exclusion=f["motivo_exclusion"],
            )
            for f in filas
        ]
        siguiente = codificar_cursor((items[-1].id,)) if hay_mas and items else None
        return ResultadoAudiencia(embudo.seleccionados, embudo, items, siguiente)


def _despues(cursor: str) -> int:
    try:
        (valor,) = decodificar_cursor(cursor)
        if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
            raise CursorInvalido("cursor inválido")
    except (CursorInvalido, ValueError) as exc:
        raise ErrorValidacion(
            errores=[ErrorCampo("cursor", "CURSOR_INVALIDO", "El cursor no es válido.")]
        ) from exc
    return valor


def _zona_valida(zona: str) -> str:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(zona)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ErrorValidacion(
            errores=[ErrorCampo("zona_horaria", "ZONA_INVALIDA", "La zona horaria no existe.")]
        ) from exc
    return zona
