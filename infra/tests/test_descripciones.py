"""EC2 y RDS rechazan en el despliegue descripciones con tildes u otros caracteres.

CloudFormation no lo detecta al sintetizar (falló CcNetwork-test en T-045), así que se revisa
aquí en todas las plantillas.
"""

import re

import pytest
from aws_cdk.assertions import Template

from infra.app import construir_stacks, crear_app

PERMITIDA = "034362033822"
# Conjunto que acepta EC2 para descripciones de grupos de seguridad y de sus reglas.
EC2_VALIDA = re.compile(r"^[a-zA-Z0-9. _\-:/()#,@\[\]+=&;{}!$*]{0,255}$")
ASCII = re.compile(r"^[\x20-\x7e]*$")


@pytest.fixture(scope="module")
def plantillas() -> dict[str, Template]:
    app, amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    return {k: Template.from_stack(s) for k, s in construir_stacks(app, amb, destino).items()}


def _descripciones(plantillas, tipo: str, *campos: str):
    for stack, t in plantillas.items():
        for logico, r in t.find_resources(tipo).items():
            for campo in campos:
                valor = r["Properties"].get(campo)
                if isinstance(valor, str):
                    yield stack, logico, campo, valor


def test_grupos_de_seguridad_y_reglas_con_descripcion_valida_en_ec2(plantillas):
    tipos = (
        ("AWS::EC2::SecurityGroup", ("GroupDescription",)),
        ("AWS::EC2::SecurityGroupIngress", ("Description",)),
        ("AWS::EC2::SecurityGroupEgress", ("Description",)),
    )
    invalidas = [
        (s, nombre, c, v)
        for tipo, campos in tipos
        for s, nombre, c, v in _descripciones(plantillas, tipo, *campos)
        if not EC2_VALIDA.match(v)
    ]
    assert invalidas == []


def test_reglas_en_linea_de_los_grupos_de_seguridad_tambien(plantillas):
    malas = []
    for stack, t in plantillas.items():
        for logico, r in t.find_resources("AWS::EC2::SecurityGroup").items():
            for regla in r["Properties"].get("SecurityGroupIngress", []) + r["Properties"].get(
                "SecurityGroupEgress", []
            ):
                d = regla.get("Description")
                if isinstance(d, str) and not EC2_VALIDA.match(d):
                    malas.append((stack, logico, d))
    assert malas == []


def test_descripciones_de_rds_en_ascii(plantillas):
    tipos = (
        ("AWS::RDS::DBParameterGroup", ("Description",)),
        ("AWS::RDS::DBSubnetGroup", ("DBSubnetGroupDescription",)),
        ("AWS::RDS::DBProxy", ("DBProxyName",)),
    )
    invalidas = [
        (s, nombre, c, v)
        for tipo, campos in tipos
        for s, nombre, c, v in _descripciones(plantillas, tipo, *campos)
        if not ASCII.match(v)
    ]
    assert invalidas == []
