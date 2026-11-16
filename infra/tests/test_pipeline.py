"""T-140: aserciones de ``CcPipeline`` (CodePipeline y CodeBuild).

El pipeline completo **no se crea en ``test``** sin ``-c pipeline=true``; en ``prod`` sí. Aprobación
manual antes de desplegar, instantánea de RDS previa a las migraciones (solo ``prod``), migraciones
con la tarea ``migrar`` en el orden de design.md §2.8, roles de mínimo privilegio y artefactos
cifrados.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from infra.config import esquema
from infra.pipeline import buildspecs
from infra.stacks.compute_base import COMANDO_MIGRAR, ETIQUETAS
from infra.stacks.pipeline import nombres_de_stacks
from infra.tests.ayudas_globales import (
    construir_prod,
    construir_test,
    lista,
    sentencias_de_identidad,
)

RAIZ = Path(__file__).resolve().parents[2]
CUENTA = "034362033822"
ETAPAS_PROD = ["Fuente", "Compilar", "Aprobacion", "Respaldo", "Base", "Migraciones", "Servicios"]
ETAPAS_TEST = [e for e in ETAPAS_PROD if e != "Respaldo"]


def _recursos(e, tipo: str) -> dict[str, dict]:
    return {k: v for k, v in e.json_de("pipeline")["Resources"].items() if v["Type"] == tipo}


def _pipeline(e) -> dict:
    (p,) = _recursos(e, "AWS::CodePipeline::Pipeline").values()
    return p["Properties"]


def _etapas(e) -> list[str]:
    return [s["Name"] for s in _pipeline(e)["Stages"]]


def _proyectos(e) -> dict[str, dict]:
    return {
        p["Properties"]["Name"].removeprefix(f"cc-{e.ambiente.nombre}-"): p["Properties"]
        for p in _recursos(e, "AWS::CodeBuild::Project").values()
    }


def _comandos(proyecto: dict, fase: str = "build") -> list[str]:
    spec = json.loads(proyecto["Source"]["BuildSpec"])
    return spec["phases"][fase]["commands"]


def _todos_los_comandos(proyecto: dict) -> list[str]:
    spec = json.loads(proyecto["Source"]["BuildSpec"])
    return [
        c
        for fase in ("install", "pre_build", "build")
        for c in spec["phases"].get(fase, {}).get("commands", [])
    ]


def _entorno(proyecto: dict) -> dict[str, str]:
    return {v["Name"]: v["Value"] for v in proyecto["Environment"]["EnvironmentVariables"]}


# ============================================================================ cuándo se crea
def test_el_pipeline_no_se_crea_en_test_por_defecto(global_test):
    assert "pipeline" not in global_test.stacks


def test_el_pipeline_se_crea_en_test_solo_con_la_bandera(global_test_con_pipeline):
    assert "pipeline" in global_test_con_pipeline.stacks
    assert _etapas(global_test_con_pipeline) == ETAPAS_TEST


def test_el_pipeline_se_crea_en_prod(global_prod):
    assert _etapas(global_prod) == ETAPAS_PROD


def test_en_prod_se_puede_apagar_el_pipeline():
    assert "pipeline" not in construir_prod({"pipeline": "false"}).stacks


def test_sin_repositorio_no_se_define_el_pipeline():
    with pytest.raises(esquema.ConfiguracionInvalida, match="repositorio del pipeline"):
        construir_test({"pipeline": "true"})


@pytest.mark.parametrize("repo", ["solo-nombre", "a/b/c", "/repo", "dueño/"])
def test_el_repositorio_debe_ser_propietario_y_nombre(repo):
    with pytest.raises(ValueError, match="propietario/repositorio"):
        construir_test({"pipeline": "true", "repositorio_pipeline": repo})


def test_el_pipeline_no_referencia_a_ningun_otro_stack(global_prod, global_test_con_pipeline):
    for e in (global_prod, global_test_con_pipeline):
        assert not e.stacks["pipeline"].dependencies
        assert "Fn::ImportValue" not in json.dumps(e.json_de("pipeline"))
        # y ningún otro stack depende de él (no hay ciclo con lo que despliega)
        for nombre, stack in e.stacks.items():
            assert e.stacks["pipeline"] not in stack.dependencies, nombre


# =========================================================================== orden y aprobación
@pytest.mark.parametrize("amb", ["prod", "test"])
def test_aprobacion_manual_antes_de_cualquier_despliegue(
    amb, global_prod, global_test_con_pipeline
):
    e = global_prod if amb == "prod" else global_test_con_pipeline
    etapas = _pipeline(e)["Stages"]
    nombres = [s["Name"] for s in etapas]
    (aprobacion,) = (
        a for s in etapas for a in s["Actions"] if a["ActionTypeId"]["Category"] == "Approval"
    )
    assert aprobacion["ActionTypeId"]["Provider"] == "Manual"
    for despliegue in ("Respaldo", "Base", "Migraciones", "Servicios"):
        if despliegue in nombres:
            assert nombres.index("Aprobacion") < nombres.index(despliegue)
    assert nombres.index("Compilar") < nombres.index("Aprobacion")


def test_instantanea_de_rds_antes_de_migrar_solo_en_prod(global_prod, global_test_con_pipeline):
    nombres = _etapas(global_prod)
    assert nombres.index("Respaldo") < nombres.index("Migraciones") < nombres.index("Servicios")
    assert nombres.index("Aprobacion") < nombres.index("Respaldo")
    assert "respaldo" in _proyectos(global_prod)
    assert "respaldo" not in _proyectos(global_test_con_pipeline)  # test no deja instantáneas


def test_la_instantanea_es_manual_con_etiquetas_y_espera(global_prod):
    comandos = " ".join(_comandos(_proyectos(global_prod)["respaldo"]))
    assert "aws rds create-db-snapshot" in comandos
    assert "aws rds wait db-snapshot-available" in comandos
    assert "pre-migracion" in comandos
    for etiqueta in ("proyecto", "ambiente", "responsable"):  # las instantáneas se etiquetan
        assert f"Key={etiqueta}," in comandos
    assert "CcData-$CC_AMBIENTE" in comandos
    # primer despliegue: sin base de datos no hay nada que respaldar y no falla
    assert "exit 0" in comandos


def test_la_instantanea_solo_puede_tocar_instancias_del_ambiente(global_prod):
    plantilla = global_prod.json_de("pipeline")
    politicas = [
        s
        for logico, s in sentencias_de_identidad(plantilla)
        if "Proyectorespaldo" in logico and any(a.startswith("rds:") for a in lista(s["Action"]))
    ]
    (instancia,) = (s for s in politicas if "Condition" in s)
    assert instancia["Action"] == "rds:CreateDBSnapshot"
    assert instancia["Condition"] == {"StringEquals": {"aws:ResourceTag/ambiente": "prod"}}
    texto = json.dumps(politicas)
    assert "snapshot:cc-prod-pre-migracion-*" in texto
    assert "rds:DeleteDBInstance" not in texto and "rds:Restore" not in texto


def test_las_migraciones_usan_la_tarea_migrar_y_se_detienen_si_falla(global_prod):
    comandos = " ".join(_comandos(_proyectos(global_prod)["migrar"]))
    assert "aws ecs run-task" in comandos
    assert "aws ecs wait tasks-stopped" in comandos
    assert "exitCode" in comandos
    assert 'if [ "$CODIGO" != "0" ]' in comandos and "exit 1" in comandos
    # los datos de la tarea salen de las salidas de CcComputeBase (sin valores fijos)
    for salida in ("NombreCluster", "TareaMigrar", "SubredesAplicacion", "SgEcsId"):
        assert salida in comandos
    assert "CcComputeBase-$CC_AMBIENTE" in comandos


def _cargar_migrar_todo():
    espec = importlib.util.spec_from_file_location(
        "migrar_todo", RAIZ / "scripts" / "migrar_todo.py"
    )
    modulo = importlib.util.module_from_spec(espec)
    espec.loader.exec_module(modulo)
    return modulo


def test_la_tarea_migrar_aplica_el_orden_de_design_2_8():
    """La tarea corre ``scripts/migrar_todo.py``: el orden vive ahí y es el de design.md §2.8."""
    migrar = _cargar_migrar_todo()
    assert migrar.ORDEN == (
        "dashboard",  # identidad y auditoría
        "campos",
        "colaboradores",
        "whatsapp",
        "constancias",
        "notificaciones",
    )
    assert migrar.SCRIPTS_SQL == ("roles.sql", "rls.sql", "grants.sql")
    assert "scripts/migrar_todo.py" in COMANDO_MIGRAR  # lo que ejecuta la tarea de ECS
    dockerfile = (RAIZ / "infra" / "docker" / "migrar" / "Dockerfile").read_text(encoding="utf-8")
    for servicio in migrar.ORDEN:
        assert f"services/{servicio}/migrations" in dockerfile
    assert "infra/db" in dockerfile


def test_el_pipeline_puede_ejecutar_solo_la_tarea_migrar(global_prod):
    plantilla = global_prod.json_de("pipeline")
    sentencias = [
        s for logico, s in sentencias_de_identidad(plantilla) if "Proyectomigrar" in logico
    ]
    (ejecutar,) = (s for s in sentencias if s["Action"] == "ecs:RunTask")
    assert (
        ejecutar["Resource"] == f"arn:aws:ecs:us-east-1:{CUENTA}:task-definition/cc-prod-migrar:*"
    )
    assert ejecutar["Condition"] == {
        "ArnEquals": {"ecs:cluster": f"arn:aws:ecs:us-east-1:{CUENTA}:cluster/cc-prod"}
    }
    (pasar,) = (s for s in sentencias if s["Action"] == "iam:PassRole")
    assert pasar["Condition"] == {
        "StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}
    }
    assert pasar["Resource"] == f"arn:aws:iam::{CUENTA}:role/CcComputeBase-prod-*"


def test_las_imagenes_migrar_y_ops_se_publican_con_sus_etiquetas(global_prod):
    base = _proyectos(global_prod)["base"]
    entorno = _entorno(base)
    assert entorno["CC_TAG_MIGRAR"] == ETIQUETAS["migrar"]
    assert entorno["CC_TAG_OPS"] == ETIQUETAS["ops"]
    comandos = " ".join(_comandos(base))
    assert "aws ecr describe-images" in comandos  # los repositorios son inmutables
    assert "--platform linux/arm64" in comandos
    assert "docker push" in comandos


def test_el_orden_de_los_comandos_de_base_publica_la_imagen_despues_de_los_stacks(global_prod):
    comandos = _comandos(_proyectos(global_prod)["base"])
    i_deploy = next(i for i, c in enumerate(comandos) if "cdk deploy $CC_STACKS_BASE" in c)
    i_push = next(i for i, c in enumerate(comandos) if "docker push" in c)
    assert i_deploy < i_push  # el repositorio de ECR nace en CcComputeBase


# =================================================================================== la compilación
def test_el_build_del_frontend_va_antes_del_synth_y_de_las_pruebas(global_prod):
    comandos = _todos_los_comandos(_proyectos(global_prod)["ci"])

    def posicion(texto: str) -> int:
        return next(i for i, c in enumerate(comandos) if texto in c)

    build_spa = posicion("npm run build")
    assert posicion("cd frontend && npm ci") < build_spa
    assert build_spa < posicion("pytest")  # test_nag sintetiza CcFrontend: exige frontend/dist
    assert build_spa < posicion("cdk synth")
    assert posicion("pytest") < posicion("cdk synth")


def test_la_compilacion_empaqueta_las_tres_variantes_de_lambdas_antes_del_synth(global_prod):
    comandos = _todos_los_comandos(_proyectos(global_prod)["ci"])
    empaques = [i for i, c in enumerate(comandos) if "empaquetar_lambdas.py" in c]
    assert len(empaques) == 3
    textos = [comandos[i] for i in empaques]
    assert sum("--notificaciones" in t for t in textos) == 1
    assert sum("--whatsapp" in t for t in textos) == 1
    sintetizar = next(i for i, c in enumerate(comandos) if "cdk synth" in c)
    assert max(empaques) < sintetizar


def test_la_compilacion_corre_lint_pruebas_y_synth_con_nag(global_prod):
    comandos = " ".join(_todos_los_comandos(_proyectos(global_prod)["ci"]))
    for paso in ("ruff check", "ruff format --check", "pytest", "npm test", "cdk synth"):
        assert paso in comandos
    assert "-c ambiente=$CC_AMBIENTE" in comandos
    assert "--output cdk.out" in comandos  # el despliegue usa este mismo ensamblado


def test_la_cli_de_cdk_va_fija_y_es_la_misma_en_todos_los_proyectos(global_prod):
    for nombre, proyecto in _proyectos(global_prod).items():
        assert _entorno(proyecto)["CDK_CLI_VERSION"] == buildspecs.VERSION_CLI_CDK, nombre
    comandos = " ".join(_todos_los_comandos(_proyectos(global_prod)["servicios"]))
    assert "aws-cdk@$CDK_CLI_VERSION" in comandos


def test_los_despliegues_usan_el_ensamblado_ya_sintetizado(global_prod):
    for nombre in ("base", "servicios"):
        comandos = " ".join(_comandos(_proyectos(global_prod)[nombre]))
        assert "--app cdk.out" in comandos and "--require-approval never" in comandos


def test_los_stacks_que_despliega_el_pipeline_son_todos_menos_el_suyo(
    global_prod, global_test_con_pipeline
):
    for e in (global_prod, global_test_con_pipeline):
        env = e.ambiente.nombre
        proyectos = _proyectos(e)
        base = _entorno(proyectos["base"])["CC_STACKS_BASE"].split()
        servicios = _entorno(proyectos["servicios"])["CC_STACKS_SERVICIOS"].split()
        todos = {s.stack_name for s in e.stacks.values()}
        assert set(base) | set(servicios) == todos - {f"CcPipeline-{env}"}
        assert not set(base) & set(servicios)
        assert f"CcPipeline-{env}" not in base + servicios  # nunca se despliega a sí mismo


def test_nombres_de_stacks_por_etapa():
    base, servicios = nombres_de_stacks("prod", con_recuperacion=True, con_respaldo=True)
    assert base[0] == "CcBackupRecuperacion-prod"  # el bucket réplica existe antes que CcStorage
    assert servicios[-1] == "CcBackup-prod"
    base, servicios = nombres_de_stacks("test", con_recuperacion=False, con_respaldo=False)
    assert not any("Backup" in n for n in base + servicios)


def test_los_contextos_de_cdk_se_repiten_en_la_sintesis(global_prod, global_test_con_pipeline):
    contexto = _entorno(_proyectos(global_prod)["ci"])["CC_CDK_CONTEXTO"]
    assert "-c certificado_alb_arn=arn:aws:acm:" in contexto
    assert "-c dominio_interno=interno.cc.example.com" in contexto
    assert _entorno(_proyectos(global_test_con_pipeline)["ci"])["CC_CDK_CONTEXTO"] == ""


def test_la_llave_publica_de_cloudfront_viene_de_un_parametro_solo_en_prod(
    global_prod, global_test_con_pipeline
):
    variables = {
        v["Name"]: v for v in _proyectos(global_prod)["ci"]["Environment"]["EnvironmentVariables"]
    }
    llave = variables["CC_CLAVE_PUBLICA_CLOUDFRONT"]
    assert llave["Type"] == "PARAMETER_STORE"
    assert llave["Value"] == "/cc/prod/pipeline/clave-publica-cloudfront"
    assert "CC_CLAVE_PUBLICA_CLOUDFRONT" not in _entorno(_proyectos(global_test_con_pipeline)["ci"])


# ====================================================================================== seguridad
def test_los_proyectos_son_arm_y_solo_los_de_docker_son_privilegiados(global_prod):
    privilegiados = {"ci", "base", "servicios"}
    for nombre, proyecto in _proyectos(global_prod).items():
        entorno = proyecto["Environment"]
        assert entorno["Image"].startswith("aws/codebuild/amazonlinux-aarch64"), nombre
        assert entorno["Type"] == "ARM_CONTAINER"
        assert entorno["PrivilegedMode"] is (nombre in privilegiados), nombre
        assert proyecto["EncryptionKey"]  # cifrado con la llave propia del pipeline
        assert proyecto["Source"]["Type"] == "CODEPIPELINE"


def test_ningun_buildspec_ni_variable_contiene_secretos(global_prod):
    for nombre, proyecto in _proyectos(global_prod).items():
        for variable in proyecto["Environment"]["EnvironmentVariables"]:
            assert variable["Type"] in ("PLAINTEXT", "PARAMETER_STORE"), nombre
            assert "SECRETS_MANAGER" not in variable["Type"]
        texto = proyecto["Source"]["BuildSpec"]
        for marca in ("AKIA", "ghp_", "PRIVATE KEY", "password=", "token="):
            assert marca not in texto, (nombre, marca)


def test_los_artefactos_van_cifrados_con_una_llave_propia(global_prod, global_test_con_pipeline):
    for e in (global_prod, global_test_con_pipeline):
        env = e.ambiente.nombre
        (bucket,) = _recursos(e, "AWS::S3::Bucket").values()
        p = bucket["Properties"]
        assert p["BucketName"] == f"cc-{env}-{CUENTA}-pipeline-artefactos"
        regla = p["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]
        assert regla["ServerSideEncryptionByDefault"]["SSEAlgorithm"] == "aws:kms"
        assert p["VersioningConfiguration"]["Status"] == "Enabled"
        assert p["LifecycleConfiguration"]["Rules"][0]["ExpirationInDays"] == 30
        (llave,) = _recursos(e, "AWS::KMS::Key").values()
        assert llave["Properties"]["EnableKeyRotation"] is True
        almacen = _pipeline(e)["ArtifactStore"]
        assert almacen["EncryptionKey"]["Type"] == "KMS"
        assert _pipeline(e)["PipelineType"] == "V2"


def test_en_prod_artefactos_y_llave_se_conservan_y_en_test_se_borran(
    global_prod, global_test_con_pipeline
):
    for tipo in ("AWS::S3::Bucket", "AWS::KMS::Key"):
        assert all(r["DeletionPolicy"] == "Retain" for r in _recursos(global_prod, tipo).values())
        assert all(
            r["DeletionPolicy"] == "Delete"
            for r in _recursos(global_test_con_pipeline, tipo).values()
        )


def test_los_roles_de_cdk_se_asumen_acotados_a_la_cuenta_y_a_las_regiones(global_prod):
    plantilla = global_prod.json_de("pipeline")
    asumir = [s for _, s in sentencias_de_identidad(plantilla) if s["Action"] == "sts:AssumeRole"]
    assert asumir
    recursos = {
        r for s in asumir for r in lista(s["Resource"]) if isinstance(r, str) and "cdk-" in r
    }
    # el resto de los AssumeRole son los de CodePipeline hacia sus roles de acción (GetAtt)
    for s in asumir:
        for r in lista(s["Resource"]):
            assert isinstance(r, dict) or "role/cdk-hnb659fds-" in r, r
    esperados = {
        f"arn:aws:iam::{CUENTA}:role/cdk-hnb659fds-{rol}-role-{CUENTA}-{region}"
        for rol in ("deploy", "file-publishing", "image-publishing", "lookup")
        for region in ("us-east-1", "us-east-2")  # prod despliega también la recuperación
    }
    assert recursos == esperados


def test_en_test_los_roles_de_cdk_solo_son_de_la_region_principal(global_test_con_pipeline):
    plantilla = global_test_con_pipeline.json_de("pipeline")
    texto = json.dumps(plantilla)
    assert "us-east-2" not in texto
    asumir = [s for _, s in sentencias_de_identidad(plantilla) if s["Action"] == "sts:AssumeRole"]
    cdk_roles = [s for s in asumir if "cdk-hnb659fds" in json.dumps(s["Resource"])]
    assert cdk_roles and all(CUENTA in json.dumps(s["Resource"]) for s in cdk_roles)


def test_solo_los_proyectos_de_base_publican_en_ecr_y_solo_en_repos_del_ambiente(global_prod):
    plantilla = global_prod.json_de("pipeline")
    for logico, s in sentencias_de_identidad(plantilla):
        acciones = lista(s["Action"])
        if any(a.startswith("ecr:") and a != "ecr:GetAuthorizationToken" for a in acciones):
            assert "Proyectobase" in logico
            assert s["Resource"] == f"arn:aws:ecr:us-east-1:{CUENTA}:repository/cc-prod/*"
            assert "ecr:DeleteRepository" not in acciones and "ecr:BatchDeleteImage" not in acciones


def test_ningun_proyecto_puede_modificar_iam_ni_kms_ajenos(global_prod):
    plantilla = global_prod.json_de("pipeline")
    for logico, s in sentencias_de_identidad(plantilla):
        for accion in lista(s["Action"]):
            if accion.startswith("iam:"):
                assert accion == "iam:PassRole", (logico, accion)
            if accion.startswith("kms:"):
                # solo la llave del propio pipeline (GetAtt a LlavePipeline)
                assert "LlavePipeline" in json.dumps(s["Resource"]), (logico, accion)


# ====================================================================================== conexión
def test_la_conexion_es_una_referencia_pendiente_de_autorizar(global_prod):
    (conexion,) = _recursos(global_prod, "AWS::CodeStarConnections::Connection").values()
    assert conexion["Properties"]["ProviderType"] == "GitHub"
    assert conexion["Properties"]["ConnectionName"] == "cc-prod-github"
    salidas = global_prod.json_de("pipeline")["Outputs"]
    assert "PENDIENTE" in salidas["PasoManualConexion"]["Value"]
    fuente = _pipeline(global_prod)["Stages"][0]["Actions"][0]
    assert fuente["Configuration"]["FullRepositoryId"] == "organizacion/command-center"
    assert fuente["Configuration"]["BranchName"] == "main"


def test_se_puede_reutilizar_una_conexion_existente():
    arn = f"arn:aws:codestar-connections:us-east-1:{CUENTA}:connection/00000000-0000-0000-0000-000000000000"
    e = construir_test(
        {
            "pipeline": "true",
            "repositorio_pipeline": "organizacion/repo",
            "rama_pipeline": "release",
            "conexion_codigo_arn": arn,
        }
    )
    assert not _recursos(e, "AWS::CodeStarConnections::Connection")
    fuente = _pipeline(e)["Stages"][0]["Actions"][0]["Configuration"]
    assert fuente["ConnectionArn"] == arn
    assert fuente["BranchName"] == "release"


def test_cdk_nag_no_deja_hallazgos_en_test_con_el_pipeline(tmp_path):
    """``test_nag.py`` no define el pipeline (no existe por defecto en ``test``): con la bandera se
    sintetiza aquí con las reglas AwsSolutions y no debe quedar ningún hallazgo sin reconocer."""
    from infra.tests.test_global import _violaciones

    salida = tmp_path / "test-pipeline"
    e = construir_test(
        {"pipeline": "true", "repositorio_pipeline": "organizacion/repo"},
        con_nag=True,
        salida=str(salida),
    )
    e.app.synth()  # lanza si cdk-nag encuentra un error sin reconocer
    reporte = salida / "validation-report.json"
    if reporte.exists():
        assert _violaciones(json.loads(reporte.read_text(encoding="utf-8"))) == []
