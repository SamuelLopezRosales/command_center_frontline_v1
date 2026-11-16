"""Stacks de respaldo: ``CcBackup`` (región principal) y ``CcBackupRecuperacion`` (``us-east-2``)
(design.md §14.5, §15.5; CC-NFR-005 y CC-NFR-006; T-226).

``CcBackup``: bóveda ``cc-{env}-respaldos`` cifrada con la llave ``cc-{env}-infra`` y un plan diario
de AWS Backup para la instancia de RDS (además del PITR de la propia instancia):

- ``prod``: retención de 35 días, **copia diaria a la bóveda de ``us-east-2``** con la misma
  retención, bloqueo de la bóveda en modo de gobierno (7 días mínimos; se puede quitar con un
  permiso explícito) y una política de acceso que niega borrar o acortar puntos de recuperación.
  La bóveda se conserva al destruir el stack.
- ``test``: retención de ``retencion_respaldos_dias`` (1 día), sin copia, sin bloqueo y bóveda
  borrable. CloudFormation no borra una bóveda con puntos de recuperación: ver
  ``docs/ambientes.md`` (se vacían solos al vencer su día).

``CcBackupRecuperacion`` (solo ``prod``): llave, bóveda y bucket réplica de ``constancias`` en la
región de recuperación. En ``test`` **no se crea** (región sin ``cdk bootstrap``): queda definido,
probado con un ambiente ``prod`` sintético y sin desplegar. La réplica del bucket se configura en
``CcStorage``; aquí vive el destino. Los nombres compartidos están en
``infra/constructs/recuperacion.py`` (sin referencias entre stacks ni entre regiones).

El respaldo de ``plantillas`` (réplica opcional del diseño) no se activa: las versiones de las
plantillas son inmutables y el versionado del bucket las conserva (``docs/desviaciones.md``).
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_backup as backup
from aws_cdk import aws_events as events
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs import recuperacion
from infra.constructs.nag import id_nag, reconocer
from infra.constructs.retencion import politica_retencion
from infra.stacks.storage import nombre_bucket

# 07:00 UTC = 01:00 en la Ciudad de México: fuera del horario de envíos de WhatsApp (08:00 a 20:00).
HORA_RESPALDO_UTC = 7
VENTANA_INICIO = cdk.Duration.hours(1)
VENTANA_FIN = cdk.Duration.hours(3)


class BackupStack(cdk.Stack):
    """Plan de AWS Backup de RDS en la región principal, con copia a la región de recuperación."""

    def __init__(
        self,
        scope: Construct,
        id_: str,
        *,
        ambiente: Ambiente,
        llave_infra_arn: str,
        instancia_arn: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, id_, **kwargs)
        env = ambiente.nombre
        ret = politica_retencion(ambiente)
        es_prod = recuperacion.recuperacion_habilitada(ambiente)
        # Importada por ARN: los permisos de uso van en el rol de AWS Backup (sin ciclos con
        # CcSecurity, como el resto de los stacks).
        llave = kms.Key.from_key_arn(self, "LlaveInfraImportada", llave_infra_arn)

        self.boveda = backup.BackupVault(
            self,
            "Boveda",
            backup_vault_name=recuperacion.nombre_boveda(env),
            encryption_key=llave,
            removal_policy=ret.removal_policy,
            # Sin borrado accidental: niega DeleteRecoveryPoint, UpdateRecoveryPointLifecycle y
            # PutBackupVaultAccessPolicy a todos los principales (solo prod).
            block_recovery_point_deletion=es_prod,
            lock_configuration=(
                backup.LockConfiguration(
                    min_retention=cdk.Duration.days(recuperacion.RETENCION_MINIMA_BOVEDA_DIAS)
                )
                if es_prod
                else None
            ),
        )

        copias: list[backup.BackupPlanCopyActionProps] = []
        if es_prod:
            boveda_destino = backup.BackupVault.from_backup_vault_arn(
                self,
                "BovedaRecuperacion",
                recuperacion.arn_boveda_recuperacion(env, self.account, self.partition),
            )
            copias.append(
                backup.BackupPlanCopyActionProps(
                    destination_backup_vault=boveda_destino,
                    delete_after=recuperacion.retencion_respaldos(ambiente),
                )
            )

        self.plan = backup.BackupPlan(
            self,
            "Plan",
            backup_plan_name=f"cc-{env}-rds-diario",
            backup_vault=self.boveda,
            backup_plan_rules=[
                backup.BackupPlanRule(
                    rule_name="diario",
                    schedule_expression=events.Schedule.cron(
                        hour=str(HORA_RESPALDO_UTC), minute="0"
                    ),
                    start_window=VENTANA_INICIO,
                    completion_window=VENTANA_FIN,
                    delete_after=recuperacion.retencion_respaldos(ambiente),
                    copy_actions=copias or None,
                )
            ],
        )

        self.rol = self._rol_de_respaldo(env, llave_infra_arn, es_prod)
        # L1: la clase L2 agrega al rol la política administrada AWSBackupServiceRolePolicyForBackup
        # (todos los servicios); aquí solo vale la política mínima del rol propio.
        self.seleccion = backup.CfnBackupSelection(
            self,
            "Seleccion",
            backup_plan_id=self.plan.backup_plan_id,
            backup_selection=backup.CfnBackupSelection.BackupSelectionResourceTypeProperty(
                iam_role_arn=self.rol.role_arn,
                selection_name=f"cc-{env}-rds",
                resources=[instancia_arn],
            ),
        )

        cdk.CfnOutput(self, "BovedaNombre", value=self.boveda.backup_vault_name)
        cdk.CfnOutput(self, "PlanId", value=self.plan.backup_plan_id)
        cdk.CfnOutput(
            self, "RetencionDias", value=str(recuperacion.retencion_respaldos(ambiente).to_days())
        )
        self._reconocer(env, es_prod)

    def _rol_de_respaldo(self, env: str, llave_infra_arn: str, es_prod: bool) -> iam.Role:
        """Rol de AWS Backup con permisos mínimos para respaldar y copiar la instancia de RDS.

        En lugar de la política administrada ``AWSBackupServiceRolePolicyForBackup`` (abarca todos
        los servicios), solo concede lo que necesita RDS: instantáneas con el prefijo de AWS Backup.
        La restauración la ejecuta una persona con su propio rol (``allow_restores=False``).
        """
        cuenta, region, particion = self.account, self.region, self.partition
        rol = iam.Role(
            self,
            "RolRespaldo",
            role_name=f"cc-{env}-backup",
            description="Rol que AWS Backup asume para respaldar la instancia de RDS",
            assumed_by=iam.ServicePrincipal(
                "backup.amazonaws.com",
                conditions={"StringEquals": {"aws:SourceAccount": cuenta}},
            ),
        )
        instancias = f"arn:{particion}:rds:{region}:{cuenta}:db:*"
        instantaneas = f"arn:{particion}:rds:{region}:{cuenta}:snapshot:awsbackup:*"
        rol.add_to_policy(
            iam.PolicyStatement(
                sid="RespaldarInstanciasEtiquetadas",
                actions=[
                    "rds:DescribeDBInstances",
                    "rds:CreateDBSnapshot",
                    "rds:ListTagsForResource",
                ],
                resources=[instancias],
                conditions={"StringEquals": {"aws:ResourceTag/ambiente": env}},
            )
        )
        rol.add_to_policy(
            iam.PolicyStatement(
                sid="AdministrarInstantaneasDeBackup",
                actions=[
                    "rds:DescribeDBSnapshots",
                    "rds:CreateDBSnapshot",
                    "rds:CopyDBSnapshot",
                    "rds:DeleteDBSnapshot",
                    "rds:AddTagsToResource",
                    "rds:ListTagsForResource",
                ],
                resources=[instantaneas],
            )
        )
        rol.add_to_policy(
            iam.PolicyStatement(
                sid="UsarLlaveDeInfraestructura",
                actions=[
                    "kms:Decrypt",
                    "kms:DescribeKey",
                    "kms:GenerateDataKey",
                    "kms:ReEncryptFrom",
                    "kms:ReEncryptTo",
                    "kms:CreateGrant",
                ],
                resources=[llave_infra_arn],
            )
        )
        if es_prod:
            rol.add_to_policy(
                iam.PolicyStatement(
                    sid="CopiarARegionDeRecuperacion",
                    actions=["backup:CopyIntoBackupVault"],
                    resources=[recuperacion.arn_boveda_recuperacion(env, cuenta, particion)],
                )
            )
            rol.add_to_policy(
                iam.PolicyStatement(
                    sid="UsarLlaveDeRecuperacion",
                    actions=[
                        "kms:Encrypt",
                        "kms:DescribeKey",
                        "kms:GenerateDataKey",
                        "kms:ReEncryptTo",
                        "kms:CreateGrant",
                    ],
                    resources=[recuperacion.arn_llaves_recuperacion(cuenta, particion)],
                    conditions={
                        "ForAnyValue:StringEquals": {
                            "kms:ResourceAliases": recuperacion.alias_llave_recuperacion(env)
                        }
                    },
                )
            )
        return rol

    def _reconocer(self, env: str, es_prod: bool) -> None:
        instancias = f"arn:{self.partition}:rds:{self.region}:{self.account}:db:*"
        instantaneas = f"arn:{self.partition}:rds:{self.region}:{self.account}:snapshot:awsbackup:*"
        reconocer(
            self.rol,
            f"AwsSolutions-IAM5[Resource::{id_nag(self, instancias)}]",
            f"AWS Backup respalda la instancia de RDS de cc-{env}; el identificador de la "
            "instancia lo genera CloudFormation y no se conoce al escribir la política, así que el "
            "recurso es "
            f"cualquier instancia de la cuenta y la región acotada por la etiqueta ambiente={env}.",
        )
        reconocer(
            self.rol,
            f"AwsSolutions-IAM5[Resource::{id_nag(self, instantaneas)}]",
            "AWS Backup nombra sus instantáneas con el prefijo awsbackup: y un sufijo que no se "
            "conoce de antemano; el comodín se limita a ese prefijo.",
        )
        if es_prod:
            llaves = recuperacion.arn_llaves_recuperacion(self.account, self.partition)
            reconocer(
                self.rol,
                f"AwsSolutions-IAM5[Resource::{id_nag(self, llaves)}]",
                "La llave de la región de recuperación se identifica por su alias (el "
                "identificador no se conoce antes de crearla): el recurso son las llaves de esa "
                "región y cuenta y "
                f"la condición kms:ResourceAliases la limita a cc-{env}-recuperacion.",
            )


class BackupRecoveryStack(cdk.Stack):
    """Región de recuperación (``us-east-2``): llave, bóveda y réplica de ``constancias``."""

    def __init__(self, scope: Construct, id_: str, *, ambiente: Ambiente, **kwargs) -> None:
        super().__init__(scope, id_, **kwargs)
        if not recuperacion.recuperacion_habilitada(ambiente):
            raise ValueError(
                "la región de recuperación solo se define en prod: en test no está inicializada "
                "con cdk bootstrap (docs/desviaciones.md)"
            )
        env = ambiente.nombre
        ret = politica_retencion(ambiente)

        self.llave = kms.Key(
            self,
            "LlaveRecuperacion",
            alias=recuperacion.alias_llave_recuperacion(env),
            description="Cifrado de la región de recuperación de Command Center",
            enable_key_rotation=True,
            rotation_period=cdk.Duration.days(365),
            pending_window=cdk.Duration.days(ret.kms_dias_espera),
            removal_policy=ret.removal_policy,
        )
        self.boveda = backup.BackupVault(
            self,
            "BovedaRecuperacion",
            backup_vault_name=recuperacion.nombre_boveda_recuperacion(env),
            encryption_key=self.llave,
            removal_policy=ret.removal_policy,
            block_recovery_point_deletion=True,
            lock_configuration=backup.LockConfiguration(
                min_retention=cdk.Duration.days(recuperacion.RETENCION_MINIMA_BOVEDA_DIAS)
            ),
        )

        logs = s3.Bucket(
            self,
            "Logs",
            bucket_name=nombre_bucket(env, self.account, "recuperacion-logs"),
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=ret.removal_policy,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expirar-logs-90-dias",
                    expiration=cdk.Duration.days(90),
                    abort_incomplete_multipart_upload_after=cdk.Duration.days(1),
                )
            ],
        )
        reconocer(
            logs,
            "AwsSolutions-S1",
            "Es el destino de los registros de acceso de la réplica; registrar sus propios accesos "
            "crearía un ciclo sin valor adicional (igual que el bucket logs de CcStorage).",
        )
        # Réplica de constancias: versionada y con Object Lock (la retención de cada objeto llega
        # con la réplica). Sin retención por defecto: la fija el origen (PQ-24).
        self.replica = s3.Bucket(
            self,
            "Replica",
            bucket_name=recuperacion.nombre_bucket_replica(env, self.account),
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.llave,
            bucket_key_enabled=True,
            enforce_ssl=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=True,
            object_lock_enabled=True,
            server_access_logs_bucket=logs,
            server_access_logs_prefix="constancias-replica/",
            removal_policy=ret.removal_policy,
        )

        cdk.CfnOutput(self, "LlaveRecuperacionArn", value=self.llave.key_arn)
        cdk.CfnOutput(self, "BovedaRecuperacionArn", value=self.boveda.backup_vault_arn)
        cdk.CfnOutput(self, "BucketReplica", value=self.replica.bucket_name)
