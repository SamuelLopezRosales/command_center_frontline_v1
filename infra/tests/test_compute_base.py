"""T-043: aserciones del stack CcComputeBase."""

import json

import pytest
from aws_cdk.assertions import Template

from infra.app import construir_stacks, crear_app
from infra.stacks.compute_base import COMANDO_MIGRAR, ETIQUETAS, ROLES_BD

PERMITIDA = "034362033822"


@pytest.fixture(scope="module")
def plantilla() -> Template:
    app, amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    return Template.from_stack(construir_stacks(app, amb, destino)["compute_base"])


def _tareas(plantilla) -> dict[str, dict]:
    return {
        t["Properties"]["Family"]: t["Properties"]
        for t in plantilla.find_resources("AWS::ECS::TaskDefinition").values()
    }


def test_cluster_fargate_sin_container_insights_en_test(plantilla):
    (cluster,) = plantilla.find_resources("AWS::ECS::Cluster").values()
    p = cluster["Properties"]
    assert p["ClusterName"] == "cc-test"
    ajustes = {s["Name"]: s["Value"] for s in p.get("ClusterSettings", [])}
    assert ajustes.get("containerInsights", "disabled") == "disabled"
    (asoc,) = plantilla.find_resources("AWS::ECS::ClusterCapacityProviderAssociations").values()
    assert set(asoc["Properties"]["CapacityProviders"]) == {"FARGATE", "FARGATE_SPOT"}


def test_ecs_exec_sin_registro_de_sesiones_en_cloudwatch(plantilla):
    """Grabar la sesión capturaría el código de invitación que T-049 muestra una sola vez."""
    (cluster,) = plantilla.find_resources("AWS::ECS::Cluster").values()
    assert "Configuration" not in cluster["Properties"]


def test_dos_repositorios_con_escaneo_etiquetas_inmutables_y_kms(plantilla):
    repos = plantilla.find_resources("AWS::ECR::Repository")
    assert {r["Properties"]["RepositoryName"] for r in repos.values()} == {
        "cc-test/migrar",
        "cc-test/ops",
    }
    for r in repos.values():
        p = r["Properties"]
        assert p["ImageScanningConfiguration"] == {"ScanOnPush": True}
        assert p["ImageTagMutability"] == "IMMUTABLE"
        assert p["EncryptionConfiguration"]["EncryptionType"] == "KMS"
        assert "KmsKey" in p["EncryptionConfiguration"]
        assert r["DeletionPolicy"] == "Delete"  # test: se borra con cdk destroy


def test_politica_de_ciclo_de_vida_de_los_repositorios(plantilla):
    for r in plantilla.find_resources("AWS::ECR::Repository").values():
        reglas = json.loads(r["Properties"]["LifecyclePolicy"]["LifecyclePolicyText"])["rules"]
        assert [x["rulePriority"] for x in reglas] == [1, 2]
        sin_etiqueta, todas = reglas
        assert sin_etiqueta["selection"]["tagStatus"] == "untagged"
        assert sin_etiqueta["selection"]["countType"] == "sinceImagePushed"
        assert sin_etiqueta["selection"]["countNumber"] == 7
        assert todas["selection"]["tagStatus"] == "any"
        assert todas["selection"]["countType"] == "imageCountMoreThan"
        assert todas["selection"]["countNumber"] == 10
        assert todas["action"] == {"type": "expire"}


def test_tareas_migrar_y_ops_en_fargate_arm64(plantilla):
    tareas = _tareas(plantilla)
    assert set(tareas) == {"cc-test-migrar", "cc-test-ops"}
    for t in tareas.values():
        assert t["RequiresCompatibilities"] == ["FARGATE"]
        assert t["RuntimePlatform"] == {
            "CpuArchitecture": "ARM64",
            "OperatingSystemFamily": "LINUX",
        }
        assert t["NetworkMode"] == "awsvpc"
        assert t["Cpu"] == "256" and t["Memory"] == "512"
        assert t["ExecutionRoleArn"] and t["TaskRoleArn"]


def test_cada_tarea_usa_la_etiqueta_publicada_de_su_imagen(plantilla):
    assert ETIQUETAS == {"migrar": "0.1.2", "ops": "0.1.0"}
    for familia, t in _tareas(plantilla).items():
        (c,) = t["ContainerDefinitions"]
        imagen = json.dumps(c["Image"])
        nombre = familia.removeprefix("cc-test-")
        assert imagen.endswith(f':{ETIQUETAS[nombre]}"]]}}') or f":{ETIQUETAS[nombre]}" in imagen
        otra = ETIQUETAS["ops" if nombre == "migrar" else "migrar"]
        assert f":{otra}" not in imagen


def test_las_tareas_no_llevan_valores_secretos_en_la_definicion(plantilla):
    for t in _tareas(plantilla).values():
        (c,) = t["ContainerDefinitions"]
        assert not c.get("Environment")
        assert c["Secrets"]
        texto = json.dumps(c)
        assert 'password":' not in texto.lower().replace('"name": "cc_db_password"', "")
        for s in c["Secrets"]:
            assert "secretsmanager" in json.dumps(s["ValueFrom"]) or "Ref" in json.dumps(
                s["ValueFrom"]
            )


