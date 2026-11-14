"""Asigna a cada rol de base de datos la contraseña de su secreto de Secrets Manager.

``infra/db/roles.sql`` crea los roles sin contraseña (design.md §2.6). Este script, que corre en
la tarea ``ops`` de ECS, las fija a partir de las variables ``CC_PWD_<ROL>``, que ECS inyecta desde
``cc/{env}/db/{rol}``. Es idempotente: repetirlo deja el mismo estado, y después de una rotación
vuelve a alinear la base con el secreto.

Las contraseñas nunca se imprimen ni se escriben en registros. La conexión usa ``CC_MIGRAR_URL``
(el usuario propietario de los esquemas).

    $env:CC_MIGRAR_URL = 'postgresql+psycopg://...'; $env:CC_PWD_SVC_DASHBOARD = '...'
    uv run python scripts/asignar_contrasenas.py
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

ROLES = (
    "svc_dashboard",
    "svc_colaboradores",
    "svc_campos",
    "svc_constancias",
    "svc_notificaciones",
    "svc_whatsapp",
    "migrador",
)
PREFIJO = "CC_PWD_"
LONGITUD_MINIMA = 16


class ErrorContrasenas(Exception):  # noqa: N818
    """Error de uso con un mensaje seguro para mostrar (nunca incluye una contraseña)."""


def contrasenas_desde_entorno(entorno: Mapping[str, str]) -> dict[str, str]:
    """``CC_PWD_SVC_DASHBOARD`` -> ``svc_dashboard``. Exige que estén todas y que sean robustas."""
    encontradas: dict[str, str] = {}
    faltan: list[str] = []
    cortas: list[str] = []
    for rol in ROLES:
        valor = entorno.get(f"{PREFIJO}{rol.upper()}", "")
        if not valor:
            faltan.append(rol)
        elif len(valor) < LONGITUD_MINIMA:
            cortas.append(rol)
        else:
            encontradas[rol] = valor
    if faltan:
        raise ErrorContrasenas(f"faltan contraseñas para: {', '.join(faltan)}")
    if cortas:
        raise ErrorContrasenas(
            f"contraseñas demasiado cortas (mínimo {LONGITUD_MINIMA}) para: {', '.join(cortas)}"
        )
    return encontradas


def asignar(url: str, contrasenas: Mapping[str, str]) -> list[str]:
    import psycopg
    from psycopg import sql

    crudo = url.replace("postgresql+psycopg://", "postgresql://")
    hechos: list[str] = []
    with psycopg.connect(crudo, autocommit=True) as conn:
        for rol, clave in contrasenas.items():
            existe = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (rol,)).fetchone()
            if not existe:
                raise ErrorContrasenas(f"el rol {rol} no existe: ejecute primero las migraciones")
            conn.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(rol), sql.Literal(clave))
            )
            hechos.append(rol)
    return hechos


def main() -> int:
    url = os.environ.get("CC_MIGRAR_URL")
    if not url:
        print("Falta CC_MIGRAR_URL", file=sys.stderr)
        return 2
    try:
        hechos = asignar(url, contrasenas_desde_entorno(os.environ))
    except ErrorContrasenas as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - solo el tipo: el mensaje podría traer la URL
        print(f"Falló la asignación: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"Contraseñas asignadas a {len(hechos)} roles: {', '.join(hechos)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
