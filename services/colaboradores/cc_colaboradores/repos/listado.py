"""Listado, búsqueda y filtros de colaboradores (COL-01; design.md §8.1, §2.4; CC-REQ-031 a 033).

- Búsqueda por nombre sin acentos ni mayúsculas, parcial, con la **misma expresión** que el índice
  trigrama ``colaborador_nombre_trgm``; o por prefijo del número de empleado
  (``colaborador_numero_prefijo``).
- Filtros fijos por organización, planta, estatus y tipo; filtros por campos dinámicos con
  ``EXISTS`` sobre ``valor_campo``. Solo campos activos y **no sensibles**: un sensible está
  cifrado y no se puede filtrar (design.md §8.3). Esa regla la aplica el servicio.
- Orden estable ``apellido_paterno, apellido_materno, nombres, id`` y paginación con ``total``.

Todo valor va como parámetro enlazado. Los fragmentos de SQL interpolados salen de listas fijas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cc_colaboradores.servicios.elegibilidad import SQL_CONSENTIMIENTO_VIGENTE

NOMBRE_INDEXADO = (
    "colaboradores.f_unaccent(lower(c.nombres || ' ' || c.apellido_paterno || ' ' || "
    "c.apellido_materno))"
)
COLUMNA_POR_TIPO = {
    "TEXTO": "lower(v.valor_texto) = lower(:{p})",
    "SI_NO": "v.valor_texto = :{p}",
    "NUMERO": "v.valor_numero = :{p}",
    "FECHA": "v.valor_fecha = :{p}",
    "LISTA": "v.valor_opcion_id = :{p}",
}


@dataclass(frozen=True)
class FiltroCampo:
    campo_id: int
    tipo_dato: str
    valor: str | Decimal | date | int


@dataclass
class Consulta:
    q: str | None = None
    organizacion_id: int | None = None
    planta_id: int | None = None
    estatus: str | None = None
    tipo_empleado: str | None = None
    campos: list[FiltroCampo] = field(default_factory=list)
    columnas: list[int] = field(default_factory=list)  # campo_id de columnas dinámicas
    pagina: int = 1
    limite: int = 20


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _condiciones(c: Consulta) -> tuple[list[str], dict[str, Any]]:
    cond: list[str] = []
    params: dict[str, Any] = {}
    if c.q:
        params["q_nombre"] = f"%{_escapar_like(c.q.lower())}%"
        params["q_numero"] = f"{_escapar_like(c.q.upper())}%"
        cond.append(
            f"({NOMBRE_INDEXADO} LIKE colaboradores.f_unaccent(:q_nombre) "
            "OR c.numero_empleado LIKE :q_numero)"
        )
    for nombre in ("organizacion_id", "planta_id", "estatus", "tipo_empleado"):
        valor = getattr(c, nombre)
        if valor is not None:
            cond.append(f"c.{nombre} = :{nombre}")
            params[nombre] = valor
    for i, f in enumerate(c.campos):
        p = f"f{i}"
        params[f"{p}_campo"] = f.campo_id
        params[p] = f.valor
        # Solo nombres de parámetros y una plantilla de COLUMNA_POR_TIPO: ningún valor del cliente.
        cond.append(
            "EXISTS (SELECT 1 FROM colaboradores.valor_campo v WHERE v.colaborador_id = c.id "  # noqa: S608
            f"AND v.campo_id = :{p}_campo AND {COLUMNA_POR_TIPO[f.tipo_dato].format(p=p)})"
        )
    return cond, params


async def buscar(conn: AsyncConnection, c: Consulta) -> tuple[list[dict[str, Any]], int]:
    cond, params = _condiciones(c)
    where = (" WHERE " + " AND ".join(cond)) if cond else ""
    total = (
        await conn.execute(
            text(f"SELECT count(*) FROM colaboradores.colaborador c{where}"),  # noqa: S608
            params,
        )
    ).scalar_one()
    params.update({"lim": c.limite, "off": (c.pagina - 1) * c.limite})
    filas = (
        (
            await conn.execute(
                text(
                    "SELECT c.id, c.numero_empleado, c.nombres, c.apellido_paterno, "  # noqa: S608
                    "c.apellido_materno, c.celular_ultimos4, c.celular_invalido, c.puesto, "
                    "c.tipo_empleado, c.estatus, c.fecha_ingreso, c.organizacion_id, "
                    "o.clave AS organizacion_clave, c.planta_id, p.nombre AS planta_nombre, "
                    f"{SQL_CONSENTIMIENTO_VIGENTE} AS consentimiento_vigente "
                    "FROM colaboradores.colaborador c "
                    "JOIN colaboradores.organizacion o ON o.id = c.organizacion_id "
                    "JOIN colaboradores.planta p ON p.id = c.planta_id"
                    f"{where} ORDER BY c.apellido_paterno, c.apellido_materno, c.nombres, c.id "
                    "LIMIT :lim OFFSET :off"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    items = [dict(f) for f in filas]
    if items and c.columnas:
        valores = await conn.execute(
            text(
                "SELECT colaborador_id, campo_id, valor_texto, valor_numero, valor_fecha, "
                "valor_opcion_id FROM colaboradores.valor_campo "
                "WHERE colaborador_id = ANY(:ids) AND campo_id = ANY(:campos) "
                "AND valor_cifrado IS NULL"
            ),
            {"ids": [i["id"] for i in items], "campos": c.columnas},
        )
        por_colaborador: dict[int, dict[int, Any]] = {}
        for cid, campo, t, n, f, o in valores.all():
            por_colaborador.setdefault(cid, {})[campo] = next(
                (x for x in (t, n, f, o) if x is not None), None
            )
        for i in items:
            i["valores"] = por_colaborador.get(i["id"], {})
    return items, int(total)
