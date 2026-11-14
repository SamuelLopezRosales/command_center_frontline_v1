"""T-039: aserciones del stack CcStorage."""

import json

import pytest
from aws_cdk.assertions import Match, Template

from infra.app import construir_stacks, crear_app

PERMITIDA = "034362033822"


@pytest.fixture(scope="module")
def plantilla() -> Template:
    app, amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    return Template.from_stack(construir_stacks(app, amb, destino)["storage"])


def _buckets(plantilla):
    """Buckets por el nombre lógico sin el sufijo hash (``Cargas``, ``Logs``...)."""
    return {logico[:-8]: r for logico, r in plantilla.find_resources("AWS::S3::Bucket").items()}


def test_cinco_buckets(plantilla):
    assert set(_buckets(plantilla)) == {"Logs", "Frontend", "Plantillas", "Constancias", "Cargas"}


def test_todos_bloquean_el_acceso_publico(plantilla):
    for r in _buckets(plantilla).values():
        assert r["Properties"]["PublicAccessBlockConfiguration"] == {
            "BlockPublicAcls": True,
            "BlockPublicPolicy": True,
            "IgnorePublicAcls": True,
            "RestrictPublicBuckets": True,
        }


def test_todos_exigen_tls(plantilla):
    politicas = plantilla.find_resources("AWS::S3::BucketPolicy")
    assert len(politicas) == 5
    for p in politicas.values():
        sentencias = p["Properties"]["PolicyDocument"]["Statement"]
        assert any(
            s["Effect"] == "Deny" and s["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
            for s in sentencias
        )


def test_cifrado_con_kms_y_clave_de_bucket_salvo_frontend_y_logs(plantilla):
    b = _buckets(plantilla)
    for nombre in ("Plantillas", "Constancias", "Cargas"):
        regla = b[nombre]["Properties"]["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]
        assert regla["ServerSideEncryptionByDefault"]["SSEAlgorithm"] == "aws:kms"
        assert "KMSMasterKeyID" in regla["ServerSideEncryptionByDefault"]
        assert regla["BucketKeyEnabled"] is True
    for nombre in ("Frontend", "Logs"):
        regla = b[nombre]["Properties"]["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]
        assert regla["ServerSideEncryptionByDefault"]["SSEAlgorithm"] == "AES256"


def test_constancias_con_object_lock_versionado_y_governance_minimo(plantilla):
    p = _buckets(plantilla)["Constancias"]["Properties"]
    assert p["ObjectLockEnabled"] is True
    assert p["VersioningConfiguration"] == {"Status": "Enabled"}
    assert p["ObjectLockConfiguration"] == {
        "ObjectLockEnabled": "Enabled",
        "Rule": {"DefaultRetention": {"Mode": "GOVERNANCE", "Days": 1}},
    }


def test_solo_constancias_tiene_object_lock(plantilla):
    for nombre, r in _buckets(plantilla).items():
        if nombre != "Constancias":
            assert "ObjectLockEnabled" not in r["Properties"]


def test_plantillas_versionado_y_expiracion_de_versiones_no_actuales(plantilla):
    p = _buckets(plantilla)["Plantillas"]["Properties"]
    assert p["VersioningConfiguration"] == {"Status": "Enabled"}
    reglas = p["LifecycleConfiguration"]["Rules"]
    assert any(
        r.get("NoncurrentVersionExpiration", {}).get("NoncurrentDays") == 365 for r in reglas
    )


def test_cargas_expiran_a_7_dias_y_cors_solo_put(plantilla):
    p = _buckets(plantilla)["Cargas"]["Properties"]
    assert any(r.get("ExpirationInDays") == 7 for r in p["LifecycleConfiguration"]["Rules"])
    (regla,) = p["CorsConfiguration"]["CorsRules"]
    assert regla["AllowedMethods"] == ["PUT"]
    assert regla["AllowedOrigins"] == ["https://*.cloudfront.net"]


def test_logs_expiran_a_90_dias(plantilla):
    p = _buckets(plantilla)["Logs"]["Properties"]
    assert any(r.get("ExpirationInDays") == 90 for r in p["LifecycleConfiguration"]["Rules"])


def test_los_demas_buckets_registran_su_acceso_en_logs(plantilla):
    b = _buckets(plantilla)
    for nombre in ("Frontend", "Plantillas", "Constancias", "Cargas"):
        cfg = b[nombre]["Properties"]["LoggingConfiguration"]
        assert cfg["DestinationBucketName"] == {"Ref": Match.any_value()} or "Ref" in json.dumps(
            cfg
        )
        assert cfg["LogFilePrefix"] == f"{nombre.lower()}/"
    assert "LoggingConfiguration" not in b["Logs"]["Properties"]


def test_en_test_se_pueden_borrar_con_cdk_destroy(plantilla):
    for r in _buckets(plantilla).values():
        assert r["DeletionPolicy"] == "Delete"
    # Vaciado automático al destruir el stack.
    assert len(plantilla.find_resources("Custom::S3AutoDeleteObjects")) == 5


def test_en_test_no_se_niega_el_borrado_de_versiones_de_plantilla(plantilla):
    """La negación impediría vaciar el bucket con ``cdk destroy``; solo aplica sin borrado."""
    texto = json.dumps(plantilla.to_json())
    assert "NegarBorradoDeVersionesDePlantilla" not in texto


def test_sin_credenciales_ni_politicas_publicas(plantilla):
    texto = json.dumps(plantilla.to_json())
    assert "AKIA" not in texto
    for p in plantilla.find_resources("AWS::S3::BucketPolicy").values():
        for s in p["Properties"]["PolicyDocument"]["Statement"]:
            if s["Effect"] == "Allow":
                assert s.get("Principal") != "*" and s.get("Principal") != {"AWS": "*"}


# --- Variante prod: se construye el stack con un ambiente sintético, sin tocar ambientes.json ---


@pytest.fixture(scope="module")
def plantilla_prod() -> Template:
    import dataclasses

    import aws_cdk as cdk
    from aws_cdk import aws_kms as kms

    from infra.config import esquema
    from infra.stacks.storage import StorageStack

    test = esquema.obtener_ambiente("test")
    prod = dataclasses.replace(
        test,
        nombre="prod",
        dominio="app.ejemplo.com",
        economia=dataclasses.replace(test.economia, permite_borrado=False),
    )
    app = cdk.App()
    base = cdk.Stack(app, "Base")
    llave = kms.Key(base, "K")
    stack = StorageStack(app, "CcStorage-prod", ambiente=prod, llave_infra=llave)
    return Template.from_stack(stack)


def test_prod_conserva_los_buckets_y_no_los_vacia(plantilla_prod):
    for r in plantilla_prod.find_resources("AWS::S3::Bucket").values():
        assert r["DeletionPolicy"] == "Retain"
    assert not plantilla_prod.find_resources("Custom::S3AutoDeleteObjects")


def test_prod_niega_borrar_versiones_de_plantilla(plantilla_prod):
    politicas = plantilla_prod.find_resources("AWS::S3::BucketPolicy")
    sentencias = [
        s
        for p in politicas.values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
        if s.get("Sid") == "NegarBorradoDeVersionesDePlantilla"
    ]
    assert len(sentencias) == 1
    assert sentencias[0]["Effect"] == "Deny"
    assert sorted(sentencias[0]["Action"]) == ["s3:DeleteObject", "s3:DeleteObjectVersion"]
    assert "plantillas/*/v*.json" in json.dumps(sentencias[0]["Resource"])


def test_prod_object_lock_sin_retencion_por_defecto_hasta_resolver_pq24(plantilla_prod):
    constancias = next(
        r
        for logico, r in plantilla_prod.find_resources("AWS::S3::Bucket").items()
        if logico.startswith("Constancias")
    )
    assert constancias["Properties"]["ObjectLockEnabled"] is True
    assert "Rule" not in constancias["Properties"].get("ObjectLockConfiguration", {})


def test_prod_cors_solo_desde_el_dominio_de_la_aplicacion(plantilla_prod):
    cargas = next(
        r
        for logico, r in plantilla_prod.find_resources("AWS::S3::Bucket").items()
        if logico.startswith("Cargas")
    )
    (regla,) = cargas["Properties"]["CorsConfiguration"]["CorsRules"]
    assert regla["AllowedOrigins"] == ["https://app.ejemplo.com"]