def test_migrar_compone_la_url_y_ejecuta_las_migraciones(plantilla):
    (c,) = _tareas(plantilla)["cc-test-migrar"]["ContainerDefinitions"]
    assert c["EntryPoint"] == ["sh", "-c"]
    assert c["Command"] == [COMANDO_MIGRAR]
    assert "migrar_todo.py" in COMANDO_MIGRAR and "sslmode=require" in COMANDO_MIGRAR
    nombres = {s["Name"] for s in c["Secrets"]}
    assert nombres == {"CC_DB_HOST", "CC_DB_PORT", "CC_DB_NAME", "CC_DB_USER", "CC_DB_PASSWORD"}


def test_ops_recibe_las_contrasenas_de_los_siete_roles(plantilla):
    (c,) = _tareas(plantilla)["cc-test-ops"]["ContainerDefinitions"]
    nombres = {s["Name"] for s in c["Secrets"]}
    assert {f"CC_PWD_{r.upper()}" for r in ROLES_BD} <= nombres
    assert "CC_DB_PASSWORD" in nombres
    assert "Command" not in c and "EntryPoint" not in c  # usa el CMD de la imagen (en espera)


def test_ops_tiene_ecs_exec_y_migrar_no(plantilla):
    tareas = _tareas(plantilla)
    (ops,) = tareas["cc-test-ops"]["ContainerDefinitions"]
    (migrar,) = tareas["cc-test-migrar"]["ContainerDefinitions"]
    assert ops["LinuxParameters"]["InitProcessEnabled"] is True
    assert "LinuxParameters" not in migrar


def _politicas_por_rol(plantilla) -> dict[str, list[dict]]:
    salida: dict[str, list[dict]] = {}
    for p in plantilla.find_resources("AWS::IAM::Policy").values():
        for rol in p["Properties"]["Roles"]:
            salida.setdefault(json.dumps(rol), []).extend(
                p["Properties"]["PolicyDocument"]["Statement"]
            )
    return salida


def test_roles_de_minimo_privilegio(plantilla):
    por_rol = _politicas_por_rol(plantilla)
    comodines = []
    for rol, sentencias in por_rol.items():
        for s in sentencias:
            if s["Resource"] == "*":
                comodines.append((rol, s["Action"]))
    acciones = {tuple(sorted(a)) if isinstance(a, list) else (a,) for _, a in comodines}
    assert acciones == {
        ("ecr:GetAuthorizationToken",),
        (
            "ssmmessages:CreateControlChannel",
            "ssmmessages:CreateDataChannel",
            "ssmmessages:OpenControlChannel",
            "ssmmessages:OpenDataChannel",
        ),
    }
    # Solo el rol de tarea de ops tiene el canal de ECS Exec.
    con_ssm = [r for r, a in comodines if "ssmmessages" in json.dumps(a)]
    assert len(con_ssm) == 1 and "Tareaops" in con_ssm[0] and "TaskRole" in con_ssm[0]


def test_el_rol_de_tarea_de_migrar_no_tiene_permisos_de_aws(plantilla):
    por_rol = _politicas_por_rol(plantilla)
    assert not [r for r in por_rol if "Tareamigrar" in r and "TaskRole" in r]


def test_el_rol_de_ejecucion_lee_solo_los_secretos_que_inyecta(plantilla):
    texto = json.dumps(_politicas_por_rol(plantilla))
    assert "secretsmanager:GetSecretValue" in texto
    assert "AKIA" not in json.dumps(plantilla.to_json())


def test_registros_de_30_dias_por_tarea(plantilla):
    grupos = plantilla.find_resources("AWS::Logs::LogGroup")
    assert {g["Properties"]["LogGroupName"] for g in grupos.values()} == {
        "/cc/test/migrar",
        "/cc/test/ops",
    }
    for g in grupos.values():
        assert g["Properties"]["RetentionInDays"] == 30


def test_salidas_para_ecs_run_task(plantilla):
    salidas = plantilla.to_json()["Outputs"]
    assert {"NombreCluster", "TareaMigrar", "TareaOps", "SubredesAplicacion", "SgEcsId"} <= set(
        salidas
    )


def test_los_roles_de_ejecucion_pueden_descifrar_los_secretos(plantilla):
    """Sin kms:Decrypt, ECS no puede inyectar secretos cifrados con la llave (falló en T-047)."""
    con_kms = set()
    for pol in plantilla.find_resources("AWS::IAM::Policy").values():
        for s in pol["Properties"]["PolicyDocument"]["Statement"]:
            acciones = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
            if "kms:Decrypt" in acciones:
                assert s["Resource"] != "*"
                con_kms.update(json.dumps(r) for r in pol["Properties"]["Roles"])
    for nombre in ("Tareamigrar", "Tareaops"):
        assert any(nombre in r and "ExecutionRole" in r for r in con_kms), nombre
