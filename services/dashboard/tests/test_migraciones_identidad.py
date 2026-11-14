"""T-027: migraciones de identidad y auditoria."""

import importlib.util
from pathlib import Path

import psycopg
import pytest
from cc_common.bitacora import CLAVES_DETALLE

from tests.fixtures.migrar import bajar, subir

pytestmark = pytest.mark.docker
VERSIONES = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _crudo(base_datos) -> str:
    return base_datos.url_sync.replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture
def bd(base_datos):
    subir("dashboard", base_datos.url_sync)
    return base_datos


def test_tablas_y_version(bd):
    with psycopg.connect(_crudo(bd)) as c:
        tablas = {
            f"{r[0]}.{r[1]}"
            for r in c.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema IN ('identidad', 'auditoria')"
            )
        }
        version = c.execute("SELECT version_num FROM identidad.alembic_version").fetchone()[0]
    assert {
        "identidad.empresa",
        "identidad.usuario",
        "identidad.invitacion_registro",
        "auditoria.bitacora",
    } <= tablas
    assert version == "0001"


def test_restricciones_de_usuario(bd):
    with psycopg.connect(_crudo(bd), autocommit=True) as c:
        emp = c.execute(
            "INSERT INTO identidad.empresa (razon_social) VALUES ('E') RETURNING id"
        ).fetchone()[0]
        c.execute(
            "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
            "VALUES (%s, 'A', 'A@x.com', 's1')",
            (emp,),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(
                "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
                "VALUES (%s, 'B', 'a@X.com', 's2')",
                (emp,),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub, rol) "
                "VALUES (%s, 'C', 'c@x.com', 's3', 'ADMIN')",
                (emp,),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "UPDATE identidad.empresa SET horario_envio_inicio = '21:00' WHERE id = %s", (emp,)
            )


def test_invitacion_solo_hash_de_32_bytes(bd):
    with psycopg.connect(_crudo(bd), autocommit=True) as c:
        emp = c.execute(
            "INSERT INTO identidad.empresa (razon_social) VALUES ('E') RETURNING id"
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO identidad.invitacion_registro (empresa_id, codigo_hash, fecha_expira) "
                "VALUES (%s, 'codigo-en-claro'::bytea, now())",
                (emp,),
            )
        c.execute(
            "INSERT INTO identidad.invitacion_registro (empresa_id, codigo_hash, fecha_expira) "
            "VALUES (%s, sha256('x'), now() + interval '72 hours')",
            (emp,),
        )


def test_bitacora_inmutable_y_detalle_permitido(bd):
    with psycopg.connect(_crudo(bd), autocommit=True) as c:
        emp = c.execute(
            "INSERT INTO identidad.empresa (razon_social) VALUES ('E') RETURNING id"
        ).fetchone()[0]
        rid = c.execute(
            "INSERT INTO auditoria.bitacora (empresa_id, accion, entidad, origen, detalle) "
            "VALUES (%s, 'ALTA', 'colaborador', 'USUARIO', '{\"campos\": [\"puesto\"]}') RETURNING id",
            (emp,),
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("UPDATE auditoria.bitacora SET accion = 'X' WHERE id = %s", (rid,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("DELETE FROM auditoria.bitacora WHERE id = %s", (rid,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("TRUNCATE auditoria.bitacora")
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO auditoria.bitacora (empresa_id, accion, entidad, origen, detalle) "
                "VALUES (%s, 'ALTA', 'colaborador', 'USUARIO', '{\"valor\": \"XAXX010101000\"}')",
                (emp,),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO auditoria.bitacora (empresa_id, accion, entidad, origen) "
                "VALUES (%s, 'ALTA', 'colaborador', 'OTRO')",
                (emp,),
            )


def test_sube_y_baja(base_datos):
    subir("dashboard", base_datos.url_sync)
    bajar("dashboard", base_datos.url_sync)
    with psycopg.connect(_crudo(base_datos)) as c:
        n = c.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema IN ('identidad', 'auditoria') AND table_name <> 'alembic_version'"
        ).fetchone()[0]
    assert n == 0
    subir("dashboard", base_datos.url_sync)  # se puede volver a subir


def test_claves_de_detalle_sincronizadas():
    spec = importlib.util.spec_from_file_location(
        "m0001", VERSIONES / "0001_identidad_auditoria.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert set(modulo.CLAVES_DETALLE) == set(CLAVES_DETALLE)
