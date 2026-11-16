"""Stack CcFrontend: despliegue de la SPA, configuración de ejecución e invalidación (T-139;
design.md §13.1, §13.7).

Publica ``frontend/dist`` (``npm run build`` en ``frontend/``) en el bucket ``frontend`` de
``CcStorage`` (importado por nombre) y genera ``config.json`` junto a la SPA con los identificadores
públicos de Cognito, la región y la URL base de la API. **Sin secretos**: la SPA lo lee antes de
montar (``frontend/src/shared/config.ts``), así el mismo paquete sirve a cualquier ambiente sin
recompilar. Después del despliegue invalida ``/*`` en CloudFront.

Si ``frontend/dist`` no existe la síntesis falla con el comando que lo genera: publicar un bucket
vacío dejaría la aplicación caída sin ningún aviso.
"""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy

from constructs import Construct
from infra.config.esquema import Ambiente
from infra.constructs.nag import reconocer

RAIZ = Path(__file__).resolve().parents[2]
DIST_SPA = RAIZ / "frontend" / "dist"
# El HTML y config.json cambian en cada despliegue y se invalidan en CloudFront; el navegador
# siempre revalida (los archivos con huella de contenido de /assets no se ven afectados).
CACHE_CONTROL = "public, max-age=0, must-revalidate"


def verificar_dist(ruta: Path = DIST_SPA) -> Path:
    if not (ruta / "index.html").is_file():
        raise FileNotFoundError(
            "Falta frontend/dist. Ejecute: npm run build (dentro de frontend/) antes de sintetizar "
            "o desplegar CcFrontend."
        )
    return ruta


class FrontendStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        id_: str,
        *,
        ambiente: Ambiente,
        bucket_frontend: str,
        distribucion_id: str,
        distribucion_dominio: str,
        dominio_publico: str,
        user_pool_id: str,
        cliente_id: str,
        ruta_spa: Path | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, id_, **kwargs)
        ruta = verificar_dist(ruta_spa or DIST_SPA)
        es_prod = not ambiente.economia.permite_borrado

        bucket = s3.Bucket.from_bucket_name(self, "BucketSpa", bucket_frontend)
        distribucion = cloudfront.Distribution.from_distribution_attributes(
            self,
            "Distribucion",
            distribution_id=distribucion_id,
            domain_name=distribucion_dominio,
        )
        # Identificadores públicos: ni contraseñas, ni claves, ni tokens.
        self.configuracion = {
            "userPoolId": user_pool_id,
            "userPoolClientId": cliente_id,
            "region": self.region,
            # Mismo origen: CloudFront sirve la SPA y /api (design.md §11.4).
            "apiBaseUrl": f"https://{dominio_publico}",
        }
        self.despliegue = s3deploy.BucketDeployment(
            self,
            "Spa",
            sources=[
                s3deploy.Source.asset(str(ruta)),
                s3deploy.Source.json_data("config.json", self.configuracion),
            ],
            destination_bucket=bucket,
            distribution=distribucion,
            distribution_paths=["/*"],
            cache_control=[s3deploy.CacheControl.from_string(CACHE_CONTROL)],
            prune=True,
            retain_on_delete=es_prod,
            memory_limit=512,
        )
        self._reconocer_despliegue(bucket_frontend)
        cdk.CfnOutput(self, "UrlSpa", value=f"https://{dominio_publico}")

    def _reconocer_despliegue(self, bucket_frontend: str) -> None:
        """La función de ``BucketDeployment`` es un recurso singleton de CDK (no es nuestro)."""
        (manejador,) = (
            c for c in self.node.children if c.node.id.startswith("Custom::CDKBucketDeployment")
        )
        manejador_estandar = "Función y rol administrados por CDK para BucketDeployment"
        reconocer(
            manejador,
            "AwsSolutions-L1",
            f"{manejador_estandar}: su tiempo de ejecución lo fija la versión de CDK.",
        )
        reconocer(
            manejador,
            "AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/"
            "AWSLambdaBasicExecutionRole]",
            f"{manejador_estandar}: política administrada para escribir sus registros.",
        )
        for accion in (
            "s3:GetObject*",
            "s3:GetBucket*",
            "s3:List*",
            "s3:DeleteObject*",
            "s3:Abort*",
        ):
            reconocer(
                manejador,
                f"AwsSolutions-IAM5[Action::{accion}]",
                f"{manejador_estandar}: {accion} es el conjunto de acciones de lectura, listado "
                f"o borrado que CDK concede sobre el bucket de la SPA y el de activos.",
            )
        for recurso in (
            f"arn:aws:s3:::{bucket_frontend}/*",
            f"arn:aws:s3:::cdk-hnb659fds-assets-{self.account}-{self.region}/*",
            "*",
        ):
            reconocer(
                manejador,
                f"AwsSolutions-IAM5[Resource::{recurso}]",
                f"{manejador_estandar}: el comodín cubre los objetos de la SPA, los activos de "
                "CDK o la invalidación de CloudFront (cloudfront:CreateInvalidation no admite "
                "recurso específico en este uso).",
            )
