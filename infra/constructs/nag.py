"""Reconocimiento de reglas de cdk-nag (cdk-nag 3 usa la API nativa ``Validations``).

Toda excepción lleva su motivo por escrito (tasks.md, T-015). El reconocimiento sobre un
constructo aplica también a sus hijos.
"""

from __future__ import annotations

import aws_cdk as cdk

from constructs import IConstruct


def reconocer(scope: IConstruct, regla: str, motivo: str) -> None:
    if not motivo or len(motivo) < 20:
        raise ValueError(f"la excepción {regla} necesita un motivo escrito")
    cdk.Validations.of(scope).acknowledge(cdk.Acknowledgment(id=regla, reason=motivo))
