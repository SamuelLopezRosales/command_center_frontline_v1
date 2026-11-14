"""Exporta el OpenAPI de un servicio a ``contracts/openapi/<servicio>.json`` (design.md §3.1).

Uso: ``uv run python scripts/exportar_openapi.py dashboard [--verificar]``.
La salida es determinista (claves ordenadas). Con ``--verificar`` no escribe: falla si el
archivo del repositorio no coincide (para CI y las pruebas de contrato).
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONTRATOS = RAIZ / "contracts" / "openapi"


def generar(servicio: str) -> str:
    sys.path[:0] = [str(RAIZ / "services" / "shared"), str(RAIZ / "services" / servicio)]
    modulo = importlib.import_module(f"cc_{servicio}.main")
    app = modulo.crear_app(motor=object(), verificador=object())
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Uso: exportar_openapi.py <servicio> [--verificar]", file=sys.stderr)
        return 2
    servicio = argv[1]
    contenido = generar(servicio)
    destino = CONTRATOS / f"{servicio}.json"
    if "--verificar" in argv:
        actual = destino.read_text(encoding="utf-8") if destino.exists() else ""
        if actual != contenido:
            aviso = f"El contrato {destino.name} no está al día: ejecute exportar_openapi.py"
            print(f"{aviso} {servicio}", file=sys.stderr)
            return 1
        return 0
    CONTRATOS.mkdir(parents=True, exist_ok=True)
    destino.write_text(contenido, encoding="utf-8")
    print(f"Escrito {destino.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
