"""Apoyo de las pruebas E2E (T-133): llena la plantilla de carga masiva descargada desde la SPA.

Uso: uv run python frontend/tests/e2e/apoyo/preparar_carga.py PLANTILLA.xlsx SALIDA.xlsx SUFIJO [N_FILAS] [N_ERRORES]

Estructura (services/colaboradores/cc_colaboradores/excel/modelo.py): hoja «Colaboradores», fila 1
encabezados, fila 2 claves técnicas, datos desde la fila 3. Los datos son ficticios.
Imprime en JSON los números de empleado generados.
"""

from __future__ import annotations

import json
import sys

from openpyxl import load_workbook

HOJA = "Colaboradores"
FILA_CLAVES = 2
PRIMERA_FILA = 3


def main(entrada: str, salida: str, sufijo: str, filas: int = 2, con_error: int = 0) -> None:
    libro = load_workbook(entrada)
    hoja = libro[HOJA]
    columnas = {
        str(c.value).strip(): c.column
        for c in hoja[FILA_CLAVES]
        if c.value is not None and str(c.value).strip()
    }
    for fila in range(PRIMERA_FILA, hoja.max_row + 1):  # quita los ejemplos de la plantilla
        for col in range(1, hoja.max_column + 1):
            hoja.cell(row=fila, column=col).value = None
    numeros = []
    base = int(sufijo, 36) % 10_000_000
    for i in range(filas):
        numero = f"CM-{sufijo}-{i + 1}"
        numeros.append(numero)
        celular = f"55{(base * 10 + i) % 100_000_000:08d}"
        valores = {
            "numero_empleado": numero,
            "nombres": f"Carga{i + 1}",
            "apellido_paterno": f"Masiva{sufijo}",
            "apellido_materno": "Ficticia",
            "celular_whatsapp": "123" if i >= filas - con_error else celular,
            "organizacion": "MATRIZ",
            "fecha_ingreso": "03/02/2025",
            "puesto": "Operador de pruebas",
            "tipo_empleado": "OPERATIVO",
            "planta": "Planta Monterrey",
            "estatus": "ACTIVO",
        }
        for clave, valor in valores.items():
            if clave in columnas:
                hoja.cell(row=PRIMERA_FILA + i, column=columnas[clave]).value = valor
    libro.save(salida)
    print(json.dumps({"numeros": numeros, "columnas": sorted(columnas)}))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], a[2], int(a[3]) if len(a) > 3 else 2, int(a[4]) if len(a) > 4 else 0)
