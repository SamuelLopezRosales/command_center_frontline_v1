"""Datos ficticios de demostración: 10 colaboradores y 3 organizaciones en la plantilla de carga.

Toma la plantilla real del cliente (carpeta ``plantilla_carga`` de
``kiro_command_center_frontline_v1``), la copia y escribe los datos EDITANDO EL XML del libro, no
con ``openpyxl``: la hoja Colaboradores trae listas desplegables en formato extendido (x14) que
``openpyxl`` borraría al guardar.

Todo es ficticio. Los RFC, CURP, NSS y números de celular cumplen el formato que exige el sistema
pero no corresponden a personas reales; no los use fuera de un ambiente de pruebas.

    uv run python scripts/datos_demo.py            # escribe en docs/datos_demo/
    uv run python scripts/datos_demo.py --salida otra/carpeta
"""

from __future__ import annotations

import argparse
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLA = next(
    (RAIZ / "kiro_command_center_frontline_v1" / "plantilla_carga").glob("*.xlsx"), None
)
SALIDA = RAIZ / "docs" / "datos_demo"
NOMBRE_XLSX = "Plantilla_Carga_Colaboradores_DEMO.xlsx"
NOMBRE_GUIA = "alta_previa_en_la_aplicacion.md"

PRIMERA_FILA = 3  # las filas 1 y 2 son encabezados y nombres técnicos
HOJA_COLABORADORES = "xl/worksheets/sheet2.xml"
HOJA_ORGANIZACIONES = "xl/worksheets/sheet3.xml"
EPOCA_EXCEL = date(1899, 12, 30)

# Estilos de celda de la plantilla: texto, fecha y número de las filas de captura.
S_TEXTO, S_FECHA, S_NUMERO = 19, 20, 21
S_TEXTO_ORG = 23


@dataclass(frozen=True)
class Organizacion:
    clave: str
    razon_social: str
    rfc: str
    registro_patronal: str
    domicilio: str
    firmante: str
    cargo: str


ORGANIZACIONES = (
    Organizacion(
        "ORG01",
        "Industrias Norte Demo, S.A. de C.V.",
        "INO190101AB1",
        "B5612345678",
        "Av. Industria 1200, Parque Industrial Apodaca, Apodaca, N.L.",
        "Lic. Andrea Villarreal Cantú",
        "Gerente de Recursos Humanos",
    ),
    Organizacion(
        "ORG02",
        "Servicios Logísticos Demo, S.A. de C.V.",
        "SLD200315QR4",
        "C7823456789",
        "Blvd. Los Fundadores 450, Col. Industrial, Saltillo, Coah.",
        "Lic. Ricardo Esquivel Moreno",
        "Director de Administración",
    ),
    Organizacion(
        "ORG03",
        "Comercializadora Demo del Golfo, S.A. de C.V.",
        "CDG180720MN8",
        "D9034567890",
        "Av. Constitución 800, Col. Centro, Monterrey, N.L.",
        "Lic. Gabriela Montemayor Ríos",
        "Gerente de Capital Humano",
    ),
)

PLANTAS = ("Planta Apodaca", "Planta Saltillo", "Oficinas Centrales")

# Opciones de las listas que la persona debe dar de alta en «Configurar campos» antes de cargar.
OPCIONES = {
    "Área": ("Producción", "Calidad", "Logística", "Administración", "Ventas"),
    "Departamento": (
        "Línea 1",
        "Línea 2",
        "Laboratorio",
        "Recursos Humanos",
        "Almacén",
        "Transporte",
        "Finanzas",
        "Comercial",
        "Atención a clientes",
    ),
    "Turno": ("Matutino", "Vespertino", "Nocturno"),
}


@dataclass(frozen=True)
class Colaborador:
    numero: str
    nombres: str
    paterno: str
    materno: str
    organizacion: str
    ingreso: date
    puesto: str
    tipo: str
    planta: str
    area: str
    departamento: str
    turno: str
    estatus: str
    sueldo: int
    periodicidad: str
    nacimiento: date
    sexo: str  # H o M
    estado: str  # clave de entidad de nacimiento para la CURP


