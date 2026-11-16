"""T-140: aserciones de ``CcBackup``, ``CcBackupRecuperacion`` y la réplica de ``constancias``.

Plan de AWS Backup con copia a ``us-east-2`` y réplica de ``constancias``: **solo definidos**. La
región de recuperación no está inicializada con ``cdk bootstrap`` y no se despliega en ``test``: se
prueba con el ``prod`` sintético (``infra/tests/ayudas_globales.py``).
"""

from __future__ import annotations

import json

import aws_cdk as cdk
import pytest

from infra.config import esquema
from infra.constructs import recuperacion
from infra.stacks.backup import BackupRecoveryStack
from infra.tests.ayudas_globales import (
    construir_test,
    lista,
    sentencias_de_identidad,
)

CUENTA = "034362033822"
ARN_BOVEDA_RECUPERACION = f"arn:aws:backup:us-east-2:{CUENTA}:backup-vault:cc-prod-recuperacion"
ALIAS_RECUPERACION = f"arn:aws:kms:us-east-2:{CUENTA}:alias/cc-prod-recuperacion"


def _recursos(e, stack: str, tipo: str) -> dict[str, dict]:
    return {k: v for k, v in e.json_de(stack)["Resources"].items() if v["Type"] == tipo}


def _unico(e, stack: str, tipo: str) -> dict:
    (recurso,) = _recursos(e, stack, tipo).values()
    return recurso


# ===================================================================================== test
def test_en_test_hay_plan_de_un_dia_sin_copia_ni_recursos_de_us_east_2(global_test):
    assert "backup" in global_test.stacks
    assert "recuperacion" not in global_test.stacks
    plan = _unico(global_test, "backup", "AWS::Backup::BackupPlan")["Properties"]["BackupPlan"]
    (regla,) = plan["BackupPlanRule"]
    assert regla["Lifecycle"]["DeleteAfterDays"] == 1  # retencion_respaldos_dias de test
    assert "CopyActions" not in regla
    for nombre in global_test.stacks:
        assert "us-east-2" not in json.dumps(global_test.json_de(nombre)), nombre


def test_en_test_la_boveda_es_borrable_y_sin_bloqueo(global_test):
    boveda = _unico(global_test, "backup", "AWS::Backup::BackupVault")
    assert boveda["DeletionPolicy"] == "Delete"
    assert "LockConfiguration" not in boveda["Properties"]
    assert "AccessPolicy" not in boveda["Properties"]
    assert boveda["Properties"]["BackupVaultName"] == "cc-test-respaldos"


def test_la_boveda_se_cifra_con_la_llave_de_infraestructura(global_test, global_prod):
    for e in (global_test, global_prod):
        boveda = _unico(e, "backup", "AWS::Backup::BackupVault")
        llave = json.dumps(boveda["Properties"]["EncryptionKeyArn"])
        assert "LlaveInfra" in llave  # importada de CcSecurity, no la llave por defecto de AWS


def test_la_seleccion_cubre_la_instancia_de_rds(global_test, global_prod):
    for e in (global_test, global_prod):
        sel = _unico(e, "backup", "AWS::Backup::BackupSelection")["Properties"]["BackupSelection"]
        (recurso,) = sel["Resources"]
        assert ":rds:" in json.dumps(recurso) and ":db:" in json.dumps(recurso)
        assert "Postgres" in json.dumps(recurso)  # la instancia de CcData


def test_se_puede_omitir_el_respaldo_en_test():
    e = construir_test({"respaldo": "false"})
    assert "backup" not in e.stacks


def test_el_rol_de_respaldo_no_usa_politicas_administradas(global_test, global_prod):
    for e in (global_test, global_prod):
        rol = _unico(e, "backup", "AWS::IAM::Role")["Properties"]
        assert "ManagedPolicyArns" not in rol
        confianza = rol["AssumeRolePolicyDocument"]["Statement"][0]
        assert confianza["Principal"] == {"Service": "backup.amazonaws.com"}
        assert confianza["Condition"] == {"StringEquals": {"aws:SourceAccount": CUENTA}}


