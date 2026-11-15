"""Generador de la plantilla de carga (COL-16; design.md §10.3; CC-REQ-034).

La plantilla se arma con la configuración vigente de la empresa: los once campos fijos más los
campos dinámicos activos, en su orden. Hojas: Instrucciones, Colaboradores, Organizaciones,
Catálogos (oculta), Diccionario y ``_meta`` (oculta, con el código de cada columna).
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from cc_colaboradores.campos_cliente import DefinicionCampo
from cc_colaboradores.excel.modelo import (
    FIJOS,
    HOJA_CATALOGOS,
    HOJA_COLABORADORES,
    HOJA_DICCIONARIO,
    HOJA_INSTRUCCIONES,
    HOJA_META,
    HOJA_ORGANIZACIONES,
    MAX_FILAS,
    PRIMERA_FILA_DATOS,
    VERSION_PLANTILLA,
)

ULTIMA_FILA = PRIMERA_FILA_DATOS + MAX_FILAS - 1
MAX_CATALOGO = 500
ENCABEZADO = PatternFill("solid", fgColor="1F3A5F")
CLAVES = PatternFill("solid", fgColor="E8EEF5")
COLUMNAS_ORGANIZACION = (
    ("clave", "Clave *"),
    ("razon_social", "Razón social *"),
    ("rfc", "RFC"),
    ("registro_patronal", "Registro patronal"),
    ("domicilio_fiscal", "Domicilio fiscal"),
    ("nombre_firmante", "Nombre de quien firma constancias"),
    ("cargo_firmante", "Cargo de quien firma"),
)
CLAVES_ORGANIZACION = {
    "clave": "clave_organizacion",
}
TIPOS = {
    "TEXTO": "Texto",
    "NUMERO": "Número",
    "FECHA": "Fecha (dd/mm/aaaa)",
    "LISTA": "Lista de opciones",
    "SI_NO": "Sí o no",
}


def _encabezado(celda) -> None:
    celda.font = Font(bold=True, color="FFFFFF")
    celda.fill = ENCABEZADO
    celda.alignment = Alignment(wrap_text=True, vertical="center")


def _rango(columna: int, desde: int, hasta: int, hoja: str | None = None) -> str:
    letra = get_column_letter(columna)
    rango = f"${letra}${desde}:${letra}${hasta}"
    return f"'{hoja}'!{rango}" if hoja else rango


def generar(
    definiciones: Sequence[DefinicionCampo],
    organizaciones: Sequence[dict[str, Any]],
    plantas: Sequence[str],
) -> bytes:
    activas = sorted((d for d in definiciones if d.activo), key=lambda d: (d.orden, d.id))
    wb = Workbook()

    # ---- Instrucciones
    ws_i = wb.active
    ws_i.title = HOJA_INSTRUCCIONES
    instrucciones = [
        "Plantilla de carga de colaboradores",
        "",
        "1. Capture un colaborador por fila en la hoja Colaboradores, desde la fila 3.",
        "2. Las columnas con asterisco (*) son obligatorias. No cambie la fila 1 ni la fila 2.",
        "3. La carga crea a quien no existe y actualiza a quien ya existe, por número de empleado.",
        "   Quien no aparece en el archivo no se modifica ni se da de baja.",
        "4. Una celda vacía no borra el valor que el colaborador ya tiene.",
        "5. Las organizaciones deben existir (hoja Organizaciones); la carga no las crea.",
        "6. El consentimiento de WhatsApp no se captura aquí: se registra en la ficha.",
        f"7. Máximo {MAX_FILAS:,} filas por archivo y 5 MB. Divida archivos más grandes.",
        "8. El Diccionario explica cada columna. Al terminar, descargue el reporte de errores.",
        "",
        "Esta plantilla refleja los campos activos al descargarla. Si cambia la configuración de",
        "campos, descargue una plantilla nueva.",
    ]
    for i, linea in enumerate(instrucciones, start=1):
        ws_i.cell(row=i, column=1, value=linea)
    ws_i["A1"].font = Font(bold=True, size=14)
    ws_i.column_dimensions["A"].width = 100

    # ---- Colaboradores
    ws = wb.create_sheet(HOJA_COLABORADORES)
    columnas: list[tuple[str, str, str, DefinicionCampo | None]] = [
        (f.encabezado, f.clave, f.clave, None) for f in FIJOS
    ]
    for d in activas:
        encabezado = d.nombre_campo + (" *" if d.obligatorio else "")
        columnas.append((encabezado, d.clave, d.codigo_interno, d))
    for i, (encabezado, clave, _codigo, _d) in enumerate(columnas, start=1):
        c1, c2 = ws.cell(row=1, column=i, value=encabezado), ws.cell(row=2, column=i, value=clave)
        _encabezado(c1)
        c2.fill = CLAVES
        c2.font = Font(italic=True, color="555555")
        ws.column_dimensions[get_column_letter(i)].width = max(16, min(34, len(encabezado) + 2))
    ws.freeze_panes = ws.cell(row=PRIMERA_FILA_DATOS, column=1)
    ws.row_dimensions[1].height = 32

    # ---- Organizaciones (referencia)
    ws_o = wb.create_sheet(HOJA_ORGANIZACIONES)
    for i, (campo, encabezado) in enumerate(COLUMNAS_ORGANIZACION, start=1):
        _encabezado(ws_o.cell(row=1, column=i, value=encabezado))
        ws_o.cell(row=2, column=i, value=CLAVES_ORGANIZACION.get(campo, campo)).fill = CLAVES
        ws_o.column_dimensions[get_column_letter(i)].width = 26
    organizaciones_activas = [o for o in organizaciones if o.get("activa", True)]
    for r, o in enumerate(organizaciones_activas[:MAX_CATALOGO], start=PRIMERA_FILA_DATOS):
        for i, (campo, _) in enumerate(COLUMNAS_ORGANIZACION, start=1):
            ws_o.cell(row=r, column=i, value=o.get(campo))

    # ---- Catálogos (oculta): plantas y opciones de listas
    ws_c = wb.create_sheet(HOJA_CATALOGOS)
    ws_c.cell(row=1, column=1, value="Planta")
    for r, nombre in enumerate(plantas[:MAX_CATALOGO], start=2):
        ws_c.cell(row=r, column=1, value=nombre)
    rangos_lista: dict[int, str] = {}
    siguiente = 2
    for d in activas:
        if d.tipo_dato != "LISTA":
            continue
        ws_c.cell(row=1, column=siguiente, value=d.codigo_interno)
        opciones = sorted((o for o in d.opciones if o.activo), key=lambda o: (o.orden, o.id))
        for r, o in enumerate(opciones[:MAX_CATALOGO], start=2):
            ws_c.cell(row=r, column=siguiente, value=o.etiqueta)
        rangos_lista[d.id] = _rango(siguiente, 2, max(2, len(opciones) + 1), HOJA_CATALOGOS)
        siguiente += 1
    ws_c.sheet_state = "hidden"

    # ---- validaciones de la hoja Colaboradores
    def validacion(**kw) -> DataValidation:
        dv = DataValidation(allow_blank=True, showErrorMessage=True, **kw)
        ws.add_data_validation(dv)
        return dv

    posicion = {clave: i for i, (_, clave, _, _) in enumerate(columnas, start=1)}

    def aplicar(dv: DataValidation, columna: int) -> None:
        letra = get_column_letter(columna)
        dv.add(f"{letra}{PRIMERA_FILA_DATOS}:{letra}{ULTIMA_FILA}")

    aplicar(
        validacion(type="textLength", operator="equal", formula1="10"), posicion["celular_whatsapp"]
    )
    aplicar(
        validacion(type="date", operator="greaterThan", formula1="DATE(1950,1,1)"),
        posicion["fecha_ingreso"],
    )
    aplicar(
        validacion(type="list", formula1='"Administrativo,Operativo"'), posicion["tipo_empleado"]
    )
    aplicar(validacion(type="list", formula1='"ACTIVO,BAJA"'), posicion["estatus"])
    aplicar(
        validacion(type="list", formula1=f"{HOJA_ORGANIZACIONES}!$A$3:$A${MAX_CATALOGO + 2}"),
        posicion["organizacion"],
    )
    aplicar(
        validacion(type="list", formula1=_rango(1, 2, MAX_CATALOGO + 1, HOJA_CATALOGOS)),
        posicion["planta"],
    )
    for i, (_enc, _clave, _codigo, d) in enumerate(columnas, start=1):
        if d is None:
            continue
        if d.tipo_dato == "LISTA":
            aplicar(validacion(type="list", formula1=rangos_lista[d.id]), i)
        elif d.tipo_dato == "SI_NO":
            aplicar(validacion(type="list", formula1='"Sí,No"'), i)
        elif d.tipo_dato == "NUMERO":
            aplicar(
                validacion(
                    type="decimal",
                    operator="between",
                    formula1="-99999999999",
                    formula2="99999999999",
                ),
                i,
            )

    # ---- Diccionario
    ws_d = wb.create_sheet(HOJA_DICCIONARIO)
    for i, t in enumerate(("Columna", "Clave", "Tipo", "Obligatorio", "Sensible", "Detalle"), 1):
        _encabezado(ws_d.cell(row=1, column=i, value=t))
        ws_d.column_dimensions[get_column_letter(i)].width = 24 if i < 6 else 70
    detalles_fijos = {
        "numero_empleado": "Llave de la carga: si ya existe se actualiza; si no, se crea.",
        "celular_whatsapp": "10 dígitos, sin lada internacional ni signos.",
        "organizacion": "Clave de una organización existente (hoja Organizaciones).",
        "fecha_ingreso": "dd/mm/aaaa o fecha de Excel.",
        "tipo_empleado": "Administrativo u Operativo.",
        "planta": "Nombre de una planta existente.",
        "estatus": "ACTIVO o BAJA. BAJA da de baja al colaborador sin borrarlo.",
    }
    fila = 2
    for f in FIJOS:
        valores = (
            f.encabezado.replace(" *", ""),
            f.clave,
            "Fijo",
            "Sí",
            "No",
            detalles_fijos.get(f.clave, ""),
        )
        for i, v in enumerate(valores, start=1):
            ws_d.cell(row=fila, column=i, value=v)
        fila += 1
    for d in activas:
        detalle = []
        if d.formato_validacion:
            detalle.append("Debe cumplir el formato configurado.")
        if d.tipo_dato == "LISTA":
            detalle.append("Opciones: " + ", ".join(o.etiqueta for o in d.opciones if o.activo))
        valores = (
            d.nombre_campo,
            d.clave,
            TIPOS.get(d.tipo_dato, d.tipo_dato),
            "Sí" if d.obligatorio else "No",
            "Sí" if d.es_sensible else "No",
            " ".join(detalle),
        )
        for i, v in enumerate(valores, start=1):
            ws_d.cell(row=fila, column=i, value=v)
        fila += 1

    # ---- _meta (oculta): versión y código de cada columna
    ws_m = wb.create_sheet(HOJA_META)
    ws_m["A1"], ws_m["B1"] = "version", VERSION_PLANTILLA
    ws_m["A2"], ws_m["B2"] = "columna", "codigo"
    for i, (_enc, _clave, codigo, _d) in enumerate(columnas, start=1):
        ws_m.cell(row=i + 2, column=1, value=i)
        ws_m.cell(row=i + 2, column=2, value=codigo)
    ws_m.sheet_state = "hidden"

    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()
