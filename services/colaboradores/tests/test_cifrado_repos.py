"""T-201: repositorios de colaborador y valor de campo con cifrado (PostgreSQL real)."""

import asyncio
import logging
from datetime import date

import psycopg
import pytest
from ayudantes_colaboradores import LLAVE_HMAC
from cc_colaboradores.campos_cliente import DefinicionCampo, OpcionCampo
from cc_colaboradores.cifrado import FueraDeTransaccion
from cc_colaboradores.repos import colaborador as repo
from cc_colaboradores.repos import valor_campo as repo_valor
from cc_colaboradores.validador_campos import ValidadorCampos
from cc_common.crypto import ErrorCifrado, hmac_celular
from cc_common.db import transaccion
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.docker

CELULAR = "8112345678"


def _q(datos, sql, params=()):
    with psycopg.connect(datos["bd"].url_admin) as c:
        return c.execute(sql, params).fetchall()


def _catalogos(datos):
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        org = c.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORG1', 'Org') RETURNING id",
            (datos["a"],),
        ).fetchone()[0]
        planta = c.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Norte') RETURNING id",
            (datos["a"],),
        ).fetchone()[0]
    return org, planta


def _fijos(datos, numero="E-001", celular=CELULAR):
    org, planta = _catalogos(datos) if "org" not in datos else (datos["org"], datos["planta"])
    datos["org"], datos["planta"] = org, planta
    return repo.DatosFijos(
        numero_empleado=numero,
        nombres="Juan",
        apellido_paterno="Pérez",
        apellido_materno="López",
        celular=celular,
        organizacion_id=org,
        planta_id=planta,
        fecha_ingreso=date(2020, 1, 15),
        puesto="Operador",
        tipo_empleado="OPERATIVO",
    )


async def _alta(motor, cifrador, datos, **kw):
    async with transaccion(motor, datos["a"]) as conn, cifrador.transaccion(conn, datos["a"]):
        return await repo.insertar(conn, cifrador, empresa_id=datos["a"], datos=_fijos(datos, **kw))


async def test_celular_cifrado_con_hash_y_ultimos4(motor, cifrador, datos):
    cid = await _alta(motor, cifrador, datos)
    cifrado, h, ult = _q(
        datos,
        "SELECT celular_cifrado, celular_hash, celular_ultimos4 FROM colaboradores.colaborador "
        "WHERE id = %s",
        (cid,),
    )[0]
    assert CELULAR.encode() not in bytes(cifrado)
    assert bytes(h) == hmac_celular(LLAVE_HMAC, CELULAR) and ult == "5678"
    async with transaccion(motor, datos["a"]) as conn, cifrador.transaccion(conn, datos["a"]):
        assert (
            await repo.leer_celular(conn, cifrador, empresa_id=datos["a"], colaborador_id=cid)
            == CELULAR
        )


async def test_celular_copiado_a_otra_fila_no_descifra(motor, cifrador, datos):
    """Los datos autenticados incluyen el id: un valor copiado a otra fila es inútil."""
    c1 = await _alta(motor, cifrador, datos)
    c2 = await _alta(motor, cifrador, datos, numero="E-002", celular="8119999999")
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        c.execute(
            "UPDATE colaboradores.colaborador SET celular_cifrado = "
            "(SELECT celular_cifrado FROM colaboradores.colaborador WHERE id = %s) WHERE id = %s",
            (c1, c2),
        )
    async with transaccion(motor, datos["a"]) as conn, cifrador.transaccion(conn, datos["a"]):
        with pytest.raises(ErrorCifrado):
            await repo.leer_celular(conn, cifrador, empresa_id=datos["a"], colaborador_id=c2)


async def test_duplicados_por_numero_y_celular(motor, cifrador, datos):
    await _alta(motor, cifrador, datos)
    with pytest.raises(IntegrityError) as exc:
        await _alta(motor, cifrador, datos, numero="E-009")
    from cc_colaboradores.errores import desde_integridad

    assert desde_integridad(exc.value).codigo == "CELULAR_DUPLICADO"
    with pytest.raises(IntegrityError) as exc:
        await _alta(motor, cifrador, datos, celular="8110000000")
    assert desde_integridad(exc.value).codigo == "NUMERO_EMPLEADO_DUPLICADO"


def _defs(datos):
    c = datos["campos"]
    return [
        DefinicionCampo(c["nss"], "NSS", "nss", "CAMP-0001", "TEXTO", es_sensible=True),
        DefinicionCampo(
            c["area"],
            "AREA",
            "area",
            "CAMP-0002",
            "LISTA",
            opciones=(OpcionCampo(datos["opcion"], "Ventas", "VENTAS"),),
        ),
        DefinicionCampo(c["sueldo"], "SUELDO", "sueldo", "CAMP-0003", "NUMERO", es_sensible=True),
        DefinicionCampo(c["antiguedad_fecha"], "F", "antiguedad_fecha", "CAMP-0004", "FECHA"),
    ]


