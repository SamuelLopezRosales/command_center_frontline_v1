"""Ayudas de las pruebas de ``CcCompute`` y ``CcWorkersLambdas`` (T-224)."""

from __future__ import annotations

import dataclasses
import fnmatch
import json
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_kms as kms
from aws_cdk.assertions import Template

from infra.config import esquema

PERMITIDA = "034362033822"
ENV_AWS = cdk.Environment(account=PERMITIDA, region="us-east-1")
CERTIFICADO = f"arn:aws:acm:us-east-1:{PERMITIDA}:certificate/00000000-0000-0000-0000-000000000000"
DOMINIO_INTERNO = "interno.cc.example.com"


def ambiente_prod() -> esquema.Ambiente:
    """``prod`` sintético (no existe en ambientes.json): valores de economía de producción."""
    test = esquema.obtener_ambiente("test")
    return dataclasses.replace(
        test,
        nombre="prod",
        etiquetas={**test.etiquetas, "ambiente": "prod"},
        economia=dataclasses.replace(
            test.economia,
            nat="gateway",
            rds_clase="db.t4g.medium",
            rds_multi_az=True,
            rds_proxy=True,
            waf_habilitado=True,
            workers_min_tareas=1,
            tareas_por_servicio=2,
            concurrencia_aprovisionada_webhook=2,
            retencion_respaldos_dias=14,
            permite_borrado=False,
        ),
        dominio="cc.example.com",
    )


def base_sintetica(app: cdk.App) -> dict[str, Any]:
    """VPC, grupos de seguridad y llaves de apoyo para construir los stacks de prod aislados."""
    base = cdk.Stack(app, "Base", env=ENV_AWS)
    vpc = ec2.Vpc(
        base,
        "V",
        availability_zones=["us-east-1a", "us-east-1b"],
        nat_gateways=0,
        subnet_configuration=[
            ec2.SubnetConfiguration(name="aplicacion", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)
        ],
    )
    return {
        "vpc": vpc,
        "sg_ecs": ec2.SecurityGroup(base, "SgEcs", vpc=vpc),
        "sg_alb": ec2.SecurityGroup(base, "SgAlb", vpc=vpc),
        "sg_lambda": ec2.SecurityGroup(base, "SgLambda", vpc=vpc),
        "llave_infra": kms.Key(base, "KInfra"),
        "llave_datos": kms.Key(base, "KDatos"),
    }


def buckets(env: str) -> dict[str, str]:
    return {
        "bucket_plantillas": f"cc-{env}-{PERMITIDA}-plantillas",
        "bucket_constancias": f"cc-{env}-{PERMITIDA}-constancias",
        "bucket_cargas": f"cc-{env}-{PERMITIDA}-cargas",
    }


def construir_prod() -> tuple[Template, Template]:
    """``(CcCompute-prod, CcWorkersLambdas-prod)`` con el ambiente sintético."""
    from infra.stacks.compute import ComputeStack
    from infra.stacks.workers_lambdas import WorkersLambdasStack

    app = cdk.App()
    b = base_sintetica(app)
    amb = ambiente_prod()
    compute = ComputeStack(
        app,
        "CcCompute-prod",
        ambiente=amb,
        llave_infra=b["llave_infra"],
        llave_datos=b["llave_datos"],
        vpc=b["vpc"],
        sg_ecs=b["sg_ecs"],
        sg_alb=b["sg_alb"],
        host_bd="bd.interna",
        user_pool_id="us-east-1_prod",
        user_pool_arn=f"arn:aws:cognito-idp:us-east-1:{PERMITIDA}:userpool/us-east-1_prod",
        cliente_id="cliente-prod",
        certificado_arn=CERTIFICADO,
        dominio_interno=DOMINIO_INTERNO,
        env=ENV_AWS,
        **buckets("prod"),
    )
    workers = WorkersLambdasStack(
        app,
        "CcWorkersLambdas-prod",
        ambiente=amb,
        llave_infra=b["llave_infra"],
        llave_datos=b["llave_datos"],
        vpc=b["vpc"],
        sg_ecs=b["sg_ecs"],
        sg_lambda=b["sg_lambda"],
        host_bd="bd.interna",
        host_bd_lambda="proxy.interno",
        url_interna=compute.url_interna,
        user_pool_arn=f"arn:aws:cognito-idp:us-east-1:{PERMITIDA}:userpool/us-east-1_prod",
        user_pool_id="us-east-1_prod",
        cliente_id="cliente-prod",
        env=ENV_AWS,
        **buckets("prod"),
    )
    return Template.from_stack(compute), Template.from_stack(workers)


# ----------------------------------------------------------------------------- plantillas JSON
def recursos(plantilla: Template, tipo: str) -> dict[str, dict]:
    return plantilla.find_resources(tipo)


def propiedades(plantilla: Template, tipo: str) -> list[dict]:
    return [r["Properties"] for r in recursos(plantilla, tipo).values()]


def _referencia_a(valor: Any, logico: str) -> bool:
    return logico in json.dumps(valor)


def sentencias_de_rol(plantilla: Template, id_logico_rol: str) -> list[dict]:
    """Todas las sentencias de las políticas en línea de un rol."""
    resultado: list[dict] = []
    for pol in recursos(plantilla, "AWS::IAM::Policy").values():
        if {"Ref": id_logico_rol} in pol["Properties"]["Roles"]:
            resultado += _lista(pol["Properties"]["PolicyDocument"]["Statement"])
    return resultado


def _lista(x: Any) -> list:
    return x if isinstance(x, list) else [x]


def acciones(sentencia: dict) -> list[str]:
    return _lista(sentencia["Action"])


def recursos_de(sentencia: dict) -> list:
    return _lista(sentencia["Resource"])


def texto(valor: Any) -> str:
    return json.dumps(valor, sort_keys=True)


def rol_logico_por_nombre(plantilla: Template, nombre: str) -> str:
    (lid,) = (
        lid
        for lid, r in recursos(plantilla, "AWS::IAM::Role").items()
        if r["Properties"].get("RoleName") == nombre
    )
    return lid


def coincide_alb(patron: str, ruta: str) -> bool:
    """Coincidencia de un patrón de ruta del ALB (``*`` cualquier cadena, ``?`` un carácter)."""
    return fnmatch.fnmatchcase(ruta, patron)


def entorno_contenedor(tarea: dict) -> dict[str, Any]:
    (c,) = tarea["ContainerDefinitions"]
    return {e["Name"]: e["Value"] for e in c.get("Environment", [])}
