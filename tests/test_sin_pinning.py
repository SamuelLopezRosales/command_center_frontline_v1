"""T-142: el código no fija estado de sesión en PostgreSQL (RDS Proxy "pinning", design.md §4.8, §15.3).

RDS Proxy "ancla" (pin) una conexión de cliente a una conexión de base de datos cuando la sesión
cambia de estado (``SET`` de sesión, ``set_config(..., false)``, sentencias preparadas con nombre,
``SET ROLE``, candados consultivos de sesión...). Un cliente anclado deja de compartir conexiones y
el Proxy pierde su razón de ser. El diseño fija ``app.empresa_id`` con ``set_config(..., true)``
(local a la transacción) y por eso no debe haber pinning por esa causa.

Estas pruebas garantizan, sin necesidad de un RDS Proxy (en ``test`` no existe):
1. Estática: todo ``set_config`` del código de producción usa ``true`` como tercer argumento, no hay
   ``SET``/``RESET`` de sesión ni ``options=-c`` en la conexión ni candados consultivos de sesión.
2. Dinámica: tras cada transacción la sesión vuelve a quedar sin ``app.empresa_id`` (no hay fuga
   entre clientes que compartan la conexión).

Lo que SOLO se verifica en ``prod`` (con RDS Proxy): la métrica ``DatabaseConnectionsCurrentlySessionPinned``
de CloudWatch debe mantenerse en 0 bajo carga; ver docs/resultados-carga-local.md.
"""

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CARPETAS = ("services", "lambdas", "scripts")


def _codigo_de_produccion() -> list[Path]:
    archivos = []
    for carpeta in CARPETAS:
        for ruta in (RAIZ / carpeta).rglob("*.py"):
            partes = set(ruta.relative_to(RAIZ).parts)
            if partes & {"tests", "__pycache__", ".venv", "node_modules"}:
                continue
            if ruta.name.startswith("test_") or ruta.name == "pruebas.py":
                continue
            archivos.append(ruta)
    return archivos


def _ocurrencias(patron: re.Pattern[str]) -> list[str]:
    halladas = []
    for ruta in _codigo_de_produccion():
        for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
            if linea.lstrip().startswith("#"):
                continue
            if patron.search(linea):
                halladas.append(f"{ruta.relative_to(RAIZ).as_posix()}:{n}: {linea.strip()}")
    return halladas


def test_el_codigo_de_produccion_usa_set_config_en_transaccion():
    todas = _ocurrencias(re.compile(r"set_config\("))
    assert todas, "se esperaban usos de set_config (RLS por empresa)"
    # Docstrings y comentarios que mencionan ``set_config(..., true)`` no son SQL.
    sql = [t for t in todas if "SELECT set_config" in t]
    assert sql, "se esperaban consultas SELECT set_config"
    for t in sql:
        assert re.search(
            r"set_config\('app\.empresa_id',\s*[^,]+,\s*true\)", t
        ), f"set_config debe ser local a la transacción (tercer argumento true): {t}"


def test_sin_set_de_sesion_ni_options_ni_candados_de_sesion():
    # SET/RESET de parámetros de sesión (SET LOCAL sí se permite; UPDATE ... SET no es parámetro).
    prohibidos = {
        "SET SESSION / SET de parámetro": re.compile(
            r"""["'(]\s*(?:SET\s+(?!LOCAL\b)(?:SESSION\s+)?(?:app\.|ROLE\b|SESSION\b|search_path\b|"""
            r"""statement_timeout\b|lock_timeout\b|TIME\s+ZONE\b)|RESET\s+\w)""",
            re.IGNORECASE,
        ),
        "set_config con tercer argumento false": re.compile(r"set_config\([^)]*,\s*false\s*\)"),
        "opciones de conexión -c": re.compile(r"""options\s*=\s*["']-c"""),
        "candado consultivo de sesión": re.compile(
            r"pg_advisory_lock\s*\(|pg_try_advisory_lock\s*\("
        ),
        "PREPARE con nombre": re.compile(r"""["']\s*PREPARE\s+\w+""", re.IGNORECASE),
        "LISTEN": re.compile(r"""["']\s*LISTEN\s""", re.IGNORECASE),
    }
    fallas = {nombre: _ocurrencias(p) for nombre, p in prohibidos.items()}
    assert {k: v for k, v in fallas.items() if v} == {}


def test_las_conexiones_de_servicio_no_usan_autocommit():
    """Con autocommit, ``set_config(..., true)`` se pierde en la misma sentencia: RLS no filtraría."""
    usos = _ocurrencias(re.compile(r"autocommit\s*=\s*True|AUTOCOMMIT"))
    # solo las herramientas de operación (migraciones y contraseñas de roles) lo usan
    assert [u for u in usos if not u.startswith("scripts/")] == []


@pytest.mark.docker
async def test_la_sesion_queda_limpia_tras_cada_transaccion(bd_migrada):
    """Con un grupo de UNA conexión (como un cliente compartiendo conexión de base de datos), la
    empresa de una transacción no sobrevive a la siguiente."""
    import psycopg
    from cc_common.db import crear_motor, transaccion
    from sqlalchemy import text

    motor = crear_motor(bd_migrada.url_rol("svc_colaboradores"), tamano=1, desborde=0)
    leer = text("SELECT coalesce(current_setting('app.empresa_id', true), '')")
    try:
        async with transaccion(motor, 7) as conn:
            assert (await conn.execute(leer)).scalar_one() == "7"
        async with transaccion(motor, None) as conn:
            assert (await conn.execute(leer)).scalar_one() == ""
        with pytest.raises(RuntimeError, match="boom"):
            async with transaccion(motor, 9) as conn:
                raise RuntimeError("boom")
        async with transaccion(motor, None) as conn:
            assert (await conn.execute(leer)).scalar_one() == ""
    finally:
        await motor.dispose()

    # Lambdas (psycopg síncrono): la misma regla con ``fijar_empresa`` y confirmación.
    from notif_comun.bd import fijar_empresa

    with psycopg.connect(bd_migrada.url_rol("svc_notificaciones", asincrona=False)) as c:
        fijar_empresa(c, 11)
        assert c.execute("SELECT current_setting('app.empresa_id', true)").fetchone()[0] == "11"
        c.commit()
        assert (
            c.execute("SELECT coalesce(current_setting('app.empresa_id', true), '')").fetchone()[0]
            == ""
        )