async def test_sensibles_solo_en_valor_cifrado_y_enmascarados(motor, cifrador, datos):
    cid = await _alta(motor, cifrador, datos)
    defs = _defs(datos)
    valores, errores = ValidadorCampos(defs).validar(
        {
            "CAMP-0001": "12345678901",
            "CAMP-0002": "VENTAS",
            "CAMP-0003": "9500",
            "CAMP-0004": "2021-03-15",
        }
    )
    assert errores == []
    async with transaccion(motor, datos["a"]) as conn, cifrador.transaccion(conn, datos["a"]):
        await repo_valor.guardar(
            conn, cifrador, empresa_id=datos["a"], colaborador_id=cid, valores=valores
        )
    filas = {
        f[0]: f[1:]
        for f in _q(
            datos,
            "SELECT campo_id, valor_texto, valor_numero, valor_fecha, valor_opcion_id, valor_cifrado "
            "FROM colaboradores.valor_campo WHERE colaborador_id = %s",
            (cid,),
        )
    }
    c = datos["campos"]
    for sensible in (c["nss"], c["sueldo"]):
        t, n, f, o, x = filas[sensible]
        assert (t, n, f, o) == (None, None, None, None) and x is not None
        assert b"12345678901" not in bytes(x) and b"9500" not in bytes(x)
    assert filas[c["area"]][3] == datos["opcion"] and filas[c["area"]][4] is None
    assert filas[c["antiguedad_fecha"]][2] == date(2021, 3, 15)

    async with transaccion(motor, datos["a"]) as conn, cifrador.transaccion(conn, datos["a"]):
        oculto, d1 = await repo_valor.leer(
            conn, cifrador, empresa_id=datos["a"], colaborador_id=cid, definiciones=defs
        )
        claro, d2 = await repo_valor.leer(
            conn,
            cifrador,
            empresa_id=datos["a"],
            colaborador_id=cid,
            definiciones=defs,
            incluir_sensibles=True,
        )
    assert oculto["CAMP-0001"] == {"presente": True} and d1 == []
    assert claro["CAMP-0001"] == "12345678901" and str(claro["CAMP-0003"]) == "9500.0000"
    assert sorted(d2) == ["CAMP-0001", "CAMP-0003"]


def test_check_un_solo_valor_lo_aplica_la_base(datos):
    with psycopg.connect(datos["bd"].url_admin) as c, pytest.raises(psycopg.errors.CheckViolation):
        c.execute(
            "INSERT INTO colaboradores.valor_campo (empresa_id, colaborador_id, campo_id) "
            "VALUES (%s, 1, %s)",
            (datos["a"], datos["campos"]["nss"]),
        )


async def test_el_sql_registrado_no_contiene_valores_sensibles(motor, cifrador, datos, caplog):
    motor.sync_engine.echo = True  # SQLAlchemy registra sentencias y parámetros
    try:
        with caplog.at_level(logging.INFO, logger="sqlalchemy.engine"):
            cid = await _alta(motor, cifrador, datos)
            valores, _ = ValidadorCampos(_defs(datos)).validar({"CAMP-0001": "98765432109"})
            async with (
                transaccion(motor, datos["a"]) as conn,
                cifrador.transaccion(conn, datos["a"]),
            ):
                await repo_valor.guardar(
                    conn, cifrador, empresa_id=datos["a"], colaborador_id=cid, valores=valores
                )
    finally:
        motor.sync_engine.echo = False
    assert "INSERT INTO colaboradores.colaborador" in caplog.text
    assert CELULAR not in caplog.text and "98765432109" not in caplog.text


async def test_una_dek_por_empresa_incluso_con_altas_simultaneas(motor, cifrador, datos, kms):
    datos["org"], datos["planta"] = _catalogos(datos)
    await asyncio.gather(
        *(
            _alta(motor, cifrador, datos, numero=f"E-1{i}", celular=f"81100000{i:02d}")
            for i in range(5)
        )
    )
    assert _q(
        datos, "SELECT count(*) FROM colaboradores.clave_datos WHERE empresa_id = %s", (datos["a"],)
    ) == [(1,)]
    assert kms.llamadas["generate"] == 1


async def test_dek_de_una_transaccion_revertida_no_se_guarda(motor, cifrador, datos):
    with pytest.raises(RuntimeError):
        async with transaccion(motor, datos["a"]) as conn, cifrador.transaccion(conn, datos["a"]):
            await repo.insertar(conn, cifrador, empresa_id=datos["a"], datos=_fijos(datos))
            raise RuntimeError("falla")
    assert _q(datos, "SELECT count(*) FROM colaboradores.clave_datos") == [(0,)]
    assert _q(datos, "SELECT count(*) FROM colaboradores.colaborador") == [(0,)]


def test_cifrar_fuera_de_transaccion_es_un_error(cifrador):
    with pytest.raises(FueraDeTransaccion):
        cifrador.cifrar("x", empresa_id=1, tabla="t", columna="c", registro=1)


async def test_rls_otra_empresa_no_ve_los_datos(motor, cifrador, datos):
    cid = await _alta(motor, cifrador, datos)
    async with transaccion(motor, datos["b"]) as conn:
        from sqlalchemy import text

        r = await conn.execute(
            text("SELECT count(*) FROM colaboradores.colaborador WHERE id = :i"), {"i": cid}
        )
        assert r.scalar_one() == 0
        r = await conn.execute(text("SELECT count(*) FROM colaboradores.clave_datos"))
        assert r.scalar_one() == 0
