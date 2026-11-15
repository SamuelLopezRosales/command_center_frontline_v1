"""Catálogo de variables para el editor (CON-15; CC-REQ-061).

Se compone con las variables fijas, de organización, derivadas y del sistema, más los campos
activos de INT-CAM-01. ``{{empresa}}`` no se ofrece: queda pendiente (PQ-17).
"""

from __future__ import annotations

from cc_common.auth import UsuarioActual

from cc_constancias.render.catalogo_variables import Catalogo, Variable


async def listar(campos, u: UsuarioActual) -> list[Variable]:
    return Catalogo(await campos.definiciones(u.empresa_id)).activas()
