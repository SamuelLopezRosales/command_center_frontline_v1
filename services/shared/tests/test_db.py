"""Integración de cc_common.db con PostgreSQL real (T-023)."""

from datetime import UTC, datetime

import psycopg
import pytest
from cc_common.db import con_reintento, crear_motor, transaccion
from cc_common.paginacion import (
    CursorInvalido,
    acotar,
    codificar_cursor,
    decodificar_cursor,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.docker

ESQUEMA = """
CREATE TABLE prueba_rls (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                         empresa_id bigint NOT NULL, dato text NOT NULL);
ALTER TABLE prueba_rls ENABLE ROW LEVEL SECURITY;
CREATE POLICY por_empresa ON prueba_rls
  USING (empresa_id = NULLIF(current_setting('app.empresa_id', true), '')::bigint)
  WITH CHECK (empresa_id = NULLIF(current_setting('app.empresa_id', true), '')::bigint);
CREATE ROLE svc_prueba LOGIN PASSWORD 'svc_prueba';
GRANT USAGE ON SCHEMA public TO svc_prueba;
GRANT SELECT, INSERT, UPDATE ON prueba_rls TO svc_prueba;
INSERT INTO prueba_rls (empresa_id, dato) VALUES (1, 'a1'), (1, 'a2'), (2, 'b1');
"""


@pytest.fixture
def url_servicio(base_datos):
    """URL del rol de servicio: no es dueño de la tabla, así que RLS siempre aplica."""
    crudo = base_datos.url_sync.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(crudo, autocommit=True) as c:
        c.execute(ESQUEMA)
    yield base_datos.url_async.replace("cc:cc@", "svc_prueba:svc_prueba@")
    with psycopg.connect(crudo, autocommit=True) as c:
        c.execute("DROP OWNED BY svc_prueba; DROP ROLE svc_prueba;")


async def _datos(motor, empresa_id):
    async with transaccion(motor, empresa_id) as conn:
        r = await conn.execute(text("SELECT dato FROM prueba_rls ORDER BY dato"))
        return [x[0] for x in r]


async def test_rls_aisla_por_empresa(url_servicio):
    motor = crear_motor(url_servicio)
    try:
        assert await _datos(motor, 1) == ["a1", "a2"]
        assert await _datos(motor, 2) == ["b1"]
        assert await _datos(motor, None) == []  # sin empresa no ve nada
    finally:
        await motor.dispose()


async def test_no_puede_insertar_en_otra_empresa(url_servicio):
    motor = crear_motor(url_servicio)
    try:
        with pytest.raises(DBAPIError):
            async with transaccion(motor, 1) as conn:
                await conn.execute(
                    text("INSERT INTO prueba_rls (empresa_id, dato) VALUES (2, 'x')")
                )
    finally:
        await motor.dispose()


async def test_empresa_id_dura_solo_la_transaccion(url_servicio):
    motor = crear_motor(url_servicio, tamano=1, desborde=0)
    try:
        assert await _datos(motor, 1) == ["a1", "a2"]
        async with motor.connect() as conn:  # misma conexión del pool, sin set_config
            r = await conn.execute(text("SELECT current_setting('app.empresa_id', true)"))
            assert r.scalar() in (None, "")
    finally:
        await motor.dispose()


async def test_empresa_id_invalido(url_servicio):
    motor = crear_motor(url_servicio)
    try:
        with pytest.raises(ValueError):
            async with transaccion(motor, 0):
                pass
    finally:
        await motor.dispose()


async def test_reintento_ante_serialization_failure(url_servicio):
    motor = crear_motor(url_servicio)
    intentos = {"n": 0}

    async def operacion():
        intentos["n"] += 1
        async with transaccion(motor, 1) as conn:
            if intentos["n"] < 3:
                await conn.execute(
                    text("DO $$ BEGIN RAISE EXCEPTION USING ERRCODE = '40001'; END $$")
                )
            return "ok"

    try:
        assert await con_reintento(operacion) == "ok"
        assert intentos["n"] == 3
    finally:
        await motor.dispose()


async def test_sin_reintento_para_otros_errores(url_servicio):
    motor = crear_motor(url_servicio)
    intentos = {"n": 0}

    async def operacion():
        intentos["n"] += 1
        async with transaccion(motor, 1) as conn:
            await conn.execute(text("SELECT 1/0"))

    try:
        with pytest.raises(DBAPIError):
            await con_reintento(operacion)
        assert intentos["n"] == 1
    finally:
        await motor.dispose()


async def test_paginacion_por_cursor_estable(url_servicio):
    motor = crear_motor(url_servicio)
    try:
        async with transaccion(motor, 1) as conn:
            await conn.execute(
                text(
                    "INSERT INTO prueba_rls (empresa_id, dato) "
                    "SELECT 1, 'z' || g FROM generate_series(1, 25) g"
                )
            )
        vistos, cursor = [], None
        while True:
            async with transaccion(motor, 1) as conn:
                filtro = "WHERE id > :ultimo" if cursor else ""
                params = {"ultimo": decodificar_cursor(cursor)[0]} if cursor else {}
                r = await conn.execute(
                    text(f"SELECT id FROM prueba_rls {filtro} ORDER BY id LIMIT 10"),  # noqa: S608
                    params,
                )
                ids = [x[0] for x in r]
            if not ids:
                break
            vistos += ids
            cursor = codificar_cursor((ids[-1],))
        assert len(vistos) == 27 and vistos == sorted(set(vistos))
    finally:
        await motor.dispose()


def test_cursor_con_fecha_ida_y_vuelta():
    llave = (datetime(2026, 11, 14, 9, 42, tzinfo=UTC), 142)
    assert decodificar_cursor(codificar_cursor(llave)) == llave
    with pytest.raises(CursorInvalido):
        decodificar_cursor("no-es-cursor!!")


def test_acotar_limites():
    assert acotar(None, 100) == 20
    assert acotar(500, 100) == 100
    assert acotar(0, 100) == 1
