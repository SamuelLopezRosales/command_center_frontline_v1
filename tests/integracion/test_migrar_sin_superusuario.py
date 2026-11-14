"""T-047: las migraciones corren con un usuario que NO es superusuario, como el maestro de RDS.

Las demás pruebas migran con el superusuario del contenedor, por eso no detectaron que
``roles.sql`` fallaba en RDS (``permission denied to alter role``).
"""

import uuid

import psycopg
import pytest

from scripts.migrar_todo import migrar
from tests.fixtures.plugin import INIT_SQL

pytestmark = pytest.mark.docker


@pytest.fixture
def base_como_rds(postgres_servidor):
    """Base cuyo dueño es un rol con CREATEROLE y CREATEDB, sin SUPERUSER (como rds_superuser)."""
    host = postgres_servidor.get_container_host_ip()
    puerto = postgres_servidor.get_exposed_port(5432)
    admin = f"postgresql://cc:cc@{host}:{puerto}/cc"
    maestro = f"maestro_{uuid.uuid4().hex[:8]}"
    nombre = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(
            f"CREATE ROLE {maestro} LOGIN PASSWORD '{maestro}' "  # solo pruebas locales
            "NOSUPERUSER NOBYPASSRLS CREATEROLE CREATEDB"
        )
        c.execute(f'CREATE DATABASE "{nombre}" OWNER {maestro}')
    # En RDS las extensiones de confianza las crea el maestro; aquí se adelantan como en RDS.
    with psycopg.connect(admin.rsplit("/", 1)[0] + f"/{nombre}", autocommit=True) as c:
        c.execute(INIT_SQL.read_text(encoding="utf-8"))
    try:
        yield {
            "url": f"postgresql+psycopg://{maestro}:{maestro}@{host}:{puerto}/{nombre}",
            "admin_bd": admin.rsplit("/", 1)[0] + f"/{nombre}",
            "maestro": maestro,
        }
    finally:
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')
            try:
                c.execute(f"DROP ROLE IF EXISTS {maestro}")
            except psycopg.Error:
                pass  # puede quedar como otorgante de membresías; no afecta a otras pruebas


def test_migrar_con_usuario_sin_superusuario_y_repetible(base_como_rds):
    migrar(base_como_rds["url"], salida=lambda _m: None)
    migrar(base_como_rds["url"], salida=lambda _m: None)  # repetir no cambia nada ni falla
    with psycopg.connect(base_como_rds["admin_bd"]) as c:
        roles = c.execute(
            "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
            "WHERE rolname LIKE 'svc\\_%' OR rolname = 'migrador' ORDER BY 1"
        ).fetchall()
        assert len(roles) == 7
        assert all(not su and not bypass for _, su, bypass in roles)
        rls = c.execute(
            "SELECT count(*) FROM pg_class WHERE relname = 'colaborador' AND relrowsecurity"
        ).fetchone()[0]
        assert rls == 1


def test_un_rol_de_servicio_con_bypassrls_no_pasa_en_silencio(base_como_rds, postgres_servidor):
    """Si alguien diera BYPASSRLS a un rol de servicio, el script falla en lugar de ignorarlo."""
    migrar(base_como_rds["url"], salida=lambda _m: None)
    host = postgres_servidor.get_container_host_ip()
    puerto = postgres_servidor.get_exposed_port(5432)
    admin = f"postgresql://cc:cc@{host}:{puerto}/cc"
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute("ALTER ROLE svc_campos BYPASSRLS")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            migrar(base_como_rds["url"], salida=lambda _m: None)
    finally:
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute("ALTER ROLE svc_campos NOBYPASSRLS")
