"""Stack CcNetwork: VPC, NAT, endpoint de S3 y grupos de seguridad (design.md §13.3).

En ``test`` la salida a internet usa una instancia NAT ``t4g.micro`` en lugar de NAT Gateway
(cambio A, tasks.md §0.4). En ``prod`` se usa una NAT Gateway por zona. Ningún grupo de
seguridad admite entrada desde ``0.0.0.0/0``.
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_logs as logs

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs.nag import reconocer

PUERTO_POSTGRES = 5432


class NetworkStack(cdk.Stack):
    @property
    def availability_zones(self) -> list[str]:
        """Zonas fijas: sin esto la VPC consulta las zonas a AWS durante la síntesis."""
        return [f"{self.region}a", f"{self.region}b"]

    def __init__(self, scope: Construct, id_: str, *, ambiente: Ambiente, **kwargs) -> None:
        super().__init__(scope, id_, **kwargs)
        eco = ambiente.economia
        es_instancia = eco.nat == "instancia"

        if es_instancia:
            self.nat_provider: ec2.NatProvider | None = ec2.NatProvider.instance_v2(
                # t4g.micro (1 GB): en t4g.nano (512 MB) iptables-services se queda sin memoria al
                # instalarse en el arranque y la instancia nunca llega a hacer NAT (T-047).
                instance_type=ec2.InstanceType("t4g.micro"),
                machine_image=ec2.MachineImage.latest_amazon_linux2023(
                    cpu_type=ec2.AmazonLinuxCpuType.ARM_64
                ),
                # Sin el valor por defecto, que abre el grupo de seguridad a todo IPv4.
                default_allowed_traffic=ec2.NatTrafficDirection.OUTBOUND_ONLY,
            )
            nat_gateways = 1
        else:
            self.nat_provider = ec2.NatProvider.gateway()
            nat_gateways = 2

        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            # Zonas fijas: evitan la búsqueda de zonas en AWS durante la síntesis y hacen la
            # plantilla determinista.
            availability_zones=[f"{ambiente.region}a", f"{ambiente.region}b"],
            nat_gateways=nat_gateways,
            nat_gateway_provider=self.nat_provider,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="publica", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="aplicacion", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=22
                ),
                ec2.SubnetConfiguration(
                    name="datos", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24
                ),
            ],
            restrict_default_security_group=True,
        )

        if es_instancia and isinstance(self.nat_provider, ec2.NatInstanceProviderV2):
            # La instancia NAT solo acepta tráfico que nace dentro de la VPC.
            self.nat_provider.security_group.add_ingress_rule(
                ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
                ec2.Port.all_traffic(),
                # EC2 solo admite ASCII y algunos signos en las descripciones de reglas.
                "Trafico saliente de las subredes privadas",
            )
            reconocer(
                self.nat_provider.security_group,
                "AwsSolutions-EC23",
                "La entrada usa el rango de la VPC (valor resuelto al desplegar), no 0.0.0.0/0; "
                "lo comprueba infra/tests/test_network.py.",
            )
            self._cifrar_disco_nat()

        self.vpc.add_gateway_endpoint(
            "EndpointS3",
            service=ec2.GatewayVpcEndpointAwsService.S3,
            subnets=[ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)],
        )

        def sg(nombre: str, descripcion: str) -> ec2.SecurityGroup:
            return ec2.SecurityGroup(
                self,
                f"Sg{nombre}",
                vpc=self.vpc,
                description=descripcion,
                security_group_name=f"cc-{ambiente.nombre}-{nombre.lower()}",
                allow_all_outbound=True,
            )

        self.sg_vpclink = sg("VpcLink", "VPC Link de API Gateway hacia el ALB")
        self.sg_alb = sg("Alb", "ALB interno de los servicios")
        self.sg_ecs = sg("Ecs", "Tareas de ECS Fargate")
        self.sg_lambda = sg("Lambda", "Lambdas dentro de la VPC")
        self.sg_proxy = sg("Proxy", "RDS Proxy (solo cuando el ambiente lo despliega)")
        self.sg_rds = sg("Rds", "Instancia de PostgreSQL")

        https = ec2.Port.tcp(443)
        self.sg_alb.add_ingress_rule(self.sg_vpclink, https, "Desde el VPC Link")
        self.sg_alb.add_ingress_rule(self.sg_ecs, https, "Llamadas internas desde ECS")
        self.sg_alb.add_ingress_rule(self.sg_lambda, https, "Llamadas internas desde Lambda")
        if not ambiente.dominio:
            # Sin dominio propio (PQ-22) no hay certificado para el ALB interno: el listener es
            # HTTP en el puerto 80 y no sale de la VPC (T-224; docs/desviaciones.md).
            http = ec2.Port.tcp(80)
            self.sg_alb.add_ingress_rule(self.sg_vpclink, http, "HTTP desde el VPC Link")
            self.sg_alb.add_ingress_rule(self.sg_ecs, http, "HTTP interno desde ECS")
            self.sg_alb.add_ingress_rule(self.sg_lambda, http, "HTTP interno desde Lambda")
        self.sg_ecs.add_ingress_rule(self.sg_alb, ec2.Port.tcp(8000), "Desde el ALB")
        pg = ec2.Port.tcp(PUERTO_POSTGRES)
        self.sg_rds.add_ingress_rule(self.sg_ecs, pg, "PostgreSQL desde ECS")
        self.sg_proxy.add_ingress_rule(self.sg_lambda, pg, "PostgreSQL desde Lambda")
        self.sg_rds.add_ingress_rule(self.sg_proxy, pg, "PostgreSQL desde RDS Proxy")
        if not eco.rds_proxy:
            # Sin RDS Proxy (cambio B), las Lambdas se conectan directo a la instancia.
            self.sg_rds.add_ingress_rule(self.sg_lambda, pg, "PostgreSQL desde Lambda (sin proxy)")

        if ambiente.nombre == "prod":
            self._registrar_flujos(ambiente)
        self._reconocer_reglas(ambiente, es_instancia)

    def _registrar_flujos(self, ambiente: Ambiente) -> None:
        """Registro de flujo de la VPC (AwsSolutions-VPC7): solo el tráfico rechazado, a CloudWatch
        Logs con 30 días de retención. Es lo que permite investigar un bloqueo de red sin pagar el
        registro de todo el tráfico."""
        grupo = logs.LogGroup(
            self,
            "GrupoFlujosVpc",
            log_group_name=f"/cc/{ambiente.nombre}/vpc-flujos",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        self.vpc.add_flow_log(
            "FlujosRechazados",
            destination=ec2.FlowLogDestination.to_cloud_watch_logs(grupo),
            traffic_type=ec2.FlowLogTrafficType.REJECT,
        )

    def _cifrar_disco_nat(self) -> None:
        """El constructo de instancia NAT no expone el disco: se fuerza el disco raíz cifrado."""
        for hijo in self.vpc.node.find_all():
            if isinstance(hijo, ec2.CfnInstance):
                hijo.add_property_override(
                    "BlockDeviceMappings",
                    [
                        {
                            "DeviceName": "/dev/xvda",
                            "Ebs": {
                                "Encrypted": True,
                                "VolumeType": "gp3",
                                # 10 GB: cambiar el disco fuerza una instancia nueva; el script
                                # de arranque (iptables) solo corre en el primer arranque.
                                "VolumeSize": 10,
                                "DeleteOnTermination": True,
                            },
                        }
                    ],
                )
                reconocer(
                    hijo,
                    "AwsSolutions-EC26",
                    "Disco raíz de la instancia NAT cifrado mediante property override "
                    "(cdk-nag no ve los overrides); lo comprueba test_network.py.",
                )

    def _reconocer_reglas(self, ambiente: Ambiente, es_instancia: bool) -> None:
        if ambiente.nombre != "prod":
            reconocer(
                self.vpc,
                "AwsSolutions-VPC7",
                "Prototipo de 1 a 2 semanas con presupuesto de 50 USD: los registros de flujo "
                "de la VPC se agregan en producción (tasks.md §0.4).",
            )
        if es_instancia:
            reconocer(
                self,
                "AwsSolutions-EC28",
                "Instancia NAT de prueba: sin monitoreo detallado por costo (cambio A).",
            )
            reconocer(
                self,
                "AwsSolutions-EC29",
                "Instancia NAT de prueba: se destruye con el prototipo (cambio A).",
            )
