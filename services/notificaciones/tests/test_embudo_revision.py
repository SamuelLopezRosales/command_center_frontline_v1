"""T-107: embudo y revisión (NOT-18) con `colaboradores` real (INT-COL-06 por ASGI) y RLS.

Reproduce el ejemplo de ``cv1_09``: 61 seleccionados, 56 con consentimiento, 54 activos y 54 con
celular válido (5 sin consentimiento y 2 en BAJA).
"""

import json

import httpx
import psycopg
import pytest
from ayudantes_notificaciones import SECRETO_INTERNO, app_colaboradores, construir_app, sql
from cc_colaboradores.campos_cliente import CacheCampos
from cc_common.db import crear_motor
from cc_common.errores import ErrorProveedor
from cc_common.internal_client import ClienteInterno
from cc_notificaciones.clientes import ColaboradoresHttp, StubCampos, StubColaboradores

pytestmark = pytest.mark.docker


class _CamposVacios:
    """INT-CAM-01 desde `colaboradores`: sin campos dinámicos (los criterios usan fijos)."""

    async def definiciones(self, empresa_id):
        return []


def _insertar(
    c, empresa, org, planta, prefijo, n, *, consent=True, estatus="ACTIVO", invalido=False, desde=0
):
    c.execute(
        """
        INSERT INTO colaboradores.colaborador
          (empresa_id, organizacion_id, planta_id, numero_empleado, nombres, apellido_paterno,
           apellido_materno, celular_cifrado, celular_hash, celular_ultimos4, celular_invalido,
           fecha_ingreso, puesto, tipo_empleado, estatus, fecha_baja, consentimiento_whatsapp)
        SELECT %(e)s, %(o)s, %(p)s, %(pre)s || g, 'Nombre' || g, 'Paterno' || g, 'Materno',
               '\\x00'::bytea, sha256(convert_to(%(e)s::text || %(pre)s || g, 'UTF8')),
               lpad((g %% 10000)::text, 4, '0'), %(inv)s, DATE '2020-01-01', 'Puesto',
               'OPERATIVO', %(est)s, CASE WHEN %(est)s = 'BAJA' THEN DATE '2026-01-01' END, %(con)s
        FROM generate_series(%(d)s::int, %(h)s::int) g
        """,
        {
            "e": empresa,
            "o": org,
            "p": planta,
            "pre": prefijo,
            "inv": invalido,
            "est": estatus,
            "con": consent,
            "d": desde + 1,
            "h": desde + n,
        },
    )


@pytest.fixture
def mundo(datos):
    a, b = datos["a"], datos["b"]
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:

        def uno(consulta, params):
            return c.execute(consulta, params).fetchone()[0]

        org = uno(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORG', 'Org') RETURNING id",
            (a,),
        )
        planta = lambda e, nombre: uno(  # noqa: E731
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, %s) RETURNING id",
            (e, nombre),
        )
        norte, sur, aparte = planta(a, "Norte"), planta(a, "Sur"), planta(a, "Aparte")
        # Norte: 61 = 5 sin consentimiento (uno de ellos también en BAJA) + 2 en BAJA + 54 válidos
        _insertar(c, a, org, norte, "S", 5, consent=False)
        c.execute(
            "UPDATE colaboradores.colaborador SET estatus = 'BAJA', fecha_baja = DATE '2026-01-01' "
            "WHERE numero_empleado = 'S1'"
        )
        _insertar(c, a, org, norte, "B", 2, estatus="BAJA")
        _insertar(c, a, org, norte, "V", 54)
        _insertar(c, a, org, sur, "R", 3)  # otra planta: no entra en la audiencia
        # Aparte: celular inválido y BAJA con celular inválido (orden de los motivos)
        _insertar(c, a, org, aparte, "I", 2, invalido=True)
        _insertar(c, a, org, aparte, "J", 1, invalido=True, estatus="BAJA")
        _insertar(c, a, org, aparte, "K", 1)
        org_b = uno(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORGB', 'OrgB') RETURNING id",
            (b,),
        )
        _insertar(c, b, org_b, planta(b, "Norte B"), "X", 4)
    return {**datos, "norte": norte, "sur": sur, "aparte": aparte}


@pytest.fixture
async def col_app(datos):
    """La app real de `colaboradores` con su propio rol de base de datos."""
    motor_col = crear_motor(datos["bd"].url_rol("svc_colaboradores"))
    app = app_colaboradores(motor_col, CacheCampos(_CamposVacios()), SECRETO_INTERNO)
    yield app
    await motor_col.dispose()


@pytest.fixture
def cliente_col(col_app):
    interno = ClienteInterno(
        "http://colaboradores",
        servicio="notificaciones",
        secreto=lambda: SECRETO_INTERNO,
        transporte=httpx.ASGITransport(app=col_app),
        reintentos=0,
    )
    return ColaboradoresHttp(interno)


