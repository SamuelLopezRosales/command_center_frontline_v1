"""Aplica todas las migraciones y los scripts de seguridad de la base (design.md §2.8, T-031).

Orden: identidad/auditoria (dashboard), campos, colaboradores, whatsapp, constancias,
notificaciones; después ``infra/db/roles.sql``, ``rls.sql`` y ``grants.sql``.

La URL llega por ``CC_MIGRAR_URL`` (``postgresql+psycopg://...``); nunca se imprime.
Sale con código distinto de cero si cualquier paso falla. Es idempotente.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ), str(RAIZ / "services" / "shared")]

ORDEN = ("dashboard", "campos", "colaboradores", "whatsapp", "constancias", "notificaciones")
SCRIPTS_SQL = ("roles.sql", "rls.sql", "grants.sql")


def migrar(url: str, *, raiz: Path = RAIZ, salida=print) -> None:
    import psycopg
    from alembic import command
    from alembic.config import Config

    anterior = os.environ.get("CC_MIGRAR_URL")
    os.environ["CC_MIGRAR_URL"] = url
    try:
        for servicio in ORDEN:
            salida(f"migración: {servicio}")
            command.upgrade(Config(str(raiz / "services" / servicio / "alembic.ini")), "head")
    finally:
        if anterior is None:
            os.environ.pop("CC_MIGRAR_URL", None)
        else:
            os.environ["CC_MIGRAR_URL"] = anterior
    crudo = url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(crudo, autocommit=True) as conn:
        for nombre in SCRIPTS_SQL:
            salida(f"script: {nombre}")
            conn.execute((raiz / "infra" / "db" / nombre).read_text(encoding="utf-8"))


def main() -> int:
    url = os.environ.get("CC_MIGRAR_URL")
    if not url:
        print("Falta CC_MIGRAR_URL", file=sys.stderr)
        return 2
    try:
        migrar(url)
    except Exception as exc:  # noqa: BLE001 - se reporta el tipo, nunca la URL
        print(
            f"Migración fallida: {type(exc).__name__}: {str(exc).splitlines()[0][:300]}",
            file=sys.stderr,
        )
        return 1
    print("Migraciones aplicadas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
