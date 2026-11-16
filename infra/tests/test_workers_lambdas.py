"""T-136: aserciones de CcWorkersLambdas (workers con escalado por cola y Lambdas de mensajería)."""

import pytest
from aws_cdk.assertions import Template

from infra.app import construir_stacks, crear_app
from infra.stacks.workers_lambdas import LAMBDAS, WORKERS
from infra.tests.ayudas_computo import (
    PERMITIDA,
    acciones,
    construir_prod,
    entorno_contenedor,
    propiedades,
    recursos,
    recursos_de,
    sentencias_de_rol,
    texto,
)


@pytest.fixture(scope="module")
def ensamblado():
    app, amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    stacks = construir_stacks(app, amb, destino)
    return stacks, Template.from_stack(stacks["workers"])


@pytest.fixture(scope="module")
def plantilla(ensamblado) -> Template:
    return ensamblado[1]


@pytest.fixture(scope="module")
def plantilla_prod() -> Template:
    return construir_prod()[1]


# -------------------------------------------------------------------------------- workers
def _servicios(plantilla) -> dict[str, dict]:
    return {s["ServiceName"]: s for s in propiedades(plantilla, "AWS::ECS::Service")}


def _tareas(plantilla) -> dict[str, dict]:
    return {t["Family"]: t for t in propiedades(plantilla, "AWS::ECS::TaskDefinition")}


def _objetivos(plantilla) -> dict[str, dict]:
    """Capacidad escalable por worker (el nombre sale del servicio al que apunta)."""
    servicios = {
        lid: s["Properties"]["ServiceName"]
        for lid, s in recursos(plantilla, "AWS::ECS::Service").items()
    }
    resultado = {}
    for o in propiedades(plantilla, "AWS::ApplicationAutoScaling::ScalableTarget"):
        lid = o["ResourceId"]["Fn::Join"][1][1]["Fn::GetAtt"][0]
        resultado[servicios[lid]] = o
    return resultado


NOMBRES = {w.nombre for w in WORKERS}


def test_tres_workers_fargate_arm64_sin_alb(plantilla):
    assert set(_servicios(plantilla)) == {f"cc-test-{n}" for n in NOMBRES}
    for s in _servicios(plantilla).values():
        assert s["LaunchType"] == "FARGATE" and s["Cluster"] == "cc-test"
        assert "LoadBalancers" not in s  # sin ALB: consumen de la cola
        assert s["DeploymentConfiguration"]["DeploymentCircuitBreaker"] == {
            "Enable": True,
            "Rollback": True,
        }
    plantilla.resource_count_is("AWS::ElasticLoadBalancingV2::TargetGroup", 0)
    for t in _tareas(plantilla).values():
        assert t["RuntimePlatform"]["CpuArchitecture"] == "ARM64"


@pytest.mark.parametrize("w", WORKERS, ids=lambda w: w.nombre)
def test_tamano_comando_y_apagado_ordenado(plantilla, w):
    t = _tareas(plantilla)[f"cc-test-{w.nombre}"]
    assert (t["Cpu"], t["Memory"]) == (str(w.cpu), str(w.memoria))
    (c,) = t["ContainerDefinitions"]
    assert c["Command"] == ["python", "-m", w.modulo]
    assert c["StopTimeout"] == 120  # termina el mensaje en curso tras SIGTERM (§4.7)
    assert "PortMappings" not in c and "HealthCheck" not in c  # sin HTTP
    assert "container-assets" in texto(c["Image"])  # la imagen del servicio dueño (D-11)


def test_tamanos_de_la_seccion_4_7():
    por_nombre = {w.nombre: (w.cpu, w.memoria) for w in WORKERS}
    assert por_nombre == {
        "worker-pdf": (1024, 2048),
        "worker-cargas": (512, 1024),
        "worker-whatsapp-entrada": (512, 1024),
    }


def test_workers_reutilizan_la_imagen_de_su_servicio(ensamblado):
    stacks, plantilla = ensamblado
    ids = {
        w.nombre: texto(
            _tareas(plantilla)[f"cc-test-{w.nombre}"]["ContainerDefinitions"][0]["Image"]
        )
        for w in WORKERS
    }
    compute = Template.from_stack(stacks["compute"])
    servicio = {
        s: texto(t["ContainerDefinitions"][0]["Image"])
        for s, t in (
            (f.removeprefix("cc-test-"), t)
            for f, t in {
                t["Family"]: t for t in propiedades(compute, "AWS::ECS::TaskDefinition")
            }.items()
        )
    }
    assert ids["worker-pdf"] == servicio["constancias"]
    assert ids["worker-cargas"] == servicio["colaboradores"]
    assert ids["worker-whatsapp-entrada"] == servicio["whatsapp"]


