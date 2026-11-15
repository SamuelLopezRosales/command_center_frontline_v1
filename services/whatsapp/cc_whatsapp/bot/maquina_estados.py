"""Máquina de estados de la conversación (design.md §7.1).

``[*] -> VERIFICANDO`` (palabra clave de un colaborador elegible) o ``[*] -> ACTIVA`` (respuesta a
una notificación, ``verificada = false``); ``VERIFICANDO -> ACTIVA`` con código y dato correctos;
``VERIFICANDO -> BLOQUEADA`` al tercer intento fallido; ``ACTIVA -> VERIFICANDO`` si pide una
constancia sin estar verificada; ``ACTIVA`` y ``VERIFICANDO -> CERRADA`` por inactividad;
``BLOQUEADA -> CERRADA`` al vencer el bloqueo.
"""

from __future__ import annotations

VERIFICANDO = "VERIFICANDO"
ACTIVA = "ACTIVA"
BLOQUEADA = "BLOQUEADA"
CERRADA = "CERRADA"

ABIERTAS = (VERIFICANDO, ACTIVA, BLOQUEADA)

TRANSICIONES: dict[str, frozenset[str]] = {
    VERIFICANDO: frozenset({VERIFICANDO, ACTIVA, BLOQUEADA, CERRADA}),
    ACTIVA: frozenset({VERIFICANDO, CERRADA}),
    BLOQUEADA: frozenset({CERRADA}),
    CERRADA: frozenset(),
}


class TransicionInvalida(Exception):  # noqa: N818
    def __init__(self, origen: str, destino: str) -> None:
        super().__init__(f"{origen} -> {destino}")
        self.origen = origen
        self.destino = destino


def validar(origen: str, destino: str) -> None:
    if destino not in TRANSICIONES.get(origen, frozenset()):
        raise TransicionInvalida(origen, destino)
