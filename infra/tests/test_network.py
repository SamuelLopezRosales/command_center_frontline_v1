import pytest
from aws_cdk.assertions import Template

from infra.app import construir_stacks, crear_app

PERMITIDA = "034362033822"


@pytest.fixture(scope="module")
def plantilla() -> Template:
    app, amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    return Template.from_stack(construir_stacks(app, amb, destino)["network"])


def test_vpc_con_tres_tipos_de_subred_en_dos_zonas(plantilla):
    plantilla.resource_count_is("AWS::EC2::VPC", 1)
    # 3 tipos de subred por 2 zonas.
    plantilla.resource_count_is("AWS::EC2::Subnet", 6)


def test_test_usa_instancia_nat_y_no_nat_gateway(plantilla):
    plantilla.resource_count_is("AWS::EC2::NatGateway", 0)
    instancias = plantilla.find_resources("AWS::EC2::Instance")
    assert len(instancias) == 1
    (nat,) = instancias.values()
    assert nat["Properties"]["InstanceType"] == "t4g.nano"
    assert nat["Properties"]["SourceDestCheck"] is False


def test_disco_de_la_instancia_nat_cifrado(plantilla):
    (nat,) = plantilla.find_resources("AWS::EC2::Instance").values()
    (disco,) = nat["Properties"]["BlockDeviceMappings"]
    assert disco["Ebs"]["Encrypted"] is True
    assert disco["Ebs"]["VolumeType"] == "gp3"


def test_zonas_fijas_sin_busqueda_en_aws(plantilla):
    zonas = {
        s["Properties"]["AvailabilityZone"]
        for s in plantilla.find_resources("AWS::EC2::Subnet").values()
    }
    assert zonas == {"us-east-1a", "us-east-1b"}


def test_endpoint_de_s3_tipo_gateway(plantilla):
    endpoints = plantilla.find_resources("AWS::EC2::VPCEndpoint")
    assert len(endpoints) == 1
    (ep,) = endpoints.values()
    assert ep["Properties"]["VpcEndpointType"] == "Gateway"


def test_grupos_de_seguridad_esperados(plantilla):
    nombres = {
        sg["Properties"].get("GroupName")
        for sg in plantilla.find_resources("AWS::EC2::SecurityGroup").values()
    }
    for n in ("vpclink", "alb", "ecs", "lambda", "proxy", "rds"):
        assert f"cc-test-{n}" in nombres


def test_sin_entradas_abiertas_a_internet(plantilla):
    for sg in plantilla.find_resources("AWS::EC2::SecurityGroup").values():
        for regla in sg["Properties"].get("SecurityGroupIngress", []):
            assert regla.get("CidrIp") != "0.0.0.0/0"
            assert regla.get("CidrIpv6") != "::/0"
    for regla in plantilla.find_resources("AWS::EC2::SecurityGroupIngress").values():
        assert regla["Properties"].get("CidrIp") != "0.0.0.0/0"


def test_lambda_llega_directo_a_rds_sin_proxy_en_test(plantilla):
    """Cambio B: sin RDS Proxy, existe la regla Lambda -> RDS en el puerto 5432."""
    reglas = plantilla.find_resources("AWS::EC2::SecurityGroupIngress")
    descripciones = {r["Properties"].get("Description") for r in reglas.values()}
    assert "PostgreSQL desde Lambda (sin proxy)" in descripciones
