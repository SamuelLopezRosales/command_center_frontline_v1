import json

import pytest
from aws_cdk.assertions import Match, Template

from infra.app import construir_stacks, crear_app

PERMITIDA = "034362033822"


@pytest.fixture(scope="module")
def plantilla() -> Template:
    app, amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    stacks = construir_stacks(app, amb, destino)
    return Template.from_stack(stacks["security"])


def test_dos_llaves_con_rotacion_anual(plantilla):
    plantilla.resource_count_is("AWS::KMS::Key", 2)
    plantilla.all_resources_properties(
        "AWS::KMS::Key", {"EnableKeyRotation": True, "RotationPeriodInDays": 365}
    )
    alias = {
        r["Properties"]["AliasName"] for r in plantilla.find_resources("AWS::KMS::Alias").values()
    }
    assert alias == {"alias/cc-test-datos", "alias/cc-test-infra"}


def test_llaves_borrables_en_test(plantilla):
    for llave in plantilla.find_resources("AWS::KMS::Key").values():
        assert llave["DeletionPolicy"] == "Delete"
        assert llave["Properties"]["PendingWindowInDays"] == 7


def test_cinco_secretos_cifrados_con_kms_y_sin_valor_en_la_plantilla(plantilla):
    secretos = plantilla.find_resources("AWS::SecretsManager::Secret")
    nombres = {s["Properties"]["Name"] for s in secretos.values()}
    assert nombres == {
        "cc/test/meta",
        "cc/test/hmac-celular",
        "cc/test/hmac-codigo",
        "cc/test/internal-auth",
        "cc/test/cf-signing-key",
    }
    for s in secretos.values():
        props = s["Properties"]
        assert "KmsKeyId" in props
        assert "GenerateSecretString" in props
        assert "SecretString" not in props
        assert s["DeletionPolicy"] == "Delete"


def test_parametros_de_configuracion(plantilla):
    parametros = {
        p["Properties"]["Name"]: p["Properties"]["Value"]
        for p in plantilla.find_resources("AWS::SSM::Parameter").values()
    }
    assert parametros["/cc/test/estrategia-entrega"] == "enlace"
    assert parametros["/cc/test/horario-envio-inicio"] == "08:00"
    assert parametros["/cc/test/horario-envio-fin"] == "20:00"


def test_sin_politicas_iam_con_recurso_comodin(plantilla):
    """Las políticas de IAM no usan Resource "*". Las políticas de llave de KMS sí lo usan
    por definición (el recurso es la propia llave) y se excluyen."""
    for politica in plantilla.find_resources("AWS::IAM::Policy").values():
        for sentencia in politica["Properties"]["PolicyDocument"]["Statement"]:
            assert sentencia.get("Resource") != "*"


def test_plantilla_sin_credenciales(plantilla):
    texto = json.dumps(plantilla.to_json())
    assert "AKIA" not in texto
    assert Match is not None