COLABORADORES = (
    Colaborador(
        "E-2001",
        "Carlos Alberto",
        "Hernández",
        "Lozano",
        "ORG01",
        date(2021, 3, 15),
        "Operador de producción",
        "Operativo",
        "Planta Apodaca",
        "Producción",
        "Línea 1",
        "Matutino",
        "ACTIVO",
        9500,
        "Quincenal",
        date(1992, 5, 14),
        "H",
        "NL",
    ),  # fmt: skip
    Colaborador(
        "E-2002",
        "María Fernanda",
        "García",
        "Treviño",
        "ORG01",
        date(2020, 8, 3),
        "Analista de calidad",
        "Administrativo",
        "Planta Apodaca",
        "Calidad",
        "Laboratorio",
        "Matutino",
        "ACTIVO",
        14500,
        "Quincenal",
        date(1991, 11, 2),
        "M",
        "NL",
    ),  # fmt: skip
    Colaborador(
        "E-2003",
        "José Luis",
        "Martínez",
        "Salinas",
        "ORG01",
        date(2019, 11, 18),
        "Técnico de mantenimiento",
        "Operativo",
        "Planta Apodaca",
        "Producción",
        "Línea 2",
        "Vespertino",
        "ACTIVO",
        11800,
        "Quincenal",
        date(1988, 2, 27),
        "H",
        "CL",
    ),  # fmt: skip
    Colaborador(
        "E-2004",
        "Laura Patricia",
        "Sánchez",
        "Cavazos",
        "ORG01",
        date(2018, 5, 21),
        "Coordinadora de Recursos Humanos",
        "Administrativo",
        "Oficinas Centrales",
        "Administración",
        "Recursos Humanos",
        "Matutino",
        "ACTIVO",
        22000,
        "Mensual",
        date(1985, 9, 9),
        "M",
        "NL",
    ),  # fmt: skip
    Colaborador(
        "E-2005",
        "Miguel Ángel",
        "Ramírez",
        "Garza",
        "ORG01",
        date(2023, 1, 9),
        "Operador de producción",
        "Operativo",
        "Planta Apodaca",
        "Producción",
        "Línea 2",
        "Nocturno",
        "BAJA",
        3200,
        "Semanal",
        date(1996, 7, 30),
        "H",
        "NL",
    ),  # fmt: skip
    Colaborador(
        "E-2006",
        "Patricia Elena",
        "Flores",
        "Villarreal",
        "ORG02",
        date(2022, 6, 27),
        "Auxiliar de almacén",
        "Operativo",
        "Planta Saltillo",
        "Logística",
        "Almacén",
        "Matutino",
        "ACTIVO",
        8700,
        "Quincenal",
        date(1994, 1, 19),
        "M",
        "CL",
    ),  # fmt: skip
    Colaborador(
        "E-2007",
        "Roberto Carlos",
        "Morales",
        "Cantú",
        "ORG02",
        date(2021, 10, 4),
        "Operador de montacargas",
        "Operativo",
        "Planta Saltillo",
        "Logística",
        "Transporte",
        "Vespertino",
        "ACTIVO",
        9100,
        "Quincenal",
        date(1990, 12, 5),
        "H",
        "CL",
    ),  # fmt: skip
    Colaborador(
        "E-2008",
        "Fernanda Itzel",
        "Ortega",
        "Núñez",
        "ORG02",
        date(2017, 2, 13),
        "Contadora general",
        "Administrativo",
        "Oficinas Centrales",
        "Administración",
        "Finanzas",
        "Matutino",
        "ACTIVO",
        26500,
        "Mensual",
        date(1987, 4, 23),
        "M",
        "NL",
    ),  # fmt: skip
    Colaborador(
        "E-2009",
        "Daniel Alejandro",
        "Reyes",
        "Guerra",
        "ORG03",
        date(2024, 4, 15),
        "Ejecutivo de ventas",
        "Administrativo",
        "Oficinas Centrales",
        "Ventas",
        "Comercial",
        "Matutino",
        "ACTIVO",
        18000,
        "Quincenal",
        date(1993, 8, 11),
        "H",
        "NL",
    ),  # fmt: skip
    Colaborador(
        "E-2010",
        "Ana Sofía",
        "Treviño",
        "Domínguez",
        "ORG03",
        date(2025, 2, 3),
        "Asesora de atención a clientes",
        "Administrativo",
        "Oficinas Centrales",
        "Ventas",
        "Atención a clientes",
        "Vespertino",
        "ACTIVO",
        13500,
        "Quincenal",
        date(1998, 3, 8),
        "M",
        "NL",
    ),  # fmt: skip
)

_ACENTOS = str.maketrans("ÁÉÍÓÚÜáéíóúü", "AEIOUUaeiouu")
_VOCALES = "AEIOU"


def _limpio(texto: str) -> str:
    return re.sub(r"[^A-Z]", "", texto.translate(_ACENTOS).upper())


def _primera_vocal_interna(palabra: str) -> str:
    return next((c for c in palabra[1:] if c in _VOCALES), "X")


def _consonante_interna(palabra: str) -> str:
    return next((c for c in palabra[1:] if c not in _VOCALES), "X")