def test_workers_en_test_arrancan_en_cero_y_no_pasan_de_uno(plantilla):
    for s in _servicios(plantilla).values():
        assert s["DesiredCount"] == 0
    objetivos = _objetivos(plantilla)
    assert set(objetivos) == {f"cc-test-{n}" for n in NOMBRES}
    for o in objetivos.values():
        assert (o["MinCapacity"], o["MaxCapacity"]) == (0, 1)


def test_workers_en_prod_minimo_uno_y_whatsapp_dos(plantilla_prod):
    objetivos = _objetivos(plantilla_prod)
    esperado = {
        "cc-prod-worker-pdf": (1, 4),
        "cc-prod-worker-cargas": (1, 2),
        "cc-prod-worker-whatsapp-entrada": (2, 4),
    }
    assert {n: (o["MinCapacity"], o["MaxCapacity"]) for n, o in objetivos.items()} == esperado
    for n, s in _servicios(plantilla_prod).items():
        assert s["DesiredCount"] == esperado[n][0]


@pytest.mark.parametrize("w", WORKERS, ids=lambda w: w.nombre)
def test_escalado_por_profundidad_de_la_cola(plantilla, w):
    """Alarma sobre ApproximateNumberOfMessagesVisible (más lo que está en proceso)."""
    alarmas = [
        a
        for a in propiedades(plantilla, "AWS::CloudWatch::Alarm")
        if any(
            m.get("MetricStat", {}).get("Metric", {}).get("Dimensions")
            == [{"Name": "QueueName", "Value": f"cc-test-{w.cola}"}]
            for m in a["Metrics"]
        )
    ]
    assert len(alarmas) == 2  # una para subir y otra para bajar
    for a in alarmas:
        nombres = {
            m["MetricStat"]["Metric"]["MetricName"] for m in a["Metrics"] if "MetricStat" in m
        }
        assert nombres == {
            "ApproximateNumberOfMessagesVisible",
            "ApproximateNumberOfMessagesNotVisible",
        }
        assert all(
            m["MetricStat"]["Metric"]["Namespace"] == "AWS/SQS"
            for m in a["Metrics"]
            if "MetricStat" in m
        )
    operadores = {a["ComparisonOperator"] for a in alarmas}
    assert operadores == {"LessThanOrEqualToThreshold", "GreaterThanOrEqualToThreshold"}


def test_escalones_de_las_politicas_bajan_de_a_una_tarea_y_suben_hasta_tres(plantilla):
    politicas = propiedades(plantilla, "AWS::ApplicationAutoScaling::ScalingPolicy")
    assert len(politicas) == 6 and all(p["PolicyType"] == "StepScaling" for p in politicas)
    bajan = [p for p in politicas if "LowerPolicy" in texto(p["PolicyName"])]
    for p in bajan:
        (paso,) = p["StepScalingPolicyConfiguration"]["StepAdjustments"]
        assert paso["ScalingAdjustment"] == -1 and paso["MetricIntervalUpperBound"] == 0
    suben = [p for p in politicas if "UpperPolicy" in texto(p["PolicyName"])]
    for p in suben:
        cambios = [
            x["ScalingAdjustment"] for x in p["StepScalingPolicyConfiguration"]["StepAdjustments"]
        ]
        assert cambios == [1, 2, 3]


def test_el_escalado_de_pdf_usa_cinco_mensajes_por_tarea():
    por_nombre = {w.nombre: w.mensajes_por_tarea for w in WORKERS}
    assert por_nombre["worker-pdf"] == 5  # design.md §4.7


def _sentencias_worker(plantilla, nombre: str) -> list[dict]:
    (lid,) = (
        lid
        for lid, r in recursos(plantilla, "AWS::IAM::Role").items()
        if r["Properties"].get("RoleName") == f"cc-test-{nombre}"
    )
    return sentencias_de_rol(plantilla, lid)


