"""Stack CcStorage: buckets de S3 (design.md §13.4; CC-REQ-081, CC-NFR-009).

Todos los buckets tienen bloqueo total de acceso público, política que exige TLS y registro de
acceso hacia el bucket ``logs``. El cifrado es con la llave ``cc-{env}-infra`` y clave de bucket
habilitada, salvo ``frontend`` (cifrado administrado por S3, design.md §13.4) y ``logs``
(el registro de acceso de S3 no admite KMS).

Diferencias por ambiente (política de retención, ``infra/constructs/retencion.py``):

- ``test``: los buckets se borran con ``cdk destroy`` y vacían sus objetos al hacerlo. La
  retención de Object Lock en ``constancias`` es de 1 día (el mínimo de S3): los PDF más
  recientes de un día impiden vaciar el bucket hasta que venza su retención. Tampoco se aplica
  la política que niega el borrado de versiones de plantilla, porque impediría ese vaciado.
- ``prod``: ``RETAIN``, sin vaciado automático, sin retención por defecto hasta resolver PQ-24 y
  con la negación de borrado en ``plantillas``.

Réplica de ``constancias`` (CC-NFR-006, design.md §14.5; T-226): en ``prod`` el bucket replica
sus objetos (con su retención de Object Lock) al bucket ``constancias-replica`` de ``us-east-2``,
que crea ``CcBackupRecuperacion``. El bucket de destino debe existir antes de configurar la
réplica, así que ``CcStorage`` depende de ese stack (``infra/app.py``). Los nombres se arman en
``infra/constructs/recuperacion.py``: ningún valor viaja por referencias entre regiones. En
``test`` no se crea (la región de recuperación no está inicializada con ``cdk bootstrap``).
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs import recuperacion
from infra.constructs.nag import id_nag, reconocer
from infra.constructs.retencion import politica_retencion

# Origen permitido para subir cargas en ``test`` mientras no hay dominio propio (PQ-22): los
# dominios de CloudFront. Con ``dominio`` configurado se usa solo ese origen.
ORIGEN_CORS_SIN_DOMINIO = "https://*.cloudfront.net"
PATRON_VERSIONES_PLANTILLA = "plantillas/*/v*.json"
# Los PDF se guardan en ``constancias/{empresa}/{año}/{folio}.pdf`` (cc_constancias.almacenamiento).
PREFIJO_CONSTANCIAS = "constancias"


def nombre_bucket(env: str, cuenta: str, logico: str) -> str:
    """Nombre físico fijo de cada bucket (``cc-{env}-{cuenta}-{nombre}``).

    Con nombre conocido, los demás stacks (``CcCompute``, ``CcEdge``) lo importan por nombre sin
    referencias de CloudFormation que los acoplen a ``CcStorage`` (design.md §13.7, T-224).
    """
    return f"cc-{env}-{cuenta}-{logico}"


class StorageStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        id_: str,
        *,
        ambiente: Ambiente,
        llave_infra: kms.IKey,
        **kwargs,
    ) -> None:
        super().__init__(scope, id_, **kwargs)
        ret = politica_retencion(ambiente)
        self._ret = ret
        self._llave = llave_infra
        self._env = ambiente.nombre

        self.logs = self._bucket(
            "Logs",
            cifrado=s3.BucketEncryption.S3_MANAGED,
            con_llave=False,
            ciclo_vida=[
                s3.LifecycleRule(
                    id="expirar-logs-90-dias",
                    expiration=cdk.Duration.days(90),
                    abort_incomplete_multipart_upload_after=cdk.Duration.days(1),
                )
            ],
        )
        reconocer(
            self.logs,
            "AwsSolutions-S1",
            "Es el destino de los registros de acceso de los demás buckets; registrar sus "
            "propios accesos crearía un ciclo sin valor adicional (design.md §13.4).",
        )

        self.frontend = self._bucket(
            "Frontend",
            cifrado=s3.BucketEncryption.S3_MANAGED,
            con_llave=False,
            registro="frontend/",
        )

        self.plantillas = self._bucket(
            "Plantillas",
            versionado=True,
            registro="plantillas/",
            ciclo_vida=[
                s3.LifecycleRule(
                    id="expirar-versiones-no-actuales-365-dias",
                    noncurrent_version_expiration=cdk.Duration.days(365),
                    abort_incomplete_multipart_upload_after=cdk.Duration.days(1),
                )
            ],
        )
        if not ambiente.economia.permite_borrado:
            self.plantillas.add_to_resource_policy(
                iam.PolicyStatement(
                    sid="NegarBorradoDeVersionesDePlantilla",
                    effect=iam.Effect.DENY,
                    principals=[iam.AnyPrincipal()],
                    actions=["s3:DeleteObject", "s3:DeleteObjectVersion"],
                    resources=[self.plantillas.arn_for_objects(PATRON_VERSIONES_PLANTILLA)],
                )
            )

        retencion = (
            s3.ObjectLockRetention.governance(cdk.Duration.days(ret.object_lock_dias))
            if ret.object_lock_dias
            else None
        )
        self.constancias = self._bucket(
            "Constancias",
            versionado=True,
            registro="constancias/",
            object_lock=True,
            retencion_por_defecto=retencion,
        )

        # T-225. CloudFront (OAC) lee la SPA y los PDF. La política se define aquí y no en CcEdge:
        # un bucket admite una sola política y la de ``enforce_ssl`` ya vive en este stack. El
        # ARN exacto de la distribución crearía un ciclo CcStorage-CcEdge, así que se admite a las
        # distribuciones de esta cuenta (``docs/desviaciones.md``).
        for bucket, objetos in (
            (self.frontend, "*"),
            (self.constancias, f"{PREFIJO_CONSTANCIAS}/*"),
        ):
            bucket.add_to_resource_policy(
                iam.PolicyStatement(
                    sid="CloudFrontLeeConOac",
                    effect=iam.Effect.ALLOW,
                    principals=[iam.ServicePrincipal("cloudfront.amazonaws.com")],
                    actions=["s3:GetObject"],
                    resources=[bucket.arn_for_objects(objetos)],
                    conditions={
                        "StringLike": {
                            "aws:SourceArn": f"arn:{self.partition}:cloudfront::{self.account}"
                            ":distribution/*"
                        }
                    },
                )
            )

        self.rol_replicacion: iam.Role | None = None
        if recuperacion.recuperacion_habilitada(ambiente):
            self._replicar_constancias(ambiente)

        origen = f"https://{ambiente.dominio}" if ambiente.dominio else ORIGEN_CORS_SIN_DOMINIO
        self.cargas = self._bucket(
            "Cargas",
            registro="cargas/",
            ciclo_vida=[
                s3.LifecycleRule(
                    id="expirar-cargas-7-dias",
                    expiration=cdk.Duration.days(7),
                    abort_incomplete_multipart_upload_after=cdk.Duration.days(1),
                )
            ],
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.PUT],
                    allowed_origins=[origen],
                    allowed_headers=["*"],
                    exposed_headers=["ETag"],
                    max_age=3000,
                )
            ],
        )

        for nombre, bucket in {
            "LogsBucket": self.logs,
            "FrontendBucket": self.frontend,
            "PlantillasBucket": self.plantillas,
            "ConstanciasBucket": self.constancias,
            "CargasBucket": self.cargas,
        }.items():
            cdk.CfnOutput(self, nombre, value=bucket.bucket_name)

    def _bucket(
        self,
        nombre: str,
        *,
        cifrado: s3.BucketEncryption = s3.BucketEncryption.KMS,
        con_llave: bool = True,
        versionado: bool = False,
        registro: str | None = None,
        ciclo_vida: list[s3.LifecycleRule] | None = None,
        cors: list[s3.CorsRule] | None = None,
        object_lock: bool = False,
        retencion_por_defecto: s3.ObjectLockRetention | None = None,
    ) -> s3.Bucket:
        ret = self._ret
        extra: dict = {}
        if con_llave:
            extra = {"encryption_key": self._llave, "bucket_key_enabled": True}
        if registro:
            extra.update(server_access_logs_bucket=self.logs, server_access_logs_prefix=registro)
        if object_lock:
            extra.update(object_lock_enabled=True)
            if retencion_por_defecto is not None:
                extra.update(object_lock_default_retention=retencion_por_defecto)
        return s3.Bucket(
            self,
            nombre,
            bucket_name=nombre_bucket(self._env, self.account, nombre.lower()),
            encryption=cifrado,
            enforce_ssl=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=versionado or object_lock,
            lifecycle_rules=ciclo_vida,
            cors=cors,
            removal_policy=ret.removal_policy,
            auto_delete_objects=ret.auto_borrar_objetos,
            **extra,
        )

    def _replicar_constancias(self, ambiente: Ambiente) -> None:
        """Réplica de ``constancias`` hacia la región de recuperación (solo ``prod``).

        Sin retraso garantizado (S3 RTC cuesta aparte): el RPO de la réplica es de minutos. No
        replica las marcas de borrado: borrar en el origen nunca borra la réplica.
        """
        env = ambiente.nombre
        destino = recuperacion.arn_bucket_replica(env, self.account, self.partition)
        alias = recuperacion.arn_alias_llave_recuperacion(env, self.account, self.partition)
        # La llave se importa por ARN: el permiso va en el rol y no en la política de la llave
        # (modificarla desde aquí crearía una dependencia circular con CcSecurity).
        llave = kms.Key.from_key_arn(self, "LlaveInfraReplicacion", self._llave.key_arn)
        rol = iam.Role(
            self,
            "RolReplicacion",
            role_name=f"cc-{env}-s3-replicacion-constancias",
            description="Rol que S3 asume para replicar constancias a la región de recuperación",
            assumed_by=iam.ServicePrincipal(
                "s3.amazonaws.com",
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            ),
        )
        origen = self.constancias
        rol.add_to_policy(
            iam.PolicyStatement(
                sid="LeerConfiguracionDelOrigen",
                actions=["s3:GetReplicationConfiguration", "s3:ListBucket"],
                resources=[origen.bucket_arn],
            )
        )
        rol.add_to_policy(
            iam.PolicyStatement(
                sid="LeerObjetosDelOrigen",
                actions=[
                    "s3:GetObjectVersionForReplication",
                    "s3:GetObjectVersionAcl",
                    "s3:GetObjectVersionTagging",
                    "s3:GetObjectRetention",
                    "s3:GetObjectLegalHold",
                ],
                resources=[origen.arn_for_objects("*")],
            )
        )
        rol.add_to_policy(
            iam.PolicyStatement(
                sid="EscribirReplicaEnElDestino",
                actions=[
                    "s3:ReplicateObject",
                    "s3:ReplicateTags",
                    "s3:ObjectOwnerOverrideToBucketOwner",
                ],
                resources=[f"{destino}/*"],
            )
        )
        # Descifra con la llave de infraestructura (origen) y cifra con la de la región de
        # recuperación, identificada por su alias (el identificador no se conoce de antemano).
        llave.grant_decrypt(rol)
        rol.add_to_policy(
            iam.PolicyStatement(
                sid="CifrarReplicaConLlaveDeRecuperacion",
                actions=["kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"],
                resources=[recuperacion.arn_llaves_recuperacion(self.account, self.partition)],
                conditions={
                    "ForAnyValue:StringEquals": {
                        "kms:ResourceAliases": recuperacion.alias_llave_recuperacion(env)
                    }
                },
            )
        )
        self.rol_replicacion = rol

        cfn = self.constancias.node.default_child
        assert isinstance(cfn, s3.CfnBucket)
        cfn.replication_configuration = s3.CfnBucket.ReplicationConfigurationProperty(
            role=rol.role_arn,
            rules=[
                s3.CfnBucket.ReplicationRuleProperty(
                    id="constancias-a-recuperacion",
                    status="Enabled",
                    priority=1,
                    filter=s3.CfnBucket.ReplicationRuleFilterProperty(prefix=""),
                    delete_marker_replication=s3.CfnBucket.DeleteMarkerReplicationProperty(
                        status="Disabled"
                    ),
                    source_selection_criteria=s3.CfnBucket.SourceSelectionCriteriaProperty(
                        sse_kms_encrypted_objects=s3.CfnBucket.SseKmsEncryptedObjectsProperty(
                            status="Enabled"
                        )
                    ),
                    destination=s3.CfnBucket.ReplicationDestinationProperty(
                        bucket=destino,
                        encryption_configuration=s3.CfnBucket.EncryptionConfigurationProperty(
                            replica_kms_key_id=alias
                        ),
                    ),
                )
            ],
        )
        for recurso, motivo in (
            (
                self.constancias.arn_for_objects("*"),
                "los objetos del bucket constancias que S3 replica (todas sus versiones)",
            ),
            (f"{destino}/*", "los objetos del bucket réplica de la región de recuperación"),
            (
                recuperacion.arn_llaves_recuperacion(self.account, self.partition),
                "la llave de la región de recuperación, identificada por su alias (el "
                "identificador no se conoce antes de crearla; la condición kms:ResourceAliases "
                "la limita a cc-{env}-recuperacion)".replace("{env}", env),
            ),
        ):
            reconocer(
                rol,
                f"AwsSolutions-IAM5[Resource::{id_nag(self, recurso)}]",
                f"El rol de replicación solo opera sobre {motivo}; el comodín es de objetos de un "
                "único bucket o de las llaves de una región, no de recursos ajenos.",
            )
