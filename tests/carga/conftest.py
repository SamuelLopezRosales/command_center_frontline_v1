"""Pruebas de carga locales (T-142): rutas a los ayudantes de los servicios.

Las pruebas de este directorio llevan el marcador ``carga`` y no entran en la corrida normal
(``addopts`` excluye ``carga``). Se corren con::

    uv run pytest tests/carga -m carga -s -p no:cacheprovider

``-s`` muestra las líneas ``[T-142] ...`` con los números medidos. Reutilizan los ayudantes y las
fixtures de cada servicio (Testcontainers y LocalStack) sin copiarlos: se agregan al final de
``sys.path`` los directorios de pruebas de los servicios.
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
for ruta in (
    "services/colaboradores/tests",
    "services/constancias/tests",
    "services/dashboard/tests",
    "services/whatsapp/tests",
):
    if str(RAIZ / ruta) not in sys.path:
        sys.path.append(str(RAIZ / ruta))
