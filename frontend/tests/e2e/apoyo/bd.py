"""Apoyo de las pruebas E2E (T-134): lecturas de la base LOCAL para las capturas de pantalla.

  uv run python frontend/tests/e2e/apoyo/bd.py codigo-verificacion

Imprime una línea JSON con el código de verificación de una constancia real del stack local.
"""

from __future__ import annotations

import json

import psycopg

DB = dict(
    host="127.0.0.1",
    port=55432,
    dbname="command_center",
    user="cc_local",
    password="cc_local_solo_desarrollo",  # pragma: allowlist secret
)

with psycopg.connect(**DB) as con:
    fila = con.execute(
        "SELECT codigo_verificacion FROM constancias.constancia_generada ORDER BY id LIMIT 1"
    ).fetchone()
print(json.dumps({"codigo": fila[0] if fila else None}))
