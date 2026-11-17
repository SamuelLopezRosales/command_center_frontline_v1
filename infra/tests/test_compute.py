"""T-135: aserciones del stack CcCompute (servicios de ECS y ALB interno con reglas por ruta)."""

import json
from pathlib import Path

import pytest
from aws_cdk.assertions import Template

from infra.app import construir_stacks, crear_app
from infra.constructs.servicios import SERVICIOS
from infra.stacks.compute import REGLAS_ALB, TAMANOS
from infra.tests.ayudas_computo import (
    CERTIFICADO,
    DOMINIO_INTERNO,
    PERMITIDA,
    acciones,
    coincide_alb,
    construir_prod,
    entorno_contenedor,
    propiedades,
    recursos,
    recursos_de,
    rol_logico_por_nombre,
    sentencias_de_rol,
    texto,
)


@pytest.fixture(scope="module")
def ensamblado():
    app, amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    stacks = construir_stacks(app, amb, destino)
    return stacks, Template.from_stack(stacks["compute"])


@pytest.fixture(scope="module")
def plantilla(ensamblado) -> Template:
    return ensamblado[1]


@pytest.fixture(scope="module")
def plantilla_prod() -> Template:
    return construir_prod()[0]


def _tareas(plantilla) -> dict[str, dict]:
    return {t["Family"]: t for t in propiedades(plantilla, "AWS::ECS::TaskDefinition")}


def _servicios(plantilla) -> dict[str, dict]:
    return {s["ServiceName"]: s for s in propiedades(plantilla, "AWS::ECS::Service")}


# ------------------------------------------------------------------------------ servicios
def test_seis_servicios_fargate_arm64(plantilla):
    servicios = _servicios(plantilla)
    assert set(servicios) == {f"cc-test-{s}" for s in SERVICIOS}
    for s in servicios.values():
        assert s["LaunchType"] == "FARGATE"
        assert s["Cluster"] == "cc-test"  # el clúster es el de CcComputeBase, importado
        assert s["NetworkConfiguration"]["AwsvpcConfiguration"]["AssignPublicIp"] == "DISABLED"
    tareas = _tareas(plantilla)
    assert set(tareas) == {f"cc-test-{s}" for s in SERVICIOS}
    for t in tareas.values():
        assert t["RuntimePlatform"] == {
            "CpuArchitecture": "ARM64",
            "OperatingSystemFamily": "LINUX",
        }
        assert t["RequiresCompatibilities"] == ["FARGATE"]


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_tamano_por_servicio(plantilla, servicio):
    cpu, memoria = TAMANOS[servicio]
    t = _tareas(plantilla)[f"cc-test-{servicio}"]
    assert (t["Cpu"], t["Memory"]) == (str(cpu), str(memoria))
    # design.md §13.6: 0.5 vCPU y 1 GB; campos 0.25 vCPU y 0.5 GB.
    assert (cpu, memoria) == ((256, 512) if servicio == "campos" else (512, 1024))


def test_una_tarea_por_servicio_y_sin_autoescalado_en_test(plantilla):
    for s in _servicios(plantilla).values():
        assert s["DesiredCount"] == 1
    plantilla.resource_count_is("AWS::ApplicationAutoScaling::ScalableTarget", 0)


def test_prod_dos_tareas_y_autoescalado_de_2_a_6_por_cpu_al_60(plantilla_prod):
    for s in _servicios(plantilla_prod).values():
        assert s["DesiredCount"] == 2
    objetivos = propiedades(plantilla_prod, "AWS::ApplicationAutoScaling::ScalableTarget")
    assert len(objetivos) == 6
    for o in objetivos:
        assert (o["MinCapacity"], o["MaxCapacity"]) == (2, 6)
        assert o["ScalableDimension"] == "ecs:service:DesiredCount"
    politicas = propiedades(plantilla_prod, "AWS::ApplicationAutoScaling::ScalingPolicy")
    assert len(politicas) == 6
    for p in politicas:
        cfg = p["TargetTrackingScalingPolicyConfiguration"]
        assert cfg["TargetValue"] == 60
        assert cfg["PredefinedMetricSpecification"] == {
            "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
        }


