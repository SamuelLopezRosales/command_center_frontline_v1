"""Stack CcAuth: Cognito y las Lambdas de sus triggers (design.md §11.2, §4.6, §13.1).

Grupo de usuarios ``cc-{env}``:
- MFA obligatorio con aplicación autenticadora (TOTP); sin SMS (CC-REQ-002, DS-21).
- Contraseña de al menos 12 caracteres con mayúscula, minúscula, número y símbolo (CC-REQ-001).
- Registro propio, controlado por ``cognito-pre-signup`` (invitación de un solo uso, D-02). El
  código viaja en el atributo ``custom:codigo_invitacion``.
- Recuperación de contraseña por correo (CC-REQ-006).
- Plan de funciones Essentials (DS-20): necesario para que ``cognito-pre-token`` (evento V2)
  agregue ``empresa_id`` y ``rol`` al token de acceso. **Tiene costo** por usuario activo.
- Token de acceso e ID de 15 minutos; actualización de 8 horas con rotación (CC-REQ-004).

Lambdas (Python 3.12, arm64, 256 MB, 10 s, en la VPC, concurrencia reservada 5, registros de
30 días): se publican con el alias ``live`` y Cognito invoca el alias, de modo que revertir es
mover el alias (design.md §14.6). Se conectan a PostgreSQL como ``svc_dashboard``.

El código sale de ``build/lambdas`` (``scripts/empaquetar_lambdas.py``, con psycopg para arm64).
Si no existe, la síntesis falla: desplegar sin dependencias dejaría a todos sin poder iniciar
sesión. Las pruebas usan ``CC_LAMBDAS_DESDE_FUENTE=1`` para no depender del paquete.
"""

from __future__ import annotations

import os
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as sm

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs.nag import reconocer
from infra.constructs.retencion import politica_retencion

RAIZ = Path(__file__).resolve().parents[2]
PAQUETE = RAIZ / "build" / "lambdas"
FUENTE = RAIZ / "lambdas"
GRUPO_SUBREDES_APLICACION = "aplicacion"
CONCURRENCIA_RESERVADA = 5
# Por defecto el MFA es obligatorio (CC-REQ-002); "OPTIONAL" u "OFF" solo en ambientes de prueba.
MODOS_MFA = {
    "ON": cognito.Mfa.REQUIRED,
    "OPTIONAL": cognito.Mfa.OPTIONAL,
    "OFF": cognito.Mfa.OFF,
}
ATRIBUTO_CODIGO = "codigo_invitacion"  # se lee como custom:codigo_invitacion

# nombre -> (módulo del handler, descripción)
TRIGGERS: dict[str, tuple[str, str]] = {
    "pre-signup": ("pre_signup", "LAM-07: valida la invitación antes del registro"),
    "post-confirmation": ("post_confirmation", "LAM-08: crea el usuario al confirmar el correo"),
    "pre-token": ("pre_token", "LAM-09: agrega empresa_id y rol al token de acceso"),
}


def _codigo_lambdas() -> lambda_.Code:
    if os.environ.get("CC_LAMBDAS_DESDE_FUENTE") == "1":
        return lambda_.Code.from_asset(
            str(FUENTE), exclude=["**/tests/**", "**/__pycache__/**", "*.pyc", ".gitkeep"]
        )
    if not (PAQUETE / "cognito_triggers").is_dir():
        raise FileNotFoundError(
            "Falta build/lambdas. Ejecute: uv run python scripts/empaquetar_lambdas.py"
        )
    return lambda_.Code.from_asset(str(PAQUETE))


class AuthStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        id_: str,
        *,
        ambiente: Ambiente,
        vpc: ec2.IVpc,
        sg_lambda: ec2.ISecurityGroup,
        llave_infra: kms.IKey,
        secreto_bd: sm.ISecret,
        host_bd: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, id_, **kwargs)
        env = ambiente.nombre
        ret = politica_retencion(ambiente)
        es_prod = not ambiente.economia.permite_borrado
        # La llave se importa por ARN: los permisos de uso van en el rol de cada función. El
        # secreto adjunto a la instancia no expone su llave, así que CDK no concede el descifrado.
        llave = kms.Key.from_key_arn(self, "LlaveInfraImportada", llave_infra.key_arn)
        # Importado para no modificar CcNetwork desde aquí (dependencia circular).
        sg = ec2.SecurityGroup.from_security_group_id(
            self, "SgLambdaImportado", sg_lambda.security_group_id, mutable=False
        )

        self.pool = cognito.UserPool(
            self,
            "Pool",
            user_pool_name=f"cc-{env}",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True, username=False),
            sign_in_case_sensitive=False,
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=False),
                fullname=cognito.StandardAttribute(required=True, mutable=True),
            ),
            custom_attributes={
                ATRIBUTO_CODIGO: cognito.StringAttribute(min_len=1, max_len=128, mutable=True)
            },
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
                temp_password_validity=cdk.Duration.days(3),
            ),
            mfa=MODOS_MFA[ambiente.economia.mfa],
            mfa_second_factor=(
                cognito.MfaSecondFactor(sms=False, otp=True)
                if ambiente.economia.mfa != "OFF"
                else None
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            feature_plan=cognito.FeaturePlan.ESSENTIALS,
            email=cognito.UserPoolEmail.with_cognito(),
            user_verification=cognito.UserVerificationConfig(
                email_style=cognito.VerificationEmailStyle.CODE,
                email_subject="Command Center: confirma tu correo",
                email_body="Tu código de verificación de Command Center es {####}",
            ),
            deletion_protection=es_prod,
            removal_policy=ret.removal_policy,
        )

        self.cliente = self.pool.add_client(
            "ClienteSpa",
            user_pool_client_name=f"cc-{env}-spa",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=True),
            disable_o_auth=True,
            access_token_validity=cdk.Duration.minutes(15),
            id_token_validity=cdk.Duration.minutes(15),
            refresh_token_validity=cdk.Duration.hours(8),
            refresh_token_rotation_grace_period=cdk.Duration.seconds(30),
            enable_token_revocation=True,
            prevent_user_existence_errors=True,
            read_attributes=cognito.ClientAttributes().with_standard_attributes(
                email=True, email_verified=True, fullname=True
            ),
            write_attributes=cognito.ClientAttributes()
            .with_standard_attributes(email=True, fullname=True)
            .with_custom_attributes(ATRIBUTO_CODIGO),
        )

        codigo = _codigo_lambdas()
        subredes = ec2.SubnetSelection(subnet_group_name=GRUPO_SUBREDES_APLICACION)
        self.funciones: dict[str, lambda_.Function] = {}
        self.alias: dict[str, lambda_.Alias] = {}
        for nombre, (modulo, descripcion) in TRIGGERS.items():
            entorno = {"CC_DB_SECRET_ARN": secreto_bd.secret_arn}
            if host_bd:
                entorno["CC_DB_HOST"] = host_bd
            fn = lambda_.Function(
                self,
                f"Fn-{nombre}",
                function_name=f"cc-{env}-cognito-{nombre}",
                description=descripcion,
                runtime=lambda_.Runtime.PYTHON_3_12,
                architecture=lambda_.Architecture.ARM_64,
                handler=f"cognito_triggers.{modulo}.handler",
                code=codigo,
                memory_size=256,
                timeout=cdk.Duration.seconds(10),
                reserved_concurrent_executions=(
                    CONCURRENCIA_RESERVADA if ambiente.economia.reservar_concurrencia else None
                ),
                environment=entorno,
                vpc=vpc,
                vpc_subnets=subredes,
                security_groups=[sg],
                log_group=logs.LogGroup(
                    self,
                    f"Logs-{nombre}",
                    log_group_name=f"/aws/lambda/cc-{env}-cognito-{nombre}",
                    retention=logs.RetentionDays.ONE_MONTH,
                    removal_policy=ret.removal_policy,
                ),
                current_version_options=lambda_.VersionOptions(removal_policy=ret.removal_policy),
            )
            secreto_bd.grant_read(fn)
            llave.grant_decrypt(fn)
            self.funciones[nombre] = fn
            self.alias[nombre] = lambda_.Alias(
                self, f"Alias-{nombre}", alias_name="live", version=fn.current_version
            )

        self.pool.add_trigger(cognito.UserPoolOperation.PRE_SIGN_UP, self.alias["pre-signup"])
        self.pool.add_trigger(
            cognito.UserPoolOperation.POST_CONFIRMATION, self.alias["post-confirmation"]
        )
        self.pool.add_trigger(
            cognito.UserPoolOperation.PRE_TOKEN_GENERATION_CONFIG,
            self.alias["pre-token"],
            cognito.LambdaVersion.V2_0,
        )

        # Política aparte: dentro del rol por defecto crearía un ciclo (el grupo invoca a la
        # función y la función necesitaría el ARN del grupo).
        iam.Policy(
            self,
            "PermisoActualizarAtributos",
            statements=[
                iam.PolicyStatement(
                    actions=["cognito-idp:AdminUpdateUserAttributes"],
                    resources=[self.pool.user_pool_arn],
                )
            ],
            roles=[self.funciones["post-confirmation"].role],
        )

        self._reconocer_reglas(env, es_prod, ambiente.economia.mfa)

        cdk.CfnOutput(self, "UserPoolId", value=self.pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolArn", value=self.pool.user_pool_arn)
        cdk.CfnOutput(self, "ClienteSpaId", value=self.cliente.user_pool_client_id)
        cdk.CfnOutput(
            self,
            "Emisor",
            value=f"https://cognito-idp.{self.region}.amazonaws.com/{self.pool.user_pool_id}",
        )

    def _reconocer_reglas(self, env: str, es_prod: bool, mfa: str) -> None:
        for regla in ("AwsSolutions-COG3", "AwsSolutions-COG8"):
            reconocer(
                self.pool,
                regla,
                "El modo de seguridad avanzada y la rotación a plan Plus tienen un costo mayor. "
                "Se usa el plan Essentials (DS-20); el bloqueo por intentos fallidos integrado "
                "cubre CC-REQ-003.",
            )
        if mfa != "ON":
            reconocer(
                self.pool,
                "AwsSolutions-COG2",
                f"MFA {mfa} por decisión del responsable del ambiente (docs/desviaciones.md). "
                "Solo se admite fuera de los ambientes tipo prod.",
            )
        for fn in self.funciones.values():
            reconocer(
                fn,
                "AwsSolutions-L1",
                "Python 3.12 es el tiempo de ejecución fijado por el diseño (restricción de "
                "stack, design.md §1.4) para todos los componentes.",
            )
            reconocer(
                fn.role,
                "AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/"
                "AWSLambdaVPCAccessExecutionRole]",
                "Política administrada de AWS para que una Lambda en la VPC cree sus interfaces "
                "de red y escriba registros.",
            )
            reconocer(
                fn.role,
                "AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/"
                "AWSLambdaBasicExecutionRole]",
                "Política administrada de AWS para que la función escriba sus registros.",
            )
            reconocer(
                fn.role,
                "AwsSolutions-IAM5[Resource::*]",
                "Las acciones ec2:CreateNetworkInterface, DescribeNetworkInterfaces y "
                "DeleteNetworkInterface de una Lambda en VPC no admiten un recurso específico.",
            )
            reconocer(
                fn.role,
                "AwsSolutions-IAM5[Action::kms:GenerateDataKey*]",
                "Acciones estándar de CDK para leer un secreto cifrado; el recurso es solo la "
                f"llave cc-{env}-infra.",
            )
            reconocer(
                fn.role,
                "AwsSolutions-IAM5[Action::kms:ReEncrypt*]",
                "Acciones estándar de CDK para leer un secreto cifrado; el recurso es solo la "
                f"llave cc-{env}-infra.",
            )
