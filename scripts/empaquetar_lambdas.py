"""Empaqueta las Lambdas de los triggers de Cognito para ``cdk diff`` y ``cdk deploy``.

Genera ``build/lambdas/`` con el paquete ``cognito_triggers`` (sin pruebas) y sus dependencias
para Linux arm64 y Python 3.12 (psycopg con su biblioteca de PostgreSQL incluida). ``boto3`` ya
viene en el entorno de ejecución de Lambda.

No llama a AWS: solo descarga paquetes de PyPI. Es idempotente: reconstruye la carpeta.

    uv run python scripts/empaquetar_lambdas.py
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


def main() -> int:
    try:
        carpeta = empaquetar()
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"No se pudo empaquetar: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    tam = sum(f.stat().st_size for f in carpeta.rglob("*") if f.is_file()) / 1_048_576
    print(f"Paquete listo en {carpeta.relative_to(RAIZ)} ({tam:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
