import ast
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_sqs as sqs
from aws_cdk.assertions import Match, Template

from infra.app import crear_app

PERMITIDA = "034362033822"
ESPERADAS = {"proyecto": "command-center", "ambiente": "test", "responsable": "Samuel Lopez"}


def _stack_de_prueba() -> Template:
    app, _amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    stack = cdk.Stack(
        app, "PruebaEtiquetas", env=cdk.Environment(account=destino.cuenta, region=destino.region)
    )
    sqs.Queue(stack, "Cola")
    return Template.from_stack(stack)


def test_las_tres_etiquetas_llegan_a_los_recursos():
    plantilla = _stack_de_prueba()
    # CDK ordena las etiquetas por clave; arrayWith exige ese mismo orden.
    etiquetas = [{"Key": k, "Value": v} for k, v in sorted(ESPERADAS.items())]
    plantilla.has_resource_properties(
        "AWS::SQS::Queue", {"Tags": Match.array_with([Match.object_like(e) for e in etiquetas])}
    )


def test_valores_exactos():
    recursos = _stack_de_prueba().find_resources("AWS::SQS::Queue")
    (cola,) = recursos.values()
    tags = {t["Key"]: t["Value"] for t in cola["Properties"]["Tags"]}
    assert tags == ESPERADAS


def test_no_se_etiqueta_recurso_por_recurso():
    """Ningún archivo de infra, salvo etiquetas.py, llama a Tags.of(...)."""
    raiz = Path(__file__).resolve().parent.parent
    infractores = []
    for archivo in raiz.rglob("*.py"):
        if "tests" in archivo.parts or archivo.name == "etiquetas.py" or "cdk.out" in str(archivo):
            continue
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if (
                isinstance(nodo, ast.Attribute)
                and nodo.attr == "of"
                and isinstance(nodo.value, ast.Attribute)
                and nodo.value.attr == "Tags"
            ):
                infractores.append(str(archivo.relative_to(raiz)))
    assert infractores == []
