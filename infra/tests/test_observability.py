"""T-139 (observabilidad): paneles, alarmas de §15.2 con su runbook, retención de logs y CloudTrail."""

import pytest

from infra.constructs.servicios import SERVICIOS
from infra.stacks.messaging import COLAS
from infra.stacks.observability import (
    ALMACENAMIENTO_RDS_GB,
    CARPETA_RUNBOOKS,
    MAX_CONEXIONES_RDS,
    RETENCION_CLOUDTRAIL_DIAS,
    RETENCION_LOGS_DIAS,
    UMBRALES,
)
from infra.tests.ayudas_borde import (
    RAIZ,
    alarmas_por_nombre,
    construir_borde_prod,
    indice_de_runbooks,
    propiedades,
    recursos,
    texto,
)


@pytest.fixture(scope="module")
def plantilla(ensamblado_test):
    return ensamblado_test[1]["observability"]


@pytest.fixture(scope="module")
def prod():
    return construir_borde_prod()["observability"]


def _esperadas(env: str) -> set[str]:
    """Alarmas del índice de runbooks (``docs/runbooks/README.md``) expandidas a nombres reales."""
    nombres: set[str] = set()
    for ident in indice_de_runbooks():
        if ident == "dlq-{cola}":
            nombres |= {f"cc-{env}-dlq-{c.nombre}" for c in COLAS}
        elif ident.endswith("-{servicio}"):
            nombres |= {f"cc-{env}-{ident.removesuffix('{servicio}')}{s}" for s in SERVICIOS}
        else:
            nombres.add(f"cc-{env}-{ident}")
    return nombres


# ------------------------------------------------------------------------------ alarmas
def test_cada_alarma_del_indice_de_runbooks_existe_y_no_hay_alarmas_sin_runbook(plantilla):
    esperadas = _esperadas("test")
    # La conmutación de RDS es un evento (regla de EventBridge), no una métrica.
    esperadas_alarmas = esperadas - {"cc-test-rds-conmutacion"}
    assert set(alarmas_por_nombre(plantilla)) == esperadas_alarmas
    (regla,) = (
        p
        for p in propiedades(plantilla, "AWS::Events::Rule")
        if p["Name"] == "cc-test-rds-conmutacion"
    )
    assert regla["EventPattern"]["detail"]["EventCategories"] == ["failover"]
    assert regla["EventPattern"]["source"] == ["aws.rds"]


def test_el_indice_cubre_todas_las_alarmas_del_diseno():
    ids = set(indice_de_runbooks())
    assert {"dlq-{cola}", "cola-antigua-wa-salida", "cola-antigua-cola-pdf"} <= ids
    assert {"webhook-firma-invalida", "webhook-5xx", "meta-errores", "pdf-lento"} <= ids
    assert {"rds-cpu", "rds-conexiones", "rds-almacenamiento", "rds-conmutacion"} <= ids
    assert {"programadas-atrasadas", "cognito-pre-token-errores", "ses-rebotes"} <= ids
    assert {"error-descifrado", "5xx-{servicio}", "latencia-{servicio}"} <= ids


def test_cada_alarma_enlaza_su_runbook_del_indice_y_marca_el_umbral_por_confirmar(plantilla):
    indice = indice_de_runbooks()
    for nombre, a in alarmas_por_nombre(plantilla).items():
        ident = nombre.removeprefix("cc-test-")
        archivo = next(
            f
            for i, f in indice.items()
            if i == ident
            or (i == "dlq-{cola}" and ident.startswith("dlq-"))
            or (i.endswith("-{servicio}") and ident.startswith(i.removesuffix("{servicio}")))
        )
        assert (RAIZ / CARPETA_RUNBOOKS / archivo).is_file(), f"{archivo} no existe"
        assert f"{CARPETA_RUNBOOKS}/{archivo}" in a["AlarmDescription"]
        assert "[POR CONFIRMAR, PQ-20]" in a["AlarmDescription"]
        assert len(a["AlarmDescription"]) <= 1024


def test_los_umbrales_viven_en_una_tabla_y_apuntan_a_runbooks_reales():
    for clave, u in UMBRALES.items():
        assert (RAIZ / CARPETA_RUNBOOKS / u.runbook).is_file(), clave
        assert u.severidad in ("Crítica", "Alta", "Media")
    indice = indice_de_runbooks()
    for ident, archivo in indice.items():
        clave = "dlq" if ident == "dlq-{cola}" else ident.removesuffix("-{servicio}")
        assert UMBRALES[clave].runbook == archivo, ident


