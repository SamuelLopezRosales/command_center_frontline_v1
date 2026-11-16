"""Stack CcData: PostgreSQL, RDS Proxy (opcional) y un secreto por rol (design.md §13.4, §2.6).

Por ambiente (``infra/config/ambientes.json`` y ``infra/constructs/retencion.py``):

- ``test``: ``db.t4g.micro`` en una sola zona, sin protección contra borrado, respaldos de 1 día,
  sin RDS Proxy (las Lambdas se conectan directo a la instancia, con TLS obligatorio), sin
  Performance Insights (``db.t4g.micro`` no lo admite), sin monitoreo ampliado y sin exportar
  registros a CloudWatch (esos grupos de registros no se borran con ``cdk destroy``).
- ``prod``: clase y Multi-AZ de la configuración, protección contra borrado, RDS Proxy con TLS
  obligatorio y 70 % de las conexiones, Performance Insights de 7 días, monitoreo de 60 s y
  exportación de registros.

Credenciales: el usuario maestro ``cc_admin`` queda en ``cc/{env}/db/admin``. Cada rol de base de
datos (``svc_*`` y ``migrador``) tiene su secreto ``cc/{env}/db/{rol}`` con el host y el puerto de
la instancia. Los roles los crea ``infra/db/roles.sql`` sin contraseña; asignar la contraseña del
secreto a cada rol es parte de la tarea de migraciones (T-047). La rotación cada 30 días se agrega
con el endurecimiento de producción (Fase 7): necesita que los roles ya existan y la ruta de red
de la función de rotación hacia la instancia.
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_kms as kms
from aws_cdk import aws_rds as rds
from aws_cdk import aws_secretsmanager as sm

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs.nag import reconocer
from infra.constructs.retencion import politica_retencion

NOMBRE_BD = "command_center"
USUARIO_MAESTRO = "cc_admin"
ROLES_BD = (
    "svc_dashboard",
    "svc_colaboradores",
    "svc_campos",
    "svc_constancias",
    "svc_notificaciones",
    "svc_whatsapp",
    "migrador",
)
GRUPO_SUBREDES_DATOS = "datos"


class DataStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        id_: str,
        *,
        ambiente: Ambiente,
        llave_infra: kms.IKey,
        vpc: ec2.IVpc,
        sg_rds: ec2.ISecurityGroup,
        sg_proxy: ec2.ISecurityGroup,
        **kwargs,
    ) -> None:
        super().__init__(scope, id_, **kwargs)
        env = ambiente.nombre
        eco = ambiente.economia
        ret = politica_retencion(ambiente)
        es_prod = not eco.permite_borrado
        subredes_datos = ec2.SubnetSelection(subnet_group_name=GRUPO_SUBREDES_DATOS)
        # La llave vive en CcSecurity. Importada por ARN, los permisos de uso (por ejemplo, los del
        # rol del proxy) se agregan a ese rol y no a la política de la llave, lo que evitaría una
        # dependencia circular entre CcSecurity y CcData. La política de la llave delega en IAM.
        llave_infra = kms.Key.from_key_arn(self, "LlaveInfraImportada", llave_infra.key_arn)
        # Los grupos de seguridad y sus reglas viven en CcNetwork. Se importan como no
        # modificables: si CDK agregara reglas desde aquí (por ejemplo, del proxy a la instancia)
        # CcNetwork dependería de CcData y habría una dependencia circular entre stacks.
        sg_rds = ec2.SecurityGroup.from_security_group_id(
            self, "SgRdsImportado", sg_rds.security_group_id, mutable=False
        )
        sg_proxy = ec2.SecurityGroup.from_security_group_id(
            self, "SgProxyImportado", sg_proxy.security_group_id, mutable=False
        )

        grupo_parametros = rds.ParameterGroup(
            self,
            "Parametros",
            engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_16),
            description="Command Center: TLS obligatorio y estadisticas de consultas",
            parameters={
                "rds.force_ssl": "1",
                "shared_preload_libraries": "pg_stat_statements",
            },
        )

        self.instancia = rds.DatabaseInstance(
            self,
            "Postgres",
            engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_16),
            instance_type=ec2.InstanceType(eco.rds_clase.removeprefix("db.")),
            database_name=NOMBRE_BD,
            credentials=rds.Credentials.from_generated_secret(
                USUARIO_MAESTRO,
                secret_name=f"cc/{env}/db/admin",
                encryption_key=llave_infra,
            ),
            vpc=vpc,
            vpc_subnets=subredes_datos,
            security_groups=[sg_rds],
            publicly_accessible=False,
            multi_az=eco.rds_multi_az,
            storage_type=rds.StorageType.GP3,
            allocated_storage=100 if es_prod else 20,
            max_allocated_storage=500 if es_prod else 50,
            storage_encrypted=True,
            storage_encryption_key=llave_infra,
            parameter_group=grupo_parametros,
            backup_retention=cdk.Duration.days(eco.retencion_respaldos_dias),
            delete_automated_backups=not es_prod,
            deletion_protection=ret.proteccion_borrado_rds,
            removal_policy=ret.removal_policy,
            auto_minor_version_upgrade=True,
            copy_tags_to_snapshot=True,
            enable_performance_insights=es_prod,
            performance_insight_retention=(
                rds.PerformanceInsightRetention.DEFAULT if es_prod else None
            ),
            performance_insight_encryption_key=llave_infra if es_prod else None,
            monitoring_interval=cdk.Duration.seconds(60) if es_prod else None,
            cloudwatch_logs_exports=["postgresql", "upgrade"] if es_prod else None,
        )

        self.secreto_admin = self.instancia.secret
        # ``instancia.secret`` es el adjunto: la política de borrado va en el secreto de origen.
        origen = self.instancia.node.try_find_child("Secret")
        if origen is not None:
            origen.apply_removal_policy(ret.removal_policy)
        self.secretos_roles: dict[str, sm.ISecret] = {}
        for rol in ROLES_BD:
            secreto = rds.DatabaseSecret(
                self,
                f"Secreto-{rol}",
                username=rol,
                secret_name=f"cc/{env}/db/{rol}",
                encryption_key=llave_infra,
                dbname=NOMBRE_BD,
            )
            secreto.apply_removal_policy(ret.removal_policy)
            self.secretos_roles[rol] = secreto.attach(self.instancia)

        self.proxy: rds.DatabaseProxy | None = None
        if eco.rds_proxy:
            self.proxy = rds.DatabaseProxy(
                self,
                "Proxy",
                proxy_target=rds.ProxyTarget.from_instance(self.instancia),
                secrets=[s for r, s in self.secretos_roles.items() if r != "migrador"],
                vpc=vpc,
                vpc_subnets=subredes_datos,
                security_groups=[sg_proxy],
                require_tls=True,
                max_connections_percent=70,
                idle_client_timeout=cdk.Duration.minutes(30),
            )
            self.proxy.apply_removal_policy(ret.removal_policy)

        self._reconocer_reglas(env, es_prod, eco.rds_multi_az)

        cdk.CfnOutput(self, "RdsEndpoint", value=self.instancia.db_instance_endpoint_address)
        cdk.CfnOutput(self, "RdsPuerto", value=self.instancia.db_instance_endpoint_port)
        if self.proxy is not None:
            cdk.CfnOutput(self, "ProxyEndpoint", value=self.proxy.endpoint)

    def _reconocer_reglas(self, env: str, es_prod: bool, multi_az: bool) -> None:
        reconocer(
            self,
            "AwsSolutions-SMG4",
            f"cc/{env}/db/*: la rotación de 30 días se agrega con el endurecimiento de "
            "producción (Fase 7); necesita que los roles existan y una ruta de red para la "
            "función de rotación. Las contraseñas se asignan en la tarea de migraciones.",
        )
        reconocer(
            self.instancia,
            "AwsSolutions-RDS6",
            "Los servicios se autentican con la contraseña del secreto de su rol (design.md "
            "§2.6); la autenticación IAM de la base no se usa en v1.",
        )
        reconocer(
            self.instancia,
            "AwsSolutions-RDS11",
            "El puerto 5432 es el que usan los servicios y los grupos de seguridad; la "
            "instancia está en subredes aisladas y solo admite entrada desde ECS, el proxy y "
            "las Lambdas por grupo de seguridad.",
        )
        if not multi_az:
            reconocer(
                self.instancia,
                "AwsSolutions-RDS3",
                "Prototipo de 1 a 2 semanas con presupuesto de 50 USD: instancia en una sola "
                "zona (tasks.md §0.4); producción usa Multi-AZ.",
            )
        if es_prod:
            reconocer(
                self.instancia,
                "AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/"
                "AmazonRDSEnhancedMonitoringRole]",
                "El monitoreo ampliado de RDS (60 s, solo prod) exige este rol: la política "
                "administrada de AWS es la única forma documentada de concederle a RDS el envío "
                "de métricas a CloudWatch Logs; no hay una política propia equivalente.",
            )
        if not es_prod:
            reconocer(
                self.instancia,
                "AwsSolutions-RDS10",
                "En test la instancia se destruye con cdk destroy, que ejecuta Samuel a mano "
                "(tasks.md, reglas 8 y 9); producción conserva la protección contra borrado.",
            )