def test_corte_de_circuito_con_reversion_y_despliegue_continuo(plantilla):
    for s in _servicios(plantilla).values():
        cfg = s["DeploymentConfiguration"]
        assert cfg["DeploymentCircuitBreaker"] == {"Enable": True, "Rollback": True}
        assert (cfg["MinimumHealthyPercent"], cfg["MaximumPercent"]) == (100, 200)
        assert s["EnableExecuteCommand"] is False


def test_verificacion_de_salud_en_el_contenedor_y_en_el_alb(plantilla):
    for t in _tareas(plantilla).values():
        (c,) = t["ContainerDefinitions"]
        assert "/salud" in c["HealthCheck"]["Command"][1]
        assert c["StopTimeout"] == 120
        assert c["PortMappings"] == [{"ContainerPort": 8000, "Protocol": "tcp"}]
    grupos = propiedades(plantilla, "AWS::ElasticLoadBalancingV2::TargetGroup")
    assert len(grupos) == 6
    for g in grupos:
        assert g["HealthCheckPath"] == "/salud"
        assert g["Matcher"] == {"HttpCode": "200"}
        assert (g["Port"], g["Protocol"], g["TargetType"]) == (8000, "HTTP", "ip")


def test_logs_de_30_dias_y_se_borran_en_test(plantilla):
    grupos = recursos(plantilla, "AWS::Logs::LogGroup")
    assert {g["Properties"]["LogGroupName"] for g in grupos.values()} == {
        f"/cc/test/{s}" for s in SERVICIOS
    }
    for g in grupos.values():
        assert g["Properties"]["RetentionInDays"] == 30
        assert g["DeletionPolicy"] == "Delete"


# ------------------------------------------------------------------------------ imágenes
def test_imagenes_como_activos_de_cdk_arm64_desde_la_raiz(ensamblado):
    stacks, _ = ensamblado
    ensamblaje = stacks["compute"].node.root.synth()
    activos = json.loads(
        Path(ensamblaje.directory, "CcCompute-test.assets.json").read_text("utf-8")
    )
    imagenes = activos["dockerImages"]
    assert len(imagenes) == 6
    dockerfiles = {i["source"]["dockerFile"] for i in imagenes.values()}
    assert dockerfiles == {f"services/{s}/Dockerfile" for s in SERVICIOS}
    for i in imagenes.values():
        assert i["source"]["platform"] == "linux/arm64"
        # El contexto es la raíz del repositorio: solo entra lo que el Dockerfile copia.
        contexto = Path(ensamblaje.directory, i["source"]["directory"])
        presentes = {p.name for p in contexto.iterdir()}
        assert presentes == {"services"}
        for sospechoso in ("tests", "node_modules", ".venv", "migrations", "__pycache__"):
            assert not list(contexto.rglob(sospechoso))


def test_cada_servicio_usa_su_imagen_publicada_por_cdk_no_un_repositorio_manual(plantilla):
    for t in _tareas(plantilla).values():
        (c,) = t["ContainerDefinitions"]
        assert "container-assets" in texto(c["Image"])
        assert "cc-test/migrar" not in texto(c["Image"])


# ------------------------------------------------------------------------------ ALB
def test_alb_interno_http_en_test_sin_certificado_y_con_proteccion_apagada(plantilla):
    (alb,) = propiedades(plantilla, "AWS::ElasticLoadBalancingV2::LoadBalancer")
    assert alb["Scheme"] == "internal" and alb["Type"] == "application"
    atributos = {a["Key"]: a["Value"] for a in alb["LoadBalancerAttributes"]}
    assert atributos["routing.http.drop_invalid_header_fields.enabled"] == "true"
    assert atributos["deletion_protection.enabled"] == "false"
    (listener,) = propiedades(plantilla, "AWS::ElasticLoadBalancingV2::Listener")
    # Sin dominio (PQ-22) no hay certificado: HTTP interno en 80 (docs/desviaciones.md).
    assert (listener["Port"], listener["Protocol"]) == (80, "HTTP")
    assert listener["DefaultActions"][0]["FixedResponseConfig"]["StatusCode"] == "404"


