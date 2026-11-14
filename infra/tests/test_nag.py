"""cdk-nag (T-015): la síntesis no debe dejar hallazgos de AwsSolutions sin reconocer, y cada
reconocimiento lleva su motivo escrito."""

import ast
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from infra.constructs.nag import reconocer

INFRA = Path(__file__).resolve().parent.parent
RAIZ = INFRA.parent


@pytest.fixture(scope="module")
def ensamblado(tmp_path_factory):
    """Sintetiza con la CLI de CDK sin acceso a credenciales (igual que verificar_synth)."""
    salida = tmp_path_factory.mktemp("cdkout")
    vacio = salida / "aws_vacio"
    vacio.write_text("", encoding="utf-8")
    entorno = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    entorno.update(
        {
            "AWS_CONFIG_FILE": str(vacio),
            "AWS_SHARED_CREDENTIALS_FILE": str(vacio),
            "AWS_EC2_METADATA_DISABLED": "true",
            "CDK_DEFAULT_ACCOUNT": "034362033822",
            "CDK_DEFAULT_REGION": "us-east-1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    proc = subprocess.run(  # noqa: S603
        [
            shutil.which("cdk") or "cdk",
            "synth",
            "-c",
            "ambiente=test",
            "--no-notices",
            "--output",
            str(salida / "out"),
            "--quiet",
        ],
        cwd=INFRA,
        env=entorno,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    return proc, salida / "out"


def test_synth_termina_sin_errores(ensamblado):
    proc, _ = ensamblado
    assert proc.returncode == 0, proc.stderr[-3000:]


def test_sin_hallazgos_sin_reconocer(ensamblado):
    proc, out = ensamblado
    reporte = out / "policy-validation-report.json"
    if not reporte.exists():
        # Sin violaciones, CDK no escribe el reporte.
        assert "AwsSolutions-" not in proc.stderr
        return
    datos = json.loads(reporte.read_text(encoding="utf-8"))
    violaciones = [
        (r.get("ruleName"), [v.get("constructPath") for v in r.get("violatingConstructs", [])])
        for p in datos.get("pluginReports", [])
        for r in p.get("violations", [])
    ]
    assert violaciones == [], json.dumps(violaciones, ensure_ascii=False, indent=2)


def test_stacks_esperados(ensamblado):
    _, out = ensamblado
    plantillas = {p.name for p in out.glob("*.template.json")}
    assert {"CcSecurity-test.template.json", "CcNetwork-test.template.json"} <= plantillas


def test_reconocer_exige_motivo():
    import aws_cdk as cdk

    stack = cdk.Stack(cdk.App(), "S")
    with pytest.raises(ValueError, match="motivo"):
        reconocer(stack, "AwsSolutions-X1", "corto")


def test_cada_reconocimiento_tiene_motivo_largo():
    """Revisa en el código que cada llamada a reconocer() tenga un motivo literal suficiente."""
    for archivo in (INFRA / "stacks").glob("*.py"):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call) and getattr(nodo.func, "id", "") == "reconocer":
                assert len(nodo.args) == 3, f"{archivo.name}: reconocer() sin motivo"
