"""Orquestador del stack local (docs/local.md). Se usa desde ``scripts/local.ps1``.

    up                 levanta todo (idempotente): contenedores, migraciones, LocalStack, datos de
                       ejemplo, servicios, workers, pasarela y SPA
    down [--borrar]    detiene los procesos (con --borrar apaga los contenedores y borra los datos)
    estado             qué corre y qué responde
    logs <nombre> [-n N]
    reiniciar-datos    borra base y LocalStack y vuelve a levantar con datos de ejemplo

Todo es SOLO de desarrollo: nada llega a AWS (``AWS_ENDPOINT_URL`` apunta a LocalStack).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import time

from scripts.local import constantes as c

PY = sys.executable
SERVICIOS_API = ("dashboard", "colaboradores", "campos", "constancias", "whatsapp")
ROL_DE = {
    "dashboard": "svc_dashboard",
    "colaboradores": "svc_colaboradores",
    "campos": "svc_campos",
    "constancias": "svc_constancias",
    "whatsapp": "svc_whatsapp",
}
# campos y colaboradores los consulta el contenedor del worker de PDF (host.docker.internal), por
# lo que escuchan en todas las interfaces; el resto solo en 127.0.0.1.
ESCUCHA_EXTERNA = frozenset({"campos", "colaboradores"})


# ---------------------------------------------------------------- utilidades


def _ejecutar(argv: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=c.RAIZ, check=False, **kw)  # noqa: S603


def _docker() -> str:
    ruta = shutil.which("docker")
    if not ruta:
        raise SystemExit("No se encontró docker en el PATH. Inicie Docker Desktop.")
    return ruta


def proceso_vivo(pid: int) -> bool:
    if sys.platform == "win32":
        r = subprocess.run(  # noqa: S603
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
        return f'"{pid}"' in r.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _matar(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(  # noqa: S603
            ["taskkill", "/PID", str(pid), "/T", "/F"],  # noqa: S607
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(pid, 15)
        except OSError:
            pass


def _leer_pids() -> dict[str, int]:
    if c.ARCHIVO_PIDS.exists():
        return json.loads(c.ARCHIVO_PIDS.read_text(encoding="utf-8"))
    return {}


def _guardar_pids(pids: dict[str, int]) -> None:
    c.LOCAL.mkdir(parents=True, exist_ok=True)
    c.ARCHIVO_PIDS.write_text(json.dumps(pids, indent=2), encoding="utf-8")


def _lanzar(nombre: str, argv: list[str], env: dict[str, str]) -> None:
    """Arranca un proceso desacoplado de esta consola, con su registro en ``.local/logs``."""
    pids = _leer_pids()
    if nombre in pids and proceso_vivo(pids[nombre]):
        return
    c.LOGS.mkdir(parents=True, exist_ok=True)
    registro = (c.LOGS / f"{nombre}.log").open("wb")
    opciones: dict = {}
    if sys.platform == "win32":
        opciones["creationflags"] = 0x00000200 | 0x08000000  # grupo nuevo + sin ventana
    else:
        opciones["start_new_session"] = True
    p = subprocess.Popen(  # noqa: S603
        argv,
        cwd=c.RAIZ,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=registro,
        stderr=subprocess.STDOUT,
        **opciones,
    )
    pids[nombre] = p.pid
    _guardar_pids(pids)
    print(f"  iniciado {nombre} (pid {p.pid})")


# ---------------------------------------------------------------- entorno de los procesos


def _url(servicio: str, host: str = "127.0.0.1") -> str:
    return f"http://{host}:{c.PUERTOS_SERVICIOS[servicio]}"


def _base_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AWS_", "CC_"))}
    rutas = [str(c.RAIZ), str(c.RAIZ / "services" / "shared")] + [
        str(c.RAIZ / "services" / s) for s in SERVICIOS_API
    ]
    env.update(
        PYTHONPATH=os.pathsep.join(rutas),
        PYTHONIOENCODING="utf-8",
        PYTHONUNBUFFERED="1",
        CC_AMBIENTE="local",
        CC_REGION=c.REGION,
        # Todo el SDK de AWS va a LocalStack; las credenciales son ficticias.
        AWS_ENDPOINT_URL=c.LOCALSTACK,
        AWS_ACCESS_KEY_ID="test",
        AWS_SECRET_ACCESS_KEY="test",  # noqa: S106  # pragma: allowlist secret
        AWS_DEFAULT_REGION=c.REGION,
        AWS_EC2_METADATA_DISABLED="true",
    )
    return env


def entorno_servicio(
    nombre: str, secretos: dict, *, empresa_id: int | None = None
) -> dict[str, str]:
    from scripts.local.aprovisionar import url_cola

    env = _base_env()
    rol = ROL_DE.get(nombre, "")
    env.update(
        CC_DB_HOST=c.DB_HOST,
        CC_DB_PUERTO=str(c.DB_PUERTO),
        CC_DB_NOMBRE=c.DB_NOMBRE,
        CC_DB_SSL="false",
        CC_DB_USUARIO=rol,
        CC_DB_CONTRASENA=secretos["roles"].get(rol, ""),
        CC_COGNITO_EMISOR=c.EMISOR,
        CC_COGNITO_CLIENT_ID=c.CLIENT_ID,
        CC_INTERNAL_AUTH_SECRETO_ID=c.SECRETOS_AWS["internal_auth"],
        CC_KMS_LLAVE_DATOS=c.LLAVE_ALIAS,
        CC_EVENTOS_ACTIVOS="true",
        CC_HMAC_CELULAR_SECRETO_ID=c.SECRETOS_AWS["hmac_celular"],
        CC_CODIGO_HMAC_SECRETO_ID=c.SECRETOS_AWS["whatsapp_hmac"],
        CC_CAMPOS_URL=_url("campos"),
        CC_COLABORADORES_URL=_url("colaboradores"),
        CC_CONSTANCIAS_URL=_url("constancias"),
        CC_COLA_CARGAS_URL=url_cola("cola-cargas"),
        CC_COLA_PDF_URL=url_cola("cola-pdf"),
        CC_COLA_WA_SALIDA_URL=url_cola("wa-salida.fifo"),
        CC_COLA_ENTRADA_URL=url_cola("wa-entrada.fifo"),
        CC_COLA_ESTADOS_URL=url_cola("wa-estados"),
        CC_COLA_SALIDA_URL=url_cola("wa-salida.fifo"),
        CC_BUS_EVENTOS=c.BUS,
    )
    # colaboradores y constancias consumen cada uno su cola ``ev-<servicio>``.
    env["CC_COLA_EVENTOS_URL"] = url_cola(f"ev-{nombre}")
    if empresa_id is not None:
        env["CC_EMPRESA_ID"] = str(empresa_id)
    return env


def _spec_procesos(
    secretos: dict, empresa_id: int, *, con_pdf: bool, con_spa: bool
) -> list[tuple[str, list[str], dict[str, str], str]]:
    """(nombre, argv, entorno, url de salud) en orden de arranque."""
    procs: list[tuple[str, list[str], dict[str, str], str]] = []
    env_pasarela = _base_env()
    procs.append(
        (
            "pasarela",
            [PY, "-m", "uvicorn", "scripts.local.pasarela:crear_app", "--factory"]
            + ["--host", "127.0.0.1", "--port", str(c.PUERTO_PASARELA), "--no-server-header"],
            env_pasarela,
            f"http://127.0.0.1:{c.PUERTO_PASARELA}/salud",
        )
    )
    for s in SERVICIOS_API:
        fabrica = (
            "scripts.local.lanzadores:app_dashboard"
            if s == "dashboard"
            else f"cc_{s}.main:crear_app"
        )
        host = "0.0.0.0" if (s in ESCUCHA_EXTERNA and con_pdf) else "127.0.0.1"  # noqa: S104
        procs.append(
            (
                s,
                [PY, "-m", "uvicorn", fabrica, "--factory", "--host", host]
                + ["--port", str(c.PUERTOS_SERVICIOS[s]), "--no-server-header"],
                entorno_servicio(s, secretos, empresa_id=empresa_id),
                f"{_url(s)}/salud",
            )
        )
    env_cargas = entorno_servicio("colaboradores", secretos)
    procs.append(
        ("worker-cargas", [PY, "-m", "scripts.local.lanzadores", "worker-cargas"], env_cargas, "")
    )
    procs.append(
        (
            "worker-whatsapp",
            [PY, "-m", "scripts.local.lanzadores", "worker-whatsapp"],
            entorno_servicio("whatsapp", secretos, empresa_id=empresa_id),
            "",
        )
    )
    if con_spa:
        env_spa = _base_env()
        env_spa.update(
            VITE_AUTH_LOCAL="true",
            CC_API_URL=f"http://127.0.0.1:{c.PUERTO_PASARELA}",
        )
        npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
        procs.append(
            (
                "spa",
                [
                    npm,
                    "--prefix",
                    "frontend",
                    "run",
                    "dev",
                    "--",
                    "--port",
                    str(c.PUERTO_SPA),
                    "--strictPort",
                ],
                env_spa,
                f"http://localhost:{c.PUERTO_SPA}/",
            )
        )
    return procs


# ---------------------------------------------------------------- worker de PDF (contenedor)


def _iniciar_worker_pdf(secretos: dict) -> None:
    """WeasyPrint no carga en Windows (sin Pango): el worker corre en un contenedor Linux."""
    docker = _docker()
    existe = _ejecutar(
        [docker, "ps", "-q", "-f", f"name=^{c.CONTENEDOR_PDF}$"], capture_output=True, text=True
    )
    if existe.stdout.strip():
        return
    _ejecutar([docker, "rm", "-f", c.CONTENEDOR_PDF], capture_output=True)
    if not _ejecutar(
        [docker, "image", "ls", "-q", c.IMAGEN_PDF], capture_output=True, text=True
    ).stdout.strip():
        print(f"  construyendo la imagen {c.IMAGEN_PDF} (una sola vez; trae Pango y fuentes)...")
        r = _ejecutar(
            [docker, "build", "-f", "infra/docker/pruebas-pdf/Dockerfile", "-t", c.IMAGEN_PDF]
            + ["infra/docker/pruebas-pdf"]
        )
        if r.returncode != 0:
            print("  AVISO: no se pudo construir la imagen del PDF; el resto del stack sigue.")
            return
    host = "host.docker.internal"
    from scripts.local.aprovisionar import url_cola

    q = lambda n: url_cola(n, f"http://{host}:4566")  # noqa: E731
    env_vars = {
        "PYTHONPATH": "/app/services/shared:/app/services/constancias",
        "PYTHONDONTWRITEBYTECODE": "1",
        "CC_AMBIENTE": "local",
        "CC_REGION": c.REGION,
        "CC_DB_HOST": host,
        "CC_DB_PUERTO": str(c.DB_PUERTO),
        "CC_DB_NOMBRE": c.DB_NOMBRE,
        "CC_DB_SSL": "false",
        "CC_DB_USUARIO": "svc_constancias",
        "CC_DB_CONTRASENA": secretos["roles"]["svc_constancias"],
        "CC_INTERNAL_AUTH_SECRETO_ID": c.SECRETOS_AWS["internal_auth"],
        "CC_KMS_LLAVE_DATOS": c.LLAVE_ALIAS,
        "CC_CAMPOS_URL": _url("campos", host),
        "CC_COLABORADORES_URL": _url("colaboradores", host),
        "CC_COLA_PDF_URL": q("cola-pdf"),
        "CC_COLA_WA_SALIDA_URL": q("wa-salida.fifo"),
        "CC_COLA_EVENTOS_URL": q("ev-constancias"),
        "AWS_ENDPOINT_URL": c.LOCALSTACK_DESDE_CONTENEDOR,
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",  # pragma: allowlist secret
        "AWS_DEFAULT_REGION": c.REGION,
    }
    argv = [docker, "run", "-d", "--name", c.CONTENEDOR_PDF, "--add-host", f"{host}:host-gateway"]
    argv += ["-v", f"{c.RAIZ}:/app:ro", "-w", "/app"]
    for k, v in env_vars.items():
        argv += ["-e", f"{k}={v}"]
    argv += [c.IMAGEN_PDF, "python", "-m", "cc_constancias.workers.worker_pdf"]
    r = _ejecutar(argv, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  AVISO: no arrancó el worker de PDF: {r.stderr.strip()[:300]}")
    else:
        print(f"  iniciado {c.CONTENEDOR_PDF} (contenedor)")


# ---------------------------------------------------------------- comandos


def _avisar_si_localstack_perdio_estado() -> None:
    """Los borradores de plantillas y los PDF viven en S3: si LocalStack volvió vacío pero la base
    tiene datos, quedan inconsistentes y conviene empezar de cero."""
    import boto3
    import psycopg

    from scripts.local.aprovisionar import url_admin

    s3 = boto3.client(
        "s3",
        endpoint_url=c.LOCALSTACK,
        region_name=c.REGION,
        aws_access_key_id="test",  # noqa: S106
        aws_secret_access_key="test",  # noqa: S106  # pragma: allowlist secret
    )
    with contextlib.suppress(Exception):  # sin el bucket, LocalStack está vacío
        s3.head_bucket(Bucket=c.BUCKETS[0])
        return
    with psycopg.connect(url_admin()) as conn:
        hay = conn.execute("SELECT count(*) FROM colaboradores.colaborador").fetchone()[0]
    if hay:
        print(
            "  AVISO: LocalStack está vacío pero la base tiene datos (se perdieron borradores y "
            "PDF). "
            "Ejecute `reiniciar-datos` para empezar de cero."
        )


def cmd_up(args: argparse.Namespace) -> int:
    from scripts.local import aprovisionar, sembrado

    docker = _docker()
    c.LOCAL.mkdir(parents=True, exist_ok=True)
    print("1/6 Contenedores (PostgreSQL y LocalStack)...")
    if _ejecutar([docker, "compose", "up", "-d", "--wait"]).returncode != 0:
        print("No se pudo levantar docker compose. ¿Docker Desktop está iniciado?")
        return 1
    secretos = aprovisionar.cargar_secretos()
    print("2/6 Migraciones y roles de base de datos...")
    aprovisionar.migrar()
    aprovisionar.asignar_contrasenas(secretos)
    _avisar_si_localstack_perdio_estado()
    print("3/6 LocalStack (buckets, colas, eventos, llave KMS, secretos)...")
    aprovisionar.preparar_localstack(secretos, salida=lambda m: print(f"  {m}"))
    print("4/6 Empresa, campos y usuarios de desarrollo...")
    base = sembrado.sembrar_base(salida=lambda m: print(f"  {m}"))
    print("5/6 Procesos...")
    if not args.sin_pdf:
        _iniciar_worker_pdf(secretos)
    if not args.sin_spa and not (c.RAIZ / "frontend" / "node_modules").exists():
        print("  instalando dependencias de la SPA (npm ci)...")
        subprocess.run(  # noqa: S603
            [shutil.which("npm.cmd") or shutil.which("npm") or "npm", "ci"],
            cwd=c.RAIZ / "frontend",
            check=False,
        )
    specs = _spec_procesos(
        secretos, base["empresa_id"], con_pdf=not args.sin_pdf, con_spa=not args.sin_spa
    )
    for nombre, argv, env, _ in specs:
        _lanzar(nombre, argv, env)
    fallas = _esperar_salud(specs)
    print("6/6 Datos de ejemplo...")
    try:
        sembrado.sembrar_demo(
            f"http://127.0.0.1:{c.PUERTO_PASARELA}",
            secretos["internal_auth"],
            salida=lambda m: print(f"  {m}"),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  AVISO: los datos de ejemplo no se completaron: {exc}")
        fallas.append("datos de ejemplo")
    _imprimir_resumen()
    if fallas:
        print(f"\nCon problemas: {', '.join(fallas)}. Revise `local.ps1 logs <nombre>`.")
        return 1
    return 0


def _esperar_salud(specs) -> list[str]:
    import httpx

    fallas: list[str] = []
    limite = time.monotonic() + 90
    pendientes = {n: u for n, _, _, u in specs if u}
    while pendientes and time.monotonic() < limite:
        for nombre, url in list(pendientes.items()):
            try:
                if httpx.get(url, timeout=2.0).status_code < 500:
                    print(f"  listo {nombre}")
                    del pendientes[nombre]
            except httpx.HTTPError:
                pid = _leer_pids().get(nombre)
                if pid and not proceso_vivo(pid):
                    print(f"  FALLÓ {nombre}: el proceso terminó")
                    fallas.append(nombre)
                    del pendientes[nombre]
        time.sleep(1.0)
    for nombre in pendientes:
        print(f"  FALLÓ {nombre}: no respondió a tiempo")
        fallas.append(nombre)
    return fallas


def _imprimir_resumen() -> None:
    print("\n=== Stack local listo ===")
    print(f"  SPA:        http://localhost:{c.PUERTO_SPA}")
    print(f"  Pasarela:   http://127.0.0.1:{c.PUERTO_PASARELA}  (API y proveedor de identidad)")
    print(f"  Usuarios:   {', '.join(u['correo'] for u in c.USUARIOS_DEV)}")
    print(f"  Contraseña: {c.CONTRASENA_DEV}   (MFA: cualquier código de 6 dígitos, p. ej. 000000)")
    print("  Más datos en docs/local.md")


def cmd_down(args: argparse.Namespace) -> int:
    pids = _leer_pids()
    for nombre, pid in pids.items():
        if proceso_vivo(pid):
            _matar(pid)
            print(f"  detenido {nombre}")
    _guardar_pids({})
    docker = _docker()
    _ejecutar([docker, "rm", "-f", c.CONTENEDOR_PDF], capture_output=True)
    if args.borrar:
        # LocalStack Community no persiste su estado (buckets, borradores, PDF): apagar sus
        # contenedores implica empezar de cero, por eso es lo único que los apaga.
        _ejecutar([docker, "compose", "down", "-v"])
        print("Stack detenido. Contenedores y datos eliminados.")
    else:
        print(
            "Procesos detenidos. PostgreSQL y LocalStack siguen encendidos para conservar los "
            "datos "
            "(use `down --borrar` para apagarlos y borrar todo)."
        )
    return 0


def cmd_estado(_: argparse.Namespace) -> int:
    import httpx

    pids = _leer_pids()
    salud = {
        "pasarela": f"http://127.0.0.1:{c.PUERTO_PASARELA}/salud",
        "spa": f"http://localhost:{c.PUERTO_SPA}/",
        **{s: f"{_url(s)}/salud" for s in SERVICIOS_API},
    }
    for nombre in (
        "pasarela",
        *SERVICIOS_API,
        "worker-cargas",
        "worker-whatsapp",
        "spa",
    ):
        pid = pids.get(nombre)
        vivo = bool(pid) and proceso_vivo(pid)
        resp = "-"
        if nombre in salud and vivo:
            try:
                resp = str(httpx.get(salud[nombre], timeout=2.0).status_code)
            except httpx.HTTPError:
                resp = "sin respuesta"
        print(
            f"  {nombre:<16} {'corriendo' if vivo else 'detenido':<10} pid={pid or '-'} http={resp}"
        )
    docker = _docker()
    r = _ejecutar(
        [
            docker,
            "ps",
            "--format",
            "{{.Names}}\t{{.Status}}",
            "--filter",
            "name=postgres",
            "--filter",
            "name=localstack",
            "--filter",
            f"name={c.CONTENEDOR_PDF}",
        ],
        capture_output=True,
        text=True,
    )
    for linea in r.stdout.strip().splitlines():
        print(f"  contenedor {linea}")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    if args.nombre in {"worker-pdf", c.CONTENEDOR_PDF}:
        return _ejecutar([_docker(), "logs", "--tail", str(args.n), c.CONTENEDOR_PDF]).returncode
    archivo = c.LOGS / f"{args.nombre}.log"
    if not archivo.exists():
        print(
            f"Sin registro para '{args.nombre}'. Disponibles: "
            + ", ".join(sorted(p.stem for p in c.LOGS.glob("*.log")))
            + ", worker-pdf"
        )
        return 1
    lineas = archivo.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(lineas[-args.n :]))
    return 0


def cmd_reiniciar(args: argparse.Namespace) -> int:
    cmd_down(argparse.Namespace(borrar=True))
    # Se conservan las llaves y secretos de .local (la llave KMS se recrea con el mismo material).
    return cmd_up(args)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="local", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="comando", required=True)
    for nombre in ("up", "reiniciar-datos"):
        s = sub.add_parser(nombre)
        s.add_argument("--sin-pdf", action="store_true", help="no inicia el worker de PDF (Docker)")
        s.add_argument("--sin-spa", action="store_true", help="no inicia la SPA (Vite)")
    d = sub.add_parser("down")
    d.add_argument(
        "--borrar", action="store_true", help="apaga PostgreSQL y LocalStack y borra los datos"
    )
    sub.add_parser("estado")
    lg = sub.add_parser("logs")
    lg.add_argument("nombre")
    lg.add_argument("-n", type=int, default=60)
    a = p.parse_args(argv)
    return {
        "up": cmd_up,
        "down": cmd_down,
        "estado": cmd_estado,
        "logs": cmd_logs,
        "reiniciar-datos": cmd_reiniciar,
    }[a.comando](a)


if __name__ == "__main__":
    sys.exit(main())
