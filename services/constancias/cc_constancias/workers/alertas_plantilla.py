"""Alertas de campos vacíos en plantillas (design.md §5.4; CC-REQ-067, 163).

``recalcular`` cuenta, por cada campo dinámico que usa una plantilla, a cuántos colaboradores les
falta el valor (INT-COL-09) y lo guarda en ``alerta_plantilla``. El dashboard solo muestra las de
plantillas activas con ``total_afectados > 0``. Se dispara al publicar o restaurar una versión
(mejor esfuerzo: una falla no afecta la publicación) y con el evento ``campo.actualizado``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from cc_common.db import transaccion

from cc_constancias.render.catalogo_variables import DERIVADAS
from cc_constancias.repos import solicitudes as repo
from cc_constancias.servicios.solicitudes import contenidos_vigentes

log = logging.getLogger("cc.alertas_plantilla")


async def recalcular(
    motor,
    almacen,
    campos,
    colaboradores,
    empresa_id: int,
    *,
    plantillas: Iterable[int] | None = None,
) -> int:
    """Recalcula las alertas de ``plantillas`` (todas si es ``None``). Devuelve cuántas procesó."""
    solo = set(plantillas) if plantillas is not None else None
    por_clave = {
        d.clave: d.codigo_interno for d in await campos.definiciones(empresa_id) if d.activo
    }
    procesadas = 0
    for fila, usadas in await contenidos_vigentes(motor, almacen, empresa_id):
        if solo is not None and fila["id"] not in solo:
            continue
        codigos = sorted(
            {
                por_clave[("sueldo" if v in DERIVADAS else v)]
                for v in usadas
                if ("sueldo" if v in DERIVADAS else v) in por_clave
            }
        )
        conteos = await colaboradores.faltantes_contar(empresa_id, codigos) if codigos else {}
        async with transaccion(motor, empresa_id) as conn:
            await repo.reemplazar_alertas(
                conn,
                empresa_id=empresa_id,
                plantilla_id=fila["id"],
                totales={c: int(conteos.get(c, 0)) for c in codigos},
            )
        procesadas += 1
    return procesadas


async def recalcular_sin_fallar(motor, almacen, campos, colaboradores, empresa_id, plantilla_id):
    try:
        await recalcular(
            motor, almacen, campos, colaboradores, empresa_id, plantillas=[plantilla_id]
        )
    except Exception:  # noqa: BLE001 - mejor esfuerzo
        log.warning("no se pudo recalcular la alerta de una plantilla")
