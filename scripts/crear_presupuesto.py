"""Presupuesto de AWS con alertas (tasks.md, T-008 y T-009; regla 7).

Idempotente: primero consulta (``describe-budgets``) y solo crea si falta. Con
``--que-pasaria`` (o ``-WhatIf`` desde PowerShell) no llama a AWS: solo muestra los comandos.
Antes de cualquier llamada real se ejecuta la guardia del protocolo PA.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from infra.config import esquema  # noqa: E402
from scripts.aws_guard import verificar  # noqa: E402

DEFINICION = RAIZ / "infra" / "budget" / "presupuesto.json"
_TIPOS = {"ACTUAL": "ACTUAL", "PRONOSTICADO": "FORECASTED"}


def construir(ambiente: esquema.Ambiente) -> tuple[dict, list[dict]]:
    """Devuelve el presupuesto y las notificaciones en el formato de la API de Budgets."""
    definicion = json.loads(DEFINICION.read_text(encoding="utf-8"))
    nombre = definicion["nombre"].format(ambiente=ambiente.nombre)
    presupuesto = {
        "BudgetName": nombre,
        "BudgetLimit": {"Amount": f"{ambiente.presupuesto.monto_usd:.2f}", "Unit": "USD"},
        "TimeUnit": "MONTHLY",
        "BudgetType": "COST",
    }
    notificaciones = [
        {
            "Notification": {
                "NotificationType": _TIPOS[a.tipo],
                "ComparisonOperator": "GREATER_THAN",
                "Threshold": float(a.umbral_pct),
                "ThresholdType": "PERCENTAGE",
            },
            "Subscribers": [{"SubscriptionType": "EMAIL", "Address": ambiente.presupuesto.correo}],
        }
        for a in ambiente.presupuesto.alertas
    ]
    return presupuesto, notificaciones


def comandos(ambiente: esquema.Ambiente, cuenta: str) -> dict[str, list[str]]:
    presupuesto, notificaciones = construir(ambiente)
    base = ["aws", "budgets", "--profile", ambiente.perfil, "--region", "us-east-1"]
    return {
        "consultar": [
            *base,
            "describe-budget",
            "--account-id",
            cuenta,
            "--budget-name",
            presupuesto["BudgetName"],
            "--output",
            "json",
        ],
        "crear": [
            *base,
            "create-budget",
            "--account-id",
            cuenta,
            "--budget",
            json.dumps(presupuesto),
            "--notifications-with-subscribers",
            json.dumps(notificaciones),
        ],
        "notificaciones": [
            *base,
            "describe-notifications-for-budget",
            "--account-id",
            cuenta,
            "--budget-name",
            presupuesto["BudgetName"],
            "--output",
            "json",
        ],
    }


def _correr(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)  # noqa: S603
    return p.returncode, p.stdout, p.stderr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ambiente", default="test")
    parser.add_argument("--que-pasaria", action="store_true", help="No llama a AWS")
    args = parser.parse_args(argv)
    amb = esquema.obtener_ambiente(args.ambiente)

    if args.que_pasaria:
        cuenta = amb.cuentas_permitidas[0]
        presupuesto, notificaciones = construir(amb)
        print("Modo -WhatIf: no se llama a AWS.")
        print(
            json.dumps(
                {"presupuesto": presupuesto, "notificaciones": notificaciones},
                ensure_ascii=False,
                indent=2,
            )
        )
        for nombre, cmd in comandos(amb, cuenta).items():
            print(f"[{nombre}] {' '.join(cmd[:8])} ...")
        return 0

    guardia = verificar(args.ambiente, os.environ)
    if not guardia.ok:
        print(f"Protocolo PA detenido ({guardia.codigo}): {guardia.mensaje}")
        return 1
    cmds = comandos(amb, guardia.cuenta or "")
    codigo, _salida, error = _correr(cmds["consultar"])
    if codigo == 0:
        print("El presupuesto ya existe; no se crea otro.")
    elif "NotFoundException" in error or "not found" in error.lower():
        codigo, _salida, error = _correr(cmds["crear"])
        if codigo != 0:
            print(f"No se pudo crear el presupuesto: {error.strip()}")
            return 1
        print("Presupuesto creado.")
    else:
        print(f"No se pudo consultar el presupuesto (¿permiso de Budgets?): {error.strip()}")
        return 1
    codigo, salida, error = _correr(cmds["notificaciones"])
    print(salida if codigo == 0 else error)
    return 0 if codigo == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
