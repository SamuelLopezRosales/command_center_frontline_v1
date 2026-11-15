"""Lector de la carga masiva (design.md §10.3; CC-REQ-038, 039).

Lee con ``openpyxl`` en modo de solo lectura y sin evaluar fórmulas: la columna ``_validacion``
de la plantilla del cliente se ignora y una fórmula escrita en otra celda llega como texto.
Un archivo con estructura ajena, de más de 5 MB, con más de 2,000 filas con datos o con un ZIP
que se expande de forma desmedida se rechaza sin procesar sus filas (``ArchivoInvalido``).

Las columnas se identifican por la hoja oculta ``_meta`` (código interno) y, si no existe, por las
claves técnicas de la fila 2. La fila ``EJEMPLO-*`` de la plantilla del cliente se omite.
"""

from __future__ import annotations

import warnings
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
from typing import Any

from cc_colaboradores.excel.modelo import (
    CLAVES_FIJAS,
    COLUMNA_IGNORADA,
    FILA_CLAVES,
    HOJA_COLABORADORES,
    HOJA_META,
    MAX_BYTES,
    MAX_FILAS,
    PREFIJO_EJEMPLO,
    PRIMERA_FILA_DATOS,
    VERSION_EXTERNA,
    ArchivoInvalido,
)

MAX_DESCOMPRIMIDO = 80 * 1024 * 1024
MAX_FILAS_EXAMINADAS = MAX_FILAS + 3000  # tolera filas vacías con formato al final de la hoja
MAX_COLUMNAS = 120


@dataclass(frozen=True)
class FilaCruda:
    numero_fila: int  # número de fila en Excel
    valores: dict[str, Any]  # {código de columna: valor}; sin celdas vacías


@dataclass
class Archivo:
    version: str
    columnas: list[str]  # códigos de columna, en orden
    filas: list[FilaCruda] = field(default_factory=list)


def _invalido(motivo: str, mensaje: str) -> ArchivoInvalido:
    return ArchivoInvalido(motivo, mensaje)


def _limpiar(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, bool | int | float | datetime | date):
        return v
    return str(v).strip() or None


def _revisar_zip(contenido: bytes) -> None:
    try:
        with zipfile.ZipFile(BytesIO(contenido)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_DESCOMPRIMIDO:
                raise _invalido("ARCHIVO_DEMASIADO_GRANDE", "El archivo es demasiado grande.")
    except zipfile.BadZipFile:
        raise _invalido("NO_ES_XLSX", "El archivo no es un libro de Excel (.xlsx).") from None


def _mapa_columnas(wb, hoja) -> tuple[dict[int, str], str]:
    """``{índice de columna (0-based): código}`` y versión de la plantilla."""
    if HOJA_META in wb.sheetnames:
        filas = list(wb[HOJA_META].iter_rows(values_only=True, max_row=MAX_COLUMNAS + 5))
        if not filas or filas[0][0] != "version" or not filas[0][1]:
            raise _invalido(
                "META_INVALIDA", "La hoja de configuración de la plantilla no es válida."
            )
        mapa: dict[int, str] = {}
        for fila in filas[2:]:
            if fila and fila[0] is not None and fila[1]:
                try:
                    indice = int(fila[0]) - 1
                except (TypeError, ValueError):
                    raise _invalido(
                        "META_INVALIDA", "La hoja de configuración no es válida."
                    ) from None
                if indice < 0 or indice >= MAX_COLUMNAS:
                    raise _invalido("META_INVALIDA", "La hoja de configuración no es válida.")
                codigo = str(fila[1]).strip()
                mapa[indice] = (
                    codigo.upper() if codigo.upper().startswith("CAMP-") else codigo.lower()
                )
        return mapa, str(filas[0][1]).strip()[:30]
    claves = next(hoja.iter_rows(min_row=FILA_CLAVES, max_row=FILA_CLAVES, values_only=True), ())
    mapa = {}
    for i, valor in enumerate(claves[:MAX_COLUMNAS]):
        if isinstance(valor, str) and valor.strip():
            mapa[i] = valor.strip().lower()
    return mapa, VERSION_EXTERNA


def leer(contenido: bytes) -> Archivo:
    if len(contenido) > MAX_BYTES:
        raise _invalido("ARCHIVO_DEMASIADO_GRANDE", "El archivo pesa más de 5 MB.")
    if not contenido.startswith(b"PK"):
        raise _invalido("NO_ES_XLSX", "El archivo no es un libro de Excel (.xlsx).")
    _revisar_zip(contenido)
    from openpyxl import load_workbook

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = load_workbook(BytesIO(contenido), read_only=True, data_only=False)
    except Exception:  # noqa: BLE001 - cualquier fallo de lectura es un archivo ajeno
        raise _invalido("NO_ES_XLSX", "El archivo no es un libro de Excel (.xlsx).") from None
    try:
        if HOJA_COLABORADORES not in wb.sheetnames:
            raise _invalido("SIN_HOJA_COLABORADORES", "Falta la hoja Colaboradores.")
        hoja = wb[HOJA_COLABORADORES]
        hoja.reset_dimensions()
        mapa, version = _mapa_columnas(wb, hoja)
        codigos = list(mapa.values())
        if len(set(codigos)) != len(codigos):
            raise _invalido("COLUMNAS_REPETIDAS", "Hay columnas repetidas en la plantilla.")
        faltan = [c for c in CLAVES_FIJAS if c not in codigos]
        if faltan:
            raise _invalido(
                "ESTRUCTURA_AJENA", f"Faltan columnas de la plantilla: {', '.join(faltan)}."
            )
        archivo = Archivo(version=version, columnas=codigos)
        activas = {i: c for i, c in mapa.items() if c != COLUMNA_IGNORADA}
        examinadas = 0
        for numero, fila in enumerate(
            hoja.iter_rows(min_row=PRIMERA_FILA_DATOS, values_only=True), start=PRIMERA_FILA_DATOS
        ):
            examinadas += 1
            if examinadas > MAX_FILAS_EXAMINADAS:
                raise _invalido("DEMASIADAS_FILAS", "El archivo tiene demasiadas filas.")
            valores = {}
            for i, codigo in activas.items():
                v = _limpiar(fila[i]) if i < len(fila) else None
                if v is not None:
                    valores[codigo] = v
            if not valores:
                continue
            numero_empleado = valores.get("numero_empleado")
            if isinstance(numero_empleado, str) and numero_empleado.upper().startswith(
                PREFIJO_EJEMPLO
            ):
                continue
            if len(archivo.filas) >= MAX_FILAS:
                raise _invalido(
                    "DEMASIADAS_FILAS",
                    f"El archivo tiene más de {MAX_FILAS:,} filas; divídalo en varios.",
                )
            archivo.filas.append(FilaCruda(numero, valores))
        return archivo
    finally:
        wb.close()
