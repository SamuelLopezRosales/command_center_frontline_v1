#!/usr/bin/env python3
"""Punto de entrada de la aplicación de CDK de Command Center.

Uso: ``cdk synth -c ambiente=test``. El ambiente es obligatorio y se lee de
``infra/config/ambientes.json``. Antes de crear cualquier stack se verifica la cuenta
(``infra/guardia.py``) y se aplican las etiquetas obligatorias en el nivel de la app.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path

# ``cdk`` ejecuta este archivo desde ``infra/``; el paquete se importa como ``infra``.
# La carpeta del script se quita de sys.path: ``infra/constructs/`` (design.md §1.2) taparía
# el paquete ``constructs`` de PyPI del que depende ``aws_cdk``.
_CARPETA = Path(__file__).resolve().parent
RAIZ = _CARPETA.parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _CARPETA]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import aws_cdk as cdk  # noqa: E402

from infra.config import esquema  # noqa: E402
from infra.etiquetas import aplicar_etiquetas  # noqa: E402
from infra.guardia import Destino, verificar_cuenta  # noqa: E402


def crear_app(
    ambiente: str | None,
    entorno: Mapping[str, str] | None = None,
    app: cdk.App | None = None,
) -> tuple[cdk.App, esquema.Ambiente, Destino]:
    """Crea la aplicación de CDK para un ambiente y una cuenta validados.

    La guardia se ejecuta antes de definir cualquier stack: si falla, no se sintetiza nada.
    """
    if not ambiente:
        raise esquema.ConfiguracionInvalida(
            "falta el ambiente: use 'cdk synth -c ambiente=test' (ver infra/config/ambientes.json)"
        )
    amb = esquema.obtener_ambiente(ambiente)
    destino = verificar_cuenta(amb, entorno)
    app = app or cdk.App()
    app.node.set_context("cc:ambiente", amb.nombre)
    aplicar_etiquetas(app, amb)
    return app, amb, destino


def registrar_nag(app: cdk.App) -> None:
    """Registra las reglas AwsSolutions de cdk-nag (T-015, DS-23)."""
    from cdk_nag import AwsSolutionsChecks

    cdk.Validations.of(app).add_plugins(
        AwsSolutionsChecks(app, write_suppressions_to_cloud_formation=True)
    )


def construir_stacks(app: cdk.App, amb: esquema.Ambiente, destino: Destino) -> dict[str, cdk.Stack]:
    """Define los stacks del ambiente. Solo se llama después de la guardia de cuenta."""
    from infra.stacks.auth import AuthStack
    from infra.stacks.compute_base import ComputeBaseStack
    from infra.stacks.data import DataStack
    from infra.stacks.messaging import MessagingStack
    from infra.stacks.network import NetworkStack
    from infra.stacks.security import SecurityStack
    from infra.stacks.storage import StorageStack

    env = cdk.Environment(account=destino.cuenta, region=destino.region)
    sufijo = amb.nombre
    security = SecurityStack(app, f"CcSecurity-{sufijo}", ambiente=amb, env=env)
    network = NetworkStack(app, f"CcNetwork-{sufijo}", ambiente=amb, env=env)
    storage = StorageStack(
        app, f"CcStorage-{sufijo}", ambiente=amb, llave_infra=security.llave_infra, env=env
    )
    data = DataStack(
        app,
        f"CcData-{sufijo}",
        ambiente=amb,
        llave_infra=security.llave_infra,
        vpc=network.vpc,
        sg_rds=network.sg_rds,
        sg_proxy=network.sg_proxy,
        env=env,
    )
    messaging = MessagingStack(
        app, f"CcMessaging-{sufijo}", ambiente=amb, llave_infra=security.llave_infra, env=env
    )
    auth = AuthStack(
        app,
        f"CcAuth-{sufijo}",
        ambiente=amb,
        llave_infra=security.llave_infra,
        vpc=network.vpc,
        sg_lambda=network.sg_lambda,
        secreto_bd=data.secretos_roles["svc_dashboard"],
        host_bd=data.proxy.endpoint if data.proxy is not None else None,
        env=env,
    )
    compute_base = ComputeBaseStack(
        app,
        f"CcComputeBase-{sufijo}",
        ambiente=amb,
        llave_infra=security.llave_infra,
        vpc=network.vpc,
        sg_ecs=network.sg_ecs,
        secreto_admin=data.secreto_admin,
        secretos_roles=data.secretos_roles,
        env=env,
    )
    return {
        "compute_base": compute_base,
        "auth": auth,
        "security": security,
        "network": network,
        "storage": storage,
        "data": data,
        "messaging": messaging,
    }


def main() -> None:
    app = cdk.App()
    app, amb, destino = crear_app(app.node.try_get_context("ambiente"), app=app)
    registrar_nag(app)
    construir_stacks(app, amb, destino)
    app.synth()


if __name__ == "__main__":
    main()