def test_alb_https_con_tls_12_y_13_en_prod(plantilla_prod):
    (alb,) = propiedades(plantilla_prod, "AWS::ElasticLoadBalancingV2::LoadBalancer")
    atributos = {a["Key"]: a["Value"] for a in alb["LoadBalancerAttributes"]}
    assert atributos["deletion_protection.enabled"] == "true"
    assert atributos["access_logs.s3.enabled"] == "true"
    (listener,) = propiedades(plantilla_prod, "AWS::ElasticLoadBalancingV2::Listener")
    assert (listener["Port"], listener["Protocol"]) == (443, "HTTPS")
    assert listener["Certificates"] == [{"CertificateArn": CERTIFICADO}]
    assert listener["SslPolicy"] == "ELBSecurityPolicy-TLS13-1-2-2021-06"
    # Los servicios se llaman por el nombre que cubre el certificado.
    env = entorno_contenedor(_tareas(plantilla_prod)["cc-prod-whatsapp"])
    assert env["CC_COLABORADORES_URL"] == f"https://{DOMINIO_INTERNO}"


def test_prod_exige_https_interno():
    import aws_cdk as cdk

    from infra.stacks.compute import ComputeStack
    from infra.tests.ayudas_computo import ENV_AWS, ambiente_prod, base_sintetica, buckets

    app = cdk.App()
    b = base_sintetica(app)
    with pytest.raises(ValueError, match="HTTPS interno"):
        ComputeStack(
            app,
            "CcCompute-prod",
            ambiente=ambiente_prod(),
            llave_infra=b["llave_infra"],
            llave_datos=b["llave_datos"],
            vpc=b["vpc"],
            sg_ecs=b["sg_ecs"],
            sg_alb=b["sg_alb"],
            host_bd="bd",
            user_pool_id="p",
            user_pool_arn="arn:aws:cognito-idp:us-east-1:034362033822:userpool/p",
            cliente_id="c",
            env=ENV_AWS,
            **buckets("prod"),
        )


def _reglas(plantilla) -> list[tuple[int, list[str], str]]:
    """``(prioridad, patrones, servicio destino)`` de cada regla del listener."""
    destino_por_grupo = {
        lid: g["Properties"]["Name"].removeprefix("cc-test-").removeprefix("cc-prod-")
        for lid, g in recursos(plantilla, "AWS::ElasticLoadBalancingV2::TargetGroup").items()
    }
    salida = []
    for r in propiedades(plantilla, "AWS::ElasticLoadBalancingV2::ListenerRule"):
        (cond,) = (c for c in r["Conditions"] if c["Field"] == "path-pattern")
        (accion,) = r["Actions"]
        grupo = accion["TargetGroupArn"]["Ref"]
        salida.append(
            (int(r["Priority"]), cond["PathPatternConfig"]["Values"], destino_por_grupo[grupo])
        )
    return sorted(salida)


def _enrutar(reglas, ruta: str) -> str | None:
    for _, patrones, destino in reglas:
        if any(coincide_alb(p, ruta) for p in patrones):
            return destino
    return None  # el listener responde 404


def test_las_reglas_del_alb_son_las_del_diseno(plantilla):
    reglas = _reglas(plantilla)
    assert [(p, pat, d) for p, pat, d in reglas] == [
        (r.prioridad, list(r.patrones), r.destino) for r in REGLAS_ALB
    ]
    prioridades = [p for p, _, _ in reglas]
    assert len(set(prioridades)) == len(prioridades)  # prioridades únicas


def test_limites_de_alb_por_regla(plantilla):
    """Un ALB admite hasta 5 valores y 5 comodines por regla (si no, el despliegue falla)."""
    for _, patrones, _ in _reglas(plantilla):
        assert len(patrones) <= 5
        assert sum(p.count("*") + p.count("?") for p in patrones) <= 5


