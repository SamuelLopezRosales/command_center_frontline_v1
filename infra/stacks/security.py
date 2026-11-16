"""Stack CcSecurity: llaves de KMS, secretos y parámetros (design.md §8.3, §11.7, §13.1).

- ``cc-{env}-datos``: llave maestra del cifrado de sobre de los datos sensibles (CC-REQ-151).
- ``cc-{env}-infra``: cifrado de buckets, colas, logs y secretos.
- Secretos: se crean con un valor aleatorio. Los de Meta y la llave de firma de CloudFront
  se reemplazan después (vinculación con Meta, PQ-07; T-138). Ningún valor aparece en la
  plantilla.
- Parámetros de SSM con la configuración que cambia sin redesplegar (§13.8).
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_secretsmanager as sm
from aws_cdk import aws_ssm as ssm

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs.nag import reconocer
from infra.constructs.retencion import politica_retencion

# Secreto -> descripción. Plantilla JSON del valor generado (None: cadena aleatoria simple).
SECRETOS: dict[str, tuple[str, str | None]] = {
    "meta": (
        "Credenciales de Meta WhatsApp Cloud API (se cargan al vincular la cuenta, PQ-07)",
        '{"phone_number_id":"","waba_id":"","token":"","verify_token":"","graph_version":""}',
    ),
    "hmac-celular": ("Llave HMAC del hash de celular; solo la lee colaboradores (§8.4)", None),
    "hmac-codigo": ("Llave HMAC del código de verificación; solo la lee whatsapp (§7.2)", None),
    "internal-auth": ("Secreto del token interno entre servicios (§11.1)", None),
    "cf-signing-key": (
        "Llave privada de firma de CloudFront; se carga en T-138 (§11.3)",
        '{"key_pair_id":"","private_key_pem":""}',
    ),
    "origin-verify": (
        "Encabezado secreto de origen: CloudFront lo agrega y el ALB lo exige en las rutas de "
        "API Gateway (§11.4, T-225). Lo leen CloudFormation (referencia dinámica) y nadie más",
        None,
    ),
}

PARAMETROS: dict[str, str] = {
    "estrategia-entrega": "enlace",
    "horario-envio-inicio": "08:00",
    "horario-envio-fin": "20:00",
    "zona-horaria": "America/Mexico_City",
    "tope-mensajes-dia": "1000",
    "antiabuso-mensajes-minuto": "20",
    "antiabuso-solicitudes-dia": "5",
}


class SecurityStack(cdk.Stack):
    def __init__(self, scope: Construct, id_: str, *, ambiente: Ambiente, **kwargs) -> None:
        super().__init__(scope, id_, **kwargs)
        env = ambiente.nombre
        ret = politica_retencion(ambiente)

        self.llave_datos = kms.Key(
            self,
            "LlaveDatos",
            alias=f"alias/cc-{env}-datos",
            description="Cifrado de sobre de datos sensibles de Command Center",
            enable_key_rotation=True,
            rotation_period=cdk.Duration.days(365),
            pending_window=cdk.Duration.days(ret.kms_dias_espera),
            removal_policy=ret.removal_policy,
        )
        self.llave_infra = kms.Key(
            self,
            "LlaveInfra",
            alias=f"alias/cc-{env}-infra",
            description="Cifrado de infraestructura de Command Center",
            enable_key_rotation=True,
            rotation_period=cdk.Duration.days(365),
            pending_window=cdk.Duration.days(ret.kms_dias_espera),
            removal_policy=ret.removal_policy,
        )

        # Servicios de AWS que usan la llave sin un rol propio: EventBridge escribe en las colas
        # ``ev-*`` cifradas, SES publica rebotes y quejas en el tema SNS, SNS entrega ese tema a la
        # cola cifrada ``notif-respaldo`` (T-224) y CloudWatch publica sus alarmas. Limitado a esta
        # cuenta para evitar el uso desde otras cuentas.
        self.llave_infra.add_to_resource_policy(
            iam.PolicyStatement(
                sid="ServiciosDeAwsDeMensajeria",
                effect=iam.Effect.ALLOW,
                principals=[
                    iam.ServicePrincipal("events.amazonaws.com"),
                    iam.ServicePrincipal("ses.amazonaws.com"),
                    iam.ServicePrincipal("sns.amazonaws.com"),
                    iam.ServicePrincipal("cloudwatch.amazonaws.com"),
                ],
                actions=["kms:Decrypt", "kms:GenerateDataKey*"],
                resources=["*"],
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            )
        )

        # T-225. CloudFront lee los buckets cifrados (SPA y constancias) con OAC: el servicio de
        # CloudFront usa la llave sin un rol propio. La condición limita a las distribuciones de
        # esta cuenta (el ARN exacto de la distribución crearía un ciclo CcSecurity-CcEdge).
        self.llave_infra.add_to_resource_policy(
            iam.PolicyStatement(
                sid="CloudFrontLeeObjetosCifrados",
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("cloudfront.amazonaws.com")],
                actions=["kms:Decrypt"],
                resources=["*"],
                conditions={
                    "StringLike": {
                        "aws:SourceArn": f"arn:{self.partition}:cloudfront::{self.account}"
                        ":distribution/*"
                    }
                },
            )
        )
        # CloudTrail (CcObservability) cifra sus archivos con esta llave. Las dos sentencias son las
        # que documenta CloudTrail; el contexto de cifrado limita a los trails ``cc-{env}-*``.
        self.llave_infra.add_to_resource_policy(
            iam.PolicyStatement(
                sid="CloudTrailCifraRegistros",
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("cloudtrail.amazonaws.com")],
                actions=["kms:GenerateDataKey*"],
                resources=["*"],
                conditions={
                    "StringLike": {
                        "kms:EncryptionContext:aws:cloudtrail:arn": f"arn:{self.partition}:"
                        f"cloudtrail:*:{self.account}:trail/cc-{env}-*"
                    }
                },
            )
        )
        self.llave_infra.add_to_resource_policy(
            iam.PolicyStatement(
                sid="CloudTrailDescribeLlave",
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("cloudtrail.amazonaws.com")],
                actions=["kms:DescribeKey"],
                resources=["*"],
            )
        )

        self.secretos: dict[str, sm.Secret] = {}
        for nombre, (descripcion, plantilla) in SECRETOS.items():
            generar = (
                sm.SecretStringGenerator(
                    secret_string_template=plantilla,
                    generate_string_key="_marcador",
                    exclude_punctuation=True,
                )
                if plantilla
                else sm.SecretStringGenerator(password_length=64, exclude_punctuation=True)
            )
            self.secretos[nombre] = sm.Secret(
                self,
                f"Secreto-{nombre}",
                secret_name=f"cc/{env}/{nombre}",
                description=descripcion,
                encryption_key=self.llave_infra,
                generate_secret_string=generar,
                removal_policy=ret.removal_policy,
            )

        for nombre, valor in PARAMETROS.items():
            ssm.StringParameter(
                self,
                f"Parametro-{nombre}",
                parameter_name=f"/cc/{env}/{nombre}",
                string_value=valor,
                description=f"Command Center: {nombre}",
            )

        for nombre, secreto in self.secretos.items():
            reconocer(
                secreto,
                "AwsSolutions-SMG4",
                f"cc/{env}/{nombre}: la rotación de llaves HMAC exige recalcular hashes "
                "(design.md §8.4) y las credenciales de Meta las rota Meta; la rotación es un "
                "procedimiento operativo, no automática.",
            )

        cdk.CfnOutput(self, "LlaveDatosArn", value=self.llave_datos.key_arn)
        cdk.CfnOutput(self, "LlaveInfraArn", value=self.llave_infra.key_arn)
