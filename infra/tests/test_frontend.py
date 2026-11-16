"""T-139 (SPA): aserciones de CcFrontend (despliegue de la SPA, configuración e invalidación)."""

import re

import aws_cdk as cdk
import pytest

from infra.stacks.frontend import DIST_SPA, FrontendStack, verificar_dist
from infra.tests.ayudas_borde import construir_borde_prod, propiedades, recursos, texto
from infra.tests.ayudas_computo import ENV_AWS, PERMITIDA, ambiente_prod


@pytest.fixture(scope="module")
def plantilla(ensamblado_test):
    return ensamblado_test[1]["frontend"]


def _despliegue(plantilla) -> dict:
    (d,) = propiedades(plantilla, "Custom::CDKBucketDeployment")
    return d


def test_el_paquete_de_la_spa_existe_o_el_error_dice_como_generarlo(tmp_path):
    assert (DIST_SPA / "index.html").is_file(), "ejecute: npm run build (en frontend/)"
    assert verificar_dist(DIST_SPA) == DIST_SPA
    with pytest.raises(FileNotFoundError, match="npm run build"):
        verificar_dist(tmp_path)
    app = cdk.App()
    with pytest.raises(FileNotFoundError, match="npm run build"):
        FrontendStack(
            app,
            "CcFrontend-test",
            ambiente=ambiente_prod(),
            bucket_frontend="b",
            distribucion_id="E1",
            distribucion_dominio="d1.cloudfront.net",
            dominio_publico="d1.cloudfront.net",
            user_pool_id="p",
            cliente_id="c",
            ruta_spa=tmp_path,
            env=ENV_AWS,
        )


def test_se_publica_en_el_bucket_frontend_importado_por_nombre(plantilla):
    d = _despliegue(plantilla)
    assert d["DestinationBucketName"] == f"cc-test-{PERMITIDA}-frontend"
    assert d["Prune"] is True
    # La SPA y config.json salen del mismo despliegue: dos orígenes, uno con marcadores.
    assert len(d["SourceObjectKeys"]) == 2
    assert not recursos(plantilla, "AWS::S3::Bucket")  # no crea ni modifica buckets


def test_invalida_cloudfront_despues_del_despliegue(plantilla):
    d = _despliegue(plantilla)
    assert d["DistributionPaths"] == ["/*"]
    assert "CcEdge-test" in texto(d["DistributionId"])  # la distribución de CcEdge
    cache = d["SystemMetadata"]["cache-control"]
    assert cache == "public, max-age=0, must-revalidate"
    # El rol de la función solo puede invalidar (no crear ni borrar distribuciones).
    acciones = {
        a
        for p in propiedades(plantilla, "AWS::IAM::Policy")
        for s in p["PolicyDocument"]["Statement"]
        for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])
        if a.startswith("cloudfront:")
    }
    assert acciones == {"cloudfront:GetInvalidation", "cloudfront:CreateInvalidation"}


def test_la_configuracion_de_ejecucion_lleva_solo_identificadores_publicos(
    plantilla, ensamblado_test
):
    stacks, _ = ensamblado_test
    config = stacks["frontend"].configuracion
    assert set(config) == {
        "userPoolId",
        "userPoolClientId",
        "region",
        "apiBaseUrl",
        "registroAbierto",
    }
    assert config["region"] == "us-east-1"
    # Los valores de Cognito y la URL de CloudFront llegan por marcadores (referencias de CDK).
    marcadores = {k: v for m in _despliegue(plantilla)["SourceMarkers"] for k, v in m.items()}
    valores = texto(marcadores)
    assert "CcAuth-test" in valores  # pool y cliente
    assert "CcEdge-test" in valores  # dominio de CloudFront
    for clave in config:
        assert not re.search(r"secret|password|token|clave|key", clave, re.IGNORECASE)


def test_la_url_base_de_la_api_es_el_mismo_origen_de_cloudfront(ensamblado_test):
    stacks, _ = ensamblado_test
    url = stacks["frontend"].configuracion["apiBaseUrl"]
    assert url.startswith("https://")
    assert url == f"https://{stacks['edge'].dominio_publico}"


def test_prod_conserva_los_archivos_al_borrar_el_stack():
    d = _despliegue(construir_borde_prod()["frontend"])
    assert d["RetainOnDelete"] is True
    assert d["DistributionPaths"] == ["/*"]


def test_test_borra_los_archivos_con_el_stack(plantilla):
    assert _despliegue(plantilla)["RetainOnDelete"] is False


def test_sin_secretos_en_la_plantilla(plantilla):
    t = texto(plantilla.to_json())
    assert "PRIVATE KEY" not in t
    assert "AKIA" not in t
    assert "secretsmanager" not in t
