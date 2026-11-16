"""Región de recuperación y nombres que comparten ``CcStorage``, ``CcBackup`` y la región de
recuperación (design.md §14.5, §15.5; CC-NFR-006; T-226).

Los recursos de ``us-east-2`` (llave, bóveda de respaldos y réplica de ``constancias``) solo se
crean en ``prod``. En ``test`` la región de recuperación no está inicializada con ``cdk bootstrap``
y no se despliega nada allí (``docs/desviaciones.md``). Los nombres son fijos y conocidos para que
ningún stack dependa de otro por una referencia de CloudFormation (un ciclo rompe el despliegue):
se arman aquí y cada stack los usa como texto. La llave se identifica por su **alias**, porque el
identificador de una llave no se conoce antes de crearla.
"""

from __future__ import annotations

import aws_cdk as cdk

from infra.config.esquema import Ambiente

REGION_RECUPERACION = "us-east-2"
# Días de retención de los respaldos de AWS Backup en prod (design.md §14.5). En test se usa la
# retención de respaldos del ambiente (1 día).
RETENCION_PROD_DIAS = 35
# Retención mínima de la bóveda (modo de gobierno: se puede quitar con permiso explícito).
RETENCION_MINIMA_BOVEDA_DIAS = 7


def recuperacion_habilitada(ambiente: Ambiente) -> bool:
    """``True`` solo en los ambientes que conservan datos (``prod``); nunca en ``test``."""
    return not ambiente.economia.permite_borrado


def retencion_respaldos(ambiente: Ambiente) -> cdk.Duration:
    """Retención de los puntos de recuperación de AWS Backup según el ambiente."""
    if recuperacion_habilitada(ambiente):
        return cdk.Duration.days(RETENCION_PROD_DIAS)
    return cdk.Duration.days(ambiente.economia.retencion_respaldos_dias)


def nombre_boveda(env: str) -> str:
    return f"cc-{env}-respaldos"


def nombre_boveda_recuperacion(env: str) -> str:
    return f"cc-{env}-recuperacion"


def alias_llave_recuperacion(env: str) -> str:
    return f"alias/cc-{env}-recuperacion"


def arn_boveda_recuperacion(env: str, cuenta: str, particion: str = "aws") -> str:
    return (
        f"arn:{particion}:backup:{REGION_RECUPERACION}:{cuenta}:backup-vault:"
        f"{nombre_boveda_recuperacion(env)}"
    )


def arn_alias_llave_recuperacion(env: str, cuenta: str, particion: str = "aws") -> str:
    return f"arn:{particion}:kms:{REGION_RECUPERACION}:{cuenta}:{alias_llave_recuperacion(env)}"


def arn_llaves_recuperacion(cuenta: str, particion: str = "aws") -> str:
    """Llaves de la región de recuperación; el alias las acota (``kms:ResourceAliases``)."""
    return f"arn:{particion}:kms:{REGION_RECUPERACION}:{cuenta}:key/*"


def nombre_bucket_replica(env: str, cuenta: str) -> str:
    """Réplica de ``constancias`` en la región de recuperación."""
    return f"cc-{env}-{cuenta}-constancias-replica"


def arn_bucket_replica(env: str, cuenta: str, particion: str = "aws") -> str:
    return f"arn:{particion}:s3:::{nombre_bucket_replica(env, cuenta)}"