def test_historial_va_a_dashboard_con_mayor_prioridad_que_constancias(plantilla):
    reglas = _reglas(plantilla)
    prioridad = {d: [] for d in SERVICIOS}
    for p, patrones, d in reglas:
        prioridad[d].append((p, patrones))
    p_historial = next(
        p for p, pats, d in reglas if "/api/v1/constancias/historial" in pats and d == "dashboard"
    )
    p_constancias = next(
        p for p, pats, d in reglas if "/api/v1/constancias/*" in pats and d == "constancias"
    )
    assert p_historial < p_constancias  # menor número = se evalúa antes
    assert _enrutar(reglas, "/api/v1/constancias/historial") == "dashboard"
    assert _enrutar(reglas, "/api/v1/constancias/historial/exportar") == "dashboard"
    assert _enrutar(reglas, "/api/v1/constancias/123") == "constancias"
    assert _enrutar(reglas, "/api/v1/constancias/variables") == "constancias"


@pytest.mark.parametrize(
    ("ruta", "destino"),
    [
        ("/api/v1/plantillas", "constancias"),
        ("/api/v1/plantillas/7/versiones", "constancias"),
        ("/api/v1/plantillas-mensaje", "notificaciones"),  # no choca con /plantillas/*
        ("/api/v1/plantillas-mensaje/4", "notificaciones"),
        ("/api/v1/conversaciones/9/mensajes", "whatsapp"),
        ("/api/v1/integraciones/meta", "notificaciones"),
        ("/api/v1/integraciones/meta/verify-token:generar", "notificaciones"),
        ("/api/v1/integraciones/meta/probar", "notificaciones"),
        ("/api/v1/audiencias/previsualizar", "notificaciones"),
        ("/api/v1/notificaciones/indicadores", "notificaciones"),
        ("/api/v1/colaboradores/12", "colaboradores"),
        ("/api/v1/cargas/3", "colaboradores"),
        ("/api/v1/organizaciones", "colaboradores"),
        ("/api/v1/plantas/2", "colaboradores"),
        ("/api/v1/campos/5/opciones", "campos"),
        ("/api/v1/dashboard/indicadores", "dashboard"),
        ("/api/v1/usuarios/me", "dashboard"),
        ("/api/v1/sesion/actividad", "dashboard"),
        ("/api/v1/bitacora", "dashboard"),
        ("/api/v1/publico/verificar/ABC", "constancias"),
        ("/d/token123", "constancias"),
        ("/d/token123/descargar", "constancias"),
        # Rutas internas (token de servicio).
        ("/internal/campos", "campos"),
        ("/internal/campos/8/uso", "colaboradores"),  # INT-COL-10, antes que /internal/campos*
        ("/internal/empresas/1/campos-sugeridos", "campos"),
        ("/internal/colaboradores/contactos:resolver", "colaboradores"),
        ("/internal/organizaciones/2", "colaboradores"),
        ("/internal/plantillas-mensaje/3", "notificaciones"),
        ("/internal/plantillas/activas", "constancias"),
        ("/internal/plantillas/uso-de-variable", "constancias"),
        ("/internal/solicitudes/5/generar", "constancias"),
    ],
)
def test_enrutamiento_por_ruta(plantilla, ruta, destino):
    assert _enrutar(_reglas(plantilla), ruta) == destino


@pytest.mark.parametrize(
    "ruta", ["/webhook/meta", "/internal/desconocido", "/api/v1/otra-cosa", "/descargas/x", "/"]
)
def test_lo_que_no_es_de_un_servicio_recibe_404_del_listener(plantilla, ruta):
    assert _enrutar(_reglas(plantilla), ruta) is None


def test_internal_nunca_se_mezcla_con_las_rutas_publicas(plantilla):
    """Las rutas públicas (API Gateway) y las internas están en reglas distintas: ninguna regla
    con ``/api`` o ``/d/`` lleva ``/internal`` y las internas empiezan en la prioridad 110."""
    for prioridad, patrones, _ in _reglas(plantilla):
        internas = [p.startswith("/internal/") for p in patrones]
        assert all(internas) or not any(internas)
        assert (prioridad >= 100) == all(internas)


