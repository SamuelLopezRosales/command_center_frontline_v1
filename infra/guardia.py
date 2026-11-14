"""Guardia de cuenta de AWS para la aplicación de CDK (tasks.md, sección 0.2, regla 4).

Rechaza la síntesis y el despliegue si la cuenta de ``CDK_DEFAULT_ACCOUNT`` no está en la
lista permitida del ambiente, o si la región no coincide. La lista vive en
``infra/config/ambientes.json``, nunca en el código de los stacks.

La CLI de CDK fija ``CDK_DEFAULT_ACCOUNT`` a partir del perfil con el que se ejecuta. Si la
sesión venció o no hay perfil, la variable no existe y la guardia también falla: así no se
puede sintetizar ni desplegar "a ciegas".
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from infra.config.esquema import Ambiente


class CuentaNoPermitida(RuntimeError):
    """La cuenta o la región de AWS no están permitidas para el ambiente."""


@dataclass(frozen=True)
class Destino:
    cuenta: str
    region: str


def verificar_cuenta(ambiente: Ambiente, entorno: Mapping[str, str] | None = None) -> Destino:
    """Devuelve el destino validado o lanza ``CuentaNoPermitida``."""
    entorno = os.environ if entorno is None else entorno
    cuenta = (entorno.get("CDK_DEFAULT_ACCOUNT") or "").strip()
    region = (entorno.get("CDK_DEFAULT_REGION") or ambiente.region).strip()
    if not cuenta:
        raise CuentaNoPermitida(
            f"No se pudo determinar la cuenta de AWS para el ambiente '{ambiente.nombre}'. "
            f"Verifique la sesión con 'aws sts get-caller-identity --profile {ambiente.perfil}' "
            f"y, si venció, ejecute 'aws sso login --profile {ambiente.perfil}'."
        )
    if cuenta not in ambiente.cuentas_permitidas:
        raise CuentaNoPermitida(
            f"La cuenta {cuenta} no está permitida para el ambiente '{ambiente.nombre}'. "
            f"Cuentas permitidas: {', '.join(ambiente.cuentas_permitidas)}. "
            "No se sintetiza ni se despliega."
        )
    if region != ambiente.region:
        raise CuentaNoPermitida(
            f"La región {region} no coincide con la del ambiente '{ambiente.nombre}' "
            f"({ambiente.region})."
        )
    return Destino(cuenta=cuenta, region=region)