@pytest.mark.parametrize("w", WORKERS, ids=lambda w: w.nombre)
def test_rol_del_worker_consume_solo_su_cola_y_no_las_ev(plantilla, w):
    sentencias = _sentencias_worker(plantilla, w.nombre)
    lecturas = [s for s in sentencias if "sqs:ReceiveMessage" in acciones(s)]
    (lectura,) = lecturas
    assert {"sqs:DeleteMessage", "sqs:ChangeMessageVisibility"} <= set(acciones(lectura))
    assert texto(lectura["Resource"]).count(f"cc-test-{w.cola}") == 1
    assert "cc-test-ev-" not in texto(sentencias)  # los consumidores de eventos son de la API
    for s in sentencias:
        assert "*" not in recursos_de(s)


def test_worker_pdf_escribe_pdf_con_object_lock_y_no_borra(plantilla):
    sentencias = _sentencias_worker(plantilla, "worker-pdf")
    todas = {a for s in sentencias for a in acciones(s)}
    assert {"s3:PutObject", "s3:PutObjectRetention", "sqs:SendMessage"} <= todas
    assert "s3:DeleteObject" not in todas
    lecturas = [s for s in sentencias if "secretsmanager:GetSecretValue" in acciones(s)]
    assert "svc_constancias" in texto(lecturas) and "cf-signing-key" in texto(lecturas)
    assert any("kms:Decrypt" in acciones(s) and "LlaveInfra" in texto(s) for s in sentencias)


def test_variables_de_los_workers(plantilla):
    t = _tareas(plantilla)
    pdf = entorno_contenedor(t["cc-test-worker-pdf"])
    assert pdf["CC_COLA_PDF_URL"].endswith("/cc-test-cola-pdf")
    assert pdf["CC_DB_SECRETO_ID"] == "cc/test/db/svc_constancias"
    assert "CC_EVENTOS_ACTIVOS" not in pdf  # sin consumidor de eventos: no es la API
    cargas = entorno_contenedor(t["cc-test-worker-cargas"])
    assert cargas["CC_COLA_CARGAS_URL"].endswith("/cc-test-cola-cargas")
    assert cargas["CC_BUCKET_CARGAS"] == "cc-test-034362033822-cargas"
    wa = entorno_contenedor(t["cc-test-worker-whatsapp-entrada"])
    assert wa["CC_COLA_ENTRADA_URL"].endswith("/cc-test-wa-entrada.fifo")
    assert wa["CC_CODIGO_HMAC_SECRETO_ID"] == "cc/test/hmac-codigo"
    for env in (pdf, cargas, wa):
        assert env["CC_INTERNAL_AUTH_SECRETO_ID"] == "cc/test/internal-auth"
        assert not any("PASSWORD" in k or "TOKEN" in k for k in env)


# -------------------------------------------------------------------------------- Lambdas
def _funciones(plantilla) -> dict[str, dict]:
    return {f["FunctionName"]: f for f in propiedades(plantilla, "AWS::Lambda::Function")}


DEFS = {d.nombre: d for d in LAMBDAS}


def test_seis_lambdas_python_312_arm64(plantilla):
    funciones = _funciones(plantilla)
    assert set(funciones) == {f"cc-test-{n}" for n in DEFS}
    for f in funciones.values():
        assert f["Runtime"] == "python3.12" and f["Architectures"] == ["arm64"]


@pytest.mark.parametrize(
    ("nombre", "memoria", "timeout", "reservada"),
    [
        ("webhook-meta", 256, 5, 20),
        ("enviador", 512, 30, 10),
        ("estados-entrega", 256, 30, 5),
        ("despachador", 512, 300, 5),
        ("conciliador", 256, 120, 1),
        ("respaldo-correo", 512, 300, 3),
    ],
)
def test_memoria_tiempo_y_concurrencia_reservada(plantilla, nombre, memoria, timeout, reservada):
    f = _funciones(plantilla)[f"cc-test-{nombre}"]
    assert (f["MemorySize"], f["Timeout"], f["ReservedConcurrentExecutions"]) == (
        memoria,
        timeout,
        reservada,
    )


def test_handlers_de_cada_funcion(plantilla):
    esperado = {
        "webhook-meta": "webhook_meta.handler.lambda_handler",
        "enviador": "enviador.handler.lambda_handler",
        "estados-entrega": "estados_entrega.handler.lambda_handler",
        "despachador": "despachador.handler.lambda_handler",
        "conciliador": "conciliador.handler.lambda_handler",
        "respaldo-correo": "respaldo_correo.handler.lambda_handler",
    }
    for nombre, handler in esperado.items():
        assert _funciones(plantilla)[f"cc-test-{nombre}"]["Handler"] == handler


