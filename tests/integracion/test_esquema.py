"""T-030 a T-032: roles, RLS, permisos entre esquemas y migración completa.

- T-030: los scripts de roles, RLS y permisos son idempotentes.
- T-031: ``migrar_todo`` aplica todo en orden y falla con código distinto de cero.
- T-032: unicidad por empresa, inmutabilidad, aislamiento por empresa con RLS y
  ``permission denied`` al leer tablas de otro esquema.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

from scripts.migrar_todo import migrar

pytestmark = pytest.mark.docker
RAIZ = Path(__file__).resolve().parents[2]
ROLES = (
    "svc_dashboard",
    "svc_colaboradores",
    "svc_campos",
    "svc_constancias",
    "svc_notificaciones",
    "svc_whatsapp",
)


def _crudo(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture
def bd(base_datos):
    migrar(base_datos.url_sync, salida=lambda _m: None)
    with psycopg.connect(_crudo(base_datos.url_sync), autocommit=True) as c:
        for r in ROLES:
            c.execute(f"ALTER ROLE {r} PASSWORD '{r}'")  # solo pruebas
    return base_datos


def _como(bd, rol: str, empresa: int | None = None) -> psycopg.Connection:
    url = _crudo(bd.url_sync).replace("cc:cc@", f"{rol}:{rol}@")
    conn = psycopg.connect(url, autocommit=True)
    if empresa is not None:
        conn.execute("SELECT set_config('app.empresa_id', %s, false)", (str(empresa),))
    return conn


def _datos(bd):
    """Dos empresas con un colaborador cada una (como dueño de las tablas)."""
    ids = {}
    with psycopg.connect(_crudo(bd.url_sync), autocommit=True) as c:
        for nombre in ("A", "B"):
            emp = c.execute(
                "INSERT INTO identidad.empresa (razon_social) VALUES (%s) RETURNING id", (nombre,)
            ).fetchone()[0]
            org = c.execute(
                "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
                "VALUES (%s, 'ORG01', 'Org') RETURNING id",
                (emp,),
            ).fetchone()[0]
            pla = c.execute(
                "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'P') RETURNING id",
                (emp,),
            ).fetchone()[0]
            c.execute(
                "INSERT INTO colaboradores.colaborador (empresa_id, organizacion_id, planta_id, numero_empleado, "
                "nombres, apellido_paterno, apellido_materno, celular_cifrado, celular_hash, celular_ultimos4, "
                "fecha_ingreso, puesto, tipo_empleado) VALUES (%s,%s,%s,'EMP-0001','N','P','M',%s,%s,'1234',"
                "'2021-01-01','X','OPERATIVO')",
                (emp, org, pla, b"\x01", hashlib.sha256(nombre.encode()).digest()),
            )
            ids[nombre] = {"emp": emp, "org": org, "pla": pla}
    return ids


# ---------- T-030 / T-031 ----------


def test_scripts_idempotentes(base_datos):
    migrar(base_datos.url_sync, salida=lambda _m: None)
    migrar(base_datos.url_sync, salida=lambda _m: None)  # segunda vez sin error ni cambios


def test_roles_sin_privilegios_especiales(bd):
    with psycopg.connect(_crudo(bd.url_sync)) as c:
        filas = c.execute(
            "SELECT rolname, rolsuper, rolbypassrls, rolcreaterole FROM pg_roles "
            "WHERE rolname = ANY(%s)",
            (list(ROLES),),
        ).fetchall()
    assert len(filas) == len(ROLES)
    assert all(not s and not b and not cr for _r, s, b, cr in filas)


def test_rls_activo_en_tablas_con_empresa(bd):
    with psycopg.connect(_crudo(bd.url_sync)) as c:
        sin_rls = c.execute(
            "SELECT n.nspname || '.' || t.relname FROM pg_class t JOIN pg_namespace n ON n.oid = t.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attname = 'empresa_id' "
            "WHERE t.relkind = 'r' AND n.nspname IN ('identidad','auditoria','campos','colaboradores','whatsapp',"
            "'constancias','notificaciones') AND t.relname NOT IN ('outbox','evento_procesado') "
            "AND NOT t.relrowsecurity"
        ).fetchall()
    assert sin_rls == []


def test_migrar_todo_falla_sin_url():
    r = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "migrar_todo.py")],
        capture_output=True,
        text=True,
        env={"PATH": ""},
        check=False,
    )
    assert r.returncode == 2 and "CC_MIGRAR_URL" in r.stderr


def test_migrar_todo_falla_con_url_invalida():
    r = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "migrar_todo.py")],
        capture_output=True,
        text=True,
        env={
            "CC_MIGRAR_URL": "postgresql+psycopg://x:clave_secreta@127.0.0.1:1/nada",
            "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
        },
        check=False,
    )
    assert r.returncode == 1
    assert "clave_secreta" not in r.stderr + r.stdout


# ---------- T-032 ----------


def test_rls_aisla_por_empresa(bd):
    ids = _datos(bd)
    with _como(bd, "svc_colaboradores", ids["A"]["emp"]) as c:
        assert c.execute("SELECT count(*) FROM colaboradores.colaborador").fetchone()[0] == 1
        assert (
            c.execute(
                "SELECT count(*) FROM colaboradores.colaborador WHERE empresa_id = %s",
                (ids["B"]["emp"],),
            ).fetchone()[0]
            == 0
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(
                "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Ajena')",
                (ids["B"]["emp"],),
            )
    with _como(bd, "svc_colaboradores") as c:  # sin empresa: no ve nada
        assert c.execute("SELECT count(*) FROM colaboradores.colaborador").fetchone()[0] == 0


@pytest.mark.parametrize(
    "rol,tabla",
    [
        ("svc_notificaciones", "colaboradores.colaborador"),
        ("svc_whatsapp", "colaboradores.valor_campo"),
        ("svc_constancias", "colaboradores.colaborador"),
        ("svc_dashboard", "constancias.constancia_generada"),
        ("svc_dashboard", "colaboradores.colaborador"),
        ("svc_campos", "colaboradores.valor_campo"),
        ("svc_colaboradores", "campos.campo_colaborador"),
    ],
)
def test_lectura_entre_esquemas_prohibida(bd, rol, tabla):
    with _como(bd, rol, 1) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute(f"SELECT 1 FROM {tabla} LIMIT 1")  # noqa: S608


def test_dashboard_lee_vistas_y_bitacora(bd):
    ids = _datos(bd)
    with _como(bd, "svc_dashboard", ids["A"]["emp"]) as c:
        assert (
            c.execute("SELECT colaboradores_activos FROM colaboradores.v_resumen").fetchone()[0]
            == 1
        )
        assert c.execute("SELECT count(*) FROM constancias.v_historial").fetchone()[0] == 0
        c.execute(
            "INSERT INTO auditoria.bitacora (empresa_id, accion, entidad, origen) "
            "VALUES (%s, 'LOGIN', 'usuario', 'USUARIO')",
            (ids["A"]["emp"],),
        )
        assert c.execute("SELECT count(*) FROM auditoria.bitacora").fetchone()[0] == 1


def test_bitacora_sin_update_ni_delete_para_servicios(bd):
    ids = _datos(bd)
    with _como(bd, "svc_colaboradores", ids["A"]["emp"]) as c:
        c.execute(
            "INSERT INTO auditoria.bitacora (empresa_id, accion, entidad, origen) "
            "VALUES (%s, 'ALTA', 'colaborador', 'USUARIO')",
            (ids["A"]["emp"],),
        )
        for sql in (
            "UPDATE auditoria.bitacora SET accion = 'X'",
            "DELETE FROM auditoria.bitacora",
            "SELECT * FROM auditoria.bitacora",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(sql)


def test_alembic_version_solo_migrador(bd):
    with (
        _como(bd, "svc_colaboradores", 1) as c,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        c.execute("SELECT * FROM colaboradores.alembic_version")


def test_funciones_definer_para_cognito(bd):
    ids = _datos(bd)
    with psycopg.connect(_crudo(bd.url_sync), autocommit=True) as c:
        c.execute(
            "INSERT INTO identidad.invitacion_registro (empresa_id, codigo_hash, fecha_expira) "
            "VALUES (%s, sha256('codigo'), now() + interval '72 hours')",
            (ids["A"]["emp"],),
        )
        c.execute(
            "INSERT INTO identidad.invitacion_registro (empresa_id, codigo_hash, fecha_expira) "
            "VALUES (%s, sha256('vencido'), now() - interval '1 hour')",
            (ids["A"]["emp"],),
        )
        c.execute(
            "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
            "VALUES (%s, 'RH', 'rh@x.com', 'sub-1')",
            (ids["A"]["emp"],),
        )
    with _como(bd, "svc_dashboard") as c:  # sin empresa, como el trigger de Cognito
        assert c.execute("SELECT count(*) FROM identidad.invitacion_registro").fetchone()[0] == 0
        fila = c.execute(
            "SELECT empresa_id FROM identidad.validar_invitacion(sha256('codigo'))"
        ).fetchone()
        assert fila[0] == ids["A"]["emp"]
        assert (
            c.execute(
                "SELECT count(*) FROM identidad.validar_invitacion(sha256('vencido'))"
            ).fetchone()[0]
            == 0
        )
        u = c.execute("SELECT empresa_id, rol FROM identidad.usuario_por_sub('sub-1')").fetchone()
        assert u == (ids["A"]["emp"], "RH")
    with _como(bd, "svc_colaboradores") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("SELECT * FROM identidad.validar_invitacion(sha256('codigo'))")
