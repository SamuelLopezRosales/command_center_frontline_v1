"""Exporta los esquemas JSON de los mensajes y documentos a ``contracts/mensajes/``.

Hoy: ``contenido_plantilla.schema.json`` (contenido de las plantillas de constancia, design.md
§5.1). Lo usan el editor de la SPA y las pruebas de contrato.

Uso: ``uv run python scripts/exportar_esquemas.py [--verificar]``. La salida es determinista; con
``--verificar`` no escribe y falla si el archivo del repositorio no coincide.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "contracts" / "mensajes"


def esquemas() -> dict[str, str]:
    sys.path[:0] = [str(RAIZ / "services" / "shared"), str(RAIZ / "services" / "constancias")]
    from cc_constancias.contenido import ESQUEMA_VERSION, ContenidoPlantilla

    contenido = ContenidoPlantilla.model_json_schema()
    contenido["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    contenido["$id"] = "contenido_plantilla.schema.json"
    contenido["title"] = f"Contenido de plantilla de constancia (esquema {ESQUEMA_VERSION})"
    return {
        "contenido_plantilla.schema.json": json.dumps(
            contenido, ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n"
    }


def main(argv: list[str]) -> int:
    generados = esquemas()
    if "--verificar" in argv:
        desactualizados = [
            nombre
            for nombre, contenido in generados.items()
            if not (DESTINO / nombre).exists()
            or (DESTINO / nombre).read_text(encoding="utf-8") != contenido
        ]
        for nombre in desactualizados:
            print(
                f"El esquema {nombre} no está al día: ejecute exportar_esquemas.py", file=sys.stderr
            )
        return 1 if desactualizados else 0
    DESTINO.mkdir(parents=True, exist_ok=True)
    for nombre, contenido in generados.items():
        (DESTINO / nombre).write_text(contenido, encoding="utf-8", newline="\n")
        print(f"Escrito {(DESTINO / nombre).relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
