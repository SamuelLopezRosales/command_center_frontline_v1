"""T-040: aserciones del stack CcData."""

import dataclasses
import json

import aws_cdk as cdk
import pytest
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_kms as kms
from aws_cdk.assertions import Template

from infra.app import construir_stacks, crear_app
from infra.config import esquema
from infra.stacks.data import ROLES_BD, DataStack

PERMITIDA = "034362033822"


@pytest.fixture(scope="module")
def plantilla() -> Template:
    app, amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    return Template.from_stack(construir_stacks(app, amb, destino)["data"])


def _instancia(plantilla):
    (inst,) = plantilla.find_resources("AWS::RDS::DBInstance").values()
    return inst


# --- test ---------------------------------------------------------------------------------


def test_postgres_16_micro_en_una_zona_sin_proteccion_en_test(plantilla):
    p = _instancia(plantilla)["Properties"]
    assert p["Engine"] == "postgres" and str(p["EngineVersion"]).startswith("16")
    assert p["DBInstanceClass"] == "db.t4g.micro"
    assert p["MultiAZ"] is False
    assert p["DeletionProtection"] is False
    assert p["PubliclyAccessible"] is False
    assert p["BackupRetentionPeriod"] == 1


def test_instancia_cifrada_con_la_llave_de_infraestructura(plantilla):
    p = _instancia(plantilla)["Properties"]
    assert p["StorageEncrypted"] is True
    assert "KmsKeyId" in p  # referencia a la llave de CcSecurity


def test_instancia_borrable_con_cdk_destroy_en_test(plantilla):
    inst = _instancia(plantilla)
    assert inst["DeletionPolicy"] == "Delete"
    assert inst["Properties"]["DeleteAutomatedBackups"] is True


def test_tls_obligatorio_y_estadisticas_de_consultas(plantilla):
    (grupo,) = plantilla.find_resources("AWS::RDS::DBParameterGroup").values()
    params = grupo["Properties"]["Parameters"]
    assert params["rds.force_ssl"] == "1"
    assert "pg_stat_statements" in params["shared_preload_libraries"]
    assert grupo["Properties"]["Family"] == "postgres16"


def test_sin_rds_proxy_en_test(plantilla):
    plantilla.resource_count_is("AWS::RDS::DBProxy", 0)
    plantilla.resource_count_is("AWS::RDS::DBProxyTargetGroup", 0)


def test_en_test_sin_extras_que_dejan_recursos_huerfanos_o_no_se_admiten(plantilla):
    p = _instancia(plantilla)["Properties"]
    assert p["EnablePerformanceInsights"] is False  # db.t4g.micro no lo admite
    assert "MonitoringInterval" not in p
    assert "EnableCloudwatchLogsExports" not in p  # los grupos de logs sobrevivirían a destroy


def test_un_secreto_por_rol_mas_el_maestro(plantilla):
    secretos = plantilla.find_resources("AWS::SecretsManager::Secret")
    nombres = {s["Properties"]["Name"] for s in secretos.values()}
    assert nombres == {"cc/test/db/admin"} | {f"cc/test/db/{r}" for r in ROLES_BD}
    assert len(ROLES_BD) == 7 and "migrador" in ROLES_BD
    for s in secretos.values():
        assert "KmsKeyId" in s["Properties"]
        assert s["DeletionPolicy"] == "Delete"
        assert "SecretString" not in s["Properties"]  # el valor se genera al desplegar


def test_cada_secreto_de_rol_lleva_el_host_de_la_instancia(plantilla):
    adjuntos = plantilla.find_resources("AWS::SecretsManager::SecretTargetAttachment")
    assert len(adjuntos) == 8  # maestro y siete roles
    for a in adjuntos.values():
        assert a["Properties"]["TargetType"] == "AWS::RDS::DBInstance"


