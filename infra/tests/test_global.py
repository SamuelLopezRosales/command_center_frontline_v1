"""T-141: revisión global de IAM y aserciones de infraestructura sobre el ensamblado completo.

Se prueba ``test`` (el de ``ambientes.json``) y un ``prod`` sintético con **todos** los stacks
(``infra/tests/ayudas_globales.py``). Las pruebas fallan ante cualquier política con ``Resource: "*"``
fuera de la lista cerrada de abajo, cifrado ausente, falta de DLQ, MFA opcional, etiquetas
faltantes, ``CcEdge`` fuera de ``us-east-1`` o una lectura de secreto sin ``kms:Decrypt``. La
guardia de cuenta ya tiene sus pruebas en ``test_guardia.py``: aquí solo se comprueba que el punto
de entrada la invoca antes de definir stacks.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import aws_cdk as cdk
import pytest

from infra.stacks.edge import REGION_EDGE
from infra.tests.ayudas_globales import (
    acciones_de,
    lista,
    recursos_de_sentencia,
    sentencias_de_identidad,
    sentencias_de_recurso,
    sentencias_por_rol,
)

INFRA = Path(__file__).resolve().parent.parent
CUENTA = "034362033822"

# ------------------------------------------------------------------------------------------
# Lista cerrada de acciones que SÍ pueden llevar ``Resource: "*"`` (no admiten un recurso concreto
# o CDK las concede así). Cualquier otra acción con comodín hace fallar la prueba: no se agrega una
# entrada sin su motivo y sin revisarlo.
# ------------------------------------------------------------------------------------------
ACCIONES_CON_COMODIN_PERMITIDO: dict[str, str] = {
    "ecr:GetAuthorizationToken": (
        "La acción no admite recurso: es la credencial con la que ECS descarga imágenes y el "
        "pipeline sube las de migrar y ops."
    ),
    "ssmmessages:CreateControlChannel": "ECS Exec (tarea ops): el canal no admite recurso.",
    "ssmmessages:CreateDataChannel": "ECS Exec (tarea ops): el canal no admite recurso.",
    "ssmmessages:OpenControlChannel": "ECS Exec (tarea ops): el canal no admite recurso.",
    "ssmmessages:OpenDataChannel": "ECS Exec (tarea ops): el canal no admite recurso.",
    "cloudfront:CreateInvalidation": (
        "BucketDeployment de CcFrontend: la función administrada por CDK invalida la caché de la "
        "SPA y CDK concede esta acción sin recurso; la función solo puede tocar el bucket de la SPA."
    ),
    "cloudfront:GetInvalidation": "BucketDeployment de CcFrontend: espera la invalidación (igual).",
}

# Stacks que existen en todo ambiente (``recuperacion`` solo en ``prod``; ``pipeline`` con bandera).
STACKS_BASE = sorted(
    [
        "api",
        "auth",
        "backup",
        "compute",
        "compute_base",
        "data",
        "edge",
        "frontend",
        "messaging",
        "network",
        "observability",
        "security",
        "storage",
        "workers",
    ]
)


def _plantillas(ensamblado) -> dict[str, dict]:
    return {n: t.to_json() for n, t in ensamblado.plantillas.items()}


def _todos(*ensamblados) -> list[tuple[str, str, dict]]:
    """``(ambiente, stack, plantilla json)`` de varios ensamblados."""
    return [
        (e.ambiente.nombre, nombre, plantilla)
        for e in ensamblados
        for nombre, plantilla in _plantillas(e).items()
    ]


@pytest.fixture(scope="module")
def todas(global_test, global_prod, global_test_con_pipeline):
    return _todos(global_test, global_prod, global_test_con_pipeline)


def _recursos(plantilla: dict, tipo: str) -> dict[str, dict]:
    return {k: v for k, v in plantilla["Resources"].items() if v["Type"] == tipo}


def _tipos(e, tipo: str) -> list[dict]:
    return [r for t in _plantillas(e).values() for r in _recursos(t, tipo).values()]


# ======================================================================== comodín en políticas
def hallazgos_de_comodin(plantilla: dict, permitidas: dict[str, str]) -> list[str]:
    """Acciones con ``Resource: "*"`` en políticas de identidad que no están en ``permitidas``."""
    malas: list[str] = []
    for logico, s in sentencias_de_identidad(plantilla):
        if "*" in [r for r in recursos_de_sentencia(s) if isinstance(r, str)]:
            malas += [f"{logico}: {a}" for a in acciones_de(s) if a not in permitidas]
        if "NotResource" in s or "NotAction" in s:
            malas.append(f"{logico}: NotAction/NotResource")
    for logico, s in sentencias_de_recurso(plantilla):
        if "*" in [r for r in recursos_de_sentencia(s) if isinstance(r, str)]:
            malas.append(f"{logico}: política de recurso con Resource *")
    return malas


def test_la_lista_de_comodines_tiene_motivo_para_cada_accion():
    for accion, motivo in ACCIONES_CON_COMODIN_PERMITIDO.items():
        assert re.fullmatch(r"[a-z0-9-]+:[A-Za-z0-9]+", accion), accion  # sin comodín en el nombre
        assert len(motivo) >= 30, f"{accion}: falta el motivo"


def test_el_detector_de_comodin_falla_ante_una_accion_fuera_de_la_lista():
    """Sin esta prueba, la lista cerrada podría estar abierta sin que nadie lo note."""

    def plantilla(accion: str) -> dict:
        return {
            "Resources": {
                "P": {
                    "Type": "AWS::IAM::Policy",
                    "Properties": {
                        "PolicyDocument": {
                            "Statement": [{"Effect": "Allow", "Action": accion, "Resource": "*"}]
                        },
                        "Roles": [{"Ref": "R"}],
                    },
                }
            }
        }

    assert hallazgos_de_comodin(plantilla("s3:GetObject"), ACCIONES_CON_COMODIN_PERMITIDO)
    assert hallazgos_de_comodin(plantilla("iam:PassRole"), ACCIONES_CON_COMODIN_PERMITIDO)
    assert hallazgos_de_comodin(plantilla("sts:AssumeRole"), ACCIONES_CON_COMODIN_PERMITIDO)
    assert not hallazgos_de_comodin(
        plantilla("ecr:GetAuthorizationToken"), ACCIONES_CON_COMODIN_PERMITIDO
    )


def test_ninguna_politica_usa_resource_comodin_fuera_de_la_lista_cerrada(todas):
    fallas = {
        f"{amb}/{stack}": hallazgos
        for amb, stack, plantilla in todas
        if (hallazgos := hallazgos_de_comodin(plantilla, ACCIONES_CON_COMODIN_PERMITIDO))
    }
    assert not fallas, json.dumps(fallas, indent=2, ensure_ascii=False)


def test_ninguna_accion_es_un_comodin_de_servicio(todas):
    """Ni ``*`` ni ``servicio:*`` (``iam:*``, ``s3:*``, ``kms:*``...) en políticas de identidad."""
    patron = re.compile(r"^(\*|[a-z0-9-]+:\*)$")
    fallas = [
        f"{amb}/{stack}/{logico}: {a}"
        for amb, stack, plantilla in todas
        for logico, s in sentencias_de_identidad(plantilla)
        for a in acciones_de(s)
        if patron.match(a)
    ]
    assert not fallas, fallas


def test_ni_iam_ni_assumerole_con_resource_comodin(todas):
    fallas = [
        f"{amb}/{stack}/{logico}: {a}"
        for amb, stack, plantilla in todas
        for logico, s in sentencias_de_identidad(plantilla)
        for a in acciones_de(s)
        if (a.startswith("iam:") or a == "sts:AssumeRole")
        and "*" in [r for r in recursos_de_sentencia(s) if isinstance(r, str)]
    ]
    assert not fallas, fallas


def test_ningun_rol_usa_administrator_ni_poweruser(todas):
    prohibidas = ("AdministratorAccess", "PowerUserAccess", "IAMFullAccess")
    fallas = []
    for amb, stack, plantilla in todas:
        for logico, r in plantilla["Resources"].items():
            if r["Type"] in ("AWS::IAM::Role", "AWS::IAM::User", "AWS::IAM::Group"):
                texto = json.dumps(r.get("Properties", {}).get("ManagedPolicyArns", []))
                fallas += [f"{amb}/{stack}/{logico}: {p}" for p in prohibidas if p in texto]
            if r["Type"] == "AWS::IAM::ManagedPolicy" and any(
                p in json.dumps(r["Properties"]) for p in prohibidas
            ):
                fallas.append(f"{amb}/{stack}/{logico}")
    assert not fallas, fallas


def test_ningun_rol_se_puede_asumir_desde_cualquier_principal(todas):
    fallas = []
    for amb, stack, plantilla in todas:
        for logico, r in plantilla["Resources"].items():
            if r["Type"] != "AWS::IAM::Role":
                continue
            for s in lista(r["Properties"]["AssumeRolePolicyDocument"]["Statement"]):
                principal = s.get("Principal")
                if principal == "*" or (
                    isinstance(principal, dict) and principal.get("AWS") == "*"
                ):
                    fallas.append(f"{amb}/{stack}/{logico}")
    assert not fallas, fallas


# ====================================================================== kms:Decrypt y secretos
def roles_que_leen_secretos(plantilla: dict) -> dict[str, list[dict]]:
    return {
        rol: sentencias
        for rol, sentencias in sentencias_por_rol(plantilla).items()
        if any("secretsmanager:GetSecretValue" in acciones_de(s) for s in sentencias)
    }


def roles_sin_decrypt(plantilla: dict) -> list[str]:
    """Roles que leen un secreto cifrado pero no pueden descifrarlo con la llave (T-047)."""
    sin: list[str] = []
    for rol, sentencias in roles_que_leen_secretos(plantilla).items():
        descifra = any(
            ("kms:Decrypt" in acciones_de(s) or "kms:*" in acciones_de(s))
            and "*" not in [r for r in recursos_de_sentencia(s) if isinstance(r, str)]
            for s in sentencias
        )
        if not descifra:
            sin.append(rol)
    return sin


@pytest.mark.parametrize("stack", [*STACKS_BASE, "recuperacion", "pipeline"])
@pytest.mark.parametrize("amb", ["test", "prod"])
def test_cada_lectura_de_secreto_incluye_kms_decrypt(
    amb, stack, global_test, global_prod, global_test_con_pipeline
):
    """Una aserción por stack (en ``test`` y en ``prod``): quien lee un secreto cifrado con la llave
    de infraestructura también tiene ``kms:Decrypt`` sobre ella (lección de T-047)."""
    ensamblado = global_test if amb == "test" else global_prod
    if stack == "pipeline" and amb == "test":
        ensamblado = global_test_con_pipeline
    if stack not in ensamblado.plantillas:
        pytest.skip(f"{stack} no existe en {amb} (por diseño)")
    sin = roles_sin_decrypt(ensamblado.json_de(stack))
    assert not sin, f"{amb}/{stack}: roles que leen secretos sin kms:Decrypt: {sin}"


@pytest.mark.parametrize("stack", ["auth", "compute", "workers", "compute_base"])
def test_los_stacks_que_leen_secretos_se_detectan(stack, global_test):
    """Evita que la aserción anterior sea vacía: estos stacks sí leen secretos."""
    assert roles_que_leen_secretos(global_test.json_de(stack))


def test_data_lee_secretos_solo_con_proxy_y_descifra(global_test, global_prod):
    """RDS Proxy (``prod``) lee los secretos de roles: su rol también descifra con la llave."""
    assert not roles_que_leen_secretos(global_test.json_de("data"))
    assert roles_que_leen_secretos(global_prod.json_de("data"))
    assert not roles_sin_decrypt(global_prod.json_de("data"))


def test_el_detector_de_decrypt_falla_si_falta():
    plantilla = {
        "Resources": {
            "P": {
                "Type": "AWS::IAM::Policy",
                "Properties": {
                    "PolicyDocument": {
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Action": "secretsmanager:GetSecretValue",
                                "Resource": "arn:aws:secretsmanager:us-east-1:1:secret:x",
                            }
                        ]
                    },
                    "Roles": [{"Ref": "R"}],
                },
            }
        }
    }
    assert roles_sin_decrypt(plantilla) == ["R"]


def test_las_plantillas_no_contienen_valores_de_secretos(todas):
    """Solo se admiten referencias dinámicas al secreto de origen; nunca llaves privadas ni
    ``SecretString`` con valor."""
    permitido = re.compile(
        r"\{\{resolve:secretsmanager:cc/(test|prod)/origin-verify:SecretString:::\}\}"
    )
    fallas = []
    for amb, stack, plantilla in todas:
        texto = json.dumps(plantilla)
        for ref in re.findall(r"\{\{resolve:[^}]*\}\}", texto):
            if not permitido.fullmatch(ref):
                fallas.append(f"{amb}/{stack}: {ref}")
        for marca in ("PRIVATE KEY", "AKIA", "ASIA", "xoxb-", "ghp_"):
            if marca in texto:
                fallas.append(f"{amb}/{stack}: contiene {marca}")
        for logico, r in plantilla["Resources"].items():
            if r["Type"] == "AWS::SecretsManager::Secret" and "SecretString" in r["Properties"]:
                fallas.append(f"{amb}/{stack}/{logico}: SecretString")
    assert not fallas, fallas


# ============================================================================== cifrado
def test_rds_cifrada_con_kms_y_con_tls(global_test, global_prod):
    for e in (global_test, global_prod):
        plantilla = e.json_de("data")
        (instancia,) = _recursos(plantilla, "AWS::RDS::DBInstance").values()
        assert instancia["Properties"]["StorageEncrypted"] is True
        assert "KmsKeyId" in instancia["Properties"]
        assert instancia["Properties"]["PubliclyAccessible"] is False
        (parametros,) = _recursos(plantilla, "AWS::RDS::DBParameterGroup").values()
        assert parametros["Properties"]["Parameters"]["rds.force_ssl"] == "1"
        for proxy in _recursos(plantilla, "AWS::RDS::DBProxy").values():
            assert proxy["Properties"]["RequireTLS"] is True


def test_todos_los_buckets_cifrados_sin_acceso_publico_y_con_tls(todas):
    fallas = []
    for amb, stack, plantilla in todas:
        politicas = json.dumps(_recursos(plantilla, "AWS::S3::BucketPolicy"))
        for logico, b in _recursos(plantilla, "AWS::S3::Bucket").items():
            p = b["Properties"]
            algoritmo = json.dumps(p.get("BucketEncryption", {}))
            if "aws:kms" not in algoritmo and "AES256" not in algoritmo:
                fallas.append(f"{amb}/{stack}/{logico}: sin cifrado")
            if p.get("PublicAccessBlockConfiguration") != {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }:
                fallas.append(f"{amb}/{stack}/{logico}: acceso público no bloqueado")
            if logico not in politicas or "aws:SecureTransport" not in politicas:
                fallas.append(f"{amb}/{stack}/{logico}: sin política que exija TLS")
    assert not fallas, fallas


def test_ninguna_politica_de_bucket_concede_a_cualquier_principal(todas):
    fallas = []
    for amb, stack, plantilla in todas:
        for logico, s in sentencias_de_recurso(plantilla):
            principal = s.get("Principal")
            if principal == "*" or (isinstance(principal, dict) and principal.get("AWS") == "*"):
                fallas.append(f"{amb}/{stack}/{logico}")
    assert not fallas, fallas


def _buckets_por_nombre(e) -> dict[str, dict]:
    return {
        b["Properties"]["BucketName"]: b["Properties"]
        for t in e.plantillas.values()
        for b in _recursos(t.to_json(), "AWS::S3::Bucket").values()
        if isinstance(b["Properties"].get("BucketName"), str)
    }


def test_buckets_con_versionado_donde_el_diseno_lo_pide(global_test, global_prod):
    """§14.5: ``constancias`` y ``plantillas`` versionados (la réplica de ``prod`` también)."""
    for e in (global_test, global_prod):
        buckets = _buckets_por_nombre(e)
        env = e.ambiente.nombre
        for nombre in ("constancias", "plantillas"):
            clave = f"cc-{env}-{CUENTA}-{nombre}"
            assert buckets[clave]["VersioningConfiguration"]["Status"] == "Enabled", clave
    replica = f"cc-prod-{CUENTA}-constancias-replica"
    assert _buckets_por_nombre(global_prod)[replica]["VersioningConfiguration"]["Status"] == (
        "Enabled"
    )


def test_constancias_tiene_object_lock_tambien_la_replica(global_test, global_prod):
    for e in (global_test, global_prod):
        bucket = _buckets_por_nombre(e)[f"cc-{e.ambiente.nombre}-{CUENTA}-constancias"]
        assert bucket["ObjectLockEnabled"] is True
        assert bucket["VersioningConfiguration"]["Status"] == "Enabled"
    # En test la retención de 1 día es el único modo de poder vaciar el bucket; en prod no hay
    # retención por defecto hasta resolver PQ-24 (la fija cada objeto).
    config = _buckets_por_nombre(global_test)[f"cc-test-{CUENTA}-constancias"]
    assert config["ObjectLockConfiguration"]["Rule"]["DefaultRetention"]["Mode"] == "GOVERNANCE"
    replica = _buckets_por_nombre(global_prod)[f"cc-prod-{CUENTA}-constancias-replica"]
    assert replica["ObjectLockEnabled"] is True


def test_constancias_se_replica_solo_en_prod(global_test, global_prod):
    assert (
        _buckets_por_nombre(global_test)[f"cc-test-{CUENTA}-constancias"].get(
            "ReplicationConfiguration"
        )
        is None
    )
    config = _buckets_por_nombre(global_prod)[f"cc-prod-{CUENTA}-constancias"][
        "ReplicationConfiguration"
    ]
    assert config["Rules"][0]["Status"] == "Enabled"


def test_todas_las_colas_cifradas_y_las_de_trabajo_con_dlq(todas):
    fallas = []
    for amb, stack, plantilla in todas:
        politicas = json.dumps(_recursos(plantilla, "AWS::SQS::QueuePolicy"))
        for logico, c in _recursos(plantilla, "AWS::SQS::Queue").items():
            p = c["Properties"]
            if "KmsMasterKeyId" not in p and p.get("SqsManagedSseEnabled") is not True:
                fallas.append(f"{amb}/{stack}/{logico}: sin cifrado")
            if logico not in politicas:
                fallas.append(f"{amb}/{stack}/{logico}: sin TLS obligatorio")
            es_dlq = str(p.get("QueueName", "")).removesuffix(".fifo").endswith("-dlq")
            if es_dlq == ("RedrivePolicy" in p):
                fallas.append(f"{amb}/{stack}/{logico}: una cola de trabajo exige DLQ y la DLQ no")
    assert not fallas, fallas


def test_diez_colas_de_trabajo_con_su_dlq_y_conteo_de_recepciones(global_test, global_prod):
    for e in (global_test, global_prod):
        colas = _recursos(e.json_de("messaging"), "AWS::SQS::Queue")
        trabajo = [c for c in colas.values() if "RedrivePolicy" in c["Properties"]]
        dlqs = [c for c in colas.values() if "RedrivePolicy" not in c["Properties"]]
        assert len(trabajo) == len(dlqs) == 10
        for c in trabajo:
            assert c["Properties"]["RedrivePolicy"]["maxReceiveCount"] >= 2


def test_temas_de_sns_cifrados(todas):
    fallas = [
        f"{amb}/{stack}/{logico}"
        for amb, stack, plantilla in todas
        for logico, t in _recursos(plantilla, "AWS::SNS::Topic").items()
        if "KmsMasterKeyId" not in t["Properties"]
    ]
    assert not fallas, fallas


def test_los_grupos_de_logs_tienen_retencion(todas):
    fallas = [
        f"{amb}/{stack}/{logico}"
        for amb, stack, plantilla in todas
        for logico, g in _recursos(plantilla, "AWS::Logs::LogGroup").items()
        if "RetentionInDays" not in g["Properties"]
    ]
    assert not fallas, fallas


# ================================================================================ identidad
def test_mfa_obligatorio_solo_con_totp(global_test, global_prod):
    for e in (global_test, global_prod):
        (pool,) = _recursos(e.json_de("auth"), "AWS::Cognito::UserPool").values()
        p = pool["Properties"]
        assert p["MfaConfiguration"] == "ON"
        assert p["EnabledMfas"] == ["SOFTWARE_TOKEN_MFA"]  # sin SMS


# ================================================================================ etiquetas
def _logicos_etiquetables(stack: cdk.Stack) -> list[str]:
    return [
        stack.get_logical_id(c)
        for c in stack.node.find_all()
        if isinstance(c, cdk.CfnResource)
        and (cdk.TagManager.is_taggable(c) or cdk.TagManager.is_taggable_v2(c))
    ]


def _etiquetas_de(recurso: dict) -> dict[str, str]:
    etiquetas: dict[str, str] = {}
    for clave, valor in recurso.get("Properties", {}).items():
        if not clave.endswith("Tags"):
            continue
        if isinstance(valor, dict):
            etiquetas.update({k: v for k, v in valor.items() if isinstance(v, str)})
        else:
            etiquetas.update(
                {t["Key"]: t["Value"] for t in lista(valor) if isinstance(t, dict) and "Key" in t}
            )
    return etiquetas


@pytest.mark.parametrize("amb", ["test", "prod"])
def test_todo_recurso_etiquetable_lleva_las_tres_etiquetas(amb, global_test, global_prod):
    e = global_test if amb == "test" else global_prod
    esperadas = {"proyecto": "command-center", "ambiente": amb, "responsable": "Samuel Lopez"}
    fallas = []
    total = 0
    for nombre, stack in e.stacks.items():
        recursos = e.json_de(nombre)["Resources"]
        for logico in _logicos_etiquetables(stack):
            if logico not in recursos:
                continue
            total += 1
            etiquetas = _etiquetas_de(recursos[logico])
            if {k: etiquetas.get(k) for k in esperadas} != esperadas:
                fallas.append(f"{nombre}/{recursos[logico]['Type']}/{logico}: {etiquetas}")
    assert total > 100  # la revisión no es vacía
    assert not fallas, fallas[:20]


# =================================================================================== regiones
def test_cc_edge_esta_en_us_east_1(global_test, global_prod):
    for e in (global_test, global_prod):
        assert REGION_EDGE == "us-east-1"
        assert e.stacks["edge"].region == "us-east-1"
        for nombre, plantilla in _plantillas(e).items():
            if nombre == "edge":
                continue
            # CloudFront y el WAF con alcance CloudFront solo viven en CcEdge.
            assert not _recursos(plantilla, "AWS::CloudFront::Distribution"), nombre
            for waf in _recursos(plantilla, "AWS::WAFv2::WebACL").values():
                assert waf["Properties"]["Scope"] != "CLOUDFRONT", nombre


def test_prod_define_la_region_de_recuperacion_y_test_no(global_test, global_prod):
    assert "recuperacion" not in global_test.stacks
    assert global_prod.stacks["recuperacion"].region == "us-east-2"
    for nombre, stack in global_test.stacks.items():
        assert stack.region == "us-east-1", nombre
        assert "us-east-2" not in json.dumps(global_test.json_de(nombre)), nombre
    for nombre, stack in global_prod.stacks.items():
        if nombre != "recuperacion":
            assert stack.region == "us-east-1", nombre


def test_la_guardia_de_cuenta_se_invoca_antes_de_definir_stacks():
    """Las pruebas de comportamiento están en ``test_guardia.py``; aquí se verifica el cableado."""
    fuente = ast.parse((INFRA / "app.py").read_text(encoding="utf-8"))
    funciones = {f.name: f for f in fuente.body if isinstance(f, ast.FunctionDef)}

    def llamadas(nombre: str) -> list[str]:
        return [
            n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
            for n in ast.walk(funciones[nombre])
            if isinstance(n, ast.Call)
        ]

    assert "verificar_cuenta" in llamadas("crear_app")
    principal = llamadas("main")
    assert principal.index("crear_app") < principal.index("construir_stacks")
    import infra.tests.test_guardia as guardia

    assert hasattr(guardia, "test_crear_app_aplica_la_guardia_antes_de_crear_stacks")
    assert hasattr(guardia, "test_cuenta_ausente_falla_con_indicacion_de_login")


# ====================================================== condicionales por ambiente (economía)
def test_waf_solo_en_prod(global_test, global_prod):
    assert not _tipos(global_test, "AWS::WAFv2::WebACL")
    (waf,) = _tipos(global_prod, "AWS::WAFv2::WebACL")
    assert waf["Properties"]["Scope"] == "CLOUDFRONT"
    (distribucion,) = _tipos(global_prod, "AWS::CloudFront::Distribution")
    assert "WebACLId" in distribucion["Properties"]["DistributionConfig"]
    (d_test,) = _tipos(global_test, "AWS::CloudFront::Distribution")
    assert "WebACLId" not in d_test["Properties"]["DistributionConfig"]


def test_rds_proxy_solo_en_prod(global_test, global_prod):
    assert not _tipos(global_test, "AWS::RDS::DBProxy")
    (proxy,) = _tipos(global_prod, "AWS::RDS::DBProxy")
    assert proxy["Properties"]["RequireTLS"] is True


def test_nat_instancia_en_test_y_gateways_en_prod(global_test, global_prod):
    assert not _tipos(global_test, "AWS::EC2::NatGateway")
    (nat,) = _tipos(global_test, "AWS::EC2::Instance")
    assert nat["Properties"]["InstanceType"] == "t4g.micro"
    assert len(_tipos(global_prod, "AWS::EC2::NatGateway")) == 2
    assert not _tipos(global_prod, "AWS::EC2::Instance")


def test_rds_economica_en_test_y_multi_az_protegida_en_prod(global_test, global_prod):
    (t,) = _tipos(global_test, "AWS::RDS::DBInstance")
    (p,) = _tipos(global_prod, "AWS::RDS::DBInstance")
    assert t["Properties"]["DBInstanceClass"] == "db.t4g.micro"
    assert t["Properties"]["MultiAZ"] is False
    assert t["Properties"]["BackupRetentionPeriod"] == 1
    assert t["Properties"]["DeletionProtection"] is False
    assert p["Properties"]["MultiAZ"] is True
    assert p["Properties"]["DeletionProtection"] is True
    assert p["Properties"]["BackupRetentionPeriod"] == 14


def test_minimo_de_tareas_de_los_workers(global_test, global_prod):
    def objetivos(e) -> list[tuple[int, int]]:
        return [
            (r["Properties"]["MinCapacity"], r["Properties"]["MaxCapacity"])
            for r in _tipos(e, "AWS::ApplicationAutoScaling::ScalableTarget")
            if "worker" in json.dumps(r["Properties"]["ResourceId"])
        ]

    en_test = objetivos(global_test)
    assert len(en_test) == 3
    assert all(minimo == 0 and maximo == 1 for minimo, maximo in en_test)
    en_prod = objetivos(global_prod)
    assert len(en_prod) == 3
    assert all(minimo >= 1 for minimo, _ in en_prod)
    assert max(minimo for minimo, _ in en_prod) >= 2  # whatsapp-entrada: alta disponibilidad


# =============================================================================== red y roles
def _ingresos_abiertos(plantilla: dict) -> list[str]:
    abiertos = []
    for logico, r in plantilla["Resources"].items():
        if r["Type"] == "AWS::EC2::SecurityGroup":
            reglas = r["Properties"].get("SecurityGroupIngress", [])
        elif r["Type"] == "AWS::EC2::SecurityGroupIngress":
            reglas = [r["Properties"]]
        else:
            continue
        for regla in lista(reglas):
            if regla.get("CidrIp") == "0.0.0.0/0" or regla.get("CidrIpv6") == "::/0":
                abiertos.append(logico)
    return abiertos


def test_ningun_grupo_de_seguridad_admite_entrada_desde_internet(todas):
    """No hay excepciones documentadas: ni en ``test`` ni en ``prod`` (CloudFront y API Gateway
    son administrados y el ALB es interno)."""
    fallas = {
        f"{amb}/{stack}": abiertos
        for amb, stack, plantilla in todas
        if (abiertos := _ingresos_abiertos(plantilla))
    }
    assert not fallas, fallas


def test_el_alb_es_interno(todas):
    total = 0
    for amb, stack, plantilla in todas:
        for logico, alb in _recursos(
            plantilla, "AWS::ElasticLoadBalancingV2::LoadBalancer"
        ).items():
            total += 1
            assert alb["Properties"].get("Scheme") == "internal", f"{amb}/{stack}/{logico}"
    assert total >= 2


# ======================================================== nag sobre el ensamblado completo de prod
def _violaciones(reporte: dict) -> list:
    return [
        (r.get("ruleName"), [v.get("constructPath") for v in r.get("violatingConstructs", [])])
        for p in reporte.get("pluginReports", [])
        if "CloudFormation Validate" not in str(p.get("pluginName"))
        for r in p.get("violations", [])
    ]


def test_cdk_nag_no_deja_hallazgos_en_prod_con_todos_los_stacks(tmp_path):
    """``test_nag.py`` sintetiza ``test`` con la CLI; aquí se hace lo mismo con el ``prod`` sintético
    (donde viven WAF, Proxy, réplica, CcBackup y CcPipeline) y se lee el informe de validación."""
    from infra.tests.ayudas_globales import construir_prod

    salida = tmp_path / "prod"
    ensamblado = construir_prod(con_nag=True, salida=str(salida))
    reporte = salida / "validation-report.json"
    try:
        ensamblado.app.synth()
    except Exception as exc:  # noqa: BLE001 - se muestra el informe, no solo el mensaje
        detalle = json.dumps(_violaciones(json.loads(reporte.read_text(encoding="utf-8"))))
        pytest.fail(f"cdk-nag: {str(exc)[:200]}\n{detalle}")
    if reporte.exists():
        assert _violaciones(json.loads(reporte.read_text(encoding="utf-8"))) == []
