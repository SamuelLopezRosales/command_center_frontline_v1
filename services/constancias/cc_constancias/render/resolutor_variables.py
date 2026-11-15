"""Resolutor de variables de una plantilla (design.md §5.2, §5.3; CC-REQ-061, 076, 077, 078).

Recibe los nombres de variable que usa una versión y devuelve su valor en texto:

1. **Sistema** (``folio``, ``fecha_emision``, ``qr_verificacion``): los entrega quien genera. Si
   falta ``fecha_emision`` se calcula con la fecha de hoy en México.
2. **Derivadas** (``sueldo_mensual``, ``sueldo_letra``): se calculan aquí a partir de ``sueldo`` y
   ``periodicidad_sueldo``, que se piden a `colaboradores` aunque la plantilla no las use.
3. **Colaborador, organización y campos dinámicos**: los resuelve `colaboradores` por INT-COL-04
   (``registro_patronal`` con el respaldo de la organización y ``horario`` con la descripción de la
   opción del turno ya vienen resueltos allí).
4. Las fechas (``fecha_ingreso``, ``fecha_emision`` y campos de tipo fecha) se presentan en texto
   largo ("15 de marzo de 2021").

Una variable sin valor es **faltante** (DS-12); una que el catálogo no conoce es **desconocida** y
no se envía a ningún servicio. Nunca se registran valores: solo nombres.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from cc_constancias.clientes import ClienteColaboradores, DefinicionCampo
from cc_constancias.render import derivadas
from cc_constancias.render.catalogo_variables import (
    BASE_SUELDO,
    DERIVADAS,
    SISTEMA,
    Catalogo,
)


@dataclass
class Resolucion:
    valores: dict[str, str] = field(default_factory=dict)
    faltantes: list[str] = field(default_factory=list)
    desconocidas: list[str] = field(default_factory=list)
    factores_version: str = derivadas.FACTORES_VERSION
    sensibles_usadas: list[str] = field(default_factory=list)


def _derivadas(crudos: Mapping[str, str], pedidas: Iterable[str]) -> dict[str, str]:
    """``sueldo_mensual`` y ``sueldo_letra`` de lo pedido; omite las que no se pueden calcular."""
    pedidas = [p for p in pedidas if p in DERIVADAS]
    if not pedidas or "sueldo" not in crudos or "periodicidad_sueldo" not in crudos:
        return {}
    try:
        mensual = derivadas.sueldo_mensual(
            derivadas.a_decimal(crudos["sueldo"]), crudos["periodicidad_sueldo"]
        )
    except derivadas.SueldoInvalido:
        return {}
    todas = {
        "sueldo_mensual": derivadas.formato_moneda(mensual),
        "sueldo_letra": derivadas.importe_en_letra(mensual),
    }
    return {p: todas[p] for p in pedidas}


async def resolver(
    colaboradores: ClienteColaboradores,
    *,
    empresa_id: int,
    colaborador_id: int,
    variables: Iterable[str],
    definiciones: list[DefinicionCampo],
    sistema: Mapping[str, str] | None = None,
    ahora: datetime | None = None,
) -> Resolucion:
    catalogo = Catalogo(definiciones)
    pedidas = list(dict.fromkeys(variables))
    r = Resolucion()
    r.desconocidas = [v for v in pedidas if catalogo.estado(v) == "INEXISTENTE"]
    conocidas = [v for v in pedidas if v not in r.desconocidas]
    r.sensibles_usadas = [v for v in conocidas if catalogo.es_sensible(v)]

    delsistema = {**(sistema or {})}
    if "fecha_emision" in conocidas and "fecha_emision" not in delsistema:
        delsistema["fecha_emision"] = derivadas.fecha_en_texto(derivadas.hoy_en_mexico(ahora))
    derivadas_pedidas = [v for v in conocidas if v in DERIVADAS]

    # A `colaboradores` solo van las que él resuelve; las derivadas piden sus dos insumos.
    a_pedir = [v for v in conocidas if v not in SISTEMA and v not in DERIVADAS]
    if derivadas_pedidas:
        a_pedir += [b for b in BASE_SUELDO if b not in a_pedir]
    valores, _ = await colaboradores.datos_constancia(empresa_id, colaborador_id, a_pedir)

    fechas = catalogo.fechas()
    resultado: dict[str, str] = {}
    for v in conocidas:
        if v in SISTEMA:
            texto = delsistema.get(v)
        elif v in DERIVADAS:
            continue
        else:
            texto = valores.get(v)
            if texto and v in fechas:
                texto = derivadas.fecha_iso_en_texto(texto) or texto
        if texto is not None and str(texto).strip():
            resultado[v] = str(texto)
    resultado.update(_derivadas(valores, derivadas_pedidas))
    r.valores = {v: resultado[v] for v in conocidas if v in resultado}
    r.faltantes = [v for v in conocidas if v not in r.valores]
    return r