def test_secretos_de_roles_con_nombre_de_usuario_del_rol(plantilla):
    plantillas = {
        s["Properties"]["Name"]: s["Properties"]["GenerateSecretString"]["SecretStringTemplate"]
        for s in plantilla.find_resources("AWS::SecretsManager::Secret").values()
    }
    for rol in ROLES_BD:
        assert json.loads(plantillas[f"cc/test/db/{rol}"])["username"] == rol


def test_instancia_en_subredes_de_datos_aisladas(plantilla):
    (grupo,) = plantilla.find_resources("AWS::RDS::DBSubnetGroup").values()
    assert len(grupo["Properties"]["SubnetIds"]) == 2


def test_plantilla_sin_contrasenas_ni_llaves(plantilla):
    texto = json.dumps(plantilla.to_json())
    assert "AKIA" not in texto
    assert '"MasterUserPassword": "' not in texto  # solo referencia dinámica a Secrets Manager


# --- prod: se construye con un ambiente sintético, sin tocar ambientes.json ----------------


@pytest.fixture(scope="module")
def plantilla_prod() -> Template:
    test = esquema.obtener_ambiente("test")
    prod = dataclasses.replace(
        test,
        nombre="prod",
        economia=dataclasses.replace(
            test.economia,
            rds_clase="db.t4g.medium",
            rds_multi_az=True,
            rds_proxy=True,
            permite_borrado=False,
            retencion_respaldos_dias=14,
        ),
    )
    app = cdk.App()
    base = cdk.Stack(app, "Base", env=cdk.Environment(account=PERMITIDA, region="us-east-1"))
    vpc = ec2.Vpc(
        base,
        "V",
        availability_zones=["us-east-1a", "us-east-1b"],
        nat_gateways=0,
        subnet_configuration=[
            ec2.SubnetConfiguration(name="datos", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)
        ],
    )
    sg_rds = ec2.SecurityGroup(base, "SgRds", vpc=vpc)
    sg_proxy = ec2.SecurityGroup(base, "SgProxy", vpc=vpc)
    llave = kms.Key(base, "K")
    stack = DataStack(
        app,
        "CcData-prod",
        ambiente=prod,
        llave_infra=llave,
        vpc=vpc,
        sg_rds=sg_rds,
        sg_proxy=sg_proxy,
        env=cdk.Environment(account=PERMITIDA, region="us-east-1"),
    )
    return Template.from_stack(stack)


def test_prod_multi_az_con_proteccion_y_respaldo_de_14_dias(plantilla_prod):
    inst = _instancia(plantilla_prod)
    p = inst["Properties"]
    assert p["DBInstanceClass"] == "db.t4g.medium"
    assert p["MultiAZ"] is True
    assert p["DeletionProtection"] is True
    assert p["StorageEncrypted"] is True
    assert p["BackupRetentionPeriod"] == 14
    assert p["AllocatedStorage"] == "100" and p["MaxAllocatedStorage"] == 500
    assert inst["DeletionPolicy"] in ("Retain", "Snapshot")
    assert p["DeleteAutomatedBackups"] is False


def test_prod_con_monitoreo_performance_insights_y_logs(plantilla_prod):
    p = _instancia(plantilla_prod)["Properties"]
    assert p["EnablePerformanceInsights"] is True
    assert p["MonitoringInterval"] == 60
    assert set(p["EnableCloudwatchLogsExports"]) == {"postgresql", "upgrade"}


def test_prod_rds_proxy_con_tls_y_70_por_ciento(plantilla_prod):
    (proxy,) = plantilla_prod.find_resources("AWS::RDS::DBProxy").values()
    assert proxy["Properties"]["RequireTLS"] is True
    (destino,) = plantilla_prod.find_resources("AWS::RDS::DBProxyTargetGroup").values()
    assert destino["Properties"]["ConnectionPoolConfigurationInfo"]["MaxConnectionsPercent"] == 70


def test_prod_los_secretos_se_conservan(plantilla_prod):
    for s in plantilla_prod.find_resources("AWS::SecretsManager::Secret").values():
        assert s["DeletionPolicy"] == "Retain"
