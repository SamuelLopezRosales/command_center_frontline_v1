"""Etiquetas obligatorias aplicadas en el nivel de la aplicación de CDK (regla 6).

``cdk.Tags.of(app).add`` propaga cada etiqueta a todos los recursos etiquetables de todos
los stacks. No se define ninguna etiqueta recurso por recurso.
"""

from __future__ import annotations

import aws_cdk as cdk

from infra.config.esquema import ETIQUETAS_OBLIGATORIAS, Ambiente


def aplicar_etiquetas(app: cdk.App, ambiente: Ambiente) -> None:
    for clave in ETIQUETAS_OBLIGATORIAS:
        cdk.Tags.of(app).add(clave, ambiente.etiquetas[clave])
