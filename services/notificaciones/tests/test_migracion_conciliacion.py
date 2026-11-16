"""T-217: migración 0003 (``reencolada_en`` y funciones ``conciliar_*`` del conciliador)."""

import importlib.util
import re
from pathlib import Path

import psycopg
import pytest

from tests.fixtures.migrar import bajar, subir_todo

pytestmark = pytest.mark.docker

RAIZ = Path(__file__).resolve().parents[3]
FUNCIONES = (
    "conciliar_programadas_atrasadas",
    "conciliar_encolados_atascados",
    "conciliar_respaldos_pendientes",
    "conciliar_cierres_pendientes",
)


def _migracion():
    ruta = RAIZ / "services/notificaciones/migrations/versions/0003_conciliacion.py"
    espec = importlib.util.spec_from_file_location("migracion_0003", ruta)
    m = importlib.util.module_from_spec(espec)
    espec.loader.exec_module(m)
    return m


def _crudo(bd) -> str:
    return bd.url_sync.replace("postgresql+psycopg://", "postgresql://")


def _funciones(c) -> set[str]:
    return {
        f[0]
        for f in c.execute(
            "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'notificaciones' AND p.proname LIKE 'conciliar_%'"
        ).fetchall()
    }


def _columna(c) -> bool:
    return bool(
        c.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'notificaciones' "
            "AND table_name = 'notificacion' AND column_name = 'reencolada_en'"
        ).fetchone()
    )


def test_la_migracion_0003_sube_baja_y_vuelve_a_subir(base_datos):
    url = base_datos.url_sync
    subir_todo(url)
    with psycopg.connect(_crudo(base_datos), autocommit=True) as c:
        assert _funciones(c) == set(FUNCIONES) and _columna(c)
        assert c.execute("SELECT version_num FROM notificaciones.alembic_version").fetchone() == (
            "0003",
        )

    bajar("notificaciones", url, "0002")
    with psycopg.connect(_crudo(base_datos), autocommit=True) as c:
        assert _funciones(c) == set() and not _columna(c)
        # lo de 0002 sigue ahí
        assert c.execute(
            "SELECT count(*) FROM pg_proc WHERE proname = 'plantillas_en_revision_por_nombre'"
        ).fetchone() == (1,)

    subir_todo(url)
    with psycopg.connect(_crudo(base_datos), autocommit=True) as c:
        assert _funciones(c) == set(FUNCIONES) and _columna(c)
        # el SQL es idempotente: aplicarlo otra vez no falla ni duplica
        c.execute(_migracion().SQL_CONCILIACION)
        assert _funciones(c) == set(FUNCIONES)


def _normalizado(sql: str) -> str:
    sin_comentarios = "\n".join(
        linea for linea in sql.splitlines() if not linea.lstrip().startswith("--")
    )
    return re.sub(r"\s+", " ", sin_comentarios).strip()


def test_la_migracion_no_diverge_del_sql_que_aplican_las_pruebas_de_las_lambdas():
    archivo = (RAIZ / "lambdas/notif_comun/sql/conciliacion.sql").read_text(encoding="utf-8")
    definiciones = archivo.split("REVOKE ALL ON FUNCTION")[0]
    assert _normalizado(definiciones) == _normalizado(_migracion().SQL_CONCILIACION)
    # los mismos permisos: REVOKE a PUBLIC y GRANT EXECUTE a svc_notificaciones de las cuatro
    permisos = _normalizado(_migracion().SQL_PERMISOS)
    for f in FUNCIONES:
        assert archivo.count(f"notificaciones.{f}(") >= 3  # definición, REVOKE y GRANT
        assert permisos.count(f"notificaciones.{f}(") == 2
    assert "FROM PUBLIC" in permisos and "TO svc_notificaciones" in permisos


def test_solo_svc_notificaciones_ejecuta_las_funciones_y_sin_fijar_empresa(bd_migrada):
    """Recorren todas las empresas (SECURITY DEFINER): no necesitan ``app.empresa_id``."""
    with psycopg.connect(bd_migrada.url_admin, autocommit=True) as c:
        empresa = c.execute(
            "INSERT INTO identidad.empresa (razon_social) VALUES ('A') RETURNING id"
        ).fetchone()[0]
        usuario = c.execute(
            "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
            "VALUES (%s, 'Ana', 'ana@a.com', 'sub-a') RETURNING id",
            (empresa,),
        ).fetchone()[0]
        c.execute(
            "INSERT INTO notificaciones.notificacion (empresa_id, usuario_id, titulo, modo, "
            "zona_horaria, estado, programada_para) VALUES (%s, %s, 'T', 'CRITERIOS', "
            "'America/Mexico_City', 'PROGRAMADA', now() - interval '30 minutes')",
            (empresa, usuario),
        )
    with psycopg.connect(
        bd_migrada.url_rol("svc_notificaciones").replace("+asyncpg", ""), autocommit=True
    ) as c:
        filas = c.execute(
            "SELECT id, empresa_id FROM notificaciones.conciliar_programadas_atrasadas("
            "now(), 10, 10)"
        ).fetchall()
        assert [f[1] for f in filas] == [empresa]
        assert c.execute("SELECT count(*) FROM notificaciones.conciliar_cierres_pendientes()")
        c.execute("SELECT * FROM notificaciones.conciliar_encolados_atascados(now(), 30)")
        c.execute("SELECT * FROM notificaciones.conciliar_respaldos_pendientes(now(), 24, 5, 10)")
        # sin fijar empresa, la tabla sigue protegida por la RLS: el rol no ve nada directamente
        assert c.execute("SELECT count(*) FROM notificaciones.notificacion").fetchone() == (0,)
    with psycopg.connect(bd_migrada.url_admin, autocommit=True) as c:
        for f in FUNCIONES:
            firma = c.execute(
                "SELECT p.oid::regprocedure::text FROM pg_proc p WHERE p.proname = %s", (f,)
            ).fetchone()[0]
            assert c.execute(
                "SELECT has_function_privilege('svc_whatsapp', %s, 'EXECUTE')", (firma,)
            ).fetchone() == (False,)
            assert c.execute(
                "SELECT has_function_privilege('svc_notificaciones', %s, 'EXECUTE')", (firma,)
            ).fetchone() == (True,)