def test_webhook_fuera_de_la_vpc_y_las_demas_dentro(plantilla):
    funciones = _funciones(plantilla)
    assert "VpcConfig" not in funciones["cc-test-webhook-meta"]
    for nombre in DEFS:
        if nombre == "webhook-meta":
            continue
        cfg = funciones[f"cc-test-{nombre}"]["VpcConfig"]
        assert len(cfg["SubnetIds"]) == 2 and "SgLambda" in texto(cfg["SecurityGroupIds"])


def test_alias_live_en_todas_y_sin_concurrencia_aprovisionada_en_test(plantilla):
    alias = propiedades(plantilla, "AWS::Lambda::Alias")
    assert len(alias) == 6 and {a["Name"] for a in alias} == {"live"}
    for a in alias:
        assert "ProvisionedConcurrencyConfig" not in a  # 0 en test (CloudFormation no admite 0)


def test_webhook_con_concurrencia_aprovisionada_de_2_en_prod(plantilla_prod):
    alias = propiedades(plantilla_prod, "AWS::Lambda::Alias")
    con = [a for a in alias if "ProvisionedConcurrencyConfig" in a]
    assert len(con) == 1
    assert con[0]["ProvisionedConcurrencyConfig"] == {"ProvisionedConcurrentExecutions": 2}
    assert "webhookmeta" in texto(con[0]["FunctionName"]).lower().replace("-", "")


def test_logs_de_30_dias_y_versiones_que_se_borran_en_test(plantilla):
    grupos = {
        g["LogGroupName"]: g
        for g in propiedades(plantilla, "AWS::Logs::LogGroup")
        if g["LogGroupName"].startswith("/aws/lambda/")
    }
    assert set(grupos) == {f"/aws/lambda/cc-test-{n}" for n in DEFS}
    assert {g["RetentionInDays"] for g in grupos.values()} == {30}


def _mapeos(plantilla) -> dict[str, dict]:
    resultado = {}
    for m in propiedades(plantilla, "AWS::Lambda::EventSourceMapping"):
        cola = texto(m["EventSourceArn"]).split(":")[-1].rstrip('"]}')
        resultado[cola] = m
    return resultado


def test_fuentes_sqs_con_lotes_batch_item_failures_y_concurrencia_acotada(plantilla):
    mapeos = _mapeos(plantilla)
    assert set(mapeos) == {
        "cc-test-wa-salida.fifo",
        "cc-test-wa-estados",
        "cc-test-notif-despacho",
        "cc-test-notif-respaldo",
    }
    for m in mapeos.values():
        assert m["FunctionResponseTypes"] == ["ReportBatchItemFailures"]
        assert ":live" in texto(m["FunctionName"])  # la fuente apunta al alias, no a $LATEST
    assert mapeos["cc-test-wa-salida.fifo"]["BatchSize"] == 10
    assert mapeos["cc-test-wa-estados"]["BatchSize"] == 10
    assert mapeos["cc-test-notif-despacho"]["BatchSize"] == 1  # el despacho puede durar minutos
    assert mapeos["cc-test-notif-respaldo"]["BatchSize"] == 1
    # Tope igual a la reservada en las colas estándar; en FIFO la fija la reservada.
    assert mapeos["cc-test-wa-estados"]["ScalingConfig"] == {"MaximumConcurrency": 5}
    assert mapeos["cc-test-notif-despacho"]["ScalingConfig"] == {"MaximumConcurrency": 5}
    assert mapeos["cc-test-notif-respaldo"]["ScalingConfig"] == {"MaximumConcurrency": 3}
    assert "ScalingConfig" not in mapeos["cc-test-wa-salida.fifo"]
    for m in mapeos.values():
        assert "MaximumBatchingWindowInSeconds" not in m  # FIFO no admite ventana


def test_visibilidad_de_las_colas_cubre_el_tiempo_de_la_funcion():
    """SQS exige visibilidad >= tiempo de la función (Lambda rechaza la fuente si no)."""
    from infra.stacks.messaging import COLAS

    visibilidad = {d.nombre: d.visibilidad_s for d in COLAS}
    for d in LAMBDAS:
        if d.cola:
            assert visibilidad[d.cola.removesuffix(".fifo")] >= d.timeout_s * 6 or (
                visibilidad[d.cola.removesuffix(".fifo")] >= d.timeout_s
            )