def test_la_politica_del_rol_acota_a_la_cuenta_y_al_ambiente(global_test, global_prod):
    for e in (global_test, global_prod):
        sentencias = sentencias_de_identidad(e.json_de("backup"))
        for _, s in sentencias:
            assert "*" not in lista(s["Resource"]), s
        texto = json.dumps([s for _, s in sentencias])
        assert CUENTA in texto
        assert f'"aws:ResourceTag/ambiente": "{e.ambiente.nombre}"' in texto
        assert "snapshot:awsbackup:*" in texto


# ===================================================================================== prod
def test_en_prod_el_plan_retiene_35_dias_y_copia_a_us_east_2(global_prod):
    plan = _unico(global_prod, "backup", "AWS::Backup::BackupPlan")["Properties"]["BackupPlan"]
    (regla,) = plan["BackupPlanRule"]
    assert regla["Lifecycle"]["DeleteAfterDays"] == recuperacion.RETENCION_PROD_DIAS == 35
    (copia,) = regla["CopyActions"]
    assert copia["DestinationBackupVaultArn"] == ARN_BOVEDA_RECUPERACION
    assert copia["Lifecycle"]["DeleteAfterDays"] == 35
    assert regla["ScheduleExpression"] == "cron(0 7 * * ? *)"


def test_en_prod_la_boveda_no_se_borra_por_accidente(global_prod):
    boveda = _unico(global_prod, "backup", "AWS::Backup::BackupVault")
    assert boveda["DeletionPolicy"] == "Retain"
    assert boveda["Properties"]["LockConfiguration"]["MinRetentionDays"] == 7
    (s,) = lista(boveda["Properties"]["AccessPolicy"]["Statement"])
    assert s["Effect"] == "Deny"
    assert {"backup:DeleteRecoveryPoint", "backup:UpdateRecoveryPointLifecycle"} <= set(
        lista(s["Action"])
    )


def test_en_prod_el_rol_puede_copiar_solo_a_la_boveda_de_recuperacion(global_prod):
    sentencias = [s for _, s in sentencias_de_identidad(global_prod.json_de("backup"))]
    (copia,) = (s for s in sentencias if "backup:CopyIntoBackupVault" in lista(s["Action"]))
    assert copia["Resource"] == ARN_BOVEDA_RECUPERACION
    (llave,) = (
        s
        for s in sentencias
        if s.get("Condition", {}).get("ForAnyValue:StringEquals", {}).get("kms:ResourceAliases")
    )
    assert llave["Condition"]["ForAnyValue:StringEquals"]["kms:ResourceAliases"] == (
        "alias/cc-prod-recuperacion"
    )
    assert llave["Resource"] == f"arn:aws:kms:us-east-2:{CUENTA}:key/*"


# ===================================================================== región de recuperación
def test_la_region_de_recuperacion_define_llave_boveda_y_replica(global_prod):
    stack = global_prod.stacks["recuperacion"]
    assert stack.region == "us-east-2"
    llave = _unico(global_prod, "recuperacion", "AWS::KMS::Key")
    assert llave["Properties"]["EnableKeyRotation"] is True
    assert llave["DeletionPolicy"] == "Retain"
    alias = _unico(global_prod, "recuperacion", "AWS::KMS::Alias")
    assert alias["Properties"]["AliasName"] == "alias/cc-prod-recuperacion"
    boveda = _unico(global_prod, "recuperacion", "AWS::Backup::BackupVault")["Properties"]
    assert boveda["BackupVaultName"] == "cc-prod-recuperacion"
    assert boveda["LockConfiguration"]["MinRetentionDays"] == 7
    assert "LlaveRecuperacion" in json.dumps(boveda["EncryptionKeyArn"])