# ------------------------------------------------------------------------------ red
def test_no_crea_ni_modifica_grupos_de_seguridad(plantilla):
    """Los grupos de seguridad viven en CcNetwork y se importan sin modificar (sin ciclos)."""
    plantilla.resource_count_is("AWS::EC2::SecurityGroup", 0)
    plantilla.resource_count_is("AWS::EC2::SecurityGroupIngress", 0)
    plantilla.resource_count_is("AWS::EC2::SecurityGroupEgress", 0)
    (alb,) = propiedades(plantilla, "AWS::ElasticLoadBalancingV2::LoadBalancer")
    assert "sg" in texto(alb["SecurityGroups"]).lower()
    for s in _servicios(plantilla).values():
        sgs = s["NetworkConfiguration"]["AwsvpcConfiguration"]["SecurityGroups"]
        assert "SgEcs" in texto(sgs)


# ------------------------------------------------------------------------------ IAM
def _rol_tarea(plantilla, servicio: str) -> str:
    return rol_logico_por_nombre(plantilla, f"cc-test-{servicio}")


def _sentencias(plantilla, servicio: str) -> list[dict]:
    return sentencias_de_rol(plantilla, _rol_tarea(plantilla, servicio))


def test_un_rol_de_tarea_por_servicio_con_nombre_cc_env_servicio(plantilla):
    tareas = _tareas(plantilla)
    for s in SERVICIOS:
        lid = _rol_tarea(plantilla, s)
        t = tareas[f"cc-test-{s}"]
        assert t["TaskRoleArn"] == {"Fn::GetAtt": [lid, "Arn"]}
    roles = {r["RoleName"] for r in propiedades(plantilla, "AWS::IAM::Role") if "RoleName" in r}
    assert roles == {f"cc-test-{s}" for s in SERVICIOS}


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_roles_de_tarea_sin_comodin_de_recurso_ni_acciones_abiertas(plantilla, servicio):
    for st in _sentencias(plantilla, servicio):
        assert "*" not in recursos_de(st), st  # sin Resource "*"
        for a in acciones(st):
            assert a not in ("*",) and not a.endswith(":*"), a  # sin s3:*, kms:*, iam:*...
    texto_rol = texto(_sentencias(plantilla, servicio))
    assert "ssmmessages" not in texto_rol  # ECS Exec desactivado en los servicios


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_secretos_con_kms_decrypt_sobre_la_llave_en_la_misma_politica(plantilla, servicio):
    """Lección de T-047: leer un secreto cifrado exige ``kms:Decrypt`` sobre la llave."""
    sentencias = _sentencias(plantilla, servicio)
    lecturas = [s for s in sentencias if "secretsmanager:GetSecretValue" in acciones(s)]
    assert lecturas
    descifrados = [s for s in sentencias if "kms:Decrypt" in acciones(s) and "Condition" not in s]
    assert descifrados
    assert "LlaveInfra" in texto(descifrados[0]["Resource"])
    secretos = texto(lecturas)
    assert f"secret:cc/test/db/svc_{servicio}-" in secretos
    assert "secret:cc/test/internal-auth-" in secretos


