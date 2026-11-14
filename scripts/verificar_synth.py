"""Ejecuta ``cdk synth`` con distintos contextos y cuentas, y resume el resultado.

Uso: ``uv run python scripts/verificar_synth.py``. No llama a AWS: ``cdk synth`` sin stacks
y con la guardia de cuenta solo lee la configuración local. Fija ``CDK_DEFAULT_ACCOUNT`` de
forma explícita para no depender de un perfil de AWS.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
INFRA = RAIZ / "infra"

CASOS = [
    # (nombre, argumentos de contexto, cuenta, debe_pasar)
    ("test_cuenta_permitida", ["-c", "ambiente=test"], "034362033822", True),
    ("sin_ambiente", [], "034362033822", False),
    ("ambiente_desconocido", ["-c", "ambiente=otro"], "034362033822", False),
    ("cuenta_distinta", ["-c", "ambiente=test"], "111111111111", False),
    ("cuenta_vacia", ["-c", "ambiente=test"], "", False),
]


def ejecutar(nombre: str, contexto: list[str], cuenta: str) -> dict:
    salida = INFRA / f"cdk.out.verif.{nombre}"
    entorno = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    # Aislamiento: la CLI de CDK no debe encontrar ninguna credencial (ni el perfil por
    # defecto del equipo) y por lo tanto no consulta a AWS. Así solo cuenta la cuenta fijada.
    vacio = RAIZ / ".tmp_aws_vacio"
    vacio.write_text("", encoding="utf-8")
    entorno["AWS_CONFIG_FILE"] = str(vacio)
    entorno["AWS_SHARED_CREDENTIALS_FILE"] = str(vacio)
    entorno["AWS_EC2_METADATA_DISABLED"] = "true"
    entorno["PYTHONIOENCODING"] = "utf-8"
    entorno["CDK_DEFAULT_REGION"] = "us-east-1"
    if cuenta:
        entorno["CDK_DEFAULT_ACCOUNT"] = cuenta
    else:
        entorno.pop("CDK_DEFAULT_ACCOUNT", None)
    cdk = shutil.which("cdk") or "cdk"
    proc = subprocess.run(  # noqa: S603
        [cdk, "synth", *contexto, "--no-notices", "--output", str(salida)],
        cwd=INFRA,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    errores = [
        linea.strip()
        for linea in (proc.stderr or "").splitlines()
        if "ConfiguracionInvalida" in linea or "CuentaNoPermitida" in linea
    ]
    shutil.rmtree(salida, ignore_errors=True)
    codigo = proc.returncode
    # Sin stacks (antes de T-013), la CLI devuelve 1 tras ejecutar la app con éxito.
    # Se considera éxito de la app si no hubo error de configuración ni de guardia.
    sin_stacks = "contains no stacks" in (proc.stderr or "") + (proc.stdout or "")
    if codigo != 0 and sin_stacks and not errores:
        codigo = 0
    return {"codigo": codigo, "sin_stacks": sin_stacks, "error": errores[-1] if errores else ""}


def main() -> int:
    resultados = {}
    fallos = 0
    for nombre, contexto, cuenta, debe_pasar in CASOS:
        r = ejecutar(nombre, contexto, cuenta)
        r["esperado"] = "pasa" if debe_pasar else "falla"
        r["ok"] = (r["codigo"] == 0) == debe_pasar
        fallos += 0 if r["ok"] else 1
        resultados[nombre] = r
    destino = RAIZ / ".tmp_verificar_synth.json"
    destino.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resultados, ensure_ascii=False, indent=2))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
