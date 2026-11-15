"""Estructura común de la plantilla de carga (design.md §10.3; documento 04).

La hoja ``Colaboradores`` lleva los encabezados en la fila 1, las claves técnicas en la fila 2 y
los datos desde la fila 3 (hasta 2,000 filas). Los once campos fijos tienen clave propia; el resto
de las columnas son campos dinámicos: en la plantilla generada se identifican por su código interno
en la hoja oculta ``_meta`` (renombrar la clave no rompe la carga) y, en la plantilla del cliente
sin ``_meta``, por la ``clave`` de la fila 2.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

HOJA_COLABORADORES = "Colaboradores"
HOJA_ORGANIZACIONES = "Organizaciones"
HOJA_INSTRUCCIONES = "Instrucciones"
HOJA_DICCIONARIO = "Diccionario"
HOJA_CATALOGOS = "Catálogos"
HOJA_META = "_meta"

VERSION_PLANTILLA = "CC-2.0"
VERSION_EXTERNA = "EXTERNA"

FILA_ENCABEZADO = 1
FILA_CLAVES = 2
PRIMERA_FILA_DATOS = 3
MAX_FILAS = 2000
MAX_BYTES = 5 * 1024 * 1024
COLUMNA_IGNORADA = "_validacion"  # fórmula de Excel de la plantilla del cliente
PREFIJO_EJEMPLO = "EJEMPLO-"


@dataclass(frozen=True)
class ColumnaFija:
    clave: str
    encabezado: str
    etiqueta: str  # nombre para los mensajes de error
    obligatoria: bool = True


FIJOS: tuple[ColumnaFija, ...] = (
    ColumnaFija("numero_empleado", "Número de empleado *", "número de empleado"),
    ColumnaFija("nombres", "Nombre(s) *", "nombre(s)"),
    ColumnaFija("apellido_paterno", "Apellido paterno *", "apellido paterno"),
    ColumnaFija("apellido_materno", "Apellido materno *", "apellido materno"),
    ColumnaFija("celular_whatsapp", "Celular con WhatsApp * (10 dígitos)", "celular"),
    ColumnaFija("organizacion", "Organización * (clave)", "organización"),
    ColumnaFija("fecha_ingreso", "Fecha de ingreso * (dd/mm/aaaa)", "fecha de ingreso"),
    ColumnaFija("puesto", "Puesto *", "puesto"),
    ColumnaFija("tipo_empleado", "Tipo de empleado *", "tipo de empleado"),
    ColumnaFija("planta", "Planta / centro de trabajo *", "planta"),
    ColumnaFija("estatus", "Estatus *", "estatus"),
)
CLAVES_FIJAS = tuple(c.clave for c in FIJOS)
POR_CLAVE_FIJA = {c.clave: c for c in FIJOS}

TIPOS_EMPLEADO = {"administrativo": "ADMINISTRATIVO", "operativo": "OPERATIVO"}
ESTATUS = {"activo": "ACTIVO", "baja": "BAJA"}


class ArchivoInvalido(Exception):
    """El archivo no corresponde a la plantilla (CC-REQ-039). ``motivo`` es un código corto sin
    datos del archivo; ``mensaje`` se muestra al usuario."""

    def __init__(self, motivo: str, mensaje: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo
        self.mensaje = mensaje


def normalizar(valor: Any) -> str:
    """Minúsculas, sin acentos y sin espacios sobrantes: para comparar etiquetas y claves."""
    texto = unicodedata.normalize("NFKD", str(valor).strip().casefold())
    return "".join(c for c in texto if not unicodedata.combining(c))