@pytest.fixture
async def http(motor, mundo, cliente_col):
    campos = StubCampos({mundo["a"]: [], mundo["b"]: []})
    app = construir_app(motor, campos, cliente_col, audiencia_pagina=20)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _criterios(planta):
    return {"op": "Y", "items": [{"campo": "planta_id", "operador": "es", "valor": planta}]}


def _notificacion(datos, empresa, usuario, *, criterios=None, audiencia=None, estado="BORRADOR"):
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        return c.execute(
            "INSERT INTO notificaciones.notificacion (empresa_id, usuario_id, titulo, modo, "
            "zona_horaria, audiencia_id, criterios_snapshot_json, estado) "
            "VALUES (%s, %s, 'Aviso', 'CRITERIOS', 'America/Mexico_City', %s, %s, %s) RETURNING id",
            (empresa, usuario, audiencia, json.dumps(criterios) if criterios else None, estado),
        ).fetchone()[0]


def _renglones(datos, nid):
    return sql(
        datos,
        "SELECT colaborador_id, estado_envio, motivo_exclusion, colaborador_nombre, planta_nombre, "
        "celular_ultimos4 FROM notificaciones.notificacion_destinatario "
        "WHERE notificacion_id = %s ORDER BY colaborador_id",
        (nid,),
    )


async def _revisar(http, h, nid):
    return await http.post(f"/api/v1/notificaciones/{nid}/revisar", headers=h)


async def test_reproduce_el_ejemplo_de_cv1_09(http, h, mundo):
    nid = _notificacion(mundo, mundo["a"], mundo["ua"], criterios=_criterios(mundo["norte"]))
    r = await _revisar(http, h, nid)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["embudo"] == {
        "seleccionados": 61,
        "con_consentimiento": 56,
        "activos": 54,
        "celular_valido": 54,
    }
    assert d["excluidos_por_motivo"] == {
        "SIN_CONSENTIMIENTO": 5,
        "ESTATUS_BAJA": 2,
        "SIN_CELULAR_VALIDO": 0,
    }
    assert d["total_seleccionados"] == 61 and d["total_excluidos"] == 7 and d["revisada_en"]

    filas = _renglones(mundo, nid)
    assert len(filas) == 61 and len({f[0] for f in filas}) == 61  # uno por colaborador
    assert sum(1 for f in filas if f[1] == "PENDIENTE") == 54
    excluidos = [f for f in filas if f[1] == "EXCLUIDO"]
    assert sorted(f[2] for f in excluidos) == ["ESTATUS_BAJA"] * 2 + ["SIN_CONSENTIMIENTO"] * 5
    for _, estado, motivo, nombre, planta, ultimos4 in filas:
        assert nombre.startswith("Nombre") and planta == "Norte" and len(ultimos4) == 4
        assert (estado == "EXCLUIDO") == (motivo is not None)
    # snapshot y totales
    n = sql(
        mundo,
        "SELECT criterios_snapshot_json, total_seleccionados, total_excluidos, revisada_en "
        "FROM notificaciones.notificacion WHERE id = %s",
        (nid,),
    )[0]
    assert n[0] == _criterios(mundo["norte"]) and n[1] == 61 and n[2] == 7 and n[3] is not None
    # el celular completo nunca existe en este servicio
    cols = {
        c[0]
        for c in sql(
            mundo,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'notificaciones' AND table_name = 'notificacion_destinatario'",
        )
    }
    assert not {c for c in cols if "celular" in c} - {"celular_ultimos4"}
    assert "celular" not in r.text.replace("celular_valido", "")


async def test_un_solo_motivo_en_el_orden_consentimiento_estatus_celular(http, h, mundo):
    nid = _notificacion(mundo, mundo["a"], mundo["ua"], criterios=_criterios(mundo["aparte"]))
    d = (await _revisar(http, h, nid)).json()
    assert d["embudo"] == {
        "seleccionados": 4,
        "con_consentimiento": 4,
        "activos": 3,
        "celular_valido": 1,
    }
    # el BAJA con celular inválido cuenta como BAJA (estatus antes que celular)
    assert d["excluidos_por_motivo"] == {
        "SIN_CONSENTIMIENTO": 0,
        "ESTATUS_BAJA": 1,
        "SIN_CELULAR_VALIDO": 2,
    }
    motivos = sorted(f[2] or "-" for f in _renglones(mundo, nid))
    assert motivos == ["-", "ESTATUS_BAJA", "SIN_CELULAR_VALIDO", "SIN_CELULAR_VALIDO"]


