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


def id_nag(stack: cdk.Stack, valor: str) -> str:
    """Texto de un recurso tal como cdk-nag lo muestra en el identificador de un hallazgo.

    Los valores que son tokens (partición, cuenta o región de un stack sin ``env``) se escriben
    ``<AWS::Partition>``, ``<AWS::AccountId>``..., y las referencias a otros recursos
    ``<IdLogico.Atributo>``. Una clave de reconocimiento no puede contener un token sin resolver.
    """
    return _texto(stack.resolve(valor))


def _texto(r: object) -> str:
    if isinstance(r, str):
        return r
    if isinstance(r, dict):
        if "Fn::Join" in r:
            return "".join(_texto(p) for p in r["Fn::Join"][1])
        if "Ref" in r:
            return f"<{r['Ref']}>"
        if "Fn::GetAtt" in r:
            return f"<{r['Fn::GetAtt'][0]}.{r['Fn::GetAtt'][1]}>"
    return "?"
