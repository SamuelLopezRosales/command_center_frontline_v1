"""Catálogos estáticos del servicio campos (design.md §3.4; CC-REQ-049, 051).

- ``FIJOS``: los once campos fijos del colaborador, de solo lectura.
- ``RESERVADAS``: claves que un campo nuevo no puede usar porque ya son variables de plantilla.
- ``SUGERIDOS``: los once campos que se siembran al dar de alta una empresa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CLAVE_PATRON = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
FORMATO_MAXIMO = 200
TIPOS = ("TEXTO", "NUMERO", "FECHA", "LISTA", "SI_NO")
TIPOS_CON_FORMATO = frozenset({"TEXTO", "NUMERO"})
VALOR_OPCION = re.compile(r"^[A-Z0-9_]{1,40}$")


@dataclass(frozen=True)
class CampoFijo:
    clave: str
    nombre: str
    tipo_dato: str
    obligatorio: bool = True


FIJOS: tuple[CampoFijo, ...] = (
    CampoFijo("numero_empleado", "Número de empleado", "TEXTO"),
    CampoFijo("nombres", "Nombre(s)", "TEXTO"),
    CampoFijo("apellido_paterno", "Apellido paterno", "TEXTO"),
    CampoFijo("apellido_materno", "Apellido materno", "TEXTO"),
    CampoFijo("celular", "Celular con WhatsApp", "TEXTO"),
    CampoFijo("organizacion", "Organización", "LISTA"),
    CampoFijo("planta", "Planta o centro de trabajo", "LISTA"),
    CampoFijo("fecha_ingreso", "Fecha de ingreso", "FECHA"),
    CampoFijo("puesto", "Puesto", "TEXTO"),
    CampoFijo("tipo_empleado", "Tipo de empleado", "LISTA"),
    CampoFijo("estatus", "Estatus", "LISTA"),
)

# Variables de plantilla que ya existen (fijas, de organización, del sistema y derivadas), más los
# nombres de los campos fijos: una clave nueva no puede hacerse pasar por ninguna de ellas.
RESERVADAS = frozenset(
    {f.clave for f in FIJOS}
    | {
        "nombre_completo",
        "fecha_baja",
        "celular_whatsapp",
        "lugar",
        "horario",
        "empresa",
        "folio",
        "fecha_emision",
        "qr_verificacion",
        "sueldo_mensual",
        "sueldo_letra",
    }
)

# Sueldo mayor que cero con ``re2`` (sin lookahead): el valor llega como ``9500.0000``.
FORMATO_SUELDO = r"^(0*[1-9][0-9]*(\.[0-9]*)?|0*\.[0-9]*[1-9][0-9]*)$"
FORMATO_RFC = r"^[A-ZÑ&]{4}\d{6}[A-Z0-9]{3}$"
FORMATO_CURP = r"^[A-Z]{4}\d{6}[HMX][A-Z]{2}[B-DF-HJ-NP-TV-Z]{3}[A-Z0-9]\d$"
FORMATO_CORREO = r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$"


@dataclass(frozen=True)
class Sugerido:
    clave: str
    nombre: str
    tipo_dato: str
    es_sensible: bool = False
    activo: bool = True
    formato: str | None = None
    opciones: tuple[tuple[str, str], ...] = ()  # (etiqueta, valor)


SUGERIDOS: tuple[Sugerido, ...] = (
    Sugerido("area", "Área", "LISTA"),
    Sugerido("departamento", "Departamento", "LISTA"),
    Sugerido("turno", "Turno", "LISTA"),
    Sugerido("ruta_transporte", "Ruta de transporte", "TEXTO", activo=False),
    Sugerido("sueldo", "Sueldo (MXN)", "NUMERO", es_sensible=True, formato=FORMATO_SUELDO),
    Sugerido(
        "periodicidad_sueldo",
        "Periodicidad del sueldo",
        "LISTA",
        opciones=(
            ("Semanal", "SEMANAL"),
            ("Catorcenal", "CATORCENAL"),
            ("Quincenal", "QUINCENAL"),
            ("Mensual", "MENSUAL"),
        ),
    ),
    Sugerido("registro_patronal", "Registro patronal", "TEXTO", formato=r"^[A-Z0-9]{11}$"),
    Sugerido("nss", "NSS", "TEXTO", es_sensible=True, formato=r"^\d{11}$"),
    Sugerido("rfc", "RFC del colaborador", "TEXTO", es_sensible=True, formato=FORMATO_RFC),
    Sugerido("curp", "CURP", "TEXTO", es_sensible=True, formato=FORMATO_CURP),
    Sugerido("correo", "Correo electrónico", "TEXTO", formato=FORMATO_CORREO),
)
CLAVES_SUGERIDAS = frozenset(s.clave for s in SUGERIDOS)
