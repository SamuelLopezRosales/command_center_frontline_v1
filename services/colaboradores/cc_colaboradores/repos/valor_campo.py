"""Valores de campos dinámicos (``colaboradores.valor_campo``; design.md §2.2 y §8.3).

Un valor ocupa una sola columna (``CHECK valor_campo_un_solo_valor``): ``valor_texto``
(``TEXTO`` y ``SI_NO`` como ``SI``/``NO``), ``valor_numero``, ``valor_fecha`` o
``valor_opcion_id``. Si el campo es sensible, el valor va **solo** a ``valor_cifrado`` (texto
cifrado con AES-GCM) y nunca a las columnas tipadas, para que no se pueda filtrar ni leer en SQL.

Datos autenticados del cifrado: ``valor_campo|valor_cifrado|{colaborador_id}:{campo_id}|empresa``.
Se usa el par colaborador y campo porque el ``id`` de la fila cambia al reemplazar el valor.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cc_colaboradores.campos_cliente import DefinicionCampo
from cc_colaboradores.cifrado import Cifrador
from cc_colaboradores.validador_campos import ValorValidado

ENMASCARADO = {"presente": True}

_UPSERT = text(
    """
    INSERT INTO colaboradores.valor_campo
      (empresa_id, colaborador_id, campo_id, valor_texto, valor_numero, valor_fecha,
       valor_opcion_id, valor_cifrado)
    VALUES (:e, :c, :campo, :t, :n, :f, :o, :x)
    ON CONFLICT (colaborador_id, campo_id) DO UPDATE SET
      valor_texto = EXCLUDED.valor_texto, valor_numero = EXCLUDED.valor_numero,
      valor_fecha = EXCLUDED.valor_fecha, valor_opcion_id = EXCLUDED.valor_opcion_id,
      valor_cifrado = EXCLUDED.valor_cifrado
    """
)


def registro(colaborador_id: int, campo_id: int) -> str:
    return f"{colaborador_id}:{campo_id}"


def _a_texto(v: ValorValidado) -> str:
    if v.tipo_dato == "SI_NO":
        return "SI" if v.valor else "NO"
    if isinstance(v.valor, date):
        return v.valor.isoformat()
    return str(v.valor)


def _desde_texto(tipo: str, texto: str) -> Any:
    if tipo == "NUMERO":
        return Decimal(texto)
    if tipo == "FECHA":
        return date.fromisoformat(texto)
    if tipo == "LISTA":
        return int(texto)
    if tipo == "SI_NO":
        return texto == "SI"
    return texto


async def guardar(
    conn: AsyncConnection,
    cif: Cifrador,
    *,
    empresa_id: int,
    colaborador_id: int,
    valores: list[ValorValidado],
) -> list[str]:
    """Inserta o reemplaza los valores; ``valor = None`` borra el valor. Devuelve los códigos
    tocados (para la bitácora, sin valores)."""
    tocados: list[str] = []
    for v in valores:
        tocados.append(v.codigo_interno)
        if v.valor is None:
            await conn.execute(
                text(
                    "DELETE FROM colaboradores.valor_campo "
                    "WHERE colaborador_id = :c AND campo_id = :campo"
                ),
                {"c": colaborador_id, "campo": v.campo_id},
            )
            continue
        params: dict[str, Any] = {
            "e": empresa_id,
            "c": colaborador_id,
            "campo": v.campo_id,
            "t": None,
            "n": None,
            "f": None,
            "o": None,
            "x": None,
        }
        if v.es_sensible:
            params["x"] = cif.cifrar(
                _a_texto(v),
                empresa_id=empresa_id,
                tabla="valor_campo",
                columna="valor_cifrado",
                registro=registro(colaborador_id, v.campo_id),
            )
        elif v.tipo_dato in ("TEXTO", "SI_NO"):
            params["t"] = _a_texto(v)
        elif v.tipo_dato == "NUMERO":
            params["n"] = v.valor
        elif v.tipo_dato == "FECHA":
            params["f"] = v.valor
        elif v.tipo_dato == "LISTA":
            params["o"] = v.valor
        await conn.execute(_UPSERT, params)
    return tocados


async def leer(
    conn: AsyncConnection,
    cif: Cifrador,
    *,
    empresa_id: int,
    colaborador_id: int,
    definiciones: list[DefinicionCampo],
    incluir_sensibles: bool = False,
    solo: set[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """``{codigo_interno: valor}``. Los sensibles salen como ``{"presente": true}`` salvo con
    ``incluir_sensibles``; con ``solo`` se limita a esos códigos (descifra solo lo pedido).
    Devuelve también los códigos sensibles descifrados (bitácora)."""
    por_id = {d.id: d for d in definiciones}
    filas = await conn.execute(
        text(
            "SELECT campo_id, valor_texto, valor_numero, valor_fecha, valor_opcion_id, "
            "valor_cifrado FROM colaboradores.valor_campo WHERE colaborador_id = :c"
        ),
        {"c": colaborador_id},
    )
    salida: dict[str, Any] = {}
    descifrados: list[str] = []
    for campo_id, t, n, f, o, x in filas.all():
        d = por_id.get(campo_id)
        if d is None or (solo is not None and d.codigo_interno not in solo):
            continue  # campo eliminado, de otra configuración o no pedido: no se expone
        if x is not None:
            if not incluir_sensibles:
                salida[d.codigo_interno] = dict(ENMASCARADO)
                continue
            claro = cif.descifrar(
                x,
                empresa_id=empresa_id,
                tabla="valor_campo",
                columna="valor_cifrado",
                registro=registro(colaborador_id, campo_id),
            )
            salida[d.codigo_interno] = _desde_texto(d.tipo_dato, claro)
            descifrados.append(d.codigo_interno)
        elif d.tipo_dato == "SI_NO":
            salida[d.codigo_interno] = t == "SI"
        else:
            salida[d.codigo_interno] = next(v for v in (t, n, f, o) if v is not None)
    return salida, descifrados
