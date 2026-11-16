"""Lógica del protocolo PA (tasks.md, sección 0.3): pasos PA-1 a PA-3.

``scripts/aws_guard.ps1`` es el punto de entrada para el operador; esta función contiene las
decisiones para poder probarlas con salidas simuladas de ``aws sts get-caller-identity``.
Nunca lee ni imprime llaves de acceso: solo usa el perfil.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from infra.config import esquema  # noqa: E402

INDICACION_LOGIN = "aws sso login --profile {perfil}"
_SEÑALES_SESION_VENCIDA = (
    "token has expired",
    "sso session",
    "expiredtoken",
    "the sso session associated with this profile has expired",
    "error loading sso token",
    "unable to locate credentials",
    "refresh failed",
)


@dataclass(frozen=True)
class ResultadoGuardia:
    ok: bool
    codigo: str
    mensaje: str
    cuenta: str | None = None
    arn: str | None = None


# (código de salida, stdout, stderr)
Ejecutor = Callable[[list[str]], tuple[int, str, str]]


def _ejecutor_real(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)  # noqa: S603
    return proc.returncode, proc.stdout, proc.stderr


def verificar(
    ambiente_nombre: str = "test",
    entorno: Mapping[str, str] | None = None,
    ejecutor: Ejecutor = _ejecutor_real,
    ruta_ambientes: Path | None = None,
) -> ResultadoGuardia:
    amb = esquema.obtener_ambiente(ambiente_nombre, ruta_ambientes)
    perfil = amb.perfil
    entorno = entorno or {}

    # PA-1: el único perfil permitido es el del ambiente; no hay llaves en el entorno.
    activo = entorno.get("AWS_PROFILE", "")
    if activo != perfil:
        return ResultadoGuardia(
            False,
            "PERFIL_INCORRECTO",
            f"AWS_PROFILE debe ser '{perfil}' (valor actual: '{activo or 'sin definir'}'). "
            "No se continúa con otro perfil.",
        )
    if entorno.get("AWS_ACCESS_KEY_ID") or entorno.get("AWS_SECRET_ACCESS_KEY"):
        return ResultadoGuardia(
            False,
            "LLAVES_EN_ENTORNO",
            "Hay llaves de acceso en variables de entorno. Elimínelas: solo se usa el perfil.",
        )
    region = entorno.get("AWS_REGION") or entorno.get("AWS_DEFAULT_REGION") or amb.region
    if region != amb.region:
        return ResultadoGuardia(
            False, "REGION_INCORRECTA", f"La región debe ser '{amb.region}', no '{region}'."
        )

    # PA-2: sesión activa.
    codigo, salida, error = ejecutor(
        [
            "aws",
            "sts",
            "get-caller-identity",
            "--profile",
            perfil,
            "--region",
            amb.region,
            "--output",
            "json",
        ]
    )
    if codigo != 0:
        texto = error.lower()
        motivo = (
            "SESION_VENCIDA" if any(s in texto for s in _SEÑALES_SESION_VENCIDA) else "STS_FALLO"
        )
        return ResultadoGuardia(
            False,
            motivo,
            "No hay una sesión válida para el perfil. Ejecute: "
            + INDICACION_LOGIN.format(perfil=perfil),
        )
    try:
        identidad = json.loads(salida)
        cuenta = str(identidad["Account"])
        arn = str(identidad.get("Arn", ""))
    except (ValueError, KeyError):
        return ResultadoGuardia(False, "RESPUESTA_INVALIDA", "Respuesta de STS no reconocida.")

    # PA-3: cuenta correcta.
    if cuenta not in amb.cuentas_permitidas:
        return ResultadoGuardia(
            False,
            "CUENTA_INCORRECTA",
            f"La cuenta {cuenta} no es la permitida ({', '.join(amb.cuentas_permitidas)}). "
            "Se detiene.",
            cuenta=cuenta,
            arn=arn,
        )
    return ResultadoGuardia(
        True, "OK", f"Sesión válida en la cuenta {cuenta}.", cuenta=cuenta, arn=arn
    )


def main(argv: list[str]) -> int:
    import os

    ambiente = argv[1] if len(argv) > 1 else "test"
    r = verificar(ambiente, os.environ)
    print(json.dumps(r.__dict__, ensure_ascii=False))
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
