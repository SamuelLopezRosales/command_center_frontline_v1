"""Buildspecs de los proyectos de CodeBuild del pipeline (design.md §14.2; T-226).

Reemplazan a ``infra/pipeline/buildspec-ci.yml`` (T-016, definido y nunca desplegado). Ningún
buildspec contiene credenciales ni valores de secretos: CodeBuild usa el rol de cada proyecto y los
valores variables llegan por variables de entorno (``CC_AMBIENTE``, ``CC_CDK_CONTEXTO``...) que
define ``infra/stacks/pipeline.py``.

Orden de una ejecución (cada paso es un proyecto, ``pipeline.py`` los encadena):

1. ``ci``: lint, pruebas, ``npm run build`` del frontend **antes** del synth (``CcFrontend`` falla
   sin ``frontend/dist``), empaquetado de las tres variantes de las Lambdas y ``cdk synth`` con
   cdk-nag. Entrega el ensamblado de CDK y los archivos para las migraciones.
2. Aprobación manual.
3. ``respaldo`` (solo ``prod``): instantánea manual de RDS antes de migrar (design.md §2.8).
4. ``base``: ``cdk deploy`` de los stacks base y publicación de las imágenes ``migrar`` y ``ops``.
5. ``migrar``: la tarea de ECS ``migrar`` (``scripts/migrar_todo.py``: dashboard, campos,
   colaboradores, whatsapp, constancias, notificaciones, y luego ``roles.sql``, ``rls.sql`` y
   ``grants.sql``); si sale con un código distinto de 0, el pipeline se detiene.
6. ``servicios``: ``cdk deploy`` del resto de los stacks.
"""

from __future__ import annotations

from typing import Any

# Versión de la CLI de CDK con la que se probó el proyecto (``cdk --version`` en el equipo de
# desarrollo). Se fija: una CLI distinta puede exigir otra versión del esquema del ensamblado.
VERSION_CLI_CDK = "2.1147.0"

# Quitar del artefacto lo que pesa y no hace falta aguas abajo.
EXCLUIR_DEL_ARTEFACTO = [
    ".git/**/*",
    ".venv/**/*",
    "**/node_modules/**/*",
    "**/__pycache__/**/*",
    "**/.pytest_cache/**/*",
]

_CABECERA: dict[str, Any] = {
    "version": "0.2",
    "env": {"shell": "bash", "variables": {"PYTHONIOENCODING": "utf-8"}},
}


def _con_cdk(comandos: list[str], *, python: bool = False) -> dict[str, Any]:
    runtimes = {"nodejs": "20"}
    instalar = ["npm install -g aws-cdk@$CDK_CLI_VERSION"]
    if python:
        runtimes["python"] = "3.12"
        instalar.insert(0, "pip install --quiet uv")
    return {"runtime-versions": runtimes, "commands": instalar + comandos}


def ci() -> dict[str, Any]:
    """Equivalente en Linux de ``scripts/ci.ps1`` más el build del frontend y el empaquetado."""
    return {
        **_CABECERA,
        "phases": {
            "install": _con_cdk(
                [
                    "uv sync --python 3.12 --group dev --group infra --group servicios",
                    "(cd frontend && npm ci)",
                    "docker info > /dev/null",
                ],
                python=True,
            ),
            "pre_build": {
                "commands": [
                    # ANTES de las pruebas de infra y del synth: CcFrontend exige frontend/dist.
                    "(cd frontend && npm run build)",
                    "uv run --python 3.12 python scripts/empaquetar_lambdas.py",
                    "uv run --python 3.12 python scripts/empaquetar_lambdas.py --notificaciones",
                    "uv run --python 3.12 python scripts/empaquetar_lambdas.py --whatsapp",
                    "uv run --python 3.12 ruff check .",
                    "uv run --python 3.12 ruff format --check .",
                ]
            },
            "build": {
                "commands": [
                    "uv run --python 3.12 pytest -q -p no:cacheprovider",
                    "(cd frontend && npm test)",
                    # cdk synth con cdk-nag: la guardia de cuenta rechaza una cuenta no permitida.
                    'ARGS=($CC_CDK_CONTEXTO); if [ -n "${CC_CLAVE_PUBLICA_CLOUDFRONT:-}" ]; then '
                    'ARGS+=(-c "cloudfront_public_key_pem=$CC_CLAVE_PUBLICA_CLOUDFRONT"); fi; '
                    'cd infra && cdk synth -c ambiente=$CC_AMBIENTE "${ARGS[@]}" '
                    "--no-notices --quiet --output cdk.out",
                ]
            },
        },
        "artifacts": {
            "files": ["**/*"],
            "exclude-paths": EXCLUIR_DEL_ARTEFACTO,
        },
    }


