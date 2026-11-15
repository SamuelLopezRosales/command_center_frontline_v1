"""Resolución de variables de plantilla con datos del colaborador (design.md §5.2, §5.3).

Grupos que resuelve ``colaboradores`` (las variables de sistema y las derivadas las calcula
``constancias``):

- Fijos: ``nombre_completo``, ``numero_empleado``, ``puesto``, ``fecha_ingreso`` (``AAAA-MM-DD``),
  ``planta`` y ``tipo_empleado``.
- Organización: ``organizacion.razon_social``, ``.rfc``, ``.domicilio_fiscal``,
  ``.nombre_firmante``, ``.cargo_firmante``, ``.correo_firmante`` y ``lugar`` (``ciudad``).
- ``registro_patronal``: el del colaborador y, si no tiene, el de su organización.
- ``horario``: la ``descripcion`` de la opción elegida en el campo ``turno``.
- Campos dinámicos por su ``clave``. Una lista devuelve la etiqueta de la opción, salvo
  ``periodicidad_sueldo``, que devuelve su valor (``SEMANAL``...), base del cálculo del sueldo
  mensual. ``SI_NO`` devuelve ``Sí`` o ``No``; números y fechas, su forma canónica en texto.

Un valor vacío es "faltante" (DS-12). Solo se descifran los campos sensibles pedidos.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from cc_colaboradores.campos_cliente import DefinicionCampo
from cc_colaboradores.repos import valor_campo as repo_valor

FIJAS = ("nombre_completo", "numero_empleado", "puesto", "fecha_ingreso", "planta", "tipo_empleado")
ORGANIZACION = {
    "organizacion.razon_social": "razon_social",
    "organizacion.rfc": "rfc",
    "organizacion.domicilio_fiscal": "domicilio_fiscal",
    "organizacion.nombre_firmante": "nombre_firmante",
    "organizacion.cargo_firmante": "cargo_firmante",
    "organizacion.correo_firmante": "correo_firmante",
    "lugar": "ciudad",
}
ESPECIALES = ("registro_patronal", "horario")
LISTA_COMO_VALOR = frozenset({"periodicidad_sueldo"})


def conocidas(definiciones: list[DefinicionCampo]) -> set[str]:
    """Variables que se pueden pedir. INT-CAM-01 trae los campos no eliminados; uno inactivo
    conserva sus valores y sigue resolviendo (design.md §5.3)."""
    return set(FIJAS) | set(ORGANIZACION) | set(ESPECIALES) | {d.clave for d in definiciones}


def _texto(d: DefinicionCampo, valor: Any) -> str | None:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if d.tipo_dato == "LISTA":
        opcion = next((o for o in d.opciones if o.id == valor), None)
        if opcion is None:
            return None
        return opcion.valor if d.clave in LISTA_COMO_VALOR else opcion.etiqueta
    if d.tipo_dato == "SI_NO":
        return "Sí" if valor else "No"
    if isinstance(valor, Decimal):
        return format(valor.normalize(), "f")
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor)


async def resolver(
    conn,
    cif,
    *,
    empresa_id: int,
    fila: dict[str, Any],
    organizacion: dict[str, Any],
    definiciones: list[DefinicionCampo],
    variables: list[str],
) -> tuple[dict[str, str], list[str], list[str]]:
    """Devuelve ``(valores, faltantes, sensibles_descifrados)``."""
    por_clave = {d.clave: d for d in definiciones}
    pedidas_campo = {v for v in variables if v in por_clave}
    if "registro_patronal" in variables and "registro_patronal" in por_clave:
        pedidas_campo.add("registro_patronal")
    if "horario" in variables and "turno" in por_clave:
        pedidas_campo.add("turno")
    codigos = {por_clave[c].codigo_interno for c in pedidas_campo}
    crudos: dict[str, Any] = {}
    descifrados: list[str] = []
    if codigos:
        crudos, descifrados = await repo_valor.leer(
            conn,
            cif,
            empresa_id=empresa_id,
            colaborador_id=fila["id"],
            definiciones=definiciones,
            incluir_sensibles=True,
            solo=codigos,
        )

    def campo(clave: str) -> str | None:
        d = por_clave.get(clave)
        return _texto(d, crudos.get(d.codigo_interno)) if d else None

    valores: dict[str, str] = {}
    for v in variables:
        if v == "nombre_completo":
            r = f"{fila['nombres']} {fila['apellido_paterno']} {fila['apellido_materno']}"
        elif v == "planta":
            r = fila["planta_nombre"]
        elif v == "fecha_ingreso":
            r = fila["fecha_ingreso"].isoformat()
        elif v in FIJAS:
            r = fila[v]
        elif v in ORGANIZACION:
            r = organizacion.get(ORGANIZACION[v])
        elif v == "registro_patronal":
            r = campo("registro_patronal") or organizacion.get("registro_patronal")
        elif v == "horario":
            d = por_clave.get("turno")
            opcion = (
                next((o for o in d.opciones if o.id == crudos.get(d.codigo_interno)), None)
                if d
                else None
            )
            r = opcion.descripcion if opcion else None
        else:
            r = campo(v)
        if r is not None and str(r).strip():
            valores[v] = str(r)
    faltantes = [v for v in variables if v not in valores]
    return valores, faltantes, descifrados
