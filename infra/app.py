#!/usr/bin/env python3
"""Punto de entrada de la aplicación de CDK de Command Center.

Uso: ``cdk synth -c ambiente=test``. El ambiente es obligatorio y se lee de
``infra/config/ambientes.json``. Antes de crear cualquier stack se verifica la cuenta
(``infra/guardia.py``) y se aplican las etiquetas obligatorias en el nivel de la app.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path

# ``cdk`` ejecuta este archivo desde ``infra/``; el paquete se importa como ``infra``.
# La carpeta del script se quita de sys.path: ``infra/constructs/`` (design.md §1.2) taparía
# el paquete ``constructs`` de PyPI del que depende ``aws_cdk``.
_CARPETA = Path(__file__).resolve().parent
RAIZ = _CARPETA.parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _CARPETA]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import aws_cdk as cdk  # noqa: E402

from infra.config import esquema  # noqa: E402
from infra.etiquetas import aplicar_etiquetas  # noqa: E402
from infra.guardia import Destino, verificar_cuenta  # noqa: E402


def crear_app(
    ambiente: str | None,
    entorno: Mapping[str, str] | None = None,
    app: cdk.App | None = None,
) -> tuple[cdk.App, esquema.Ambiente, Destino]:
    """Crea la aplicación de CDK para un ambiente y una cuenta validados.

    La guardia se ejecuta antes de definir cualquier stack: si falla, no se sintetiza nada.
    """
    if not ambiente:
        raise esquema.ConfiguracionInvalida(
            "falta el ambiente: use 'cdk synth -c ambiente=test' (ver infra/config/ambientes.json)"
        )
    amb = esquema.obtener_ambiente(ambiente)
    destino = verificar_cuenta(amb, entorno)
    app = app or cdk.App()
    app.node.set_context("cc:ambiente", amb.nombre)
    aplicar_etiquetas(app, amb)
    return app, amb, destino


def registrar_nag(app: cdk.App) -> None:
    """Registra las reglas AwsSolutions de cdk-nag (T-015, DS-23)."""
    from cdk_nag import AwsSolutionsChecks

    cdk.Validations.of(app).add_plugins(
        AwsSolutionsChecks(app, write_suppressions_to_cloud_formation=True)
    )


def clave_publica_cloudfront(app: cdk.App, ambiente: str) -> str | None:
    """Llave pública de CloudFront (PEM): contexto ``-c cloudfront_public_key_pem=...`` o el archivo
    ``infra/config/cloudfront-{ambiente}.pub.pem`` (es pública y puede versionarse). Sin ninguna de
    las dos, ``test`` usa una llave inerte (``infra/stacks/edge.py``); ``prod`` la exige."""
    pem = app.node.try_get_context("cloudfront_public_key_pem")
    if pem:
        return str(pem)
    archivo = _CARPETA / "config" / f"cloudfront-{ambiente}.pub.pem"
    return archivo.read_text(encoding="utf-8") if archivo.is_file() else None


def _bandera(valor: object, *, por_defecto: bool) -> bool:
    """Interpreta un contexto ``-c nombre=true|false`` (llega como texto o como booleano)."""
    if valor in (None, ""):
        return por_defecto
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() in ("1", "true", "si", "sí", "yes")


def construir_stacks(app: cdk.App, amb: esquema.Ambiente, destino: Destino) -> dict[str, cdk.Stack]:
    """Define los stacks del ambiente. Solo se llama después de la guardia de cuenta."""
    from infra.constructs import recuperacion
    from infra.stacks.api import ApiStack
    from infra.stacks.auth import AuthStack
    from infra.stacks.backup import BackupRecoveryStack, BackupStack
    from infra.stacks.compute import ComputeStack
    from infra.stacks.compute_base import ComputeBaseStack
    from infra.stacks.data import DataStack
    from infra.stacks.edge import REGION_EDGE, EdgeStack
    from infra.stacks.frontend import FrontendStack
    from infra.stacks.messaging import MessagingStack
    from infra.stacks.network import NetworkStack
    from infra.stacks.observability import ObservabilityStack
    from infra.stacks.pipeline import CONTEXTOS_CDK, PipelineStack
    from infra.stacks.security import SecurityStack
    from infra.stacks.storage import StorageStack, nombre_bucket
    from infra.stacks.workers_lambdas import WorkersLambdasStack

    env = cdk.Environment(account=destino.cuenta, region=destino.region)
    sufijo = amb.nombre
    security = SecurityStack(app, f"CcSecurity-{sufijo}", ambiente=amb, env=env)
    network = NetworkStack(app, f"CcNetwork-{sufijo}", ambiente=amb, env=env)
    storage = StorageStack(
        app, f"CcStorage-{sufijo}", ambiente=amb, llave_infra=security.llave_infra, env=env
    )
    # T-226. Región de recuperación (solo prod): el bucket réplica de ``constancias`` debe existir
    # antes de que CcStorage configure la réplica, así que se despliega primero. En test no se crea.
    recuperacion_stack: cdk.Stack | None = None
    if recuperacion.recuperacion_habilitada(amb):
        recuperacion_stack = BackupRecoveryStack(
            app,
            f"CcBackupRecuperacion-{sufijo}",
            ambiente=amb,
            env=cdk.Environment(account=destino.cuenta, region=recuperacion.REGION_RECUPERACION),
        )
        storage.add_dependency(recuperacion_stack)
    data = DataStack(
        app,
        f"CcData-{sufijo}",
        ambiente=amb,
        llave_infra=security.llave_infra,
        vpc=network.vpc,
        sg_rds=network.sg_rds,
        sg_proxy=network.sg_proxy,
        env=env,
    )
    messaging = MessagingStack(
        app, f"CcMessaging-{sufijo}", ambiente=amb, llave_infra=security.llave_infra, env=env
    )
    auth = AuthStack(
        app,
        f"CcAuth-{sufijo}",
        ambiente=amb,
        llave_infra=security.llave_infra,
        vpc=network.vpc,
        sg_lambda=network.sg_lambda,
        secreto_bd=data.secretos_roles["svc_dashboard"],
        host_bd=data.proxy.endpoint if data.proxy is not None else None,
        env=env,
    )
    compute_base = ComputeBaseStack(
        app,
        f"CcComputeBase-{sufijo}",
        ambiente=amb,
        llave_infra=security.llave_infra,
        vpc=network.vpc,
        sg_ecs=network.sg_ecs,
        secreto_admin=data.secreto_admin,
        secretos_roles=data.secretos_roles,
        env=env,
    )
    # Parámetros opcionales de cómputo (T-224): certificado del ALB interno (HTTPS, obligatorio en
    # prod) y empresa del número de WhatsApp (PQ-07).
    certificado = app.node.try_get_context("certificado_alb_arn")
    dominio_interno = app.node.try_get_context("dominio_interno")
    empresa_wa = app.node.try_get_context("empresa_id_whatsapp")
    empresa_wa = int(empresa_wa) if empresa_wa not in (None, "") else None
    host_bd = data.instancia.db_instance_endpoint_address
    compute = ComputeStack(
        app,
        f"CcCompute-{sufijo}",
        ambiente=amb,
        llave_infra=security.llave_infra,
        llave_datos=security.llave_datos,
        vpc=network.vpc,
        sg_ecs=network.sg_ecs,
        sg_alb=network.sg_alb,
        bucket_plantillas=nombre_bucket(sufijo, destino.cuenta, "plantillas"),
        bucket_constancias=nombre_bucket(sufijo, destino.cuenta, "constancias"),
        bucket_cargas=nombre_bucket(sufijo, destino.cuenta, "cargas"),
        host_bd=host_bd,
        user_pool_id=auth.pool.user_pool_id,
        user_pool_arn=auth.pool.user_pool_arn,
        cliente_id=auth.cliente.user_pool_client_id,
        certificado_arn=certificado or None,
        dominio_interno=dominio_interno or None,
        empresa_id_whatsapp=empresa_wa,
        env=env,
    )
    workers = WorkersLambdasStack(
        app,
        f"CcWorkersLambdas-{sufijo}",
        ambiente=amb,
        llave_infra=security.llave_infra,
        llave_datos=security.llave_datos,
        vpc=network.vpc,
        sg_ecs=network.sg_ecs,
        sg_lambda=network.sg_lambda,
        bucket_plantillas=nombre_bucket(sufijo, destino.cuenta, "plantillas"),
        bucket_constancias=nombre_bucket(sufijo, destino.cuenta, "constancias"),
        bucket_cargas=nombre_bucket(sufijo, destino.cuenta, "cargas"),
        host_bd=host_bd,
        # Las Lambdas usan RDS Proxy cuando el ambiente lo despliega (§4.8).
        host_bd_lambda=data.proxy.endpoint if data.proxy is not None else host_bd,
        url_interna=compute.url_interna,
        user_pool_arn=auth.pool.user_pool_arn,
        user_pool_id=auth.pool.user_pool_id,
        cliente_id=auth.cliente.user_pool_client_id,
        empresa_id_whatsapp=empresa_wa,
        env=env,
    )
    # Los recursos de otros stacks se importan por nombre o ARN (sin referencias de CloudFormation):
    # el orden de despliegue se declara aquí.
    for dependencia in (security, network, storage, data, messaging, auth, compute_base):
        compute.add_dependency(dependencia)
        workers.add_dependency(dependencia)
    workers.add_dependency(compute)

    # ------------------------------------------- API, borde, SPA y observabilidad
    # T-225. CcEdge se fija en us-east-1 (CloudFront, WAF y ACM; design §13.2): hoy es también la
    # región principal, así que no hay referencias entre regiones; si cambiara, CDK las lleva con
    # ``cross_region_references``. Los valores opcionales de prod llegan por contexto (-c).
    contexto = app.node.try_get_context
    dominio_origen = contexto("dominio_origen_api")
    certificado_origen = contexto("certificado_origen_api_arn")
    api = ApiStack(
        app,
        f"CcApi-{sufijo}",
        ambiente=amb,
        vpc=network.vpc,
        sg_vpclink=network.sg_vpclink,
        sg_alb=network.sg_alb,
        listener_arn=compute.listener.listener_arn,
        user_pool_id=auth.pool.user_pool_id,
        cliente_id=auth.cliente.user_pool_client_id,
        dominio_interno=dominio_interno or None,
        dominio_origen=dominio_origen or None,
        certificado_origen_arn=certificado_origen or None,
        env=env,
    )
    for dependencia in (network, auth, compute, workers):
        api.add_dependency(dependencia)
    edge = EdgeStack(
        app,
        f"CcEdge-{sufijo}",
        ambiente=amb,
        llave_infra_arn=security.llave_infra.key_arn,
        bucket_frontend=nombre_bucket(sufijo, destino.cuenta, "frontend"),
        bucket_constancias=nombre_bucket(sufijo, destino.cuenta, "constancias"),
        bucket_cargas=nombre_bucket(sufijo, destino.cuenta, "cargas"),
        bucket_plantillas=nombre_bucket(sufijo, destino.cuenta, "plantillas"),
        host_origen_api=api.host_origen,
        clave_publica_pem=clave_publica_cloudfront(app, sufijo),
        zona_hospedada_id=contexto("zona_hospedada_id") or None,
        dominio_regional_api=api.dominio.regional_domain_name if api.dominio else None,
        zona_dominio_regional_api=api.dominio.regional_hosted_zone_id if api.dominio else None,
        env=cdk.Environment(account=destino.cuenta, region=REGION_EDGE),
    )
    for dependencia in (security, storage, api):
        edge.add_dependency(dependencia)
    frontend = FrontendStack(
        app,
        f"CcFrontend-{sufijo}",
        ambiente=amb,
        bucket_frontend=nombre_bucket(sufijo, destino.cuenta, "frontend"),
        distribucion_id=edge.distribucion.distribution_id,
        distribucion_dominio=edge.distribucion.distribution_domain_name,
        dominio_publico=edge.dominio_publico,
        user_pool_id=auth.pool.user_pool_id,
        cliente_id=auth.cliente.user_pool_client_id,
        env=env,
    )
    for dependencia in (storage, auth, edge):
        frontend.add_dependency(dependencia)
    observability = ObservabilityStack(
        app,
        f"CcObservability-{sufijo}",
        ambiente=amb,
        llave_infra_arn=security.llave_infra.key_arn,
        instancia_bd_id=data.instancia.instance_identifier,
        alb_nombre_completo=compute.alb.load_balancer_full_name,
        grupos_destino={n: g.target_group_full_name for n, g in compute.grupos_destino.items()},
        api_id=api.api.api_id,
        env=env,
    )
    for dependencia in (security, data, messaging, auth, compute, workers, api, edge):
        observability.add_dependency(dependencia)

    # ----------------------------------------------------------- respaldo y pipeline (T-226)
    extra: dict[str, cdk.Stack] = {}
    if recuperacion_stack is not None:
        extra["recuperacion"] = recuperacion_stack
    con_respaldo = _bandera(contexto("respaldo"), por_defecto=True)
    if con_respaldo:
        respaldo = BackupStack(
            app,
            f"CcBackup-{sufijo}",
            ambiente=amb,
            llave_infra_arn=security.llave_infra.key_arn,
            instancia_arn=data.instancia.instance_arn,
            env=env,
        )
        for dependencia in (security, data, storage):
            respaldo.add_dependency(dependencia)
        if recuperacion_stack is not None:
            respaldo.add_dependency(recuperacion_stack)
        extra["backup"] = respaldo
    # El pipeline completo no se crea en test sin pedirlo (cuesta y crea una conexión que se
    # autoriza a mano); en prod sí. ``-c pipeline=true|false`` lo cambia.
    if _bandera(contexto("pipeline"), por_defecto=recuperacion.recuperacion_habilitada(amb)):
        repositorio = contexto("repositorio_pipeline")
        if not repositorio:
            raise esquema.ConfiguracionInvalida(
                "falta el repositorio del pipeline: use -c repositorio_pipeline=propietario/repo"
            )
        extra["pipeline"] = PipelineStack(
            app,
            f"CcPipeline-{sufijo}",
            ambiente=amb,
            repositorio=str(repositorio),
            rama=str(contexto("rama_pipeline") or "main"),
            conexion_arn=contexto("conexion_codigo_arn") or None,
            contextos_cdk={k: str(contexto(k)) for k in CONTEXTOS_CDK if contexto(k)},
            con_respaldo=con_respaldo,
            env=env,
        )
    return {
        **extra,
        "api": api,
        "edge": edge,
        "frontend": frontend,
        "observability": observability,
        "compute": compute,
        "workers": workers,
        "compute_base": compute_base,
        "auth": auth,
        "security": security,
        "network": network,
        "storage": storage,
        "data": data,
        "messaging": messaging,
    }


def main() -> None:
    app = cdk.App()
    app, amb, destino = crear_app(app.node.try_get_context("ambiente"), app=app)
    registrar_nag(app)
    construir_stacks(app, amb, destino)
    app.synth()


if __name__ == "__main__":
    main()