def respaldo() -> dict[str, Any]:
    """Instantánea manual de RDS antes de migrar (solo ``prod``; design.md §2.8, §14.2)."""
    return {
        **_CABECERA,
        "phases": {
            "build": {
                "commands": [
                    "SALIDA=$(aws cloudformation describe-stacks --stack-name CcData-$CC_AMBIENTE "
                    "--query \"Stacks[0].Outputs[?OutputKey=='RdsEndpoint'].OutputValue\" "
                    "--output text 2>/dev/null || true)",
                    # Primer despliegue: aún no hay base de datos que respaldar.
                    'if [ -z "$SALIDA" ] || [ "$SALIDA" = "None" ]; then '
                    'echo "CcData-$CC_AMBIENTE no existe: no hay instantánea"; exit 0; fi',
                    # El identificador de la instancia es la primera etiqueta de su nombre DNS.
                    "INSTANCIA=${SALIDA%%.*}",
                    "SNAP=cc-$CC_AMBIENTE-pre-migracion-$(date -u +%Y%m%d-%H%M%S)",
                    "aws rds create-db-snapshot --db-instance-identifier $INSTANCIA "
                    "--db-snapshot-identifier $SNAP "
                    '--tags "Key=proyecto,Value=$CC_ETQ_PROYECTO" '
                    '"Key=ambiente,Value=$CC_ETQ_AMBIENTE" '
                    '"Key=responsable,Value=$CC_ETQ_RESPONSABLE" > /dev/null',
                    "aws rds wait db-snapshot-available --db-snapshot-identifier $SNAP",
                    'echo "Instantánea $SNAP disponible"',
                ]
            }
        },
    }


def base() -> dict[str, Any]:
    """Stacks base (``cdk deploy``) y publicación de las imágenes ``migrar`` y ``ops``."""
    return {
        **_CABECERA,
        "phases": {
            "install": _con_cdk(["docker info > /dev/null"]),
            "build": {
                "commands": [
                    "cd infra && cdk deploy $CC_STACKS_BASE --app cdk.out --require-approval never "
                    "--no-notices --ci && cd ..",
                    "CUENTA=$(aws sts get-caller-identity --query Account --output text)",
                    "REGISTRO=$CUENTA.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com",
                    "aws ecr get-login-password | docker login --username AWS --password-stdin "
                    "$REGISTRO",
                    # Los repositorios son inmutables: solo se publica la etiqueta que no existe.
                    "for IMAGEN in migrar:$CC_TAG_MIGRAR ops:$CC_TAG_OPS; do "
                    "N=${IMAGEN%%:*}; T=${IMAGEN##*:}; REPO=cc-$CC_AMBIENTE/$N; "
                    "if aws ecr describe-images --repository-name $REPO --image-ids imageTag=$T "
                    '> /dev/null 2>&1; then echo "$REPO:$T ya existe"; else '
                    "docker build --platform linux/arm64 -f infra/docker/$N/Dockerfile "
                    "-t $REGISTRO/$REPO:$T . && docker push $REGISTRO/$REPO:$T; fi; done",
                ]
            },
        },
    }


def migrar() -> dict[str, Any]:
    """Ejecuta la tarea de ECS ``migrar`` y espera su código de salida; si falla, se detiene."""
    consulta = "--query \"Stacks[0].Outputs[?OutputKey=='{}'].OutputValue\" --output text"
    cb = "aws cloudformation describe-stacks --stack-name CcComputeBase-$CC_AMBIENTE"
    return {
        **_CABECERA,
        "phases": {
            "build": {
                "commands": [
                    f"CLUSTER=$({cb} {consulta.format('NombreCluster')})",
                    f"TAREA=$({cb} {consulta.format('TareaMigrar')})",
                    f"SUBREDES=$({cb} {consulta.format('SubredesAplicacion')})",
                    f"SG=$({cb} {consulta.format('SgEcsId')})",
                    "TAREA_ARN=$(aws ecs run-task --cluster $CLUSTER --task-definition $TAREA "
                    "--launch-type FARGATE --platform-version LATEST --network-configuration "
                    '"awsvpcConfiguration={subnets=[$SUBREDES],securityGroups=[$SG],'
                    'assignPublicIp=DISABLED}" --query "tasks[0].taskArn" --output text)',
                    'echo "Migraciones en curso (registros en /cc/$CC_AMBIENTE/migrar)"',
                    "aws ecs wait tasks-stopped --cluster $CLUSTER --tasks $TAREA_ARN",
                    "CODIGO=$(aws ecs describe-tasks --cluster $CLUSTER --tasks $TAREA_ARN "
                    '--query "tasks[0].containers[0].exitCode" --output text)',
                    'if [ "$CODIGO" != "0" ]; then echo "Migración fallida (código $CODIGO)"; '
                    "exit 1; fi",
                    'echo "Migraciones aplicadas"',
                ]
            }
        },
    }


def servicios() -> dict[str, Any]:
    """``cdk deploy`` de los stacks restantes con el mismo ensamblado de la compilación."""
    return {
        **_CABECERA,
        "phases": {
            "install": _con_cdk(["docker info > /dev/null"]),
            "build": {
                "commands": [
                    "cd infra && cdk deploy $CC_STACKS_SERVICIOS --app cdk.out "
                    "--require-approval never --no-notices --ci",
                ]
            },
        },
    }
