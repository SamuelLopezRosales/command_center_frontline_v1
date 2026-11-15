"""Ayudantes de las pruebas de la carga masiva: libros de Excel y definiciones de campos."""

from io import BytesIO

from cc_colaboradores.campos_cliente import DefinicionCampo, OpcionCampo
from cc_colaboradores.excel import generador
from cc_colaboradores.excel.modelo import CLAVES_FIJAS
from openpyxl import Workbook, load_workbook

FIJAS = list(CLAVES_FIJAS)


def definiciones_basicas() -> list[DefinicionCampo]:
    """nss (sensible, 11 dígitos), área (lista), sueldo y periodicidad, fecha de antigüedad."""
    return [
        DefinicionCampo(
            101,
            "NSS",
            "nss",
            "CAMP-0001",
            "TEXTO",
            es_sensible=True,
            formato_validacion=r"\d{11}",
            orden=1,
        ),
        DefinicionCampo(
            102,
            "Área",
            "area",
            "CAMP-0002",
            "LISTA",
            orden=2,
            opciones=(
                OpcionCampo(201, "Producción", "PRODUCCION", orden=1),
                OpcionCampo(202, "Ventas", "VENTAS", orden=2),
                OpcionCampo(203, "Vieja", "VIEJA", activo=False, orden=3),
            ),
        ),
        DefinicionCampo(
            103, "Sueldo (MXN)", "sueldo", "CAMP-0003", "NUMERO", es_sensible=True, orden=3
        ),
        DefinicionCampo(
            104,
            "Periodicidad del sueldo",
            "periodicidad_sueldo",
            "CAMP-0004",
            "LISTA",
            orden=4,
            opciones=(
                OpcionCampo(211, "Semanal", "SEMANAL", orden=1),
                OpcionCampo(212, "Quincenal", "QUINCENAL", orden=2),
            ),
        ),
        DefinicionCampo(105, "Antigüedad", "antiguedad", "CAMP-0005", "FECHA", orden=5),
    ]


def fila_valida(n: int = 1, **cambios) -> dict:
    """Valores por clave técnica de una fila completa y válida."""
    base = {
        "numero_empleado": f"E-{n:04d}",
        "nombres": "María",
        "apellido_paterno": "Ramírez",
        "apellido_materno": "Ortiz",
        "celular_whatsapp": f"81{n:08d}",
        "organizacion": "ORG1",
        "fecha_ingreso": "15/03/2021",
        "puesto": "Operadora",
        "tipo_empleado": "Operativo",
        "planta": "Norte",
        "estatus": "ACTIVO",
    }
    base.update(cambios)
    return {k: v for k, v in base.items() if v is not None}


def libro(
    filas: list[dict], claves: list[str] | None = None, meta: list[str] | None = None
) -> bytes:
    """Libro mínimo: encabezados en la fila 1, claves en la fila 2 y datos desde la fila 3.

    ``meta`` agrega la hoja oculta ``_meta`` con el código de cada columna."""
    claves = claves or sorted({k for f in filas for k in f}, key=lambda k: (k not in FIJAS, k))
    wb = Workbook()
    ws = wb.active
    ws.title = "Colaboradores"
    for i, k in enumerate(claves, start=1):
        ws.cell(row=1, column=i, value=k.upper())
        ws.cell(row=2, column=i, value=k)
    for r, f in enumerate(filas, start=3):
        for i, k in enumerate(claves, start=1):
            if k in f:
                ws.cell(row=r, column=i, value=f[k])
    if meta is not None:
        m = wb.create_sheet("_meta")
        m["A1"], m["B1"] = "version", "CC-2.0"
        for i, codigo in enumerate(meta, start=1):
            m.cell(row=i + 2, column=1, value=i)
            m.cell(row=i + 2, column=2, value=codigo)
        m.sheet_state = "hidden"
    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()


def plantilla_llena(
    definiciones: list[DefinicionCampo], filas: list[dict], organizaciones=(), plantas=()
) -> bytes:
    """Plantilla generada por el sistema con ``filas`` capturadas (por clave de la fila 2 o por
    código interno de campo)."""
    base = generador.generar(definiciones, list(organizaciones), list(plantas))
    wb = load_workbook(BytesIO(base))
    ws = wb["Colaboradores"]
    meta = {int(r[0]): r[1] for r in wb["_meta"].iter_rows(min_row=3, values_only=True) if r[0]}
    columna_de = {codigo: i for i, codigo in meta.items()}
    por_clave = {ws.cell(row=2, column=i).value: i for i in range(1, ws.max_column + 1)}
    for r, f in enumerate(filas, start=3):
        for k, v in f.items():
            ws.cell(row=r, column=columna_de.get(k) or por_clave[k], value=v)
    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()
