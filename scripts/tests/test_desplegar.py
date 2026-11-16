"""Pruebas de ``scripts/desplegar.py`` (T-227) con AWS SIMULADO: ningún comando toca AWS.

Un ejecutor falso registra cada llamada y responde como lo haría AWS; así se verifica el orden de
los pasos, la guardia, la verificación previa, la aprobación y que ``-SoloRevisar`` solo lea.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from infra.config import esquema
from scripts import desplegar as d
from scripts import desplegar_costos as costos

CUENTA = "034362033822"
TOKEN_ECR = "TOKEN-ECR-SECRETO-NO-DEBE-SALIR"  # pragma: allowlist secret
ENTORNO = {"AWS_PROFILE": "cc-test"}
FRASE = "apruebo T-229"
VERBOS_ESCRITURA = (
    "put",
    "create",
    "delete",
    "update",
    "start",
    "run",
    "stop",
    "register",
    "send",
    "invoke",
    "deploy",
    "destroy",
    "terminate",
    "tag",
    "attach",
    "execute",
)


def _json(obj) -> str:
    return json.dumps(obj)


class Simulador:
    """Ejecutor falso con perillas para cada escenario de la prueba."""

    def __init__(self, **opciones) -> None:
        self.llamadas: list[list[str]] = []
        self.entradas: list[str | None] = []
        self.entornos: list[dict] = []
        self.o = {
            "cuenta": CUENTA,
            "sts_error": "",
            "bootstrap": 32,
            "libre": 900,
            "secretos": [],
            "alias": [],
            "logs": [],
            "buckets": [],
            "repos": [],
            "colas": [],
            "stacks": {},
            "arm64": True,
            "presupuesto": True,
            "exit_migrar": 0,
            "exit_ops": 0,
            "imagen_existe": False,
            "diff_rc": 0,
        }
        self.o.update(opciones)

    # -- utilidades de consulta
    def verbos(self) -> list[str]:
        """Verbo de AWS de cada llamada ``aws <servicio> <verbo>``."""
        return [c[2] for c in self.llamadas if c[0] == "aws" and len(c) > 2]

    def indice(self, *piezas: str) -> int:
        for i, c in enumerate(self.llamadas):
            if all(p in c for p in piezas):
                return i
        raise AssertionError(f"no se ejecutó: {piezas}")

    def indices(self, *piezas: str) -> list[int]:
        return [i for i, c in enumerate(self.llamadas) if all(p in c for p in piezas)]

    def __call__(self, cmd, **kw):  # noqa: C901
        self.llamadas.append(list(cmd))
        self.entradas.append(kw.get("entrada"))
        self.entornos.append(dict(kw["entorno"]) if kw.get("entorno") is not None else {})
        prog = cmd[0]
        if prog == "cdk" and "--version" in cmd:
            return 0, "2.1150.0 (build abc)", ""
        if prog == "node":
            return 0, "v20.11.0", ""
        if prog in ("uv", "npm") and "--version" in cmd:
            return 0, "0.5.0" if prog == "uv" else "10.2.0", ""
        if prog == "docker":
            return self._docker(cmd)
        if prog == "aws":
            return self._aws(cmd)
        return 0, "", ""  # cdk diff/deploy/synth, empaquetado, npm

    def _docker(self, cmd):
        sub = cmd[1]
        if sub == "version":
            return 0, "linux/amd64\n", ""
        if cmd[1:3] == ["buildx", "version"]:
            return 0, "github.com/docker/buildx v0.12", ""
        if cmd[1:3] == ["buildx", "ls"]:
            plataformas = "linux/amd64, linux/arm64" if self.o["arm64"] else "linux/amd64"
            return (
                0,
                f"NAME/NODE DRIVER STATUS PLATFORMS\ndefault docker running {plataformas}\n",
                "",
            )
        return 0, "", ""

    def _aws(self, cmd):
        o = self.o
        if cmd[1] == "--version":
            return 0, "aws-cli/2.15.0 Python/3.11", ""
        servicio, verbo = cmd[1], cmd[2]
        if servicio == "sts":
            if o["sts_error"]:
                return 255, "", o["sts_error"]
            return 0, _json({"Account": o["cuenta"], "Arn": "arn:aws:sts::1:assumed-role/r/s"}), ""
        if servicio == "cloudformation" and verbo == "list-stacks":
            resumen = [{"StackName": n, "StackStatus": e} for n, e in o["stacks"].items()]
            return 0, _json({"StackSummaries": resumen}), ""
        if servicio == "cloudformation" and verbo == "describe-stacks":
            nombre = cmd[cmd.index("--stack-name") + 1]
            return self._describe_stack(nombre)
        if servicio == "lambda":
            return (
                0,
                _json(
                    {
                        "AccountLimit": {
                            "ConcurrentExecutions": 1000,
                            "UnreservedConcurrentExecutions": o["libre"],
                        }
                    }
                ),
                "",
            )
        if servicio == "secretsmanager":
            lista = [
                {"Name": n, "DeletedDate": 1.0 if pendiente else None}
                for n, pendiente in o["secretos"]
            ]
            return 0, _json({"SecretList": lista}), ""
        if servicio == "kms":
            return 0, _json({"Aliases": [{"AliasName": a} for a in o["alias"]]}), ""
        if servicio == "logs":
            return 0, _json({"logGroups": [{"logGroupName": g} for g in o["logs"]]}), ""
        if servicio == "s3api":
            return 0, _json({"Buckets": [{"Name": b} for b in o["buckets"]]}), ""
        if servicio == "ecr" and verbo == "describe-repositories":
            return 0, _json({"repositories": [{"repositoryName": r} for r in o["repos"]]}), ""
        if servicio == "ecr" and verbo == "get-login-password":
            return 0, TOKEN_ECR + "\n", ""
        if servicio == "ecr" and verbo == "describe-images":
            if o["imagen_existe"]:
                return 0, _json({"imageDetails": [{}]}), ""
            return 254, "", "An error occurred (ImageNotFoundException) when calling..."
        if servicio == "sqs":
            return 0, _json({"QueueUrls": [f"https://sqs/1/{c}" for c in o["colas"]]}), ""
        if servicio == "budgets":
            if o["presupuesto"]:
                return 0, _json({"Budget": {}}), ""
            return 254, "", "An error occurred (NotFoundException) when calling DescribeBudget"
        if servicio == "ecs" and verbo == "run-task":
            tarea = cmd[cmd.index("--task-definition") + 1]
            return 0, _json({"tasks": [{"taskArn": f"arn:aws:ecs:x:1:task/{tarea}/abc"}]}), ""
        if servicio == "ecs" and verbo == "wait":
            return 0, "", ""
        if servicio == "ecs" and verbo == "describe-tasks":
            arn = cmd[cmd.index("--tasks") + 1]
            nombre = "migrar" if "-migrar/" in arn else "ops"
            codigo = o["exit_migrar"] if nombre == "migrar" else o["exit_ops"]
            return (
                0,
                _json(
                    {
                        "tasks": [
                            {
                                "stoppedReason": "Essential container exited",
                                "containers": [{"name": nombre, "exitCode": codigo}],
                            }
                        ]
                    }
                ),
                "",
            )
        raise AssertionError(f"orden de AWS no simulada: {cmd}")

    def _describe_stack(self, nombre):
        o = self.o
        if nombre == "CDKToolkit":
            if o["bootstrap"] is None:
                return (
                    255,
                    "",
                    "An error occurred (ValidationError): Stack with id CDKToolkit does not exist",
                )
            salidas = [{"OutputKey": "BootstrapVersion", "OutputValue": str(o["bootstrap"])}]
            return (
                0,
                _json({"Stacks": [{"StackStatus": "UPDATE_COMPLETE", "Outputs": salidas}]}),
                "",
            )
        mapa = {
            "CcComputeBase-test": {
                "NombreCluster": "cc-test",
                "TareaMigrar": "cc-test-migrar",
                "TareaOps": "cc-test-ops",
                "SubredesAplicacion": "subnet-a,subnet-b",
                "SgEcsId": "sg-1",
            },
            "CcAuth-test": {"UserPoolId": "us-east-1_X", "ClienteSpaId": "cli"},
            "CcFrontend-test": {"UrlSpa": "https://d1.cloudfront.net"},
        }
        valores = mapa.get(nombre, {})
        salidas = [{"OutputKey": k, "OutputValue": v} for k, v in valores.items()]
        return 0, _json({"Stacks": [{"StackStatus": "CREATE_COMPLETE", "Outputs": salidas}]}), ""


@pytest.fixture(autouse=True)
def artefactos(monkeypatch, tmp_path):
    """Los artefactos locales (dist y paquetes) existen: no se construye nada de verdad."""
    rutas = {}
    for nombre in ("dist", "lambdas", "notif", "wa"):
        ruta = tmp_path / "artefactos" / nombre
        ruta.mkdir(parents=True)
        rutas[nombre] = ruta
    monkeypatch.setattr(
        d.Desplegador,
        "_rutas_artefactos",
        lambda self: {f"artefacto {k}": v for k, v in rutas.items()},
    )


def crear(sim=None, *, modo="desplegar", frase=FRASE, interactivo=True, entorno=None, **kw):
    sim = sim or Simulador()
    salida: list[str] = []
    respuestas = iter([frase])
    desp = d.Desplegador(
        kw.pop("ambiente", "test"),
        modo=modo,
        entorno=ENTORNO if entorno is None else entorno,
        ejecutor=sim,
        salida=salida.append,
        leer=lambda _msg: next(respuestas),
        interactivo=interactivo,
        **kw,
    )
    return desp, sim, salida


def correr(sim=None, **kw):
    desp, sim, salida = crear(sim, **kw)
    codigo = desp.ejecutar()
    return codigo, desp, sim, salida


# ------------------------------------------------------------------------------------- guardia
def test_cuenta_incorrecta_detiene_antes_de_todo():
    codigo, _, sim, salida = correr(Simulador(cuenta="111111111111"))
    assert codigo == d.SALIDA_PREVIA
    assert "CUENTA_INCORRECTA" in "\n".join(salida)
    assert sim.verbos() == ["get-caller-identity"]


def test_sesion_vencida():
    sim = Simulador(sts_error="The SSO session associated with this profile has expired")
    codigo, _, sim, salida = correr(sim)
    assert codigo == d.SALIDA_PREVIA
    assert "SESION_VENCIDA" in "\n".join(salida) and "aws sso login" in "\n".join(salida)
    assert sim.verbos() == ["get-caller-identity"]


def test_llaves_en_el_entorno_se_rechazan_sin_llamar_a_aws():
    llave = "AKIAXXXXXXXXXXXXXXXX"  # pragma: allowlist secret
    for extra in ({"AWS_ACCESS_KEY_ID": llave}, {"AWS_SESSION_TOKEN": "tok"}):
        codigo, _, sim, salida = correr(entorno={**ENTORNO, **extra})
        assert codigo == d.SALIDA_PREVIA
        assert sim.llamadas == []
        assert "AKIA" not in "\n".join(salida) and "tok" not in " ".join(salida).split("(")[0]


def test_perfil_distinto_o_ausente():
    codigo, _, sim, salida = correr(entorno={"AWS_PROFILE": "default"})
    assert codigo == d.SALIDA_PREVIA and "PERFIL_INCORRECTO" in "\n".join(salida)
    codigo, _, sim, _ = correr(entorno={})
    assert codigo == d.SALIDA_PREVIA and sim.llamadas == []


# ----------------------------------------------------------------------- verificación previa
def hallazgos_de(sim=None, **kw):
    desp, sim, _ = crear(sim, **kw)
    desp.guardia()
    return desp.previa(), sim


def errores(hallazgos, tema):
    return [h for h in hallazgos if h.nivel == "ERROR" and tema in h.tema]


def test_previa_sin_problemas():
    h, _ = hallazgos_de()
    assert [x for x in h if x.nivel == "ERROR"] == []


def test_secreto_pendiente_de_borrado_es_conflicto_siempre():
    sim = Simulador(secretos=[("cc/test/db/admin", True), ("cc/test/otro", False)])
    h, _ = hallazgos_de(sim)
    assert errores(h, "secretos pendientes")
    # aun con el ambiente ya desplegado sigue siendo conflicto
    sim = Simulador(
        secretos=[("cc/test/db/admin", True)], stacks={"CcSecurity-test": "UPDATE_COMPLETE"}
    )
    h, _ = hallazgos_de(sim)
    assert errores(h, "secretos pendientes")


@pytest.mark.parametrize(
    ("clave", "valor", "tema"),
    [
        ("alias", ["alias/cc-test-infra"], "alias de KMS"),
        ("logs", ["/cc/test/migrar"], "grupos de logs /cc"),
        ("logs", ["/aws/lambda/cc-test-cognito-pre-token"], "grupos de logs de Lambda"),
        ("buckets", [f"cc-test-{CUENTA}-constancias"], "buckets retenidos"),
        ("repos", ["cc-test/migrar"], "repositorios de ECR"),
        ("colas", ["cc-test-wa-salida.fifo"], "colas de SQS"),
    ],
)
def test_recursos_huerfanos_son_conflicto_solo_sin_stacks(clave, valor, tema):
    h, _ = hallazgos_de(Simulador(**{clave: valor}))
    assert errores(h, tema)
    h, _ = hallazgos_de(Simulador(**{clave: valor, "stacks": {"CcData-test": "CREATE_COMPLETE"}}))
    assert not errores(h, tema)


def test_stack_en_estado_malo_bloquea():
    h, _ = hallazgos_de(Simulador(stacks={"CcBackup-test": "DELETE_FAILED"}))
    assert errores(h, "stack CcBackup-test")


def test_recursos_de_otro_ambiente_no_cuentan():
    h, _ = hallazgos_de(Simulador(alias=["alias/cc-prod-infra"], logs=["/cc/prod/migrar"]))
    assert [x for x in h if x.nivel == "ERROR"] == []


def test_cuota_de_lambda_insuficiente():
    reservada = d.concurrencia_reservada()
    h, _ = hallazgos_de(Simulador(libre=reservada + 99))
    assert errores(h, "cuota")
    h, _ = hallazgos_de(Simulador(libre=reservada + 100))
    assert not errores(h, "cuota")
    # una cuenta nueva con cuota de 10
    h, _ = hallazgos_de(Simulador(libre=10))
    assert errores(h, "cuota")


def test_bootstrap_ausente_o_viejo():
    h, sim = hallazgos_de(Simulador(bootstrap=None))
    assert errores(h, "bootstrap")
    assert "cdk bootstrap" in " ".join(x.detalle for x in h if x.tema.startswith("bootstrap"))
    assert "bootstrap" not in sim.verbos()  # solo se verifica: nunca se ejecuta
    h, _ = hallazgos_de(Simulador(bootstrap=5))
    assert errores(h, "bootstrap")


def test_docker_sin_arm64():
    h, _ = hallazgos_de(Simulador(arm64=False))
    assert errores(h, "Docker linux/arm64")


def test_presupuesto_inexistente_bloquea():
    h, _ = hallazgos_de(Simulador(presupuesto=False))
    assert errores(h, "presupuesto")


def test_variable_de_lambdas_desde_fuente_bloquea():
    h, _ = hallazgos_de(entorno={**ENTORNO, "CC_LAMBDAS_DESDE_FUENTE": "1"})
    assert errores(h, "CC_LAMBDAS_DESDE_FUENTE")


def test_la_previa_detiene_el_flujo_sin_cambiar_nada():
    codigo, _, sim, _ = correr(Simulador(secretos=[("cc/test/x", True)]))
    assert codigo == d.SALIDA_PREVIA
    assert not [c for c in sim.llamadas if c[0] == "cdk" and c[1] != "--version"]
    assert not [c for c in sim.llamadas if any("empaquetar" in x for x in c)]
    assert all(v.startswith(("get-", "describe-", "list-")) for v in sim.verbos())


# ---------------------------------------------------------------------------- ambiente prod
@pytest.fixture
def ambientes_prod(tmp_path):
    crudo = json.loads(esquema.RUTA_POR_DEFECTO.read_text(encoding="utf-8"))
    prod = copy.deepcopy(crudo["ambientes"]["test"])
    prod["cuentas_permitidas"] = ["111111111111"]
    prod["perfil"] = "cc-prod"
    prod["etiquetas"]["ambiente"] = "prod"
    prod["economia"].update(
        nat="gateway",
        rds_clase="db.t4g.medium",
        rds_multi_az=True,
        rds_proxy=True,
        waf_habilitado=True,
        workers_min_tareas=1,
        tareas_por_servicio=2,
        retencion_respaldos_dias=14,
        permite_borrado=False,
    )
    crudo["ambientes"]["prod"] = prod
    ruta = tmp_path / "ambientes.json"
    ruta.write_text(json.dumps(crudo), encoding="utf-8")
    return ruta


def test_prod_exige_contextos_y_llave_publica(ambientes_prod):
    desp, _, _ = crear(
        ambiente="prod", ruta_ambientes=ambientes_prod, entorno={"AWS_PROFILE": "cc-prod"}
    )
    assert desp.contextos_obligatorios() == [
        "certificado_alb_arn",
        "dominio_interno",
        "repositorio_pipeline",
    ]
    h = desp._previa_contextos()
    assert [x for x in h if x.tema == "contextos obligatorios" and x.nivel == "ERROR"]
    assert [x for x in h if x.tema.startswith("llave pública") and x.nivel == "ERROR"]
    # con los contextos y sin pipeline, ya no se pide el repositorio
    ctx = {
        "certificado_alb_arn": "arn:aws:acm:us-east-1:111111111111:certificate/abc",
        "dominio_interno": "cc.interno.example",
        "pipeline": "false",
    }
    desp, _, _ = crear(
        ambiente="prod",
        ruta_ambientes=ambientes_prod,
        contextos=ctx,
        entorno={"AWS_PROFILE": "cc-prod"},
    )
    assert desp.contextos_obligatorios() == ["certificado_alb_arn", "dominio_interno"]
    assert not [
        x
        for x in desp._previa_contextos()
        if x.tema == "contextos obligatorios" and x.nivel == "ERROR"
    ]


def test_prod_grupos_de_stacks_incluyen_recuperacion_y_respaldo(ambientes_prod):
    desp, _, _ = crear(ambiente="prod", ruta_ambientes=ambientes_prod)
    assert desp.base[0] == "CcBackupRecuperacion-prod"
    assert desp.servicios[-1] == "CcBackup-prod"
    assert "CcPipeline-prod" not in desp.base + desp.servicios  # el script no lo despliega


def test_prod_la_guardia_usa_la_cuenta_de_prod(ambientes_prod):
    sim = Simulador(cuenta=CUENTA)  # la cuenta de test no sirve para prod
    codigo, _, _, salida = correr(
        sim, ambiente="prod", ruta_ambientes=ambientes_prod, entorno={"AWS_PROFILE": "cc-prod"}
    )
    assert codigo == d.SALIDA_PREVIA and "CUENTA_INCORRECTA" in "\n".join(salida)


def test_frase_de_aprobacion_configurable_por_ambiente(tmp_path, ambientes_prod):
    ruta = tmp_path / "despliegue.json"
    ruta.write_text(
        json.dumps({"ambientes": {"prod": {"frase_aprobacion": "apruebo produccion 1"}}}),
        encoding="utf-8",
    )
    desp, _, _ = crear(ambiente="prod", ruta_ambientes=ambientes_prod, ruta_despliegue=ruta)
    assert desp.frase == "apruebo produccion 1"
    desp, _, _ = crear(ambiente="test")
    assert desp.frase == FRASE


# --------------------------------------------------------------------------- flujo completo
ORDEN_DEPLOY = ("cdk", "deploy")


def test_orden_de_los_pasos_de_un_despliegue_completo():
    codigo, desp, sim, salida = correr()
    assert codigo == d.SALIDA_OK, "\n".join(salida)
    llamadas = sim.llamadas
    i_guardia = sim.indice("sts", "get-caller-identity")
    i_previa = sim.indice("lambda", "get-account-settings")
    i_empaque = min(i for i, c in enumerate(llamadas) if any("empaquetar_lambdas" in a for a in c))
    i_build = sim.indice("npm", "run", "build")
    i_diff = sim.indice("cdk", "diff")
    i_base, i_servicios = (sim.indices("cdk", "deploy")[0], sim.indices("cdk", "deploy")[1])
    i_migrar = next(i for i in sim.indices("ecs", "run-task") if "cc-test-migrar" in llamadas[i])
    i_ops = next(i for i in sim.indices("ecs", "run-task") if "cc-test-ops" in llamadas[i])
    i_login = sim.indice("docker", "login")
    assert i_guardia < i_previa < i_empaque < i_build < i_diff < i_base
    # las migraciones corren ENTRE las bases y los servicios; las contraseñas antes de los servicios
    assert i_base < i_login < i_migrar < i_ops < i_servicios
    # ... y cada fase de cambio va precedida de la guardia de cuenta
    guardias = sim.indices("sts", "get-caller-identity")
    for fase in (i_base, i_login, i_migrar, i_ops, i_servicios):
        assert any(g < fase and fase - g <= 4 for g in guardias), fase
    # las tres variantes de empaquetado
    variantes = [c for c in llamadas if any("empaquetar_lambdas" in a for a in c)]
    assert [c[2:] if len(c) > 2 else [] for c in variantes] == [
        [],
        ["--notificaciones"],
        ["--whatsapp"],
    ]
    # los grupos de stacks
    assert llamadas[i_base][2:9] == desp.base and llamadas[i_servicios][2:9] == desp.servicios[:7]
    assert "CcComputeBase-test" in llamadas[i_base] and "CcCompute-test" in llamadas[i_servicios]
    # la contraseña de roles usa la tarea ops con el comando explícito
    run_ops = llamadas[i_ops]
    sobre = json.loads(run_ops[run_ops.index("--overrides") + 1])
    assert sobre["containerOverrides"][0] == {"name": "ops", "command": ["./ops.sh", "contrasenas"]}
    assert "--overrides" not in llamadas[i_migrar]
    # imágenes: ambas, arm64
    construcciones = [c for c in llamadas if c[:3] == ["docker", "buildx", "build"]]
    assert len(construcciones) == 2 and all("linux/arm64" in c for c in construcciones)


def test_la_salida_final_da_el_comando_de_ecs_exec_sin_ejecutarlo():
    codigo, _, sim, salida = correr()
    texto = "\n".join(salida)
    assert codigo == d.SALIDA_OK
    assert "aws ecs execute-command" in texto and "./ops.sh bootstrap" in texto
    assert "https://d1.cloudfront.net" in texto and "us-east-1_X" in texto
    assert not sim.indices("execute-command")  # no se ejecuta
    assert not sim.indices("ecs", "stop-task")


def test_nunca_se_ejecuta_destroy_ni_borrado():
    _, _, sim, _ = correr()
    for c in sim.llamadas:
        assert "destroy" not in c
        if c[0] == "aws" and c[1] != "--version":
            assert not c[2].startswith(("delete", "remove", "terminate", "purge"))


def test_sin_la_frase_exacta_no_se_despliega_nada():
    for frase in ("", "si", "Apruebo T-229", "apruebo T-229 y mas", "apruebo T-230"):
        codigo, _, sim, _ = correr(frase=frase)
        assert codigo == d.SALIDA_SIN_APROBACION, frase
        assert sim.indice("cdk", "diff") >= 0  # el diff sí se mostró
        assert not sim.indices("cdk", "deploy") and not sim.indices("ecs", "run-task")
        assert not sim.indices("docker", "push") and not sim.indices("docker", "login")


def test_sin_consola_interactiva_falla_aunque_se_tenga_la_frase():
    codigo, _, sim, salida = correr(interactivo=False)
    assert codigo == d.SALIDA_SIN_CONSOLA
    assert "consola interactiva" in "\n".join(salida)
    assert not sim.indices("cdk", "deploy") and not sim.indices("ecs", "run-task")


def test_la_aprobacion_no_se_pide_antes_del_diff_ni_se_reutiliza():
    pedidos: list[str] = []
    sim = Simulador()
    desp = d.Desplegador(
        "test",
        entorno=ENTORNO,
        ejecutor=sim,
        salida=lambda _: None,
        leer=lambda m: pedidos.append(m) or FRASE,
        interactivo=True,
    )
    assert desp.ejecutar() == d.SALIDA_OK
    assert len(pedidos) == 1 and FRASE in pedidos[0]


def test_no_existe_bandera_para_saltar_la_aprobacion():
    with pytest.raises(SystemExit):
        d.main(["--ambiente", "test", "--si", "--aprobar", "--yes"])


def test_migracion_fallida_detiene_todo():
    codigo, _, sim, salida = correr(Simulador(exit_migrar=1))
    assert codigo == d.SALIDA_FALLO
    assert "código 1" in "\n".join(salida)
    assert len(sim.indices("cdk", "deploy")) == 1  # solo el grupo Base
    assert not any("cc-test-ops" in c for c in sim.llamadas if "run-task" in c)


def test_contrasenas_fallidas_detienen_antes_de_los_servicios():
    codigo, _, sim, _ = correr(Simulador(exit_ops=2))
    assert codigo == d.SALIDA_FALLO
    assert len(sim.indices("cdk", "deploy")) == 1


def test_una_imagen_ya_publicada_se_omite():
    codigo, _, sim, _ = correr(Simulador(imagen_existe=True))
    assert codigo == d.SALIDA_OK
    assert not sim.indices("docker", "push") and not sim.indices("docker", "buildx", "build")


def test_secretos_no_se_registran_ni_se_imprimen():
    codigo, desp, sim, salida = correr()
    assert codigo == d.SALIDA_OK
    assert TOKEN_ECR not in "\n".join(salida)
    assert TOKEN_ECR not in repr(desp.registro)
    # el token solo viaja por la entrada estándar de docker login
    i = sim.indice("docker", "login")
    assert sim.entradas[i] == TOKEN_ECR
    assert "--password-stdin" in sim.llamadas[i]
    assert sum(1 for e in sim.entradas if e) == 1


def test_docker_usa_una_carpeta_temporal_que_se_borra():
    codigo, desp, sim, _ = correr()
    assert codigo == d.SALIDA_OK
    carpetas = {
        sim.entornos[i]["DOCKER_CONFIG"]
        for i, c in enumerate(sim.llamadas)
        if c[0] == "docker" and (c[1] in ("login", "push") or c[1:3] == ["buildx", "build"])
    }
    assert len(carpetas) == 1
    carpeta = Path(carpetas.pop())
    assert carpeta != Path.home() / ".docker"
    assert not carpeta.exists()  # se borró al terminar
    assert desp._config_docker is None


def test_la_carpeta_temporal_no_copia_credenciales(tmp_path):
    origen = tmp_path / "docker"
    (origen / "contexts").mkdir(parents=True)
    (origen / "config.json").write_text(
        json.dumps(
            {
                "credsStore": "desktop",
                "auths": {"x": {"auth": "c2VjcmV0bw=="}},  # pragma: allowlist secret
                "cliPluginsExtraDirs": ["C:/plugins"],
                "currentContext": "desktop-linux",
            }
        ),
        encoding="utf-8",
    )
    desp, _, _ = crear(entorno={**ENTORNO, "DOCKER_CONFIG": str(origen)})
    carpeta = desp._preparar_docker()
    try:
        copiado = json.loads((carpeta / "config.json").read_text(encoding="utf-8"))
        assert copiado == {"cliPluginsExtraDirs": ["C:/plugins"], "currentContext": "desktop-linux"}
    finally:
        desp._limpiar()


# ------------------------------------------------------------------------------ -SoloRevisar
def es_lectura(cmd: list[str]) -> bool:
    if cmd[0] != "aws" or cmd[1] == "--version":
        return True
    verbo = cmd[2]
    return verbo.startswith(d.VERBOS_LECTURA) and not any(v in verbo for v in VERBOS_ESCRITURA)


def test_solo_revisar_nunca_cambia_nada():
    codigo, _, sim, salida = correr(modo="revisar")
    assert codigo == d.SALIDA_OK, "\n".join(salida)
    assert sim.indice("cdk", "diff") >= 0
    assert not sim.indices("cdk", "deploy")
    assert all(es_lectura(c) for c in sim.llamadas), [c for c in sim.llamadas if not es_lectura(c)]
    assert not [c for c in sim.llamadas if c[0] == "docker" and c[1] in ("push", "login", "build")]
    assert not [c for c in sim.llamadas if "run-task" in c or "get-login-password" in c]
    texto = "\n".join(salida)
    assert "no se desplegó nada" in texto
    assert "bucket de assets del CDKToolkit" in texto  # el aviso del cdk diff
    assert "ESTIMACIONES" in texto and "Costo estimado" in texto


def test_solo_revisar_no_pide_aprobacion():
    pedidos = []
    desp = d.Desplegador(
        "test",
        modo="revisar",
        entorno=ENTORNO,
        ejecutor=Simulador(),
        salida=lambda _: None,
        leer=lambda m: pedidos.append(m) or "",
        interactivo=False,
    )
    assert desp.ejecutar() == d.SALIDA_OK and pedidos == []


def test_solo_synth_no_llama_a_aws_ni_pasa_credenciales():
    codigo, _, sim, salida = correr(
        modo="synth", entorno={"AWS_PROFILE": "cc-test", "AWS_REGION": "x"}
    )
    assert codigo == d.SALIDA_OK, "\n".join(salida)
    assert not [c for c in sim.llamadas if c[0] in ("aws", "docker")]
    i = sim.indice("cdk", "synth")
    entorno = sim.entornos[i]
    assert entorno["CDK_DEFAULT_ACCOUNT"] == CUENTA
    assert "AWS_PROFILE" not in entorno and "AWS_REGION" not in entorno
    assert entorno["AWS_EC2_METADATA_DISABLED"] == "true"
    assert "--profile" not in sim.llamadas[i]


def test_simular_no_ejecuta_nada():
    def prohibido(*a, **k):
        raise AssertionError("el modo simulado no debe ejecutar comandos")

    desp, _, _ = crear(Simulador(), modo="desplegar")
    desp.ejecutor = prohibido
    texto = "\n".join(desp.plan())
    assert "SIMULACIÓN" in texto and "cdk deploy" in texto and FRASE in texto
    desp.salida = lambda _: None
    desp.mostrar_costo()  # el costo es local


# --------------------------------------------------------------------------- argumentos
def test_contextos_validados():
    assert d.validar_contextos(["empresa_id_whatsapp=12", "respaldo=false"]) == {
        "empresa_id_whatsapp": "12",
        "respaldo": "false",
    }
    for malo in (
        "otro=1",
        "empresa_id_whatsapp=abc",
        "dominio_interno=a b;rm",
        "sin_igual",
        "pipeline=true",
    ):
        with pytest.raises(d.ErrorDespliegue) as exc:
            d.validar_contextos([malo])
        assert exc.value.codigo == d.SALIDA_USO


def test_ambiente_desconocido():
    with pytest.raises(d.ErrorDespliegue):
        d.Desplegador("no-existe", entorno=ENTORNO, ejecutor=Simulador())
    assert d.main(["--ambiente", "no-existe", "--simular"]) == d.SALIDA_USO


def test_main_simular_imprime_y_no_ejecuta(capsys):
    assert d.main(["--ambiente", "test", "--solo-revisar", "--simular", "--dias", "7"]) == 0
    fuera = capsys.readouterr().out
    assert "SIMULACIÓN" in fuera and "7 días" in fuera


def test_los_grupos_coinciden_con_nombres_de_stacks_del_codigo():
    pipeline = pytest.importorskip("infra.stacks.pipeline")
    amb = esquema.obtener_ambiente("test")
    base, servicios = d.grupos_de_stacks(amb, {})
    assert (base, servicios) == pipeline.nombres_de_stacks(
        "test", con_recuperacion=False, con_respaldo=True
    )
    base, servicios = d.grupos_de_stacks(amb, {"respaldo": "false"})
    assert (base, servicios) == pipeline.nombres_de_stacks(
        "test", con_recuperacion=False, con_respaldo=False
    )


def test_la_concurrencia_reservada_coincide_con_los_stacks():
    workers = pytest.importorskip("infra.stacks.workers_lambdas")
    auth = pytest.importorskip("infra.stacks.auth")
    esperado = sum(f.reservada for f in workers.LAMBDAS) + auth.CONCURRENCIA_RESERVADA * len(
        auth.TRIGGERS
    )
    assert d.concurrencia_reservada() == esperado


def test_etiquetas_de_imagenes_y_version_de_cdk():
    assert set(d.etiquetas_imagenes()) == {"migrar", "ops"}
    assert d.version_cli_cdk().count(".") == 2


def test_el_ps1_tiene_bom_y_el_perfil_no_es_un_parametro():
    ps1 = Path(__file__).resolve().parents[1] / "desplegar.ps1"
    datos = ps1.read_bytes()
    assert datos.startswith(b"\xef\xbb\xbf")
    texto = datos.decode("utf-8-sig")
    assert "-Perfil" not in texto and "$Perfil" not in texto and "$Cuenta" not in texto
    assert "SoloRevisar" in texto and "SoloSynth" in texto


def test_no_hay_codigo_que_borre_recursos_de_aws():
    fuente = (Path(__file__).resolve().parents[1] / "desplegar.py").read_text(encoding="utf-8")
    for prohibido in ('"destroy"', '"delete-', '"remove-', "--force-delete", "rmtree(self.raiz"):
        assert prohibido not in fuente, prohibido


# -------------------------------------------------------------------------------------- costos
def test_costo_de_test_supera_los_50_usd_encendido_todo_el_tiempo():
    amb = esquema.obtener_ambiente("test")
    c = costos.cargar_costos()
    est = costos.estimar(amb, c, dias=14)
    assert est.supera and 60 < est.total_ventana < 75
    assert est.tope_ventana == 50
    menor = costos.estimar(amb, c, dias=14, horas_servicios_dia=8)
    assert not menor.supera and menor.total_ventana < est.total_ventana
    texto = "\n".join(costos.formatear(est, c))
    assert "ESTIMACIONES" in texto and "SUPERA EL PRESUPUESTO" in texto
    assert "TOTAL" in texto


def test_costo_escala_con_los_dias_y_con_prod(ambientes_prod):
    amb = esquema.obtener_ambiente("test")
    c = costos.cargar_costos()
    a7, a14 = costos.estimar(amb, c, dias=7), costos.estimar(amb, c, dias=14)
    assert a14.total_ventana == pytest.approx(2 * a7.total_ventana, rel=0.01)
    prod = esquema.obtener_ambiente("prod", ambientes_prod)
    ep = costos.estimar(prod, c, dias=14)
    assert ep.mensual > a14.mensual
    assert any("NAT Gateway" in r.concepto for r in ep.rubros)
    assert any("WAF" in r.concepto for r in ep.rubros)
    assert any("RDS Proxy" in r.concepto for r in ep.rubros)


def test_sin_reservar_concurrencia_una_cuota_de_10_no_bloquea():
    import dataclasses

    desp, _, _ = crear(Simulador(libre=10))
    desp.amb = dataclasses.replace(
        desp.amb, economia=dataclasses.replace(desp.amb.economia, reservar_concurrencia=False)
    )
    [hallazgo] = desp._cuota(False)
    assert hallazgo.nivel == "OK" and "no reserva concurrencia" in hallazgo.detalle
    # con reserva (lo normal) la misma cuota sí bloquea
    desp2, _, _ = crear(Simulador(libre=10))
    assert desp2._cuota(False)[0].nivel == "ERROR"