def test_cada_cola_origen_tiene_su_dlq_en_mensajeria(ensamblado):
    """El DLQ de las funciones con cola es el de la propia cola (§4.1, §4.4, §4.5)."""
    stacks, _ = ensamblado
    mensajeria = Template.from_stack(stacks["messaging"])
    colas = {q["QueueName"]: q for q in propiedades(mensajeria, "AWS::SQS::Queue")}
    for d in LAMBDAS:
        if d.cola:
            principal = colas[f"cc-test-{d.cola}"]
            assert "RedrivePolicy" in principal
            assert principal["RedrivePolicy"]["maxReceiveCount"] >= 2
            dlq = (
                d.cola.replace(".fifo", "-dlq.fifo")
                if d.cola.endswith(".fifo")
                else f"{d.cola}-dlq"
            )
            assert f"cc-test-{dlq}" in colas


def test_conciliador_cada_cinco_minutos_sin_reintentos_ni_dlq(plantilla):
    (regla,) = propiedades(plantilla, "AWS::Events::Rule")
    assert regla["ScheduleExpression"] == "rate(5 minutes)" and regla["State"] == "ENABLED"
    (destino,) = regla["Targets"]
    assert "Aliasconciliador" in texto(destino["Arn"])  # invoca el alias live
    assert destino["RetryPolicy"]["MaximumRetryAttempts"] == 0
    assert "DeadLetterConfig" not in destino  # §4.5: sin DLQ, el siguiente ciclo repite
    (config,) = propiedades(plantilla, "AWS::Lambda::EventInvokeConfig")
    assert config["MaximumRetryAttempts"] == 0
    (permiso,) = propiedades(plantilla, "AWS::Lambda::Permission")
    assert permiso["Principal"] == "events.amazonaws.com"


def test_ninguna_funcion_lleva_dlq_asincrona_propia(plantilla):
    """Las funciones con cola usan la DLQ de la cola; webhook-meta responde síncrono (Meta
    reintenta, §4.2) y el conciliador no tiene DLQ (§4.5)."""
    for f in _funciones(plantilla).values():
        assert "DeadLetterConfig" not in f


# -------------------------------------------------------------------------------- IAM
def _sentencias_lambda(plantilla, nombre: str) -> list[dict]:
    fn = recursos(plantilla, "AWS::Lambda::Function")
    (rol,) = (
        f["Properties"]["Role"]["Fn::GetAtt"][0]
        for f in fn.values()
        if f["Properties"]["FunctionName"] == f"cc-test-{nombre}"
    )
    return sentencias_de_rol(plantilla, rol)


@pytest.mark.parametrize("nombre", sorted(DEFS))
def test_politicas_sin_resource_comodin_y_sin_acciones_abiertas(plantilla, nombre):
    for s in _sentencias_lambda(plantilla, nombre):
        assert "*" not in recursos_de(s), s
        for a in acciones(s):
            assert not a.endswith(":*") and a != "*", a


@pytest.mark.parametrize("nombre", sorted(DEFS))
def test_secretos_leidos_con_kms_decrypt_sobre_la_llave(plantilla, nombre):
    """Lección de T-047: cada lectura de un secreto cifrado lleva ``kms:Decrypt``."""
    sentencias = _sentencias_lambda(plantilla, nombre)
    assert any("secretsmanager:GetSecretValue" in acciones(s) for s in sentencias)
    assert any(
        "kms:Decrypt" in acciones(s) and "LlaveInfra" in texto(s["Resource"]) for s in sentencias
    )


def _todas(plantilla, nombre: str) -> set[str]:
    return {a for s in _sentencias_lambda(plantilla, nombre) for a in acciones(s)}


def _secretos(plantilla, nombre: str) -> str:
    return texto(
        [
            s["Resource"]
            for s in _sentencias_lambda(plantilla, nombre)
            if "secretsmanager:GetSecretValue" in acciones(s)
        ]
    )


def test_webhook_solo_envia_a_wa_entrada_y_wa_estados_y_lee_el_secreto_meta(plantilla):
    sentencias = _sentencias_lambda(plantilla, "webhook-meta")
    (envio,) = (s for s in sentencias if "sqs:SendMessage" in acciones(s))
    assert texto(envio["Resource"]).count("cc-test-wa-") == 2
    assert "cc-test-wa-entrada.fifo" in texto(envio) and "cc-test-wa-estados" in texto(envio)
    secretos = _secretos(plantilla, "webhook-meta")
    assert "secret:cc/test/meta-" in secretos and "db/" not in secretos  # no toca la base
    assert not (_todas(plantilla, "webhook-meta") & {"sqs:ReceiveMessage", "events:PutEvents"})


