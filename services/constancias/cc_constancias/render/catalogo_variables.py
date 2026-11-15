"""Catálogo de variables que una plantilla puede usar (design.md §3.5, §5.2; CC-REQ-061, 065).

Grupos (como el editor ``cv1_06``): ``COLABORADOR``, ``ORGANIZACION``, ``SENSIBLES`` y
``SISTEMA``. Se compone con las variables fijas, de organización, derivadas y del sistema más los
campos dinámicos de INT-CAM-01:

- Un campo activo **no sensible** va en ``COLABORADOR``; uno sensible, en ``SENSIBLES``.
- ``sueldo_mensual`` y ``sueldo_letra`` son derivadas y sensibles (salen del sueldo).
- ``registro_patronal`` va en ``ORGANIZACION`` y siempre existe: usa el del colaborador y, si no
  tiene, el de su organización, aunque el campo dinámico del mismo nombre esté desactivado.

``estado`` distingue una variable ``ACTIVA`` de una ``INACTIVA`` (campo desactivado: conserva sus
valores pero no se ofrece a RH ni se publica con él) y de una ``INEXISTENTE`` (CC-REQ-065). Un campo
eliminado ya no llega de INT-CAM-01 y también es ``INEXISTENTE``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from cc_constancias.clientes import DefinicionCampo

Grupo = Literal["COLABORADOR", "ORGANIZACION", "SENSIBLES", "SISTEMA"]
Estado = Literal["ACTIVA", "INACTIVA", "INEXISTENTE"]
Origen = Literal["SISTEMA", "DERIVADA", "COLABORADOR", "CAMPO"]

SISTEMA = ("folio", "fecha_emision", "qr_verificacion")
DERIVADAS = ("sueldo_mensual", "sueldo_letra")
FIJAS_COLABORADOR = ("nombre_completo", "puesto", "fecha_ingreso", "planta", "horario")
ORGANIZACION = (
    "organizacion.razon_social",
    "organizacion.rfc",
    "organizacion.domicilio_fiscal",
    "organizacion.nombre_firmante",
    "organizacion.cargo_firmante",
    "organizacion.correo_firmante",
    "lugar",
    "registro_patronal",
)
# Campos dinámicos que alimentan las derivadas: se piden aunque la plantilla no los use.
BASE_SUELDO = ("sueldo", "periodicidad_sueldo")


@dataclass(frozen=True)
class Variable:
    nombre: str
    grupo: Grupo
    sensible: bool
    origen: Origen
    etiqueta: str
    activa: bool = True
    tipo_dato: str | None = None  # solo campos dinámicos


class Catalogo:
    """Variables conocidas de una empresa."""

    def __init__(self, definiciones: Iterable[DefinicionCampo]) -> None:
        variables: dict[str, Variable] = {}
        for nombre in SISTEMA:
            variables[nombre] = Variable(nombre, "SISTEMA", False, "SISTEMA", nombre)
        for nombre in FIJAS_COLABORADOR:
            variables[nombre] = Variable(nombre, "COLABORADOR", False, "COLABORADOR", nombre)
        for nombre in ORGANIZACION:
            variables[nombre] = Variable(nombre, "ORGANIZACION", False, "COLABORADOR", nombre)
        for d in sorted(definiciones, key=lambda x: (x.orden, x.id)):
            if d.clave in variables:  # una clave reservada no llega aquí (CLAVE_RESERVADA)
                continue
            variables[d.clave] = Variable(
                d.clave,
                "SENSIBLES" if d.es_sensible else "COLABORADOR",
                d.es_sensible,
                "CAMPO",
                d.nombre_campo,
                activa=d.activo,
                tipo_dato=d.tipo_dato,
            )
        for nombre in DERIVADAS:  # después de los campos sensibles, como en el editor
            variables[nombre] = Variable(nombre, "SENSIBLES", True, "DERIVADA", nombre)
        self._variables = variables

    def estado(self, nombre: str) -> Estado:
        v = self._variables.get(nombre)
        if v is None:
            return "INEXISTENTE"
        return "ACTIVA" if v.activa else "INACTIVA"

    def obtener(self, nombre: str) -> Variable | None:
        return self._variables.get(nombre)

    def activas(self) -> list[Variable]:
        """Lo que ve RH en el editor: grupos en orden, y dentro de cada uno el de declaración."""
        orden = {"COLABORADOR": 0, "ORGANIZACION": 1, "SENSIBLES": 2, "SISTEMA": 3}
        return sorted(
            (v for v in self._variables.values() if v.activa), key=lambda v: orden[v.grupo]
        )

    def es_sensible(self, nombre: str) -> bool:
        v = self._variables.get(nombre)
        return bool(v and v.sensible)

    def clasificar(self, nombres: Iterable[str]) -> dict[str, list[str]]:
        """Reparte ``nombres`` en ``inexistentes``, ``inactivas`` y ``sensibles`` (cada una sin
        repetir y en orden). Es lo que usa la validación previa a la publicación."""
        salida: dict[str, list[str]] = {"inexistentes": [], "inactivas": [], "sensibles": []}
        for nombre in dict.fromkeys(nombres):
            estado = self.estado(nombre)
            if estado == "INEXISTENTE":
                salida["inexistentes"].append(nombre)
                continue
            if estado == "INACTIVA":
                salida["inactivas"].append(nombre)
            if self.es_sensible(nombre):
                salida["sensibles"].append(nombre)
        return salida

    def fechas(self) -> set[str]:
        """Variables que son una fecha y se muestran en texto largo."""
        return {"fecha_ingreso", "fecha_emision"} | {
            v.nombre for v in self._variables.values() if v.tipo_dato == "FECHA"
        }
