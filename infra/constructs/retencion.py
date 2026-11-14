"""Política de retención por ambiente (tasks.md, T-011; regla 11).

En ``test`` todo se puede borrar con ``cdk destroy`` (que ejecuta Samuel a mano): RDS sin
protección contra borrado, buckets con vaciado automático, Object Lock en GOVERNANCE con
retención mínima, secretos y llaves con la espera mínima. En ``prod`` se conserva y protege.
Ningún valor de ``test`` se aplica a ``prod``: el ambiente ``prod`` que declare
``permite_borrado`` se rechaza hasta que haya una revisión.
"""

from __future__ import annotations

from dataclasses import dataclass

import aws_cdk as cdk

from infra.config.esquema import Ambiente


@dataclass(frozen=True)
class PoliticaRetencion:
    removal_policy: cdk.RemovalPolicy
    proteccion_borrado_rds: bool
    auto_borrar_objetos: bool
    object_lock_modo: str
    object_lock_dias: int | None
    retencion_respaldos_dias: int
    secretos_dias_recuperacion: int
    kms_dias_espera: int


def politica_retencion(ambiente: Ambiente) -> PoliticaRetencion:
    eco = ambiente.economia
    if ambiente.nombre == "prod" and eco.permite_borrado:
        raise ValueError(
            "prod no puede usar la política de borrado de test sin revisión (tasks.md, regla 11)"
        )
    if eco.permite_borrado:
        return PoliticaRetencion(
            removal_policy=cdk.RemovalPolicy.DESTROY,
            proteccion_borrado_rds=False,
            auto_borrar_objetos=True,
            object_lock_modo="GOVERNANCE",
            object_lock_dias=1,
            retencion_respaldos_dias=eco.retencion_respaldos_dias,
            secretos_dias_recuperacion=7,
            kms_dias_espera=7,
        )
    return PoliticaRetencion(
        removal_policy=cdk.RemovalPolicy.RETAIN,
        proteccion_borrado_rds=True,
        auto_borrar_objetos=False,
        object_lock_modo="GOVERNANCE",
        object_lock_dias=None,  # [POR CONFIRMAR] PQ-24
        retencion_respaldos_dias=eco.retencion_respaldos_dias,
        secretos_dias_recuperacion=30,
        kms_dias_espera=30,
    )
