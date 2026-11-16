"""Empaqueta las Lambdas de los triggers de Cognito para ``cdk diff`` y ``cdk deploy``.

Genera ``build/lambdas/`` con el paquete ``cognito_triggers`` (sin pruebas) y sus dependencias
para Linux arm64 y Python 3.12 (psycopg con su biblioteca de PostgreSQL incluida). ``boto3`` ya
viene en el entorno de ejecución de Lambda.

No llama a AWS: solo descarga paquetes de PyPI. Es idempotente: reconstruye la carpeta.

    uv run python scripts/empaquetar_lambdas.py                    # triggers de Cognito
    uv run python scripts/empaquetar_lambdas.py --notificaciones   # despachador, conciliador y
                                                      # respaldo-correo (build/lambdas_notif)
    uv run python scripts/empaquetar_lambdas.py --whatsapp         # webhook-meta, enviador y
                                                      # estados-entrega (build/lambdas_wa)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ORIGEN = RAIZ / "lambdas" / "cognito_triggers"
SALIDA = RAIZ / "build" / "lambdas"
# El entorno de Lambda para Python 3.12 (Amazon Linux 2023) usa glibc 2.34.
PLATAFORMA = "aarch64-manylinux_2_28"
PYTHON = "3.12"


def empaquetar(salida: Path = SALIDA, origen: Path = ORIGEN) -> Path:
    if salida.exists():
        shutil.rmtree(salida)
    salida.mkdir(parents=True)
    shutil.copytree(
        origen,
        salida / origen.name,
        ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"),
    )
    version = metadata.version("psycopg")  # la misma que usan las pruebas (uv.lock)
    uv = shutil.which("uv") or "uv"
    subprocess.run(  # noqa: S603
        [
            uv,
            "pip",
            "install",
            "--quiet",
            "--target",
            str(salida),
            "--python-platform",
            PLATAFORMA,
            "--python-version",
            PYTHON,
            "--no-compile",
            f"psycopg[binary]=={version}",
        ],
        check=True,
    )
    return salida


# Lambdas de notificaciones (T-217, parte A): un solo paquete con el código compartido
# (``notif_comun``), las tres funciones (handlers ``despachador.handler.lambda_handler``,
# ``conciliador.handler.lambda_handler`` y ``respaldo_correo.handler.lambda_handler``) y
# ``cc_common`` (configuración y token interno). ``boto3`` viene en el entorno de Lambda.
PAQUETES_NOTIFICACIONES = ("notif_comun", "despachador", "conciliador", "respaldo_correo")
DEPENDENCIAS_NOTIFICACIONES = (
    "pydantic",
    "pydantic-settings",
    "httpx",
    "pyjwt[crypto]",
)
SALIDA_NOTIFICACIONES = RAIZ / "build" / "lambdas_notif"
IGNORAR = shutil.ignore_patterns("tests", "__pycache__", "*.pyc", "pruebas.py")


def copiar_fuentes_notificaciones(salida: Path, raiz: Path = RAIZ) -> Path:
    """Copia los paquetes de las Lambdas de notificaciones y ``cc_common`` (sin pruebas ni
    dobles de prueba). No instala dependencias: ver ``empaquetar_notificaciones``."""
    if salida.exists():
        shutil.rmtree(salida)
    salida.mkdir(parents=True)
    for nombre in PAQUETES_NOTIFICACIONES:
        shutil.copytree(raiz / "lambdas" / nombre, salida / nombre, ignore=IGNORAR)
    shutil.copytree(
        raiz / "services" / "shared" / "cc_common", salida / "cc_common", ignore=IGNORAR
    )
    return salida


def empaquetar_notificaciones(salida: Path = SALIDA_NOTIFICACIONES) -> Path:
    copiar_fuentes_notificaciones(salida)
    version = metadata.version("psycopg")
    uv = shutil.which("uv") or "uv"
    subprocess.run(  # noqa: S603
        [
            uv,
            "pip",
            "install",
            "--quiet",
            "--target",
            str(salida),
            "--python-platform",
            PLATAFORMA,
            "--python-version",
            PYTHON,
            "--no-compile",
            f"psycopg[binary]=={version}",
            *DEPENDENCIAS_NOTIFICACIONES,
        ],
        check=True,
    )
    return salida


# Lambdas de WhatsApp (T-224): ``webhook-meta`` (sin VPC ni base de datos), ``enviador`` y
# ``estados-entrega``. Importan ``cc_whatsapp`` (configuración, cliente de Meta, ventana de 24 h,
# normalización) y ``cc_common``. ``cc_common.recursos`` (secreto interno del ``enviador``) importa
# SQLAlchemy, por eso va en las dependencias aunque estas funciones no abran motor asíncrono.
PAQUETES_WHATSAPP = ("webhook_meta", "enviador", "estados_entrega")
DEPENDENCIAS_WHATSAPP = (
    "pydantic",
    "pydantic-settings",
    "httpx",
    "pyjwt[crypto]",
    "sqlalchemy",
)
SALIDA_WHATSAPP = RAIZ / "build" / "lambdas_wa"


def copiar_fuentes_whatsapp(salida: Path, raiz: Path = RAIZ) -> Path:
    """Copia las Lambdas de WhatsApp, ``cc_whatsapp`` y ``cc_common`` (sin pruebas). No instala
    dependencias: ver ``empaquetar_whatsapp``."""
    if salida.exists():
        shutil.rmtree(salida)
    salida.mkdir(parents=True)
    for nombre in PAQUETES_WHATSAPP:
        shutil.copytree(raiz / "lambdas" / nombre, salida / nombre, ignore=IGNORAR)
    shutil.copytree(
        raiz / "services" / "whatsapp" / "cc_whatsapp", salida / "cc_whatsapp", ignore=IGNORAR
    )
    shutil.copytree(
        raiz / "services" / "shared" / "cc_common", salida / "cc_common", ignore=IGNORAR
    )
    return salida


def empaquetar_whatsapp(salida: Path = SALIDA_WHATSAPP) -> Path:
    copiar_fuentes_whatsapp(salida)
    version = metadata.version("psycopg")
    uv = shutil.which("uv") or "uv"
    subprocess.run(  # noqa: S603
        [
            uv,
            "pip",
            "install",
            "--quiet",
            "--target",
            str(salida),
            "--python-platform",
            PLATAFORMA,
            "--python-version",
            PYTHON,
            "--no-compile",
            f"psycopg[binary]=={version}",
            *DEPENDENCIAS_WHATSAPP,
        ],
        check=True,
    )
    return salida


def main() -> int:
    args = sys.argv[1:]
    try:
        if "--notificaciones" in args:
            carpeta = empaquetar_notificaciones()
        elif "--whatsapp" in args:
            carpeta = empaquetar_whatsapp()
        else:
            carpeta = empaquetar()
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"No se pudo empaquetar: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    tam = sum(f.stat().st_size for f in carpeta.rglob("*") if f.is_file()) / 1_048_576
    print(f"Paquete listo en {carpeta.relative_to(RAIZ)} ({tam:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
