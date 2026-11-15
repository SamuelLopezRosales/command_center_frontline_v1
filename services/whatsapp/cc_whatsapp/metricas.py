"""Métricas de las Lambdas en formato EMF de CloudWatch (design.md §4.2 a §4.4).

Solo llevan nombre y cantidad: nunca cuerpos, números ni identificadores (CC-REQ-162).
``CONTADORES`` permite comprobarlas en las pruebas.
"""

from __future__ import annotations

import json
import time
from collections import Counter

CONTADORES: Counter[str] = Counter()
ESPACIO = "CommandCenter/WhatsApp"


def metrica(nombre: str, cantidad: int = 1) -> None:
    CONTADORES[nombre] += cantidad
    print(  # noqa: T201 - la salida estándar de Lambda es el registro de CloudWatch
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": ESPACIO,
                            "Dimensions": [[]],
                            "Metrics": [{"Name": nombre, "Unit": "Count"}],
                        }
                    ],
                },
                nombre: cantidad,
            }
        )
    )