async def test_repetir_la_revision_reemplaza_los_renglones_pendientes(http, h, mundo):
    nid = _notificacion(mundo, mundo["a"], mundo["ua"], criterios=_criterios(mundo["norte"]))
    await _revisar(http, h, nid)
    antes = {f[0]: f for f in _renglones(mundo, nid)}
    # entre revisiones: un válido retira su consentimiento y llega uno nuevo a la planta
    with psycopg.connect(mundo["bd"].url_admin, autocommit=True) as c:
        c.execute(
            "UPDATE colaboradores.colaborador SET consentimiento_whatsapp = false "
            "WHERE numero_empleado = 'V1'"
        )
        org = c.execute(
            "SELECT id FROM colaboradores.organizacion WHERE empresa_id = %s", (mundo["a"],)
        ).fetchone()[0]
        _insertar(c, mundo["a"], org, mundo["norte"], "N", 1)
    d = (await _revisar(http, h, nid)).json()
    assert d["embudo"] == {
        "seleccionados": 62,
        "con_consentimiento": 56,
        "activos": 54,
        "celular_valido": 54,
    }
    despues = {f[0]: f for f in _renglones(mundo, nid)}
    assert len(despues) == 62 and set(antes) < set(despues)  # sin duplicados ni renglones viejos
    assert sum(1 for f in despues.values() if f[1] == "PENDIENTE") == 54
    assert sum(1 for f in despues.values() if f[1] == "EXCLUIDO") == 8
    n = sql(
        mundo,
        "SELECT total_seleccionados, total_excluidos FROM notificaciones.notificacion WHERE id = %s",
        (nid,),
    )
    assert n == [(62, 8)]
    # idempotente: una tercera revisión deja el mismo estado
    await _revisar(http, h, nid)
    assert {f[0]: f for f in _renglones(mundo, nid)} == despues


async def test_usa_los_criterios_de_la_audiencia_guardada(http, h, mundo):
    r = await http.post(
        "/api/v1/audiencias",
        json={"nombre": "Sur", "criterios": _criterios(mundo["sur"])},
        headers=h,
    )
    assert r.status_code == 201
    nid = _notificacion(
        mundo,
        mundo["a"],
        mundo["ua"],
        audiencia=r.json()["id"],
        criterios=_criterios(mundo["norte"]),
    )
    d = (await _revisar(http, h, nid)).json()
    assert d["embudo"]["seleccionados"] == 3  # manda la audiencia, no el snapshot anterior
    snap = sql(
        mundo,
        "SELECT criterios_snapshot_json FROM notificaciones.notificacion WHERE id = %s",
        (nid,),
    )
    assert snap[0][0] == _criterios(mundo["sur"])


async def test_errores_404_409_y_422(http, h, hb, mundo):
    assert (await _revisar(http, h, 999999)).status_code == 404
    nid = _notificacion(mundo, mundo["a"], mundo["ua"], criterios=_criterios(mundo["norte"]))
    assert (await _revisar(http, hb, nid)).status_code == 404  # de otra empresa
    sin = _notificacion(mundo, mundo["a"], mundo["ua"])
    r = await _revisar(http, h, sin)
    assert r.status_code == 422 and r.json()["errores"][0]["codigo"] == "SIN_CRITERIOS"
    programada = _notificacion(
        mundo, mundo["a"], mundo["ua"], criterios=_criterios(mundo["norte"]), estado="CANCELADA"
    )
    r = await _revisar(http, h, programada)
    assert r.status_code == 409 and r.json()["codigo"] == "ESTADO_INVALIDO"
    assert _renglones(mundo, programada) == []
    malos = _notificacion(
        mundo,
        mundo["a"],
        mundo["ua"],
        criterios={"op": "Y", "items": [{"campo": "celular_hash", "operador": "es", "valor": "x"}]},
    )
    assert (await _revisar(http, h, malos)).status_code == 422
    assert (await http.post(f"/api/v1/notificaciones/{nid}/revisar")).status_code == 401


async def test_aislamiento_por_empresa(http, hb, h, mundo):
    # B revisa su notificación con criterios que apuntan a la planta de A: no ve a nadie de A
    nid_b = _notificacion(mundo, mundo["b"], mundo["ub"], criterios=_criterios(mundo["norte"]))
    d = (await _revisar(http, hb, nid_b)).json()
    assert d["embudo"]["seleccionados"] == 0 and d["total_seleccionados"] == 0
    assert _renglones(mundo, nid_b) == []
    # A no toca los renglones de B
    nid_a = _notificacion(mundo, mundo["a"], mundo["ua"], criterios=_criterios(mundo["norte"]))
    await _revisar(http, h, nid_a)
    assert len(_renglones(mundo, nid_a)) == 61 and _renglones(mundo, nid_b) == []


class _Falla(StubColaboradores):
    async def evaluar_audiencia(self, *a, **kw):
        raise ErrorProveedor()


async def test_si_colaboradores_falla_no_se_pierde_la_revision_anterior(
    motor, mundo, h, cliente_col
):
    campos = StubCampos({mundo["a"]: []})
    app_ok = construir_app(motor, campos, cliente_col, audiencia_pagina=20)
    app_mal = construir_app(motor, campos, _Falla())
    nid = _notificacion(mundo, mundo["a"], mundo["ua"], criterios=_criterios(mundo["norte"]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_ok), base_url="http://t"
    ) as c:
        assert (await c.post(f"/api/v1/notificaciones/{nid}/revisar", headers=h)).status_code == 200
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_mal), base_url="http://t"
    ) as c:
        r = await c.post(f"/api/v1/notificaciones/{nid}/revisar", headers=h)
    assert r.status_code == 502
    assert len(_renglones(mundo, nid)) == 61