EXPECTATIVAS = {
    # servicio: (acciones que SÍ tiene, acciones que NO debe tener)
    "dashboard": (
        {"cognito-idp:AdminDisableUser", "cognito-idp:AdminUserGlobalSignOut"},
        {
            "s3:GetObject",
            "sqs:SendMessage",
            "events:PutEvents",
            "kms:GenerateDataKey",
            "secretsmanager:PutSecretValue",
        },
    ),
    "colaboradores": (
        {"s3:GetObject", "s3:PutObject", "s3:DeleteObject", "sqs:SendMessage", "events:PutEvents"},
        {
            "scheduler:CreateSchedule",
            "sns:Publish",
            "cognito-idp:AdminDisableUser",
            "secretsmanager:PutSecretValue",
        },
    ),
    "campos": (
        {"events:PutEvents"},
        {
            "s3:GetObject",
            "sqs:SendMessage",
            "kms:GenerateDataKey",
            "sns:Publish",
            "secretsmanager:PutSecretValue",
        },
    ),
    "constancias": (
        {"s3:GetObject", "s3:PutObject", "s3:PutObjectRetention", "sqs:SendMessage"},
        {
            "s3:DeleteObject",
            "scheduler:CreateSchedule",
            "sns:Publish",
            "secretsmanager:PutSecretValue",
        },
    ),
    "notificaciones": (
        {
            "scheduler:CreateSchedule",
            "scheduler:DeleteSchedule",
            "iam:PassRole",
            "sqs:SendMessage",
            "secretsmanager:PutSecretValue",
            "secretsmanager:DescribeSecret",
        },
        {"s3:GetObject", "sns:Publish"},
    ),
    "whatsapp": (
        {"sns:Publish", "sqs:SendMessage", "events:PutEvents", "kms:Decrypt"},
        {
            "s3:GetObject",
            "scheduler:CreateSchedule",
            "iam:PassRole",
            "secretsmanager:PutSecretValue",
        },
    ),
}


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_cada_rol_solo_tiene_lo_que_su_servicio_usa(plantilla, servicio):
    tiene = {a for s in _sentencias(plantilla, servicio) for a in acciones(s)}
    debe, no_debe = EXPECTATIVAS[servicio]
    assert debe <= tiene, debe - tiene
    assert not (no_debe & tiene), no_debe & tiene


def test_constancias_no_borra_pdf_ni_versiones_de_plantilla(plantilla):
    s3 = [
        s
        for s in _sentencias(plantilla, "constancias")
        if any(a.startswith("s3:") for a in acciones(s))
    ]
    assert all("s3:DeleteObject" not in acciones(x) for x in s3)
    retencion = [x for x in s3 if "s3:PutObjectRetention" in acciones(x)]
    assert retencion[0]["Condition"] == {
        "StringEqualsIfExists": {"s3:object-lock-mode": "GOVERNANCE"}
    }
    assert "034362033822-constancias/" in texto(retencion[0]["Resource"])


def test_llave_de_datos_solo_con_el_contexto_de_cada_servicio(plantilla):
    for servicio in ("colaboradores", "constancias", "whatsapp"):
        (st,) = (
            s
            for s in _sentencias(plantilla, servicio)
            if "kms:GenerateDataKey" in acciones(s) and "Condition" in s
        )
        assert st["Condition"] == {"StringEquals": {"kms:EncryptionContext:servicio": servicio}}
        assert "LlaveDatos" in texto(st["Resource"])
    for servicio in ("dashboard", "campos", "notificaciones"):
        assert "LlaveDatos" not in texto(_sentencias(plantilla, servicio))


def test_notificaciones_solo_pasa_el_rol_de_scheduler_y_solo_a_scheduler(plantilla):
    (st,) = (s for s in _sentencias(plantilla, "notificaciones") if "iam:PassRole" in acciones(s))
    assert "role/cc-test-scheduler-destino" in texto(st["Resource"])
    assert st["Condition"] == {"StringEquals": {"iam:PassedToService": "scheduler.amazonaws.com"}}
    (sch,) = (
        s
        for s in _sentencias(plantilla, "notificaciones")
        if "scheduler:CreateSchedule" in acciones(s)
    )
    assert "schedule/cc-test-envios/*" in texto(sch["Resource"])