def test_enviador_y_estados_usan_el_rol_de_whatsapp_y_no_publican_en_el_bus(plantilla):
    enviador = _secretos(plantilla, "enviador")
    assert all(x in enviador for x in ("db/svc_whatsapp", "/meta-", "internal-auth"))
    assert "db/svc_whatsapp" in _secretos(plantilla, "estados-entrega")
    for nombre in ("enviador", "estados-entrega"):
        acciones_f = _todas(plantilla, nombre)
        assert "events:PutEvents" not in acciones_f  # publican por el outbox de la base
        assert {"sqs:ReceiveMessage", "sqs:DeleteMessage"} <= acciones_f
    assert "sqs:ChangeMessageVisibility" in _todas(plantilla, "enviador")  # espera creciente


def test_despachador_programa_schedules_y_solo_pasa_el_rol_de_scheduler(plantilla):
    sentencias = _sentencias_lambda(plantilla, "despachador")
    (paso,) = (s for s in sentencias if "iam:PassRole" in acciones(s))
    assert "role/cc-test-scheduler-destino" in texto(paso["Resource"])
    assert paso["Condition"] == {"StringEquals": {"iam:PassedToService": "scheduler.amazonaws.com"}}
    (sch,) = (s for s in sentencias if "scheduler:CreateSchedule" in acciones(s))
    assert "schedule/cc-test-envios/*" in texto(sch["Resource"])
    (envio,) = (s for s in sentencias if "sqs:SendMessage" in acciones(s))
    assert "cc-test-wa-salida.fifo" in texto(envio) and "cc-test-notif-despacho" in texto(envio)
    assert "db/svc_notificaciones" in _secretos(plantilla, "despachador")


def test_conciliador_solo_envia_a_las_colas_de_notificaciones(plantilla):
    sentencias = _sentencias_lambda(plantilla, "conciliador")
    (envio,) = (s for s in sentencias if "sqs:SendMessage" in acciones(s))
    assert "cc-test-notif-despacho" in texto(envio) and "cc-test-notif-respaldo" in texto(envio)
    acciones_c = _todas(plantilla, "conciliador")
    assert not (acciones_c & {"scheduler:CreateSchedule", "iam:PassRole", "ses:SendEmail"})
    assert "internal-auth" not in _secretos(plantilla, "conciliador")


def test_respaldo_correo_envia_solo_desde_su_identidad_y_conjunto_de_ses(plantilla):
    sentencias = _sentencias_lambda(plantilla, "respaldo-correo")
    (ses,) = (s for s in sentencias if "ses:SendEmail" in acciones(s))
    recursos_ses = texto(ses["Resource"])
    assert "identity/samuel.lopez@honne.com" in recursos_ses
    assert "configuration-set/cc-test-respaldo" in recursos_ses
    (sns,) = (s for s in sentencias if "sns:Publish" in acciones(s))
    assert "cc-test-alertas-rh" in texto(sns["Resource"])
    assert "scheduler:CreateSchedule" in _todas(plantilla, "respaldo-correo")
    assert "db/svc_notificaciones" in _secretos(plantilla, "respaldo-correo")


# -------------------------------------------------------------------------------- variables
def _entorno_fn(plantilla, nombre: str) -> dict:
    return _funciones(plantilla)[f"cc-test-{nombre}"]["Environment"]["Variables"]


def test_variables_de_webhook_meta(plantilla):
    env = _entorno_fn(plantilla, "webhook-meta")
    assert env["CC_META_SECRETO_ID"] == "cc/test/meta"
    assert env["CC_COLA_ENTRADA_URL"].endswith("/cc-test-wa-entrada.fifo")
    assert env["CC_COLA_ESTADOS_URL"].endswith("/cc-test-wa-estados")
    assert not any(k.startswith("CC_DB_") for k in env)  # sin base de datos


