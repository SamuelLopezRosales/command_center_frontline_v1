"""Fixtures compartidas de integración (T-022, design.md §16.1).

- ``postgres_servidor`` (sesión): un contenedor PostgreSQL 16 con Testcontainers.
- ``base_datos`` (por prueba): crea una base nueva con las extensiones del modelo y la borra
  al terminar, para que cada prueba empiece limpia.
- ``localstack`` (sesión): punto de acceso de LocalStack, si el entorno de docker compose
  está levantado (``.\\scripts\\dev.ps1 test-env``); si no, las pruebas que lo usan se omiten.

Las pruebas que necesitan Docker se marcan con ``@pytest.mark.docker`` y se omiten con un
mensaje claro si Docker no está disponible.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.request
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

INIT_SQL = Path(__file__).parent / "postgres_init.sql"
LOCALSTACK_URL = os.environ.get("CC_LOCALSTACK_URL", "http://localhost:4566")


def docker_disponible() -> bool:
    docker = shutil.which("docker")
    if not docker:
        return False
    try:
        r = subprocess.run(  # noqa: S603
            [docker, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and bool(r.stdout.strip())


def pytest_configure(config):
    config.addinivalue_line("markers", "docker: necesita Docker (PostgreSQL o LocalStack)")


def pytest_collection_modifyitems(config, items):
    if docker_disponible():
        return
    omitir = pytest.mark.skip(reason="Docker no está corriendo: inicie Docker Desktop")
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(omitir)


@dataclass(frozen=True)
class BaseDatos:
    url_sync: str
    url_async: str
    nombre: str


@pytest.fixture(scope="session")
def postgres_servidor():
    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:  # versiones anteriores de testcontainers
        from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16", username="cc", password="cc", dbname="cc") as pg:  # noqa: S106
        yield pg


@pytest.fixture
def base_datos(postgres_servidor) -> Iterator[BaseDatos]:
    import psycopg

    host = postgres_servidor.get_container_host_ip()
    puerto = postgres_servidor.get_exposed_port(5432)
    admin = f"postgresql://cc:cc@{host}:{puerto}/cc"
    nombre = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{nombre}"')
    url = f"postgresql://cc:cc@{host}:{puerto}/{nombre}"
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(INIT_SQL.read_text(encoding="utf-8"))
    try:
        yield BaseDatos(
            url_sync=url.replace("postgresql://", "postgresql+psycopg://"),
            url_async=url.replace("postgresql://", "postgresql+asyncpg://"),
            nombre=nombre,
        )
    finally:
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')


ROLES_SERVICIO = (
    "svc_dashboard",
    "svc_colaboradores",
    "svc_campos",
    "svc_constancias",
    "svc_notificaciones",
    "svc_whatsapp",
)


@dataclass(frozen=True)
class BaseMigrada:
    base: BaseDatos

    @property
    def url_admin(self) -> str:
        return self.base.url_sync.replace("postgresql+psycopg://", "postgresql://")

    def url_rol(self, rol: str, *, asincrona: bool = True) -> str:
        url = self.base.url_async if asincrona else self.url_admin
        return url.replace("cc:cc@", f"{rol}:{rol}@")


@pytest.fixture
def bd_migrada(base_datos) -> BaseMigrada:
    """Base con todas las migraciones, RLS y permisos; contraseñas de prueba para los roles."""
    import psycopg

    from scripts.migrar_todo import migrar

    migrar(base_datos.url_sync, salida=lambda _m: None)
    with psycopg.connect(
        base_datos.url_sync.replace("postgresql+psycopg://", "postgresql://"), autocommit=True
    ) as c:
        for rol in ROLES_SERVICIO:
            c.execute(f"ALTER ROLE {rol} PASSWORD '{rol}'")  # solo pruebas locales
    return BaseMigrada(base_datos)


@pytest.fixture(scope="session")
def localstack() -> str:
    try:
        with urllib.request.urlopen(f"{LOCALSTACK_URL}/_localstack/health", timeout=3) as r:  # noqa: S310
            if r.status == 200:
                return LOCALSTACK_URL
    except OSError:
        pass
    pytest.skip("LocalStack no está levantado: ejecute .\\scripts\\dev.ps1 test-env")