def test_notificaciones_escribe_solo_el_secreto_de_meta_con_kms(plantilla):
    """Integraciones/Meta: ``PutSecretValue`` y ``DescribeSecret`` sobre ESE secreto (ARN con el
    sufijo de Secrets Manager, sin ``*`` solo) y las acciones de KMS para cifrarlo."""
    sentencias = _sentencias(plantilla, "notificaciones")
    (escritura,) = (s for s in sentencias if "secretsmanager:PutSecretValue" in acciones(s))
    assert sorted(acciones(escritura)) == [
        "secretsmanager:DescribeSecret",
        "secretsmanager:PutSecretValue",
    ]
    recursos_escritura = texto(escritura["Resource"])
    assert recursos_escritura.endswith(':secret:cc/test/meta-??????"]]}')
    assert not isinstance(escritura["Resource"], list)  # un solo ARN, sin comodín suelto
    assert "Condition" not in escritura
    (kms,) = (s for s in sentencias if "kms:Encrypt" in acciones(s))
    assert sorted(acciones(kms)) == ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    assert kms["Condition"] == {
        "StringEquals": {"kms:ViaService": "secretsmanager.us-east-1.amazonaws.com"}
    }
    assert "LlaveDatos" not in texto(kms["Resource"])
    # La lectura (con kms:Decrypt) sigue donde estaba: ``GetSecretValue`` de sus secretos.
    leidos = texto(
        [s["Resource"] for s in sentencias if "secretsmanager:GetSecretValue" in acciones(s)]
    )
    assert "cc/test/meta-??????" in leidos


def test_consumidores_de_eventos_leen_solo_su_cola_ev(plantilla):
    for servicio, cola in (
        ("colaboradores", "ev-colaboradores"),
        ("constancias", "ev-constancias"),
        ("notificaciones", "ev-notificaciones"),
    ):
        lecturas = [
            s for s in _sentencias(plantilla, servicio) if "sqs:ReceiveMessage" in acciones(s)
        ]
        (lectura,) = lecturas
        assert texto(lectura["Resource"]).count(f"cc-test-{cola}") == 1
    for servicio in ("dashboard", "campos", "whatsapp"):
        assert "sqs:ReceiveMessage" not in texto(_sentencias(plantilla, servicio))


# ------------------------------------------------------------------------------ variables
@pytest.mark.parametrize("servicio", SERVICIOS)
def test_variables_comunes_y_sin_valores_secretos(plantilla, servicio):
    t = _tareas(plantilla)[f"cc-test-{servicio}"]
    (c,) = t["ContainerDefinitions"]
    env = entorno_contenedor(t)
    assert env["CC_AMBIENTE"] == "test" and env["CC_REGION"] == "us-east-1"
    assert env["CC_DB_SECRETO_ID"] == f"cc/test/db/svc_{servicio}"
    assert env["CC_INTERNAL_AUTH_SECRETO_ID"] == "cc/test/internal-auth"
    assert env["CC_DB_NOMBRE"] == "command_center" and env["CC_DB_SSL"] == "true"
    assert env["CC_EVENTOS_ACTIVOS"] == "true"
    assert "CC_COGNITO_EMISOR" in env and "CC_COGNITO_CLIENT_ID" in env
    assert "Secrets" not in c  # los secretos se leen por identificador, nunca por valor
    for nombre in env:
        assert not any(x in nombre for x in ("PASSWORD", "CONTRASENA", "TOKEN", "SECRET_KEY"))


