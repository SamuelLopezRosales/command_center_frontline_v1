"""Puntos de entrada del stack local para lo que los servicios no resuelven por sí solos.

- ``app_dashboard``: el servicio dashboard con un Cognito de mentira (en AWS desactivar un usuario
  llama a Cognito; en local solo se registra). Se inyecta por el parámetro ``cognito`` de
  ``crear_app``: el código del servicio no cambia.
- ``worker-cargas`` y ``worker-whatsapp``: los workers instalan un manejador de SIGTERM con
  ``loop.add_signal_handler``, que Windows no soporta. Aquí se neutraliza antes de arrancar; el
  stack los detiene con ``taskkill``.

    python -m scripts.local.lanzadores worker-cargas
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

log = logging.getLogger("cc.local")


def _solo_local() -> None:
    if os.environ.get("CC_AMBIENTE") != "local":
        raise RuntimeError("Este lanzador solo corre con CC_AMBIENTE=local.")


class CognitoLocal:
    """Sustituto de Cognito para desarrollo: acepta y registra, no hay nada que cerrar."""

    async def deshabilitar_y_cerrar_sesiones(self, username: str) -> None:
        log.info("Cognito local: se omite deshabilitar a %s", username)


def app_dashboard():
    _solo_local()
    from cc_dashboard.main import crear_app

    return crear_app(cognito=CognitoLocal())


def _sin_senales_de_unix() -> None:
    if sys.platform == "win32":
        asyncio.AbstractEventLoop.add_signal_handler = lambda self, *a, **k: None  # type: ignore[method-assign]  # noqa: ARG005


COMANDOS = ("worker-cargas", "worker-whatsapp")


def main(argv: list[str]) -> int:
    _solo_local()
    if len(argv) != 1 or argv[0] not in COMANDOS:
        print(f"Uso: python -m scripts.local.lanzadores {'|'.join(COMANDOS)}")
        return 2
    _sin_senales_de_unix()
    if argv[0] == "worker-cargas":
        from cc_colaboradores.workers.worker_cargas import ejecutar
    else:
        from cc_whatsapp.workers.worker_entrada import ejecutar
    asyncio.run(ejecutar())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
