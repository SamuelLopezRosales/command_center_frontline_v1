"""Integración de bitácora, outbox y consumo idempotente con PostgreSQL real (T-026)."""

import asyncio
import uuid

import psycopg
import pytest
from cc_common import bitacora, outbox
from cc_common.db import crear_motor, transaccion
from cc_common.eventos import procesar_una_vez
from sqlalchemy import text

pytestmark = pytest.mark.docker

DDL_BITACORA = """
CREATE SCHEMA auditoria;
CREATE TABLE auditoria.bitacora (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, empresa_id bigint NOT NULL,
  usuario_id bigint, colaborador_id bigint, accion text NOT NULL, entidad text NOT NULL,
  entidad_id bigint, fecha_hora timestamptz NOT NULL DEFAULT now(), ip inet,
  origen text NOT NULL, detalle jsonb NOT NULL DEFAULT '{}');
CREATE SCHEMA prueba;
"""


@pytest.fixture
async def motor(base_datos):
    crudo = base_datos.url_sync.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(crudo, autocommit=True) as c:
        c.execute(DDL_BITACORA)
        c.execute(outbox.ddl("prueba"))
    m = crear_motor(base_datos.url_async, tamano=4, desborde=2)
    yield m
    await m.dispose()


async def test_registrar_bitacora(motor):
    async with transaccion(motor, 1) as conn:
        resultado = await bitacora.registrar(
            conn,
            empresa_id=1,
            accion="MODIFICACION",
            entidad="colaborador",
            entidad_id=9,
            usuario_id=3,
            ip="10.0.0.1",
            detalle={"campos": ["puesto", "planta"]},
        )
        assert resultado is None  # sin RETURNING: los servicios solo insertan (hallazgo de T-201)
        fila = (
            await conn.execute(
                text(
                    "SELECT accion, detalle, ip::text FROM auditoria.bitacora WHERE entidad_id = 9"
                )
            )
        ).one()
    assert fila[0] == "MODIFICACION"
    assert fila[1] == {"campos": ["puesto", "planta"]}
    assert fila[2].startswith("10.0.0.1")


@pytest.mark.parametrize("clave", ["valor", "nombre", "celular", "rfc"])
async def test_detalle_rechaza_claves_personales(motor, clave):
    async with transaccion(motor, 1) as conn:
        with pytest.raises(bitacora.DetalleNoPermitido):
            await bitacora.registrar(
                conn, empresa_id=1, accion="ALTA", entidad="colaborador", detalle={clave: "x"}
            )


async def test_accion_desconocida(motor):
    async with transaccion(motor, 1) as conn:
        with pytest.raises(ValueError, match="desconocida"):
            await bitacora.registrar(conn, empresa_id=1, accion="BORRAR_TODO", entidad="x")


async def test_outbox_se_revierte_con_la_transaccion(motor):
    with pytest.raises(RuntimeError):
        async with transaccion(motor, 1) as conn:
            await outbox.escribir(
                conn, "prueba", destino_tipo="SQS", destino="cola", tipo="t", payload={"a": 1}
            )
            raise RuntimeError("falla de negocio")
    async with transaccion(motor, None) as conn:
        assert (await conn.execute(text("SELECT count(*) FROM prueba.outbox"))).scalar() == 0


async def test_dos_relays_no_duplican(motor):
    async with transaccion(motor, 1) as conn:
        for i in range(120):
            await outbox.escribir(
                conn, "prueba", destino_tipo="SQS", destino="cola", tipo="t", payload={"i": i}
            )
    publicados: list[int] = []

    async def publicador(m):
        await asyncio.sleep(0)
        publicados.append(m.payload["i"])

    async def relay():
        total = 0
        while n := await outbox.publicar_pendientes(motor, "prueba", publicador, lote=10):
            total += n
        return total

    totales = await asyncio.gather(relay(), relay())
    assert sum(totales) == 120
    assert sorted(publicados) == list(range(120))
    async with transaccion(motor, None) as conn:
        pendientes = await conn.execute(
            text("SELECT count(*) FROM prueba.outbox WHERE publicado_en IS NULL")
        )
        assert pendientes.scalar() == 0


async def test_fallo_de_publicacion_deja_pendiente(motor):
    async with transaccion(motor, 1) as conn:
        await outbox.escribir(
            conn, "prueba", destino_tipo="EVENTBRIDGE", destino="bus", tipo="t", payload={}
        )

    async def falla(_m):
        raise ConnectionError("sin red")

    assert await outbox.publicar_pendientes(motor, "prueba", falla) == 0
    async with transaccion(motor, None) as conn:
        fila = (
            await conn.execute(
                text("SELECT intentos, ultimo_error, publicado_en FROM prueba.outbox")
            )
        ).one()
    assert fila == (1, "ConnectionError", None)


async def test_consumo_idempotente(motor):
    eid = uuid.uuid4()
    efectos = []

    async def efecto(_conn):
        efectos.append(1)
        return "hecho"

    assert await procesar_una_vez(motor, "prueba", eid, efecto) == (True, "hecho")
    assert await procesar_una_vez(motor, "prueba", eid, efecto) == (False, None)
    assert efectos == [1]


async def test_efecto_fallido_no_marca_procesado(motor):
    eid = uuid.uuid4()

    async def falla(_conn):
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        await procesar_una_vez(motor, "prueba", eid, falla)

    async def ok(_conn):
        return 1

    assert await procesar_una_vez(motor, "prueba", eid, ok) == (True, 1)


def test_esquema_invalido():
    with pytest.raises(ValueError):
        outbox.ddl("prueba; DROP TABLE x")
