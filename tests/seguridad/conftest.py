"""Pruebas de seguridad (T-143, design.md §16.1 nivel S): fixtures y rutas a los ayudantes.

Reutilizan los ayudantes de ``tests/e2e`` (``Mundo``, ``MundoNotificaciones``) y de los servicios sin
copiarlos: se agregan al final de ``sys.path`` los directorios de pruebas. El ``mundo_seg`` es el
mundo de las notificaciones (las dos empresas, los seis servicios como apps ASGI reales, bot,
Lambdas y LocalStack); el marcador ``docker`` lo omite si Docker no está disponible.

Comando: ``uv run pytest tests/seguridad -q -p no:cacheprovider``
"""

import logging
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
for ruta in (
    "tests/seguridad",
    "tests/e2e",
    "services/constancias/tests",
    "services/whatsapp/tests",
    "services/colaboradores/tests",
):
    if str(RAIZ / ruta) not in sys.path:
        sys.path.append(str(RAIZ / ruta))


class CognitoFalso:
    """Registra las desactivaciones: una llamada rechazada por empresa no debe llegar aquí."""

    def __init__(self) -> None:
        self.deshabilitados: list[str] = []

    async def deshabilitar_y_cerrar_sesiones(self, sub: str) -> None:
        self.deshabilitados.append(sub)


@pytest.fixture
async def mundo_seg(bd_migrada, localstack, caplog):
    """Empresas A y B con los seis servicios, el bot y las Lambdas; cliente HTTP de ``campos``."""
    import httpx
    from ayudantes_e2e_notif import cerrar_mundo_notificaciones, construir_mundo_notificaciones

    # Igual que tests/e2e/conftest.py: INFO para todo; httpx en WARNING (registraría las URL que la
    # propia prueba visita, con el token del enlace).
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.WARNING, logger="httpx")
    w = await construir_mundo_notificaciones(bd_migrada, localstack)
    w.http_campos = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=w.app_campos), base_url="http://campos"
    )
    # El mundo siembra CAMP-0001 y CAMP-0002 con SQL: el contador de `campos` se adelanta para que
    # la API de campos pueda crear los suyos sin chocar con los códigos sembrados.
    for empresa in (w.a, w.b):
        w.sql(
            "INSERT INTO campos.contador_campo (empresa_id, ultimo) VALUES (%s, 100) "
            "ON CONFLICT (empresa_id) DO UPDATE SET ultimo = 100",
            (empresa.id,),
        )
    w.http_dash._transport.app.state.cognito = CognitoFalso()  # DSH-09 llamaría a AWS
    yield w
    await w.http_campos.aclose()
    await cerrar_mundo_notificaciones(w)
