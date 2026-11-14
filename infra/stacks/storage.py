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

La réplica de ``constancias`` hacia ``us-east-2`` (CC-NFR-006) se agrega con la recuperación ante
desastres (Fase 7); no se crea aquí.
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs.nag import reconocer
from infra.constructs.retencion import politica_retencion

# Origen permitido para subir cargas en ``test`` mientras no hay dominio propio (PQ-22): los
# dominios de CloudFront. Con ``dominio`` configurado se usa solo ese origen.
ORIGEN_CORS_SIN_DOMINIO = "https://*.cloudfront.net"
PATRON_VERSIONES_PLANTILLA = "plantillas/*/v*.json"


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
