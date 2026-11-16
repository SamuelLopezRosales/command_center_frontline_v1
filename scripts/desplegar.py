"""Despliegue replicable de un ambiente de Command Center (T-227; design.md §13.1, §13.9, §14.2).

Punto de entrada: ``scripts/desplegar.ps1 -Ambiente <nombre>``. Esta es la lógica, con un
**ejecutor inyectable** (como ``aws_guard.py``) para probarla con salidas simuladas sin tocar AWS.

Orden de una ejecución completa (cada paso se detiene ante el primer fallo):

1. Guardia de cuenta (PA-1 a PA-3, ``aws_guard``): perfil del ambiente, sesión, cuenta permitida y
   sin llaves de acceso en el entorno.
2. Verificación previa (solo lecturas): bootstrap de CDK, cuota de concurrencia de Lambda, nombres
   en conflicto, Docker ``linux/arm64``, presupuesto, herramientas y contextos obligatorios.
3. Empaquetado de las tres variantes de las Lambdas y ``npm run build`` del frontend.
4. ``cdk diff`` de todos los stacks y estimación del costo de la ventana.
5. **Aprobación**: la persona teclea una frase exacta en una consola interactiva. No hay bandera
   que la omita; sin consola interactiva el script termina con error.
6. ``cdk deploy`` del grupo Base, publicación de las imágenes ``migrar`` y ``ops`` en ECR (con una
   carpeta TEMPORAL de credenciales de Docker), tarea ``migrar``, tarea ``ops contrasenas`` y
   ``cdk deploy`` del grupo Servicios. Las contraseñas de los roles se asignan ANTES de que los
   servicios lean sus secretos (design.md §13.9, T-043).
7. Salida con los datos para el primer usuario: el COMANDO de ``bootstrap_admin`` por ECS Exec, que
   ejecuta la persona. El script nunca lo ejecuta ni ve el código de invitación.

Modos: ``--solo-revisar`` (pasos 1 a 4, sin desplegar nada), ``--solo-synth`` (solo ``cdk synth``
sin credenciales de AWS) y ``--simular`` (imprime lo que haría sin ejecutar nada).

Reglas de seguridad (no negociables): nunca acepta ni imprime credenciales; el perfil y la cuenta
salen de ``infra/config/ambientes.json``; jamás ejecuta ``destroy`` ni borrados (los hace la
persona, regla 8); cada paso de cambio ocurre tras la aprobación y tras la guardia de cuenta; no
escribe secretos a disco ni a los registros.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from infra.config import esquema  # noqa: E402
from scripts import aws_guard  # noqa: E402
from scripts import desplegar_costos as costos  # noqa: E402

RUTA_DESPLIEGUE = RAIZ / "infra" / "config" / "despliegue.json"
CALIFICADOR_BOOTSTRAP = "hnb659fds"

# Códigos de salida.
SALIDA_OK = 0
SALIDA_PREVIA = 1  # guardia o verificación previa fallida
SALIDA_USO = 2  # argumentos o contextos inválidos
SALIDA_SIN_APROBACION = 3  # la frase no coincide
SALIDA_SIN_CONSOLA = 4  # no hay consola interactiva: no se puede pedir aprobación
SALIDA_FALLO = 5  # falló un paso del despliegue

# Contextos ``-c`` que el script acepta y la forma de su valor. La llave pública de CloudFront no
# viaja por aquí: vive en ``infra/config/cloudfront-{ambiente}.pub.pem`` (infra/app.py).
_ARN = r"arn:aws[\w-]*:[\w-]+:[\w-]*:\d{0,12}:[\w:/.\-+]+"
_DOMINIO = r"[A-Za-z0-9]([A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?"
CONTEXTOS_PERMITIDOS: dict[str, str] = {
    "certificado_alb_arn": _ARN,
    "dominio_interno": _DOMINIO,
    "empresa_id_whatsapp": r"\d{1,9}",
    "dominio_origen_api": _DOMINIO,
    "certificado_origen_api_arn": _ARN,
    "zona_hospedada_id": r"Z[A-Z0-9]{5,30}",
    "repositorio_pipeline": r"[\w.\-]{1,100}/[\w.\-]{1,100}",
    "rama_pipeline": r"[\w.\-/]{1,100}",
    "conexion_codigo_arn": _ARN,
    "respaldo": r"true|false",
    "pipeline": r"false",  # este script nunca despliega el pipeline: solo se admite apagarlo
}
# Verbos de AWS que son lecturas (la prueba de ``-SoloRevisar`` los exige).
VERBOS_LECTURA = ("get-", "describe-", "list-", "head-", "wait")


class ErrorDespliegue(Exception):  # noqa: N818
    """Detiene el flujo con un mensaje seguro para mostrar (nunca incluye secretos)."""

    def __init__(self, mensaje: str, codigo: int = SALIDA_FALLO) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


@dataclass(frozen=True)
class Hallazgo:
    nivel: str  # "OK", "AVISO" o "ERROR"
    tema: str
    detalle: str = ""


# ``(código de salida, stdout, stderr)``. Los argumentos con nombre son opcionales: el ejecutor de
# ``aws_guard`` solo recibe la orden.
Ejecutor = Callable[..., tuple[int, str, str]]


def ejecutor_real(
    cmd: list[str],
    *,
    entorno: Mapping[str, str] | None = None,
    entrada: str | None = None,
    cwd: Path | None = None,
    transmitir: bool = False,
    timeout: int = 600,
) -> tuple[int, str, str]:
    """Ejecuta una orden. Con ``transmitir`` la salida va directo a la consola (despliegues)."""
    exe = shutil.which(cmd[0]) or cmd[0]
    orden = [exe, *cmd[1:]]
    try:
        if transmitir:
            proc = subprocess.run(  # noqa: S603
                orden,
                env=dict(entorno) if entorno is not None else None,
                cwd=cwd,
                input=entrada,
                text=True,
                timeout=timeout,
                check=False,
            )
            return proc.returncode, "", ""
        proc = subprocess.run(  # noqa: S603
            orden,
            env=dict(entorno) if entorno is not None else None,
            cwd=cwd,
            input=entrada,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return 127, "", f"no se encontró el programa '{cmd[0]}'"
    except subprocess.TimeoutExpired:
        return 124, "", f"tiempo agotado ejecutando '{cmd[0]}'"
    return proc.returncode, proc.stdout, proc.stderr


# ----------------------------------------------------- lectura de constantes del código
def _constante(ruta: Path, nombre: str):
    """Valor literal de una constante de módulo, leída con ``ast`` (sin importar aws_cdk)."""
    for nodo in ast.parse(ruta.read_text(encoding="utf-8")).body:
        if isinstance(nodo, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == nombre for t in nodo.targets):
                return ast.literal_eval(nodo.value)
        elif (
            isinstance(nodo, ast.AnnAssign)
            and isinstance(nodo.target, ast.Name)
            and nodo.target.id == nombre
            and nodo.value is not None
        ):
            return ast.literal_eval(nodo.value)
    raise KeyError(f"{nombre} no está en {ruta}")


def es_prod(amb: esquema.Ambiente) -> bool:
    """Igual que ``recuperacion_habilitada``: los ambientes que conservan datos."""
    return not amb.economia.permite_borrado


def bandera(valor: object, *, por_defecto: bool) -> bool:
    if valor in (None, ""):
        return por_defecto
    return str(valor).strip().lower() in ("1", "true", "si", "sí", "yes")


def grupos_de_stacks(
    amb: esquema.Ambiente, contextos: Mapping[str, str], raiz: Path = RAIZ
) -> tuple[list[str], list[str]]:
    """``(base, servicios)`` en el orden de ``infra/app.py`` y ``nombres_de_stacks()``."""
    ruta = raiz / "infra" / "stacks" / "pipeline.py"
    base = list(_constante(ruta, "STACKS_BASE"))
    servicios = list(_constante(ruta, "STACKS_SERVICIOS"))
    if es_prod(amb):
        base.insert(0, _constante(ruta, "STACK_RECUPERACION"))
    if bandera(contextos.get("respaldo"), por_defecto=True):
        servicios.append(_constante(ruta, "STACK_RESPALDO"))
    return [f"{n}-{amb.nombre}" for n in base], [f"{n}-{amb.nombre}" for n in servicios]


def concurrencia_reservada(raiz: Path = RAIZ) -> int:
    """Suma de la concurrencia reservada que declaran los stacks (workers, Lambdas y triggers)."""
    workers = raiz / "infra" / "stacks" / "workers_lambdas.py"
    auth = raiz / "infra" / "stacks" / "auth.py"
    total = 0
    for nodo in ast.parse(workers.read_text(encoding="utf-8")).body:
        if isinstance(nodo, ast.AnnAssign) and getattr(nodo.target, "id", "") == "LAMBDAS":
            for llamada in nodo.value.elts:  # type: ignore[union-attr]
                total += int(ast.literal_eval(llamada.args[5]))
    total += int(_constante(auth, "CONCURRENCIA_RESERVADA")) * len(_constante(auth, "TRIGGERS"))
    return total


def etiquetas_imagenes(raiz: Path = RAIZ) -> dict[str, str]:
    return dict(_constante(raiz / "infra" / "stacks" / "compute_base.py", "ETIQUETAS"))


def version_cli_cdk(raiz: Path = RAIZ) -> str:
    return str(_constante(raiz / "infra" / "pipeline" / "buildspecs.py", "VERSION_CLI_CDK"))


def _tupla_version(texto: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", texto)[:3])


def _corto(arg: str, limite: int = 140) -> str:
    return arg if len(arg) <= limite else arg[: limite - 3] + "..."


def validar_contextos(crudos: list[str]) -> dict[str, str]:
    """``['clave=valor', ...]`` a diccionario, solo con claves y formas permitidas."""
    resultado: dict[str, str] = {}
    for item in crudos:
        clave, separador, valor = item.partition("=")
        if not separador or clave not in CONTEXTOS_PERMITIDOS:
            raise ErrorDespliegue(
                f"contexto no permitido: '{clave}'. Permitidos: "
                + ", ".join(sorted(CONTEXTOS_PERMITIDOS)),
                SALIDA_USO,
            )
        if not re.fullmatch(CONTEXTOS_PERMITIDOS[clave], valor):
            raise ErrorDespliegue(f"valor inválido para el contexto '{clave}'", SALIDA_USO)
        resultado[clave] = valor
    return resultado


def cargar_despliegue(ruta: Path = RUTA_DESPLIEGUE) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else {}


# ------------------------------------------------------------------------------------ desplegador
class Desplegador:
    """Orquesta los pasos. Todo comando externo pasa por ``_ej`` (se registra sin secretos)."""

    def __init__(
        self,
        ambiente: str,
        *,
        modo: str = "desplegar",  # "desplegar" | "revisar" | "synth"
        raiz: Path = RAIZ,
        ruta_ambientes: Path | None = None,
        ruta_despliegue: Path | None = None,
        ruta_costos: Path | None = None,
        entorno: Mapping[str, str] | None = None,
        ejecutor: Ejecutor = ejecutor_real,
        salida: Callable[[str], None] = print,
        leer: Callable[[str], str] = input,
        interactivo: bool | None = None,
        dias: float | None = None,
        horas_servicios_dia: float = 24.0,
        contextos: Mapping[str, str] | None = None,
    ) -> None:
        self.raiz = raiz
        self.modo = modo
        self.ruta_ambientes = ruta_ambientes
        try:
            self.amb = esquema.obtener_ambiente(ambiente, ruta_ambientes)
        except esquema.ConfiguracionInvalida as exc:
            raise ErrorDespliegue(str(exc), SALIDA_USO) from exc
        despliegue = cargar_despliegue(ruta_despliegue or raiz / "infra/config/despliegue.json")
        propio = despliegue.get("ambientes", {}).get(ambiente, {})
        self.frase = propio.get("frase_aprobacion") or f"apruebo despliegue {ambiente}"
        self.version_bootstrap_min = int(despliegue.get("version_minima_bootstrap", 21))
        self.obligatorios_extra = list(propio.get("contextos_obligatorios", []))
        self.costos = costos.cargar_costos(ruta_costos or raiz / "infra/config/costos.json")
        self.entorno: dict[str, str] = dict(os.environ if entorno is None else entorno)
        self.ejecutor = ejecutor
        self.salida = salida
        self.leer = leer
        self.interactivo = (
            (sys.stdin.isatty() and sys.stdout.isatty()) if interactivo is None else interactivo
        )
        self.dias = dias
        self.horas_servicios_dia = horas_servicios_dia
        self.contextos = dict(contextos or {})
        self.registro: list[tuple[str, ...]] = []
        self.cuenta: str | None = None
        self._config_docker: Path | None = None
        self.base, self.servicios = grupos_de_stacks(self.amb, self.contextos, raiz)

    # ------------------------------------------------------------------ utilidades
    def _ej(
        self,
        cmd: list[str],
        *,
        entorno_extra: Mapping[str, str] | None = None,
        entorno_exacto: Mapping[str, str] | None = None,
        entrada: str | None = None,
        cwd: Path | None = None,
        transmitir: bool = False,
        timeout: int = 600,
        mostrar: bool = True,
    ) -> tuple[int, str, str]:
        """Registra la orden (nunca ``entrada`` ni salidas) y la pasa al ejecutor."""
        self.registro.append(tuple(cmd))
        if mostrar:
            self.salida("  $ " + " ".join(_corto(a) for a in cmd))
        if entorno_exacto is not None:
            entorno = dict(entorno_exacto)
        else:
            entorno = {**self.entorno, **(entorno_extra or {})}
        return self.ejecutor(
            cmd, entorno=entorno, entrada=entrada, cwd=cwd, transmitir=transmitir, timeout=timeout
        )

    def _aws(
        self, args: list[str], *, region: str | None = None, mostrar: bool = True
    ) -> tuple[int, object, str]:
        """Ejecuta ``aws`` con el perfil y la región del ambiente: ``(rc, json, error)``."""
        cmd = [
            "aws",
            *args,
            "--profile",
            self.amb.perfil,
            "--region",
            region or self.amb.region,
            "--output",
            "json",
        ]
        rc, salida, error = self._ej(cmd, mostrar=mostrar)
        datos: object = None
        if rc == 0 and salida.strip():
            try:
                datos = json.loads(salida)
            except ValueError:
                datos = None
        return rc, datos, error

    def _paso(self, titulo: str) -> None:
        self.salida("")
        self.salida(f"== {titulo}")

    def _config(self, nombre: str) -> Path:
        return self.raiz / nombre

    def _contexto_cdk(self) -> list[str]:
        args = ["-c", f"ambiente={self.amb.nombre}"]
        for clave in sorted(self.contextos):
            args += ["-c", f"{clave}={self.contextos[clave]}"]
        return args

    def _stack_regiones(self) -> list[str]:
        regiones = [self.amb.region]
        edge = _constante(self.raiz / "infra/stacks/edge.py", "REGION_EDGE")
        if edge not in regiones:
            regiones.append(edge)
        if es_prod(self.amb):
            rec = _constante(self.raiz / "infra/constructs/recuperacion.py", "REGION_RECUPERACION")
            if rec not in regiones:
                regiones.append(rec)
        return regiones

    # ------------------------------------------------------------------ 1. guardia
    def guardia(self) -> None:
        """PA-1 a PA-3 con ``aws_guard`` más el rechazo de cualquier credencial en el entorno."""
        sospechosas = [
            v
            for v in ("AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN", "AWS_ACCESS_KEY_ID")
            if self.entorno.get(v)
        ]
        if sospechosas:
            raise ErrorDespliegue(
                "Hay credenciales en variables de entorno (" + ", ".join(sospechosas) + "). "
                "Elimínelas: solo se usa el perfil del ambiente.",
                SALIDA_PREVIA,
            )
        r = aws_guard.verificar(
            self.amb.nombre,
            self.entorno,
            lambda cmd: self._ej(cmd),
            self.ruta_ambientes,
        )
        if not r.ok:
            raise ErrorDespliegue(f"Protocolo PA detenido ({r.codigo}): {r.mensaje}", SALIDA_PREVIA)
        self.cuenta = r.cuenta
        self.salida(f"PA-1 a PA-3 correctos. Cuenta: {r.cuenta}. Identidad: {r.arn}")

    # ------------------------------------------------------------------ 2. verificación previa
    def previa(self, *, con_aws: bool = True) -> list[Hallazgo]:
        hallazgos: list[Hallazgo] = []
        hallazgos += self._previa_herramientas()
        hallazgos += self._previa_contextos()
        hallazgos += self._previa_artefactos(bloqueante=False)
        if self.modo != "synth":
            hallazgos += self._previa_docker()
        if con_aws:
            hallazgos += self._previa_aws()
        for h in hallazgos:
            self.salida(f"  [{h.nivel:<5}] {h.tema}" + (f": {h.detalle}" if h.detalle else ""))
        return hallazgos

    def _version(self, cmd: list[str]) -> str | None:
        rc, salida, _ = self._ej(cmd, mostrar=False)
        if rc != 0:
            return None
        m = re.search(r"\d+\.\d+(?:\.\d+)?", salida)
        return m.group(0) if m else None

    def _previa_herramientas(self) -> list[Hallazgo]:
        h: list[Hallazgo] = []
        if self.entorno.get("CC_LAMBDAS_DESDE_FUENTE"):
            h.append(
                Hallazgo(
                    "ERROR",
                    "CC_LAMBDAS_DESDE_FUENTE definida",
                    "empaquetaría las Lambdas sin dependencias; quite la variable",
                )
            )
        minimo = version_cli_cdk(self.raiz)
        v = self._version(["cdk", "--version"])
        if v is None:
            h.append(Hallazgo("ERROR", "cdk", "no se encontró la CLI (npm install -g aws-cdk)"))
        elif _tupla_version(v) < _tupla_version(minimo):
            h.append(Hallazgo("ERROR", "cdk", f"versión {v}; se probó con {minimo} o superior"))
        else:
            h.append(Hallazgo("OK", "cdk", v))
        v = self._version(["node", "--version"])
        if v is None or _tupla_version(v) < (20,):
            h.append(Hallazgo("ERROR", "node", f"se requiere Node 20 o superior (hay: {v})"))
        else:
            h.append(Hallazgo("OK", "node", v))
        for programa in ("uv", "npm"):
            v = self._version([programa, "--version"])
            h.append(
                Hallazgo("OK", programa, v)
                if v
                else Hallazgo("ERROR", programa, "no se encontró en el PATH")
            )
        if self.modo != "synth":
            v = self._version(["aws", "--version"])
            if v is None or _tupla_version(v) < (2,):
                h.append(Hallazgo("ERROR", "aws", f"se requiere la CLI de AWS v2 (hay: {v})"))
            else:
                h.append(Hallazgo("OK", "aws", v))
        return h

    def contextos_obligatorios(self) -> list[str]:
        """Contextos sin los que la síntesis falla (infra/app.py y docs/ambientes.md §5.1)."""
        if not es_prod(self.amb):
            return list(self.obligatorios_extra)
        req = ["certificado_alb_arn", "dominio_interno"]
        pipeline = bandera(self.contextos.get("pipeline"), por_defecto=True)
        if pipeline:
            req.append("repositorio_pipeline")
        return req + [c for c in self.obligatorios_extra if c not in req]

    def _previa_contextos(self) -> list[Hallazgo]:
        h: list[Hallazgo] = []
        faltan = [c for c in self.contextos_obligatorios() if not self.contextos.get(c)]
        if faltan:
            h.append(
                Hallazgo(
                    "ERROR",
                    "contextos obligatorios",
                    "faltan " + ", ".join(faltan) + " (use -Contexto clave=valor)",
                )
            )
        elif self.contextos_obligatorios():
            h.append(Hallazgo("OK", "contextos obligatorios", "presentes"))
        else:
            h.append(Hallazgo("OK", "contextos obligatorios", "ninguno en este ambiente"))
        if es_prod(self.amb):
            llave = self.raiz / "infra" / "config" / f"cloudfront-{self.amb.nombre}.pub.pem"
            if not llave.is_file():
                h.append(
                    Hallazgo(
                        "ERROR",
                        "llave pública de CloudFront",
                        f"falta infra/config/cloudfront-{self.amb.nombre}.pub.pem (la pública)",
                    )
                )
            else:
                h.append(Hallazgo("OK", "llave pública de CloudFront", llave.name))
        return h

    def _rutas_artefactos(self) -> dict[str, Path]:
        r = self.raiz
        return {
            "frontend/dist (npm run build)": r / "frontend" / "dist" / "index.html",
            "build/lambdas (triggers de Cognito)": r / "build/lambdas/cognito_triggers",
            "build/lambdas_notif (notificaciones)": r / "build/lambdas_notif/cc_common",
            "build/lambdas_wa (WhatsApp)": r / "build/lambdas_wa/cc_common",
        }

    def _previa_artefactos(self, *, bloqueante: bool) -> list[Hallazgo]:
        h: list[Hallazgo] = []
        for nombre, ruta in self._rutas_artefactos().items():
            if ruta.exists():
                h.append(Hallazgo("OK", nombre, "presente"))
            elif bloqueante:
                h.append(Hallazgo("ERROR", nombre, "ausente tras el empaquetado"))
            else:
                h.append(Hallazgo("AVISO", nombre, "ausente: se construirá en el paso 3"))
        return h

    def _previa_docker(self) -> list[Hallazgo]:
        h: list[Hallazgo] = []
        rc, salida, _ = self._ej(
            ["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"], mostrar=False
        )
        if rc != 0:
            return [Hallazgo("ERROR", "Docker", "no responde: encienda Docker Desktop")]
        servidor = salida.strip()
        rc, _, _ = self._ej(["docker", "buildx", "version"], mostrar=False)
        if rc != 0:
            h.append(Hallazgo("ERROR", "Docker buildx", "no disponible"))
        rc, listado, _ = self._ej(["docker", "buildx", "ls"], mostrar=False)
        if "linux/arm64" in listado or servidor.endswith("/arm64"):
            h.append(Hallazgo("OK", "Docker linux/arm64", f"servidor {servidor}"))
        else:
            h.append(
                Hallazgo(
                    "ERROR",
                    "Docker linux/arm64",
                    "sin emulación arm64 (Fargate es ARM64). La persona la habilita: "
                    "docker run --privileged --rm tonistiigi/binfmt --install arm64",
                )
            )
        try:
            carpeta = Path(tempfile.mkdtemp(prefix="cc-docker-prueba-"))
            shutil.rmtree(carpeta, ignore_errors=True)
            h.append(Hallazgo("OK", "carpeta temporal de credenciales de Docker", "se puede crear"))
        except OSError as exc:
            h.append(Hallazgo("ERROR", "carpeta temporal de credenciales", type(exc).__name__))
        return h

    # -- lecturas de AWS
    def _previa_aws(self) -> list[Hallazgo]:
        h: list[Hallazgo] = []
        amb = self.amb
        env = amb.nombre
        existentes, estados = self._pila_existente(h)
        h += self._bootstrap()
        h += self._cuota(bool(existentes))
        h += self._conflictos(bool(existentes))
        h += self._presupuesto()
        # Informar al final qué stacks ya existen.
        if existentes:
            h.append(
                Hallazgo(
                    "AVISO",
                    f"stacks de '{env}' existentes",
                    f"{len(existentes)} ya desplegados: se tratará como actualización",
                )
            )
        del estados
        return h

    def _pila_existente(self, h: list[Hallazgo]) -> tuple[set[str], dict[str, str]]:
        malos = (
            "ROLLBACK_COMPLETE",
            "DELETE_FAILED",
            "ROLLBACK_FAILED",
            "UPDATE_ROLLBACK_FAILED",
            "CREATE_FAILED",
            "REVIEW_IN_PROGRESS",
        )
        estados_filtro = [
            "CREATE_IN_PROGRESS",
            "CREATE_FAILED",
            "CREATE_COMPLETE",
            "ROLLBACK_IN_PROGRESS",
            "ROLLBACK_FAILED",
            "ROLLBACK_COMPLETE",
            "DELETE_IN_PROGRESS",
            "DELETE_FAILED",
            "UPDATE_IN_PROGRESS",
            "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
            "UPDATE_COMPLETE",
            "UPDATE_FAILED",
            "UPDATE_ROLLBACK_IN_PROGRESS",
            "UPDATE_ROLLBACK_FAILED",
            "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS",
            "UPDATE_ROLLBACK_COMPLETE",
            "REVIEW_IN_PROGRESS",
        ]
        sufijo = f"-{self.amb.nombre}"
        estados: dict[str, str] = {}
        for region in self._stack_regiones():
            rc, datos, err = self._aws(
                ["cloudformation", "list-stacks", "--stack-status-filter", *estados_filtro],
                region=region,
            )
            if rc != 0 or not isinstance(datos, dict):
                h.append(Hallazgo("ERROR", f"stacks en {region}", _primera_linea(err)))
                continue
            for s in datos.get("StackSummaries", []):
                nombre = s.get("StackName", "")
                if nombre.startswith("Cc") and nombre.endswith(sufijo):
                    estados[nombre] = s.get("StackStatus", "")
        for nombre, estado in sorted(estados.items()):
            if estado in malos or estado.endswith("_IN_PROGRESS"):
                h.append(
                    Hallazgo(
                        "ERROR",
                        f"stack {nombre}",
                        f"estado {estado}: la persona debe resolverlo (el script no borra nada)",
                    )
                )
        return set(estados), estados

    def _bootstrap(self) -> list[Hallazgo]:
        h: list[Hallazgo] = []
        for region in self._stack_regiones():
            rc, datos, err = self._aws(
                ["cloudformation", "describe-stacks", "--stack-name", "CDKToolkit"], region=region
            )
            if rc != 0 or not isinstance(datos, dict) or not datos.get("Stacks"):
                h.append(
                    Hallazgo(
                        "ERROR",
                        f"bootstrap de CDK en {region}",
                        "CDKToolkit ausente. La persona lo crea: cdk bootstrap "
                        f"aws://{self.cuenta or 'CUENTA'}/{region} --profile {self.amb.perfil} "
                        f"({_primera_linea(err)})",
                    )
                )
                continue
            stack = datos["Stacks"][0]
            estado = stack.get("StackStatus", "")
            version = 0
            for o in stack.get("Outputs", []):
                if o.get("OutputKey") == "BootstrapVersion":
                    version = int(o.get("OutputValue") or 0)
            if not estado.endswith("_COMPLETE") or "ROLLBACK" in estado or "DELETE" in estado:
                h.append(Hallazgo("ERROR", f"bootstrap de CDK en {region}", f"estado {estado}"))
            elif version < self.version_bootstrap_min:
                h.append(
                    Hallazgo(
                        "ERROR",
                        f"bootstrap de CDK en {region}",
                        f"versión {version}; se requiere {self.version_bootstrap_min} o superior. "
                        "La persona lo actualiza con cdk bootstrap",
                    )
                )
            else:
                h.append(Hallazgo("OK", f"bootstrap de CDK en {region}", f"versión {version}"))
        return h

    def _cuota(self, ya_desplegado: bool) -> list[Hallazgo]:
        rc, datos, err = self._aws(["lambda", "get-account-settings"])
        if rc != 0 or not isinstance(datos, dict):
            return [Hallazgo("ERROR", "cuota de concurrencia de Lambda", _primera_linea(err))]
        limite = int(datos["AccountLimit"]["ConcurrentExecutions"])
        libre = int(datos["AccountLimit"]["UnreservedConcurrentExecutions"])
        if not self.amb.economia.reservar_concurrencia:
            return [
                Hallazgo(
                    "OK",
                    "cuota de concurrencia de Lambda",
                    f"cuota {limite}: el ambiente no reserva concurrencia, no se exige margen. Las "
                    f"funciones comparten esas {limite} ejecuciones; si hay estrangulamiento, "
                    "solicite el aumento (L-B99A9384)",
                )
            ]
        reservada = concurrencia_reservada(self.raiz)
        # AWS exige dejar al menos 100 ejecuciones sin reservar.
        necesaria = 100 if ya_desplegado else reservada + 100
        detalle = (
            f"cuota {limite}, sin reservar {libre}; el stack reserva {reservada} y AWS exige dejar "
            f"100 sin reservar (se necesitan {necesaria} libres)"
        )
        if libre >= necesaria:
            return [Hallazgo("OK", "cuota de concurrencia de Lambda", detalle)]
        return [
            Hallazgo(
                "ERROR",
                "cuota de concurrencia de Lambda",
                detalle + ". Solicite aumento de 'Concurrent executions' (L-B99A9384) en "
                "Service Quotas y espere su aprobación",
            )
        ]

    def _conflictos(self, ya_desplegado: bool) -> list[Hallazgo]:
        """Nombres que bloquearían la creación. Los secretos pendientes de borrado siempre; el
        resto solo si el ambiente aún no tiene stacks (si los tiene, esos recursos son suyos)."""
        h: list[Hallazgo] = []
        env = self.amb.nombre
        cuenta = self.cuenta or ""
        rc, datos, err = self._aws(
            [
                "secretsmanager",
                "list-secrets",
                "--include-planned-deletion",
                "--filters",
                f"Key=name,Values=cc/{env}/",
            ]
        )
        if rc != 0 or not isinstance(datos, dict):
            h.append(Hallazgo("ERROR", "secretos pendientes de borrado", _primera_linea(err)))
        else:
            pendientes = [
                s["Name"] for s in datos.get("SecretList", []) if s.get("DeletedDate") is not None
            ]
            if pendientes:
                h.append(
                    Hallazgo(
                        "ERROR",
                        "secretos pendientes de borrado",
                        ", ".join(pendientes[:6]) + f" ({len(pendientes)}): el nombre no se puede "
                        "reutilizar hasta que termine la recuperación; la persona decide si los "
                        "borra de forma forzada",
                    )
                )
            else:
                h.append(Hallazgo("OK", "secretos pendientes de borrado", "ninguno"))
        # Recursos huérfanos: solo importan si el ambiente no tiene stacks.
        consultas: list[tuple[str, list[str], str, Callable[[dict], list[str]], str]] = [
            (
                "alias de KMS",
                ["kms", "list-aliases"],
                f"alias/cc-{env}-",
                lambda d: [a["AliasName"] for a in d.get("Aliases", [])],
                "",
            ),
            (
                "grupos de logs /cc",
                ["logs", "describe-log-groups", "--log-group-name-prefix", f"/cc/{env}/"],
                f"/cc/{env}/",
                lambda d: [g["logGroupName"] for g in d.get("logGroups", [])],
                "",
            ),
            (
                "grupos de logs de Lambda",
                [
                    "logs",
                    "describe-log-groups",
                    "--log-group-name-prefix",
                    f"/aws/lambda/cc-{env}-",
                ],
                f"/aws/lambda/cc-{env}-",
                lambda d: [g["logGroupName"] for g in d.get("logGroups", [])],
                "",
            ),
            (
                "buckets retenidos",
                ["s3api", "list-buckets"],
                f"cc-{env}-{cuenta}-",
                lambda d: [b["Name"] for b in d.get("Buckets", [])],
                "",
            ),
            (
                "repositorios de ECR",
                ["ecr", "describe-repositories"],
                f"cc-{env}/",
                lambda d: [r["repositoryName"] for r in d.get("repositories", [])],
                "",
            ),
            (
                "colas de SQS",
                ["sqs", "list-queues", "--queue-name-prefix", f"cc-{env}-"],
                f"cc-{env}-",
                lambda d: [u.rsplit("/", 1)[-1] for u in d.get("QueueUrls", [])],
                "",
            ),
        ]
        for tema, args, prefijo, extraer, _ in consultas:
            rc, datos, err = self._aws(args)
            if rc != 0 or not isinstance(datos, dict):
                if rc == 0 and datos is None:
                    datos = {}  # una lista vacía puede no imprimir nada
                else:
                    h.append(Hallazgo("ERROR", tema, _primera_linea(err)))
                    continue
            nombres = [n for n in extraer(datos) if n.startswith(prefijo)]
            if not nombres:
                h.append(Hallazgo("OK", tema, "sin conflictos"))
            elif ya_desplegado:
                h.append(Hallazgo("OK", tema, f"{len(nombres)} existentes del propio ambiente"))
            else:
                h.append(
                    Hallazgo(
                        "ERROR",
                        tema,
                        f"{len(nombres)} sin stack que los posea, p. ej. {nombres[0]}: la "
                        "creación fallaría por nombre repetido; la persona los revisa o borra",
                    )
                )
        return h

    def _presupuesto(self) -> list[Hallazgo]:
        definicion = json.loads(
            (self.raiz / "infra" / "budget" / "presupuesto.json").read_text(encoding="utf-8")
        )
        nombre = definicion["nombre"].format(ambiente=self.amb.nombre)
        rc, _, err = self._aws(
            [
                "budgets",
                "describe-budget",
                "--account-id",
                self.cuenta or "",
                "--budget-name",
                nombre,
            ],
            region="us-east-1",
        )
        if rc == 0:
            return [Hallazgo("OK", "presupuesto", f"{nombre} existe")]
        return [
            Hallazgo(
                "ERROR",
                "presupuesto",
                f"'{nombre}' no existe ({_primera_linea(err)}). Créelo con "
                f".\\scripts\\crear_presupuesto.ps1 -Ambiente {self.amb.nombre} (requiere "
                "aprobación aparte)",
            )
        ]

    # ------------------------------------------------------------------ 3. empaquetado
    def empaquetar(self) -> None:
        self._paso("3. Empaquetado de Lambdas y build del frontend (local, sin AWS)")
        script = str(self.raiz / "scripts" / "empaquetar_lambdas.py")
        for variante in ([], ["--notificaciones"], ["--whatsapp"]):
            rc, _, err = self._ej(
                [sys.executable, script, *variante], cwd=self.raiz, timeout=1800, mostrar=True
            )
            if rc != 0:
                raise ErrorDespliegue(f"falló el empaquetado de las Lambdas {variante or ''}")
        frontend = self.raiz / "frontend"
        if not (frontend / "node_modules").is_dir():
            rc, _, _ = self._ej(["npm", "ci"], cwd=frontend, transmitir=True, timeout=1800)
            if rc != 0:
                raise ErrorDespliegue("falló 'npm ci' en frontend/")
        rc, _, _ = self._ej(["npm", "run", "build"], cwd=frontend, transmitir=True, timeout=1800)
        if rc != 0:
            raise ErrorDespliegue("falló 'npm run build' en frontend/")
        faltan = [h for h in self._previa_artefactos(bloqueante=True) if h.nivel == "ERROR"]
        if faltan:
            raise ErrorDespliegue("faltan artefactos: " + ", ".join(h.tema for h in faltan))
        self.salida("Artefactos presentes: frontend/dist y las tres variantes de las Lambdas.")

    # ------------------------------------------------------------------ 4. synth / diff
    def synth_aislado(self) -> None:
        """``cdk synth`` sin credenciales de AWS (como ``verificar_synth.py``)."""
        self._paso("4. cdk synth sin credenciales de AWS")
        salida_cdk = Path(tempfile.mkdtemp(prefix="cc-synth-"))
        fd, ruta_vacio = tempfile.mkstemp(prefix="cc-aws-vacio-")
        os.close(fd)
        vacio = Path(ruta_vacio)
        try:
            entorno = {k: v for k, v in self.entorno.items() if not k.startswith("AWS_")}
            entorno.update(
                {
                    "AWS_CONFIG_FILE": str(vacio),
                    "AWS_SHARED_CREDENTIALS_FILE": str(vacio),
                    "AWS_EC2_METADATA_DISABLED": "true",
                    "CDK_DEFAULT_ACCOUNT": self.amb.cuentas_permitidas[0],
                    "CDK_DEFAULT_REGION": self.amb.region,
                    "PYTHONIOENCODING": "utf-8",
                }
            )
            rc, _, _ = self._ej(
                [
                    "cdk",
                    "synth",
                    *self._contexto_cdk(),
                    "--no-notices",
                    "--quiet",
                    "--output",
                    str(salida_cdk),
                ],
                entorno_exacto=entorno,
                cwd=self.raiz / "infra",
                transmitir=True,
                timeout=1800,
            )
        finally:
            shutil.rmtree(salida_cdk, ignore_errors=True)
            vacio.unlink(missing_ok=True)
        if rc != 0:
            raise ErrorDespliegue("falló 'cdk synth'")
        self.salida("cdk synth correcto (incluye cdk-nag). No se llamó a AWS.")

    def diff(self) -> None:
        self._paso("4. cdk diff de todos los stacks (lectura)")
        self.salida(
            "AVISO: cdk diff publica las plantillas en el bucket de assets del CDKToolkit "
            "(compartido). Es lo único que escribe en la cuenta; no crea recursos del proyecto."
        )
        rc, _, _ = self._ej(
            [
                "cdk",
                "diff",
                *self.base,
                *self.servicios,
                *self._contexto_cdk(),
                "--profile",
                self.amb.perfil,
                "--no-notices",
            ],
            cwd=self.raiz / "infra",
            transmitir=True,
            timeout=1800,
        )
        if rc != 0:
            raise ErrorDespliegue("falló 'cdk diff'")

    # ------------------------------------------------------------------ costo
    def mostrar_costo(self) -> costos.Estimacion:
        dias = (
            self.dias if self.dias else float(self.costos["supuestos"]["ventana_dias_por_defecto"])
        )
        est = costos.estimar(
            self.amb, self.costos, dias=dias, horas_servicios_dia=self.horas_servicios_dia
        )
        self._paso("Costo estimado de la ventana")
        for linea in costos.formatear(est, self.costos):
            self.salida(linea)
        # Las alternativas se muestran siempre: sirven para decidir el alcance.
        for linea in costos.formatear_alternativas(self.amb, self.costos, dias):
            self.salida(linea)
        return est

    # ------------------------------------------------------------------ 5. aprobación
    def aprobar(self) -> None:
        self._paso("5. Aprobación")
        if not self.interactivo:
            raise ErrorDespliegue(
                "No hay consola interactiva: el despliegue exige que una persona teclee la frase de"
                " "
                "aprobación. No existe bandera que la omita.",
                SALIDA_SIN_CONSOLA,
            )
        self.salida(
            f"Revise el diff y el costo. Para desplegar en '{self.amb.nombre}' (cuenta "
            f"{self.cuenta}) escriba exactamente la frase de aprobación."
        )
        try:
            respuesta = self.leer(f"Frase de aprobación ({self.frase}): ")
        except (EOFError, KeyboardInterrupt):
            respuesta = ""
        if respuesta.strip() != self.frase:
            raise ErrorDespliegue(
                "La frase no coincide: no se despliega nada.", SALIDA_SIN_APROBACION
            )
        self.salida("Aprobación recibida.")

    # ------------------------------------------------------------------ 6. despliegue
    def _deploy(self, titulo: str, stacks: list[str]) -> None:
        self._paso(titulo)
        rc, _, _ = self._ej(
            [
                "cdk",
                "deploy",
                *stacks,
                *self._contexto_cdk(),
                "--profile",
                self.amb.perfil,
                "--require-approval",
                "never",  # la persona ya aprobó el diff con la frase exacta
                "--no-notices",
            ],
            entorno_extra={"DOCKER_CONFIG": str(self._config_docker)}
            if self._config_docker
            else None,
            cwd=self.raiz / "infra",
            transmitir=True,
            timeout=3600,
        )
        if rc != 0:
            raise ErrorDespliegue(
                f"falló 'cdk deploy' ({titulo}). Lo ya creado queda como está: la persona decide; "
                "el script no revierte ni borra. Repetirlo es seguro."
            )

    def _salidas(self, stack: str) -> dict[str, str]:
        rc, datos, err = self._aws(["cloudformation", "describe-stacks", "--stack-name", stack])
        if rc != 0 or not isinstance(datos, dict) or not datos.get("Stacks"):
            raise ErrorDespliegue(
                f"no se pudieron leer las salidas de {stack}: {_primera_linea(err)}"
            )
        return {o["OutputKey"]: o["OutputValue"] for o in datos["Stacks"][0].get("Outputs", [])}

    def _preparar_docker(self) -> Path:
        """Carpeta TEMPORAL de configuración de Docker: el almacén de credenciales de Windows
        rechaza el token de ECR (lección de T-046). Solo copia metadatos no secretos."""
        carpeta = Path(tempfile.mkdtemp(prefix="cc-docker-"))
        config: dict[str, object] = {}
        origen = Path(self.entorno.get("DOCKER_CONFIG") or Path.home() / ".docker")
        try:
            previo = json.loads((origen / "config.json").read_text(encoding="utf-8"))
            for clave in ("cliPluginsExtraDirs", "currentContext"):
                if clave in previo:
                    config[clave] = previo[clave]
        except (OSError, ValueError):
            pass
        if (origen / "contexts").is_dir():
            shutil.copytree(origen / "contexts", carpeta / "contexts", dirs_exist_ok=True)
        (carpeta / "config.json").write_text(json.dumps(config), encoding="utf-8")
        self._config_docker = carpeta
        return carpeta

    def _limpiar(self) -> None:
        if self._config_docker is not None:
            shutil.rmtree(self._config_docker, ignore_errors=True)
            self._config_docker = None

    def publicar_imagenes(self) -> None:
        self._paso("6b. Imágenes 'migrar' y 'ops' en ECR (linux/arm64)")
        env = self.amb.nombre
        registro = f"{self.cuenta}.dkr.ecr.{self.amb.region}.amazonaws.com"
        extra = {"DOCKER_CONFIG": str(self._config_docker)}
        rc, token, _ = self._ej(
            [
                "aws",
                "ecr",
                "get-login-password",
                "--profile",
                self.amb.perfil,
                "--region",
                self.amb.region,
            ]
        )
        if rc != 0 or not token.strip():
            raise ErrorDespliegue("no se obtuvo el token de ECR")
        rc, _, _ = self._ej(
            ["docker", "login", "--username", "AWS", "--password-stdin", registro],
            entorno_extra=extra,
            entrada=token.strip(),
        )
        del token  # nunca se imprime ni se guarda
        if rc != 0:
            raise ErrorDespliegue("falló 'docker login' en ECR")
        for nombre, etiqueta in etiquetas_imagenes(self.raiz).items():
            repo = f"cc-{env}/{nombre}"
            ref = f"{registro}/{repo}:{etiqueta}"
            rc, _, err = self._aws(
                [
                    "ecr",
                    "describe-images",
                    "--repository-name",
                    repo,
                    "--image-ids",
                    f"imageTag={etiqueta}",
                ]
            )
            if rc == 0:
                self.salida(
                    f"{repo}:{etiqueta} ya existe (los repositorios son inmutables): se omite"
                )
                continue
            if "ImageNotFoundException" not in err:
                raise ErrorDespliegue(f"no se pudo consultar {repo}: {_primera_linea(err)}")
            rc, _, _ = self._ej(
                [
                    "docker",
                    "buildx",
                    "build",
                    "--platform",
                    "linux/arm64",
                    "--load",
                    "-f",
                    f"infra/docker/{nombre}/Dockerfile",
                    "-t",
                    ref,
                    ".",
                ],
                entorno_extra=extra,
                cwd=self.raiz,
                transmitir=True,
                timeout=3600,
            )
            if rc != 0:
                raise ErrorDespliegue(f"falló la construcción de la imagen {nombre}")
            rc, _, _ = self._ej(
                ["docker", "push", ref],
                entorno_extra=extra,
                cwd=self.raiz,
                transmitir=True,
                timeout=3600,
            )
            if rc != 0:
                raise ErrorDespliegue(f"falló la publicación de la imagen {nombre}")

    def correr_tarea(
        self, titulo: str, clave_tarea: str, contenedor: str, sobrescribir: dict | None = None
    ) -> None:
        """``ecs run-task`` de ``migrar`` u ``ops``; espera y exige código de salida 0."""
        self._paso(titulo)
        env = self.amb.nombre
        salidas = self._salidas(f"CcComputeBase-{env}")
        try:
            cluster = salidas["NombreCluster"]
            tarea = salidas[clave_tarea]
            subredes = salidas["SubredesAplicacion"]
            sg = salidas["SgEcsId"]
        except KeyError as exc:
            raise ErrorDespliegue(f"falta la salida {exc} en CcComputeBase-{env}") from exc
        orden = [
            "ecs",
            "run-task",
            "--cluster",
            cluster,
            "--task-definition",
            tarea,
            "--launch-type",
            "FARGATE",
            "--platform-version",
            "LATEST",
            "--network-configuration",
            f"awsvpcConfiguration={{subnets=[{subredes}],securityGroups=[{sg}],"
            "assignPublicIp=DISABLED}",
        ]
        if sobrescribir:
            orden += ["--overrides", json.dumps(sobrescribir, separators=(",", ":"))]
        rc, datos, err = self._aws(orden)
        tareas = datos.get("tasks") if isinstance(datos, dict) else None
        if rc != 0 or not tareas:
            motivo = ""
            if isinstance(datos, dict) and datos.get("failures"):
                motivo = str(datos["failures"][0].get("reason", ""))
            raise ErrorDespliegue(
                f"no se pudo iniciar la tarea {tarea}: {motivo or _primera_linea(err)}"
            )
        arn = tareas[0]["taskArn"]
        self.salida(f"Tarea en curso (registros en /cc/{env}/{contenedor}).")
        detenida = False
        for _ in range(3):  # cada espera de AWS dura hasta 10 minutos
            rc, _, _ = self._aws(
                ["ecs", "wait", "tasks-stopped", "--cluster", cluster, "--tasks", arn]
            )
            if rc == 0:
                detenida = True
                break
        if not detenida:
            raise ErrorDespliegue(
                f"la tarea {tarea} no terminó a tiempo; revise ECS (no se detiene sola)"
            )
        rc, datos, err = self._aws(["ecs", "describe-tasks", "--cluster", cluster, "--tasks", arn])
        codigo = None
        razon = ""
        if isinstance(datos, dict) and datos.get("tasks"):
            razon = str(datos["tasks"][0].get("stoppedReason", ""))
            for c in datos["tasks"][0].get("containers", []):
                if c.get("name") == contenedor:
                    codigo = c.get("exitCode")
        if codigo != 0:
            raise ErrorDespliegue(
                f"la tarea {contenedor} terminó con código {codigo} ({razon[:120]}). "
                f"Revise el grupo de logs /cc/{env}/{contenedor}"
            )
        self.salida(f"Tarea {contenedor}: código de salida 0.")

    # ------------------------------------------------------------------ 7. datos finales
    def datos_primer_usuario(self) -> list[str]:
        env = self.amb.nombre
        perfil, region = self.amb.perfil, self.amb.region
        base = self._salidas(f"CcComputeBase-{env}")
        lineas = ["", "== 7. Datos para el primer usuario (los ejecuta LA PERSONA)"]
        try:
            auth = self._salidas(f"CcAuth-{env}")
            lineas.append(
                f"Cognito: UserPoolId={auth.get('UserPoolId', '?')}  "
                f"ClienteSpaId={auth.get('ClienteSpaId', '?')}"
            )
            front = self._salidas(f"CcFrontend-{env}")
            lineas.append(f"SPA: {front.get('UrlSpa', '?')}")
        except ErrorDespliegue:
            lineas.append("(no se pudieron leer las salidas de CcAuth o CcFrontend)")
        cluster = base["NombreCluster"]
        red = (
            f"awsvpcConfiguration={{subnets=[{base['SubredesAplicacion']}],"
            f"securityGroups=[{base['SgEcsId']}],assignPublicIp=DISABLED}}"
        )
        comun = f"--profile {perfil} --region {region}"
        lineas += [
            "El código de invitación lo ve SOLO la persona, en su consola: este script no lo",
            "ejecuta, no lo registra y no lo ve. Requiere el plugin session-manager-plugin.",
            "1) Iniciar la tarea ops (en espera) con ECS Exec:",
            f"   aws ecs run-task --cluster {cluster} --task-definition {base['TareaOps']} "
            f'--launch-type FARGATE --enable-execute-command --network-configuration "{red}" '
            f'--query "tasks[0].taskArn" --output text {comun}',
            "2) Esperar a que esté en ejecución (use el ARN del paso 1):",
            f"   aws ecs wait tasks-running --cluster {cluster} --tasks <ARN> {comun}",
            "3) Crear la empresa y la primera invitación (el código se muestra una sola vez):",
            f"   aws ecs execute-command --cluster {cluster} --task <ARN> --container ops "
            f"--interactive --command \"./ops.sh bootstrap --razon-social 'NOMBRE DE LA EMPRESA'\" "
            f"{comun}",
            "4) Detener la tarea ops al terminar (la persona):",
            f"   aws ecs stop-task --cluster {cluster} --task <ARN> {comun}",
            "5) Si usará WhatsApp: anote el id de la empresa y vuelva a ejecutar este script con",
            "   -Contexto empresa_id_whatsapp=<id> (las migraciones son idempotentes).",
            "Pasos manuales: verificar el correo de SES; en prod, cargar los secretos de",
            "Meta y la llave privada de CloudFront (docs/despliegue.md).",
        ]
        return lineas

    # ------------------------------------------------------------------ plan (simulación)
    def plan(self) -> list[str]:
        """Lo que haría el script, sin ejecutar nada (``--simular`` / ``-WhatIf``)."""
        env, perfil = self.amb.nombre, self.amb.perfil
        ctx = " ".join(self._contexto_cdk())
        lineas = [
            f"SIMULACIÓN: no se ejecuta ningún comando. Ambiente '{env}', perfil '{perfil}', "
            f"cuenta permitida {', '.join(self.amb.cuentas_permitidas)}, región {self.amb.region}.",
            f"Modo: {self.modo}. Frase de aprobación (solo modo desplegar): '{self.frase}'.",
            "1. Guardia PA-1 a PA-3: aws sts get-caller-identity (lectura).",
            "2. Verificación previa (lecturas): cdk/node/uv/npm/aws --version; docker version, "
            "buildx ls; cloudformation list-stacks y describe-stacks CDKToolkit; "
            "lambda get-account-settings; secretsmanager list-secrets; kms list-aliases; "
            "logs describe-log-groups; s3api list-buckets; ecr describe-repositories; "
            "sqs list-queues; budgets describe-budget.",
            "3. Empaquetado local: empaquetar_lambdas.py (normal, --notificaciones, --whatsapp) y "
            "npm run build en frontend/.",
            f"4. cdk diff {' '.join(self.base + self.servicios)} {ctx} --profile {perfil}",
        ]
        if self.modo == "synth":
            lineas = [
                lineas[0],
                "Modo -SoloSynth: sin guardia ni lecturas de AWS.",
                "Verificación previa local (herramientas, contextos, artefactos).",
                lineas[4 - 1],
                f"cdk synth {ctx} --output <carpeta temporal> (sin credenciales de AWS)",
            ]
        elif self.modo == "desplegar":
            lineas += [
                "5. Aprobación: pide teclear la frase exacta en consola interactiva.",
                f"6a. Guardia de nuevo y cdk deploy {' '.join(self.base)} {ctx}",
                "6b. Imágenes: docker login con carpeta TEMPORAL de credenciales, buildx "
                "linux/arm64 y push de migrar y ops (si la etiqueta no existe).",
                "6c. ecs run-task migrar (espera y exige código 0).",
                "6d. ecs run-task ops con ./ops.sh contrasenas (exige código 0).",
                f"6e. Guardia de nuevo y cdk deploy {' '.join(self.servicios)} {ctx}",
                "7. Imprime los comandos de ECS Exec de bootstrap_admin (los ejecuta la persona).",
            ]
        else:
            lineas.append("(-SoloRevisar termina aquí: no se despliega nada.)")
        return lineas

    # ------------------------------------------------------------------ flujo principal
    def ejecutar(self) -> int:
        try:
            return self._flujo()
        except ErrorDespliegue as exc:
            self.salida("")
            self.salida(f"DETENIDO: {exc}")
            return exc.codigo
        finally:
            self._limpiar()

    def _flujo(self) -> int:
        self.salida(
            f"Despliegue de '{self.amb.nombre}' ({self.modo}). Perfil {self.amb.perfil}, región "
            f"{self.amb.region}."
        )
        solo_local = self.modo == "synth"
        if not solo_local:
            self._paso("1. Guardia de cuenta (PA-1 a PA-3)")
            self.guardia()
        self._paso(
            "2. Verificación previa" + (" (solo local)" if solo_local else " (solo lecturas)")
        )
        hallazgos = self.previa(con_aws=not solo_local)
        errores = [h for h in hallazgos if h.nivel == "ERROR"]
        if errores:
            codigo = (
                SALIDA_USO
                if any(h.tema == "contextos obligatorios" for h in errores) and len(errores) == 1
                else SALIDA_PREVIA
            )
            raise ErrorDespliegue(
                f"la verificación previa encontró {len(errores)} problema(s); corríjalos antes de "
                "continuar. No se cambió nada.",
                codigo,
            )
        self.empaquetar()
        if solo_local:
            self.synth_aislado()
            self.mostrar_costo()
            self.salida("")
            self.salida("Listo (-SoloSynth): solo se sintetizó; no se llamó a AWS.")
            return SALIDA_OK
        self.diff()
        self.mostrar_costo()
        if self.modo == "revisar":
            self.salida("")
            self.salida("Revisión terminada (-SoloRevisar): no se desplegó nada.")
            return SALIDA_OK
        self.aprobar()
        self._preparar_docker()
        self.guardia()
        self._deploy("6a. cdk deploy: grupo Base", self.base)
        self.guardia()
        self.publicar_imagenes()
        self.guardia()
        self.correr_tarea("6c. Migraciones (tarea migrar)", "TareaMigrar", "migrar")
        self.guardia()
        self.correr_tarea(
            "6d. Contraseñas de los roles (tarea ops: contrasenas)",
            "TareaOps",
            "ops",
            {"containerOverrides": [{"name": "ops", "command": ["./ops.sh", "contrasenas"]}]},
        )
        self.guardia()
        self._deploy("6e. cdk deploy: grupo Servicios", self.servicios)
        for linea in self.datos_primer_usuario():
            self.salida(linea)
        self.salida("")
        self.salida(
            "Despliegue terminado. Destruir el ambiente lo hace la persona (docs/despliegue.md)."
        )
        return SALIDA_OK


def _primera_linea(texto: str) -> str:
    for linea in (texto or "").splitlines():
        if linea.strip():
            return linea.strip()[:200]
    return "sin detalle"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Despliegue replicable de Command Center (T-227)")
    p.add_argument("--ambiente", required=True)
    p.add_argument("--solo-revisar", action="store_true", help="guardia, previa y cdk diff")
    p.add_argument("--solo-synth", action="store_true", help="solo cdk synth, sin credenciales")
    p.add_argument("--simular", action="store_true", help="imprime lo que haría; no ejecuta nada")
    p.add_argument("--dias", type=float, default=None, help="días de la ventana (costo)")
    p.add_argument("--horas-servicios-por-dia", type=float, default=24.0)
    p.add_argument("--contexto", action="append", default=[], metavar="CLAVE=VALOR")
    args = p.parse_args(argv)
    if args.solo_revisar and args.solo_synth:
        p.error("--solo-revisar y --solo-synth son excluyentes")
    modo = "revisar" if args.solo_revisar else "synth" if args.solo_synth else "desplegar"
    try:
        contextos = validar_contextos(args.contexto)
        desp = Desplegador(
            args.ambiente,
            modo=modo,
            dias=args.dias,
            horas_servicios_dia=args.horas_servicios_por_dia,
            contextos=contextos,
        )
    except ErrorDespliegue as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.codigo
    if args.simular:
        for linea in desp.plan():
            print(linea)
        desp.mostrar_costo()
        return SALIDA_OK
    return desp.ejecutar()


if __name__ == "__main__":
    sys.exit(main())
