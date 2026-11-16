"""Ensamblados completos de ``test`` y de un ``prod`` sintético para la revisión global (T-226).

``prod`` no existe en ``ambientes.json``: se construye con ``ambiente_prod()`` (valores de producción
de ``ayudas_computo``). Los contextos opcionales de ``prod`` (certificados, dominio, llave pública
de CloudFront, repositorio del pipeline) son cadenas de prueba. Se carga el ``context`` de
``infra/cdk.json`` para sintetizar igual que la CLI (``enablePartitionLiterals``, políticas mínimas).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk.assertions import Template

from infra.app import construir_stacks, registrar_nag
from infra.config import esquema
from infra.etiquetas import aplicar_etiquetas
from infra.guardia import Destino
from infra.stacks.edge import CLAVE_PUBLICA_INERTE
from infra.tests.ayudas_computo import (
    CERTIFICADO,
    DOMINIO_INTERNO,
    PERMITIDA,
    ambiente_prod,
)

INFRA = Path(__file__).resolve().parent.parent
CONTEXTO_CDK = json.loads((INFRA / "cdk.json").read_text(encoding="utf-8"))["context"]

# Contextos que ``prod`` necesita (CcCompute, CcApi, CcEdge y CcPipeline).
CONTEXTO_PROD: dict[str, Any] = {
    "certificado_alb_arn": CERTIFICADO,
    "dominio_interno": DOMINIO_INTERNO,
    "cloudfront_public_key_pem": CLAVE_PUBLICA_INERTE,
    "zona_hospedada_id": "Z0000000EXAMPLE",
    "dominio_origen_api": "origen.cc.example.com",
    "certificado_origen_api_arn": CERTIFICADO,
    "repositorio_pipeline": "organizacion/command-center",
}


@dataclass
class Ensamblado:
    """Todos los stacks de un ambiente y sus plantillas."""

    app: cdk.App
    ambiente: esquema.Ambiente
    stacks: dict[str, cdk.Stack]
    plantillas: dict[str, Template]

    def json_de(self, nombre: str) -> dict:
        return self.plantillas[nombre].to_json()


def construir(
    ambiente: esquema.Ambiente,
    *,
    contexto: dict[str, Any] | None = None,
    con_nag: bool = False,
    salida: str | None = None,
) -> Ensamblado:
    """Construye todos los stacks de ``ambiente`` (sin tocar AWS) y sus plantillas."""
    app = cdk.App(context={**CONTEXTO_CDK, **(contexto or {})}, outdir=salida)
    app.node.set_context("cc:ambiente", ambiente.nombre)
    aplicar_etiquetas(app, ambiente)
    if con_nag:
        registrar_nag(app)
    stacks = construir_stacks(app, ambiente, Destino(PERMITIDA, ambiente.region))
    plantillas = {n: Template.from_stack(s) for n, s in stacks.items()}
    return Ensamblado(app, ambiente, stacks, plantillas)


def construir_prod(contexto: dict[str, Any] | None = None, **kwargs) -> Ensamblado:
    """Ensamblado completo del ``prod`` sintético, con todos los stacks."""
    return construir(ambiente_prod(), contexto={**CONTEXTO_PROD, **(contexto or {})}, **kwargs)


def construir_test(contexto: dict[str, Any] | None = None, **kwargs) -> Ensamblado:
    return construir(esquema.obtener_ambiente("test"), contexto=contexto, **kwargs)


# ------------------------------------------------------------------------- lectura de políticas
TIPOS_CON_POLITICA_DE_IDENTIDAD = ("AWS::IAM::Policy", "AWS::IAM::ManagedPolicy")
TIPOS_CON_POLITICA_DE_RECURSO = (
    "AWS::S3::BucketPolicy",
    "AWS::SQS::QueuePolicy",
    "AWS::SNS::TopicPolicy",
    "AWS::ECR::Repository",
)


def lista(x: Any) -> list:
    return x if isinstance(x, list) else [x]


def sentencias_de_identidad(plantilla: dict) -> list[tuple[str, dict]]:
    """``(id lógico del dueño, sentencia)`` de las políticas de identidad: políticas en línea,
    administradas propias y políticas incrustadas en un rol. Solo ``Allow``."""
    resultado: list[tuple[str, dict]] = []
    for logico, r in plantilla.get("Resources", {}).items():
        propiedades = r.get("Properties", {})
        documentos: list[dict] = []
        if r["Type"] in TIPOS_CON_POLITICA_DE_IDENTIDAD:
            documentos.append(propiedades["PolicyDocument"])
        elif r["Type"] == "AWS::IAM::Role":
            documentos += [p["PolicyDocument"] for p in propiedades.get("Policies", [])]
        for doc in documentos:
            resultado += [
                (logico, s) for s in lista(doc.get("Statement", [])) if s.get("Effect") == "Allow"
            ]
    return resultado


def sentencias_de_recurso(plantilla: dict) -> list[tuple[str, dict]]:
    """Sentencias ``Allow`` de las políticas de bucket, cola y tema (no las de llaves de KMS, donde
    ``Resource: "*"`` significa "esta llave")."""
    resultado: list[tuple[str, dict]] = []
    for logico, r in plantilla.get("Resources", {}).items():
        if r["Type"] in ("AWS::S3::BucketPolicy", "AWS::SQS::QueuePolicy", "AWS::SNS::TopicPolicy"):
            doc = r["Properties"]["PolicyDocument"]
            resultado += [
                (logico, s) for s in lista(doc.get("Statement", [])) if s.get("Effect") == "Allow"
            ]
    return resultado


def acciones_de(sentencia: dict) -> list[str]:
    return [str(a) for a in lista(sentencia.get("Action", []))]


def recursos_de_sentencia(sentencia: dict) -> list:
    return lista(sentencia.get("Resource", []))


def roles_de_politica(plantilla: dict, logico_politica: str) -> list[str]:
    """Ids lógicos de los roles a los que aplica una política (``Roles`` o el propio rol)."""
    r = plantilla["Resources"][logico_politica]
    if r["Type"] == "AWS::IAM::Role":
        return [logico_politica]
    roles = r["Properties"].get("Roles", [])
    return [x["Ref"] for x in roles if isinstance(x, dict) and "Ref" in x]


def sentencias_por_rol(plantilla: dict) -> dict[str, list[dict]]:
    """Todas las sentencias ``Allow`` efectivas de cada rol (en línea o por política asociada)."""
    por_rol: dict[str, list[dict]] = {}
    for logico, sentencia in sentencias_de_identidad(plantilla):
        for rol in roles_de_politica(plantilla, logico):
            por_rol.setdefault(rol, []).append(sentencia)
    return por_rol