def test_todas_las_alarmas_notifican_al_tema_de_operacion_y_sin_datos_no_alarman(plantilla):
    (tema,) = (
        lid
        for lid, r in recursos(plantilla, "AWS::SNS::Topic").items()
        if r["Properties"]["TopicName"] == "cc-test-alertas-ops"
    )
    for nombre, a in alarmas_por_nombre(plantilla).items():
        assert a["AlarmActions"] == [{"Ref": tema}], nombre
        assert a["TreatMissingData"] == "notBreaching", nombre
    (t,) = propiedades(plantilla, "AWS::SNS::Topic")
    assert "KmsMasterKeyId" in t  # cifrado con la llave de infraestructura
    (regla,) = (
        p
        for p in propiedades(plantilla, "AWS::Events::Rule")
        if p["Name"] == "cc-test-rds-conmutacion"
    )
    assert regla["Targets"][0]["Arn"] == {"Ref": tema}


def _umbral(plantilla, nombre: str) -> float:
    return alarmas_por_nombre(plantilla)[nombre]["Threshold"]


def test_umbrales_de_la_seccion_15_2(plantilla):
    a = alarmas_por_nombre(plantilla)
    for c in COLAS:
        d = a[f"cc-test-dlq-{c.nombre}"]
        assert d["MetricName"] == "ApproximateNumberOfMessagesVisible"
        assert d["Threshold"] == 0 and d["ComparisonOperator"] == "GreaterThanThreshold"
        assert d["Dimensions"][0]["Value"].startswith(f"cc-test-{c.nombre}-dlq")
    assert a["cc-test-dlq-wa-salida"]["Dimensions"][0]["Value"] == "cc-test-wa-salida-dlq.fifo"
    assert _umbral(plantilla, "cc-test-cola-antigua-wa-salida") == 300  # 5 minutos
    assert _umbral(plantilla, "cc-test-cola-antigua-cola-pdf") == 600  # 10 minutos
    assert a["cc-test-cola-antigua-wa-salida"]["Dimensions"][0]["Value"] == "cc-test-wa-salida.fifo"
    assert _umbral(plantilla, "cc-test-webhook-firma-invalida") == 10
    assert a["cc-test-webhook-firma-invalida"]["Namespace"] == "CommandCenter/WhatsApp"
    assert _umbral(plantilla, "cc-test-pdf-lento") == 5000  # 5 s de CC-NFR-001
    assert a["cc-test-pdf-lento"]["ExtendedStatistic"] == "p95"
    assert _umbral(plantilla, "cc-test-rds-cpu") == 80
    assert _umbral(plantilla, "cc-test-programadas-atrasadas") == 0
    assert a["cc-test-programadas-atrasadas"]["EvaluationPeriods"] == 3  # 15 minutos
    assert a["cc-test-programadas-atrasadas"]["Namespace"] == "CommandCenter/Notificaciones"
    assert _umbral(plantilla, "cc-test-cognito-pre-token-errores") == 0
    assert a["cc-test-cognito-pre-token-errores"]["Dimensions"][0]["Value"] == (
        "cc-test-cognito-pre-token"
    )
    assert _umbral(plantilla, "cc-test-ses-rebotes") == 0.05
    assert _umbral(plantilla, "cc-test-error-descifrado") == 0
    assert _umbral(plantilla, "cc-test-webhook-5xx") == 0
    assert a["cc-test-webhook-5xx"]["Dimensions"][0]["Value"] == "cc-test-webhook-meta"


def test_rds_conexiones_y_almacenamiento_se_calculan_para_la_clase_y_el_disco(plantilla, prod):
    a = alarmas_por_nombre(plantilla)
    assert a["cc-test-rds-conexiones"]["Threshold"] == pytest.approx(
        0.8 * MAX_CONEXIONES_RDS["db.t4g.micro"]
    )
    alm = a["cc-test-rds-almacenamiento"]
    assert alm["ComparisonOperator"] == "LessThanThreshold"
    assert alm["Threshold"] == pytest.approx(0.2 * ALMACENAMIENTO_RDS_GB["test"] * 2**30)
    p = alarmas_por_nombre(prod)
    assert p["cc-prod-rds-conexiones"]["Threshold"] == pytest.approx(
        0.8 * MAX_CONEXIONES_RDS["db.t4g.medium"]
    )
    assert p["cc-prod-rds-almacenamiento"]["Threshold"] == pytest.approx(
        0.2 * ALMACENAMIENTO_RDS_GB["prod"] * 2**30
    )