def test_variables_propias_de_cada_servicio(plantilla):
    envs = {s: entorno_contenedor(_tareas(plantilla)[f"cc-test-{s}"]) for s in SERVICIOS}
    assert "CC_COGNITO_USER_POOL_ID" in envs["dashboard"]
    col = envs["colaboradores"]
    assert col["CC_BUCKET_CARGAS"] == "cc-test-034362033822-cargas"
    assert col["CC_BUCKET_PLANTILLAS"] == "cc-test-034362033822-plantillas"
    assert col["CC_COLA_CARGAS_URL"].endswith("/034362033822/cc-test-cola-cargas")
    assert col["CC_COLA_EVENTOS_URL"].endswith("/cc-test-ev-colaboradores")
    assert col["CC_HMAC_CELULAR_SECRETO_ID"] == "cc/test/hmac-celular"
    assert col["CC_KMS_LLAVE_DATOS"] == "alias/cc-test-datos"
    con = envs["constancias"]
    assert con["CC_BUCKET_CONSTANCIAS"] == "cc-test-034362033822-constancias"
    assert con["CC_COLA_PDF_URL"].endswith("/cc-test-cola-pdf")
    assert con["CC_COLA_WA_SALIDA_URL"].endswith("/cc-test-wa-salida.fifo")
    assert con["CC_COLA_EVENTOS_URL"].endswith("/cc-test-ev-constancias")
    assert con["CC_CLOUDFRONT_CLAVE_SECRETO_ID"] == "cc/test/cf-signing-key"
    wa = envs["whatsapp"]
    assert wa["CC_META_SECRETO_ID"] == "cc/test/meta"
    assert wa["CC_CODIGO_HMAC_SECRETO_ID"] == "cc/test/hmac-codigo"
    assert "cc-test-alertas-rh" in texto(wa["CC_ALERTAS_TOPIC_ARN"])
    assert "CC_NOTIFICACIONES_URL" in wa and "CC_EMPRESA_ID" not in wa
    no = envs["notificaciones"]
    assert no["CC_SCHEDULER_GRUPO"] == "cc-test-envios"
    assert "scheduler-destino" in texto(no["CC_SCHEDULER_ROL_ARN"])
    assert "cc-test-notif-despacho" in texto(no["CC_SCHEDULER_DESTINO_ARN"])
    assert no["CC_CONSUMIDOR_ACTIVO"] == "true"
    assert envs["campos"]["CC_BUS_EVENTOS"] == "cc-test-eventos"
    # Las llamadas entre servicios van por el ALB interno.
    for s in ("campos", "constancias", "whatsapp", "notificaciones", "colaboradores"):
        for k, v in envs[s].items():
            if k.endswith("_URL") and k.startswith(
                ("CC_CAMPOS", "CC_COLABORADORES", "CC_CONSTANCIAS", "CC_NOTIFICACIONES")
            ):
                assert "DNSName" in texto(v) and "http://" in texto(v)


def test_empresa_del_numero_de_whatsapp_se_pasa_por_contexto():
    app, amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    app.node.set_context("empresa_id_whatsapp", "7")
    stacks = construir_stacks(app, amb, destino)
    plantilla = Template.from_stack(stacks["compute"])
    env = entorno_contenedor(_tareas(plantilla)["cc-test-whatsapp"])
    assert env["CC_EMPRESA_ID"] == "7"


# ------------------------------------------------------------------------------ cdk-nag y orden
def test_orden_de_despliegue_declarado(ensamblado):
    stacks, _ = ensamblado
    dependencias = {d.stack_name for d in stacks["compute"].dependencies}
    assert {
        "CcSecurity-test",
        "CcNetwork-test",
        "CcStorage-test",
        "CcData-test",
        "CcMessaging-test",
        "CcAuth-test",
        "CcComputeBase-test",
    } <= dependencias
    trabajadores = {d.stack_name for d in stacks["workers"].dependencies}
    assert "CcCompute-test" in trabajadores


def test_sin_credenciales_en_la_plantilla(plantilla):
    t = texto(plantilla.to_json())
    assert "AKIA" not in t and "BEGIN PRIVATE KEY" not in t


def test_rutas_publicas_exigen_el_encabezado_secreto_de_origen_y_las_internas_no(plantilla):
    """T-225: el ALB exige ``X-Origin-Verify`` solo en las reglas que llegan por API Gateway.
    El valor es una referencia dinámica a Secrets Manager: nunca está en la plantilla."""
    reglas = propiedades(plantilla, "AWS::ElasticLoadBalancingV2::ListenerRule")
    assert reglas
    for r in reglas:
        cabeceras = [c for c in r["Conditions"] if c["Field"] == "http-header"]
        if int(r["Priority"]) < 100:
            (c,) = cabeceras
            assert c["HttpHeaderConfig"]["HttpHeaderName"] == "X-Origin-Verify"
            (valor,) = c["HttpHeaderConfig"]["Values"]
            assert valor.startswith("{{resolve:secretsmanager:cc/test/origin-verify:")
        else:
            assert cabeceras == []