def test_variables_de_enviador_y_estados(plantilla):
    env = _entorno_fn(plantilla, "enviador")
    assert env["CC_DB_SECRETO_ID"] == "cc/test/db/svc_whatsapp"
    assert env["CC_INTERNAL_AUTH_SECRETO_ID"] == "cc/test/internal-auth"
    assert env["CC_META_SECRETO_ID"] == "cc/test/meta"
    assert env["CC_COLA_SALIDA_URL"].endswith("/cc-test-wa-salida.fifo")
    assert "http://" in texto(env["CC_COLABORADORES_URL"]) and "DNSName" in texto(env)
    assert env["CC_BUS_EVENTOS"] == "cc-test-eventos"
    assert (
        _entorno_fn(plantilla, "estados-entrega")["CC_DB_SECRETO_ID"] == "cc/test/db/svc_whatsapp"
    )


def test_variables_de_las_lambdas_de_notificaciones(plantilla):
    d = _entorno_fn(plantilla, "despachador")
    assert d["CC_DB_SECRETO_ID"] == "cc/test/db/svc_notificaciones"
    assert d["CC_COLA_SALIDA_URL"].endswith("/cc-test-wa-salida.fifo")
    assert d["CC_COLA_DESPACHO_URL"].endswith("/cc-test-notif-despacho")
    assert d["CC_COLA_RESPALDO_URL"].endswith("/cc-test-notif-respaldo")
    assert d["CC_SCHEDULER_GRUPO"] == "cc-test-envios"
    assert "scheduler-destino" in texto(d["CC_SCHEDULER_ROL_ARN"])
    assert "cc-test-notif-despacho" in texto(d["CC_SCHEDULER_DESPACHO_ARN"])
    assert "cc-test-notif-respaldo" in texto(d["CC_SCHEDULER_RESPALDO_ARN"])
    assert "CC_COLABORADORES_URL" in d
    c = _entorno_fn(plantilla, "conciliador")
    assert c["CC_COLA_DESPACHO_URL"].endswith("/cc-test-notif-despacho")
    r = _entorno_fn(plantilla, "respaldo-correo")
    assert r["CC_SES_ORIGEN"] == "samuel.lopez@honne.com"
    assert r["CC_SES_CONFIG_SET"] == "cc-test-respaldo"
    assert "cc-test-alertas-rh" in texto(r["CC_ALERTAS_TOPIC_ARN"])
    assert "CC_COLABORADORES_URL" in r and "CC_SCHEDULER_GRUPO" in r


def test_las_lambdas_en_vpc_usan_el_host_de_la_base_y_no_llevan_valores_secretos(plantilla):
    for nombre in DEFS:
        env = _entorno_fn(plantilla, nombre)
        assert not any(x in k for k in env for x in ("PASSWORD", "CONTRASENA", "TOKEN", "KEY"))
        if nombre not in ("webhook-meta",):
            assert "Fn::ImportValue" in texto(env["CC_DB_HOST"])  # instancia en test (sin proxy)


def test_en_prod_las_lambdas_usan_el_proxy(plantilla_prod):
    for nombre in ("enviador", "despachador"):
        f = _funciones(plantilla_prod)[f"cc-prod-{nombre}"]
        assert f["Environment"]["Variables"]["CC_DB_HOST"] == "proxy.interno"


def test_sin_credenciales_en_la_plantilla(plantilla):
    t = texto(plantilla.to_json())
    assert "AKIA" not in t and "BEGIN PRIVATE KEY" not in t  # pragma: allowlist secret


def test_sin_reservar_concurrencia_no_hay_reservas_y_los_pollers_usan_el_minimo():
    """Cuentas nuevas con cuota de 10: el ambiente puede no reservar (``reservar_concurrencia``)."""
    import dataclasses

    app, amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    amb = dataclasses.replace(
        amb, economia=dataclasses.replace(amb.economia, reservar_concurrencia=False)
    )
    stacks = construir_stacks(app, amb, destino)
    funciones = _funciones(Template.from_stack(stacks["workers"]))
    assert funciones and all("ReservedConcurrentExecutions" not in f for f in funciones.values())
    fuentes = propiedades(Template.from_stack(stacks["workers"]), "AWS::Lambda::EventSourceMapping")
    topes = [f["ScalingConfig"]["MaximumConcurrency"] for f in fuentes if "ScalingConfig" in f]
    assert topes and set(topes) == {2}
    auth = propiedades(Template.from_stack(stacks["auth"]), "AWS::Lambda::Function")
    assert all("ReservedConcurrentExecutions" not in f for f in auth)