def rfc_ficticio(c: Colaborador) -> str:
    p, m, n = _limpio(c.paterno), _limpio(c.materno), _limpio(c.nombres.split()[0])
    base = f"{p[0]}{_primera_vocal_interna(p)}{m[0]}{n[0]}{c.nacimiento:%y%m%d}"
    return f"{base}{_consecutivo(c):02d}1"


def curp_ficticia(c: Colaborador) -> str:
    p, m, n = _limpio(c.paterno), _limpio(c.materno), _limpio(c.nombres.split()[0])
    base = f"{p[0]}{_primera_vocal_interna(p)}{m[0]}{n[0]}{c.nacimiento:%y%m%d}"
    consonantes = f"{_consonante_interna(p)}{_consonante_interna(m)}{_consonante_interna(n)}"
    return f"{base}{c.sexo}{c.estado}{consonantes}A{_consecutivo(c) % 10}"


def _consecutivo(c: Colaborador) -> int:
    """1 a 10, a partir de «E-2001» a «E-2010»."""
    return int(c.numero.split("-")[1]) - 2000


def nss_ficticio(c: Colaborador) -> str:
    n = _consecutivo(c)
    return f"42{n:02d}{c.ingreso:%y}{n * 7919 % 100000:05d}"


def celular_ficticio(c: Colaborador) -> str:
    return f"81555{_consecutivo(c):05d}"


def correo_ficticio(c: Colaborador) -> str:
    n = _limpio(c.nombres.split()[0]).lower()
    return f"{n}.{_limpio(c.paterno).lower()}@demo.example"


def _registro_patronal(c: Colaborador) -> str:
    return next(o.registro_patronal for o in ORGANIZACIONES if o.clave == c.organizacion)


# ------------------------------------------------------------------ edición del XML


def _texto(ref: str, estilo: int, valor: str | None) -> str:
    if valor is None or valor == "":
        return f'<c r="{ref}" s="{estilo}"/>'
    return f'<c r="{ref}" s="{estilo}" t="inlineStr"><is><t>{escape(valor)}</t></is></c>'


def _numero(ref: str, estilo: int, valor: int) -> str:
    return f'<c r="{ref}" s="{estilo}"><v>{valor}</v></c>'


def _serie(d: date) -> int:
    return (d - EPOCA_EXCEL).days


def _celdas_colaborador(fila: int, c: Colaborador) -> str:
    """Las 22 columnas de captura (A a V) en el orden de la plantilla v1.3."""
    t = lambda col, v: _texto(f"{col}{fila}", S_TEXTO, v)  # noqa: E731
    return "".join(
        [
            t("A", c.numero),
            t("B", c.nombres),
            t("C", c.paterno),
            t("D", c.materno),
            t("E", celular_ficticio(c)),
            t("F", c.organizacion),
            _numero(f"G{fila}", S_FECHA, _serie(c.ingreso)),
            t("H", c.puesto),
            t("I", c.tipo),
            t("J", c.planta),
            t("K", c.area),
            t("L", c.departamento),
            t("M", c.turno),
            t("N", None),  # ruta de transporte: el campo viene desactivado
            t("O", c.estatus),
            _numero(f"P{fila}", S_NUMERO, c.sueldo),
            t("Q", c.periodicidad),
            t("R", _registro_patronal(c)),
            t("S", nss_ficticio(c)),
            t("T", rfc_ficticio(c)),
            t("U", curp_ficticia(c)),
            t("V", correo_ficticio(c)),
        ]
    )


def _reemplazar_fila(xml: str, fila: int, celdas: str, *, conservar_columna: str | None) -> str:
    patron = re.compile(rf'(<row r="{fila}"[^>]*>)(.*?)(</row>)', re.DOTALL)
    m = patron.search(xml)
    if m is None:
        raise ValueError(f"La plantilla no tiene la fila {fila}")
    resto = ""
    if conservar_columna:
        # La columna de validación (W) lleva una fórmula: se conserva y se actualiza su valor.
        ref = f'<c r="{conservar_columna}{fila}"'
        # En la plantilla del cliente alguna celda de validación viene vacía (sin fórmula): se
        # conserva tal cual.
        w = re.search(rf"{ref}[^>]*?/>|{ref}.*?</c>", m.group(2), re.DOTALL)
        if w is not None:
            resto = re.sub(r"<v\s*/>|<v>.*?</v>", "<v>OK</v>", w.group(0), count=1)
    return xml[: m.start()] + m.group(1) + celdas + resto + m.group(3) + xml[m.end() :]