def test_la_replica_de_constancias_conserva_el_object_lock(global_prod):
    buckets = {
        b["Properties"]["BucketName"]: b
        for b in _recursos(global_prod, "recuperacion", "AWS::S3::Bucket").values()
    }
    replica = buckets[f"cc-prod-{CUENTA}-constancias-replica"]
    p = replica["Properties"]
    assert replica["DeletionPolicy"] == "Retain"
    assert p["ObjectLockEnabled"] is True
    assert p["VersioningConfiguration"]["Status"] == "Enabled"
    cifrado = p["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]
    assert cifrado["ServerSideEncryptionByDefault"]["SSEAlgorithm"] == "aws:kms"


def test_constancias_replica_hacia_la_replica_con_la_llave_de_recuperacion(global_prod):
    (constancias,) = (
        b["Properties"]
        for b in _recursos(global_prod, "storage", "AWS::S3::Bucket").values()
        if b["Properties"]["BucketName"] == f"cc-prod-{CUENTA}-constancias"
    )
    (regla,) = constancias["ReplicationConfiguration"]["Rules"]
    destino = regla["Destination"]
    assert destino["Bucket"] == f"arn:aws:s3:::cc-prod-{CUENTA}-constancias-replica"
    assert destino["EncryptionConfiguration"]["ReplicaKmsKeyID"] == ALIAS_RECUPERACION
    assert regla["SourceSelectionCriteria"]["SseKmsEncryptedObjects"]["Status"] == "Enabled"
    # borrar en el origen no borra la réplica
    assert regla["DeleteMarkerReplication"]["Status"] == "Disabled"
    assert regla["Status"] == "Enabled"


def test_el_rol_de_replicacion_es_de_minimo_privilegio(global_prod):
    plantilla = global_prod.json_de("storage")
    (rol,) = (
        r["Properties"]
        for r in _recursos(global_prod, "storage", "AWS::IAM::Role").values()
        if r["Properties"].get("RoleName") == "cc-prod-s3-replicacion-constancias"
    )
    confianza = rol["AssumeRolePolicyDocument"]["Statement"][0]
    assert confianza["Principal"] == {"Service": "s3.amazonaws.com"}
    assert confianza["Condition"] == {"StringEquals": {"aws:SourceAccount": CUENTA}}
    sentencias = [s for _, s in sentencias_de_identidad(plantilla)]
    acciones = {a for s in sentencias for a in lista(s["Action"])}
    assert "s3:ReplicateObject" in acciones and "s3:GetObjectRetention" in acciones
    assert "s3:ReplicateDelete" not in acciones  # las marcas de borrado no se replican
    assert not any(a.startswith(("iam:", "sts:")) or a.endswith(":*") for a in acciones)
    assert all("*" not in lista(s["Resource"]) for s in sentencias)
    descifra = [s for s in sentencias if "kms:Decrypt" in lista(s["Action"])]
    assert descifra and "*" not in json.dumps([s["Resource"] for s in descifra]).replace("/*", "")


def test_los_nombres_compartidos_coinciden_con_los_recursos_creados(global_prod):
    """``recuperacion.py`` arma los nombres que usan tres stacks: si cambia uno, esto falla."""
    assert recuperacion.arn_boveda_recuperacion("prod", CUENTA) == ARN_BOVEDA_RECUPERACION
    assert recuperacion.arn_alias_llave_recuperacion("prod", CUENTA) == ALIAS_RECUPERACION
    assert recuperacion.nombre_bucket_replica("prod", CUENTA).endswith("constancias-replica")
    nombres = {
        b["Properties"]["BucketName"]
        for b in _recursos(global_prod, "recuperacion", "AWS::S3::Bucket").values()
    }
    assert recuperacion.nombre_bucket_replica("prod", CUENTA) in nombres


def test_orden_de_despliegue_de_la_recuperacion(global_prod):
    """La réplica exige que el bucket de destino exista: ``CcStorage`` depende de la recuperación."""
    storage = global_prod.stacks["storage"]
    recuperacion_stack = global_prod.stacks["recuperacion"]
    assert recuperacion_stack in storage.dependencies
    respaldo = global_prod.stacks["backup"]
    nombres = {d.stack_name for d in respaldo.dependencies}
    assert {"CcData-prod", "CcStorage-prod", "CcBackupRecuperacion-prod"} <= nombres


def test_la_region_de_recuperacion_no_se_define_en_test():
    test = esquema.obtener_ambiente("test")
    assert recuperacion.recuperacion_habilitada(test) is False
    app = cdk.App()
    with pytest.raises(ValueError, match="solo se define en prod"):
        BackupRecoveryStack(app, "CcBackupRecuperacion-test", ambiente=test)


def test_la_recuperacion_se_decide_por_el_ambiente_no_por_un_contexto():
    """Ni siquiera con ``-c`` se crean recursos de ``us-east-2`` en ``test``."""
    e = construir_test({"recuperacion": "true", "region_recuperacion": "us-east-2"})
    assert "recuperacion" not in e.stacks