def test_5xx_y_latencia_por_servicio(plantilla):
    a = alarmas_por_nombre(plantilla)
    for s in SERVICIOS:
        cinco = a[f"cc-test-5xx-{s}"]
        assert cinco["Threshold"] == 5
        assert cinco["EvaluationPeriods"] == 1  # durante 5 minutos
        expresion = [m for m in cinco["Metrics"] if "Expression" in m][0]["Expression"]
        # Con pocas solicitudes un solo error no es "5 %": exige un mínimo.
        assert "solicitudes >= 10" in expresion
        lat = a[f"cc-test-latencia-{s}"]
        assert lat["Threshold"] == 2
        assert lat["ExtendedStatistic"] == "p95"
        assert lat["EvaluationPeriods"] * lat["Period"] == 600  # durante 10 minutos
        assert lat["MetricName"] == "TargetResponseTime"
        dims = {d["Name"] for d in lat["Dimensions"]}
        assert dims == {"LoadBalancer", "TargetGroup"}


def test_errores_de_meta_se_miden_con_un_filtro_de_metricas_del_registro_de_enviador(plantilla):
    (f,) = propiedades(plantilla, "AWS::Logs::MetricFilter")
    assert f["LogGroupName"] == "/aws/lambda/cc-test-enviador"
    assert "meta_error_*" in f["FilterPattern"]
    (m,) = f["MetricTransformations"]
    assert m["MetricNamespace"] == "CommandCenter/Observabilidad"
    assert m["MetricName"] == "meta_errores"
    a = alarmas_por_nombre(plantilla)["cc-test-meta-errores"]
    assert a["Threshold"] == 10
    assert a["EvaluationPeriods"] * 5 == 10  # durante 10 minutos


def test_cada_umbral_de_la_tabla_esta_marcado_por_confirmar_en_la_tabla_de_runbooks():
    texto_indice = (RAIZ / CARPETA_RUNBOOKS / "README.md").read_text(encoding="utf-8")
    assert "POR CONFIRMAR" in texto_indice
    assert "PQ-20" in texto_indice


# ------------------------------------------------------------------------------ paneles
def test_test_agrupa_los_paneles_en_tres_gratuitos(plantilla):
    nombres = {p["DashboardName"] for p in propiedades(plantilla, "AWS::CloudWatch::Dashboard")}
    assert nombres == {"cc-test-operacion", "cc-test-colas-whatsapp", "cc-test-constancias"}


def test_prod_crea_los_cinco_paneles_de_la_seccion_15_2(prod):
    nombres = {p["DashboardName"] for p in propiedades(prod, "AWS::CloudWatch::Dashboard")}
    assert nombres == {
        "cc-prod-operacion",
        "cc-prod-colas",
        "cc-prod-whatsapp",
        "cc-prod-constancias",
        "cc-prod-base-de-datos",
    }


def _cuerpo_panel(plantilla, nombre: str) -> str:
    (p,) = (
        p
        for p in propiedades(plantilla, "AWS::CloudWatch::Dashboard")
        if p["DashboardName"] == nombre
    )
    return texto(p["DashboardBody"])


def test_contenido_de_los_paneles(plantilla, prod):
    operacion = _cuerpo_panel(prod, "cc-prod-operacion")
    assert "TargetResponseTime" in operacion and "HTTPCode_Target_5XX_Count" in operacion
    for s in SERVICIOS:
        assert f"targetgroup/cc-prod-{s}/abc" in operacion
    colas = _cuerpo_panel(prod, "cc-prod-colas")
    assert "ApproximateAgeOfOldestMessage" in colas and "cc-prod-cola-pdf-dlq" in colas
    assert "envios_ok" in _cuerpo_panel(prod, "cc-prod-whatsapp")
    assert "duracion_generacion_ms" in _cuerpo_panel(prod, "cc-prod-constancias")
    bd = _cuerpo_panel(prod, "cc-prod-base-de-datos")
    assert "DatabaseConnections" in bd and "FreeStorageSpace" in bd and "CPUUtilization" in bd
    # En test la base de datos va en el panel de operación y WhatsApp con las colas.
    assert "FreeStorageSpace" in _cuerpo_panel(plantilla, "cc-test-operacion")
    assert "envios_ok" in _cuerpo_panel(plantilla, "cc-test-colas-whatsapp")