def _hoja_colaboradores(xml: str) -> str:
    # Sin datos de ejemplo: las 10 filas reemplazan al «EJEMPLO-001».
    for i, c in enumerate(COLABORADORES):
        fila = PRIMERA_FILA + i
        xml = _reemplazar_fila(xml, fila, _celdas_colaborador(fila, c), conservar_columna="W")
    return xml


def _hoja_organizaciones(xml: str) -> str:
    for i, o in enumerate(ORGANIZACIONES):
        fila = PRIMERA_FILA + i
        valores = (
            o.clave,
            o.razon_social,
            o.rfc,
            o.registro_patronal,
            o.domicilio,
            o.firmante,
            o.cargo,
        )
        celdas = "".join(
            _texto(f"{col}{fila}", S_TEXTO_ORG, v)
            for col, v in zip("ABCDEFG", valores, strict=True)
        )
        xml = _reemplazar_fila(xml, fila, celdas, conservar_columna=None)
    return xml


def generar_xlsx(plantilla: Path, destino: Path) -> Path:
    cambios = {
        HOJA_COLABORADORES: _hoja_colaboradores,
        HOJA_ORGANIZACIONES: _hoja_organizaciones,
    }
    destino.parent.mkdir(parents=True, exist_ok=True)
    with (
        zipfile.ZipFile(plantilla) as origen,
        zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as salida,
    ):
        for item in origen.infolist():
            datos = origen.read(item.filename)
            if item.filename in cambios:
                datos = cambios[item.filename](datos.decode("utf-8")).encode("utf-8")
            salida.writestr(item, datos)
    return destino


# ------------------------------------------------------------------ guía de alta previa


def guia_markdown() -> str:
    filas_org = "\n".join(
        f"| `{o.clave}` | {o.razon_social} | {o.rfc} | {o.registro_patronal} |"
        for o in ORGANIZACIONES
    )
    plantas = "\n".join(f"- {p}" for p in PLANTAS)
    opciones = "\n".join(f"- **{campo}**: {', '.join(vals)}" for campo, vals in OPCIONES.items())
    return f"""# Datos de demostración: qué dar de alta antes de cargar el Excel

Todo es **ficticio**. El Excel `{NOMBRE_XLSX}` trae 10 colaboradores y 3 organizaciones, pero la
carga masiva **no crea** organizaciones, plantas ni opciones de listas: las busca entre las que ya
existen. Si faltan, la fila se rechaza con `ORGANIZACION_NO_EXISTE`, `PLANTA_NO_EXISTE` o un error
de opción. Dé de alta primero esto, en la aplicación, en este orden:

## 1. Organizaciones (menú Colaboradores → Organizaciones)

| Clave | Razón social | RFC | Registro patronal |
|---|---|---|---|
{filas_org}

El domicilio fiscal y la persona que firma están en la hoja «Organizaciones» del Excel.

## 2. Plantas

{plantas}

## 3. Opciones de las listas (menú Colaboradores → Campos)

Las listas vienen **sin opciones**. En cada campo, agregue exactamente estas (con esa ortografía):

{opciones}

*Periodicidad del sueldo* ya trae sus opciones (Semanal, Catorcenal, Quincenal, Mensual).
*Ruta de transporte* viene desactivada y el Excel la deja vacía.

## 4. Cargar el archivo

Menú Colaboradores → Carga masiva → suba `{NOMBRE_XLSX}`, revise el resumen y confirme. Debe dar
**10 filas válidas**: 9 `ACTIVO` y 1 `BAJA` (el colaborador E-2005, para ver cómo se
trata una baja).

## Para probar WhatsApp

- Los celulares del archivo son ficticios (`81555xxxxx`): **no les envíe mensajes reales**.
- Los colaboradores cargados por Excel quedan **sin consentimiento de WhatsApp**. Para probar el
  bot o una notificación, edite uno y marque el consentimiento, y cambie su celular por uno suyo.
- Una notificación solo llega a quien está `ACTIVO`, con consentimiento vigente y celular válido.
"""


def generar(salida: Path = SALIDA, plantilla: Path | None = PLANTILLA) -> list[Path]:
    if plantilla is None or not plantilla.exists():
        raise FileNotFoundError(
            "No se encontró la plantilla en kiro_command_center_frontline_v1/plantilla_carga/"
        )
    xlsx = generar_xlsx(plantilla, salida / NOMBRE_XLSX)
    guia = salida / NOMBRE_GUIA
    guia.write_text(guia_markdown(), encoding="utf-8")
    return [xlsx, guia]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--salida", type=Path, default=SALIDA)
    args = p.parse_args(argv)
    for ruta in generar(args.salida):
        print(f"Escrito: {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
