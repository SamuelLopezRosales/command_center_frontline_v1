"""Ayudas de las pruebas de ``CcApi``, ``CcEdge``, ``CcFrontend`` y ``CcObservability`` (T-225).

Los valores de otros stacks son cadenas fijas: así cada stack de ``prod`` se prueba aislado, con el
``prod`` sintético de ``ayudas_computo`` (no existe en ``ambientes.json``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk.assertions import Template

from infra.constructs.servicios import SERVICIOS
from infra.stacks.api import ApiStack
from infra.stacks.edge import CLAVE_PUBLICA_INERTE, EdgeStack
from infra.stacks.frontend import FrontendStack
from infra.stacks.observability import ObservabilityStack
from infra.stacks.storage import nombre_bucket
from infra.tests.ayudas_computo import (
    CERTIFICADO,
    DOMINIO_INTERNO,
    ENV_AWS,
    PERMITIDA,
    ambiente_prod,
    base_sintetica,
)

RAIZ = Path(__file__).resolve().parents[2]
README_RUNBOOKS = RAIZ / "docs" / "runbooks" / "README.md"
ARN_LISTENER = (
    f"arn:aws:elasticloadbalancing:us-east-1:{PERMITIDA}:listener/app/cc-prod-interno/abc/def"
)
LLAVE_ARN = f"arn:aws:kms:us-east-1:{PERMITIDA}:key/00000000-0000-0000-0000-000000000001"
ENV_EDGE = cdk.Environment(account=PERMITIDA, region="us-east-1")


def construir_borde_prod() -> dict[str, Template]:
    """``CcApi``, ``CcEdge``, ``CcFrontend`` y ``CcObservability`` con el ``prod`` sintético."""
    app = cdk.App()
    b = base_sintetica(app)
    amb = ambiente_prod()
    api = ApiStack(
        app,
        "CcApi-prod",
        ambiente=amb,
        vpc=b["vpc"],
        sg_vpclink=b["sg_lambda"],
        sg_alb=b["sg_alb"],
        listener_arn=ARN_LISTENER,
        user_pool_id="us-east-1_prod",
        cliente_id="cliente-prod",
        dominio_interno=DOMINIO_INTERNO,
        dominio_origen="origen.cc.example.com",
        certificado_origen_arn=CERTIFICADO,
        env=ENV_AWS,
    )
    edge = EdgeStack(
        app,
        "CcEdge-prod",
        ambiente=amb,
        llave_infra_arn=LLAVE_ARN,
        bucket_frontend=nombre_bucket("prod", PERMITIDA, "frontend"),
        bucket_constancias=nombre_bucket("prod", PERMITIDA, "constancias"),
        bucket_cargas=nombre_bucket("prod", PERMITIDA, "cargas"),
        bucket_plantillas=nombre_bucket("prod", PERMITIDA, "plantillas"),
        host_origen_api=api.host_origen,
        clave_publica_pem=CLAVE_PUBLICA_INERTE,
        zona_hospedada_id="Z0000000EXAMPLE",
        dominio_regional_api=api.dominio.regional_domain_name,
        zona_dominio_regional_api=api.dominio.regional_hosted_zone_id,
        env=ENV_EDGE,
    )
    frontend = FrontendStack(
        app,
        "CcFrontend-prod",
        ambiente=amb,
        bucket_frontend=nombre_bucket("prod", PERMITIDA, "frontend"),
        distribucion_id=edge.distribucion.distribution_id,
        distribucion_dominio=edge.distribucion.distribution_domain_name,
        dominio_publico=edge.dominio_publico,
        user_pool_id="us-east-1_prod",
        cliente_id="cliente-prod",
        env=ENV_AWS,
    )
    obs = ObservabilityStack(
        app,
        "CcObservability-prod",
        ambiente=amb,
        llave_infra_arn=LLAVE_ARN,
        instancia_bd_id="bd-prod",
        alb_nombre_completo="app/cc-prod-interno/abc",
        grupos_destino={s: f"targetgroup/cc-prod-{s}/abc" for s in SERVICIOS},
        api_id=api.api.api_id,
        env=ENV_AWS,
    )
    return {
        "api": Template.from_stack(api),
        "edge": Template.from_stack(edge),
        "frontend": Template.from_stack(frontend),
        "observability": Template.from_stack(obs),
    }


def recursos(plantilla: Template, tipo: str) -> dict[str, dict]:
    return plantilla.find_resources(tipo)


def propiedades(plantilla: Template, tipo: str) -> list[dict]:
    return [r["Properties"] for r in recursos(plantilla, tipo).values()]


def texto(valor: Any) -> str:
    return json.dumps(valor, sort_keys=True)


def alarmas_por_nombre(plantilla: Template) -> dict[str, dict]:
    return {p["AlarmName"]: p for p in propiedades(plantilla, "AWS::CloudWatch::Alarm")}


def indice_de_runbooks() -> dict[str, str]:
    """``{identificador sin cc-{env}-: archivo del runbook}`` leído de ``docs/runbooks/README.md``.

    Solo cuenta los identificadores con formato ``cc-{env}-...`` de la primera columna; las filas
    con plantillas (``{cola}``, ``{servicio}``) se devuelven tal cual.
    """
    resultado: dict[str, str] = {}
    for linea in README_RUNBOOKS.read_text(encoding="utf-8").splitlines():
        if not linea.startswith("| `cc-{env}-"):
            continue
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        archivo = re.search(r"\(([\w-]+\.md)\)", celdas[2])
        assert archivo, f"fila sin runbook: {linea}"
        for ident in re.findall(r"`cc-\{env\}-([^`]+)`", celdas[0]):
            # Dentro de una lista de colas entre paréntesis solo cuenta el primer identificador.
            resultado[ident] = archivo.group(1)
        # La fila de las DLQ menciona las colas como `cola-pdf`, etc. (sin el prefijo).
    return resultado