# ------------------------------------------------------------------------------ retención de logs
def test_todo_grupo_de_logs_de_la_aplicacion_tiene_retencion_de_30_dias(ensamblado_test):
    """Se fija donde se crea cada grupo (CcAuth, CcCompute, CcWorkersLambdas, CcApi): ninguno
    queda con retención infinita (design.md §15.1)."""
    _, plantillas = ensamblado_test
    grupos = {
        (n, lid): r["Properties"]
        for n, t in plantillas.items()
        for lid, r in recursos(t, "AWS::Logs::LogGroup").items()
    }
    assert len(grupos) >= 16
    sin = [k for k, p in grupos.items() if p.get("RetentionInDays") != RETENCION_LOGS_DIAS]
    assert not sin, sin
    assert RETENCION_LOGS_DIAS == 30


def test_observabilidad_no_duplica_grupos_de_logs(plantilla):
    assert not recursos(plantilla, "AWS::Logs::LogGroup")


# ------------------------------------------------------------------------------ CloudTrail
def test_cloudtrail_de_gestion_con_validacion_de_integridad_y_bucket_cifrado(plantilla):
    (t,) = propiedades(plantilla, "AWS::CloudTrail::Trail")
    assert t["EnableLogFileValidation"] is True
    assert t["IsLogging"] is True
    assert t["IncludeGlobalServiceEvents"] is True
    assert t["IsMultiRegionTrail"] is True
    assert "KMSKeyId" in t
    assert "CloudWatchLogsLogGroupArn" not in t  # costo: sin entrega a CloudWatch Logs
    (sel,) = t["EventSelectors"]
    assert sel["IncludeManagementEvents"] is True
    assert sel["ReadWriteType"] == "All"
    assert "DataResources" not in sel  # solo eventos de gestión (el primer trail es gratis)


def test_el_bucket_de_cloudtrail_es_propio_privado_cifrado_y_con_retencion_de_un_ano(plantilla):
    buckets = recursos(plantilla, "AWS::S3::Bucket")
    (lid, b) = next(iter(buckets.items()))
    assert len(buckets) == 1
    p = b["Properties"]
    assert p["BucketName"].endswith("-cloudtrail") or "cloudtrail" in texto(p["BucketName"])
    regla = p["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]
    assert regla["ServerSideEncryptionByDefault"]["SSEAlgorithm"] == "aws:kms"
    assert "KMSMasterKeyID" in regla["ServerSideEncryptionByDefault"]
    assert p["PublicAccessBlockConfiguration"]["BlockPublicAcls"] is True
    assert p["PublicAccessBlockConfiguration"]["RestrictPublicBuckets"] is True
    (vida,) = (r for r in p["LifecycleConfiguration"]["Rules"] if r["Id"] == "retencion-cloudtrail")
    assert vida["ExpirationInDays"] == RETENCION_CLOUDTRAIL_DIAS == 365
    # test se puede destruir con cdk destroy; prod conserva el bucket.
    assert b["DeletionPolicy"] == "Delete"
    politicas = propiedades(plantilla, "AWS::S3::BucketPolicy")
    todas = texto(politicas)
    assert "aws:SecureTransport" in todas
    assert "cloudtrail.amazonaws.com" in todas


def test_prod_conserva_el_bucket_de_cloudtrail(prod):
    (b,) = recursos(prod, "AWS::S3::Bucket").values()
    assert b["DeletionPolicy"] == "Retain"
    (t,) = propiedades(prod, "AWS::CloudTrail::Trail")
    assert t["EnableLogFileValidation"] is True


def test_la_plantilla_no_lleva_secretos(plantilla):
    t = texto(plantilla.to_json())
    assert "AKIA" not in t and "PRIVATE KEY" not in t
    assert "secretsmanager" not in t
