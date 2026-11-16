"""T-216: modo INDIVIDUAL y GRUPO de punta a punta con `colaboradores` real (INT-COL-06 por ASGI).

Un colaborador individual se evalúa como el criterio estable ``colaborador_id`` (decisión de T-216):
pasa por el mismo embudo (consentimiento, estatus, celular válido) y por la revisión (NOT-18) y la
confirmación (NOT-19).
"""

import httpx
import psycopg
import pytest
from ayudantes_notificaciones import VARIABLES, construir_app, insertar_plantilla, sql
from cc_notificaciones.clientes import StubCampos

# Fixtures y ayudantes de la prueba del embudo (T-215): misma base, misma app real de colaboradores.
from test_embudo_revision import _insertar, cliente_col, col_app  # noqa: F401

pytestmark = pytest.mark.docker

BASE = "/api/v1/notificaciones"


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
        planta = uno(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Norte') RETURNING id",
            (a,),
        )
        _insertar(c, a, org, planta, "V", 2)  # válidos
        _insertar(c, a, org, planta, "S", 1, consent=False)
        _insertar(c, a, org, planta, "B", 1, estatus="BAJA")
        _insertar(c, a, org, planta, "I", 1, invalido=True)
        org_b = uno(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORGB', 'OrgB') RETURNING id",
            (b,),
        )
        planta_b = uno(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Norte B') RETURNING id",
            (b,),
        )
        _insertar(c, b, org_b, planta_b, "X", 2)
        ids = {
            n: uno("SELECT id FROM colaboradores.colaborador WHERE numero_empleado = %s", (n,))
            for n in ("V1", "S1", "B1", "I1", "X1")
        }
    return {**datos, "planta": planta, "ids": ids}


@pytest.fixture
async def http(motor, mundo, cliente_col, scheduler, reloj):  # noqa: F811
    campos = StubCampos({mundo["a"]: [], mundo["b"]: []})
    app = construir_app(motor, campos, cliente_col, scheduler=scheduler, reloj=reloj)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _cuerpo(plantilla, **extra):
    return {
        "titulo": "Constancia lista",
        "plantilla_mensaje_id": plantilla,
        "variables": VARIABLES,
        **extra,
    }


async def _revisar_y_confirmar(http, h, nid):
    rev = await http.post(f"{BASE}/{nid}/revisar", headers=h)
    conf = await http.post(f"{BASE}/{nid}/confirmar", json={"modo_envio": "AHORA"}, headers=h)
    return rev, conf


async def test_individual_valido_se_revisa_y_se_confirma(http, h, mundo):
    p = insertar_plantilla(mundo)
    cid = mundo["ids"]["V1"]
    r = await http.post(BASE, json=_cuerpo(p, modo="INDIVIDUAL", colaborador_id=cid), headers=h)
    assert r.status_code == 201, r.text
    nid = r.json()["id"]
    assert r.json()["colaborador_id"] == cid
    rev, conf = await _revisar_y_confirmar(http, h, nid)
    assert rev.status_code == 200, rev.text
    assert rev.json()["embudo"] == {
        "seleccionados": 1,
        "con_consentimiento": 1,
        "activos": 1,
        "celular_valido": 1,
    }
    assert conf.status_code == 202 and conf.json()["estado"] == "ENVIANDO"
    # un solo renglón, con el colaborador pedido y solo los últimos 4 del celular
    filas = sql(
        mundo,
        "SELECT colaborador_id, estado_envio, celular_ultimos4 "
        "FROM notificaciones.notificacion_destinatario WHERE notificacion_id = %s",
        (nid,),
    )
    assert len(filas) == 1 and filas[0][0] == cid and filas[0][1] == "PENDIENTE"
    d = (await http.get(f"{BASE}/{nid}/destinatarios", headers=h)).json()["items"]
    assert d[0]["celular_enmascarado"].startswith("+52 •• •••• ") and len(d) == 1
    # la bitácora lleva el criterio individual (solo el id) y los totales
    (detalle,) = (
        f[0]
        for f in sql(
            mundo, "SELECT detalle FROM auditoria.bitacora WHERE accion = 'NOTIFICACION_ENVIO'"
        )
    )
    assert detalle["criterios"]["items"][0] == {
        "campo": "colaborador_id",
        "operador": "es",
        "valor": cid,
    }
    assert detalle["totales"] == {"seleccionados": 1, "excluidos": 0, "validos": 1}


@pytest.mark.parametrize(
    ("clave", "motivo"),
    [("S1", "SIN_CONSENTIMIENTO"), ("B1", "ESTATUS_BAJA"), ("I1", "SIN_CELULAR_VALIDO")],
)
async def test_individual_no_elegible_queda_excluido_y_no_se_puede_enviar(
    http, h, mundo, clave, motivo
):
    p = insertar_plantilla(mundo)
    r = await http.post(
        BASE, json=_cuerpo(p, modo="INDIVIDUAL", colaborador_id=mundo["ids"][clave]), headers=h
    )
    assert r.status_code == 201
    rev, conf = await _revisar_y_confirmar(http, h, r.json()["id"])
    assert rev.status_code == 200 and rev.json()["excluidos_por_motivo"][motivo] == 1
    assert conf.status_code == 422
    assert ("notificacion", "SIN_DESTINATARIOS_VALIDOS") in {
        (e["campo"], e["codigo"]) for e in conf.json()["errores"]
    }


async def test_individual_de_otra_empresa_o_inexistente_no_se_crea(http, h, hb, mundo):
    p = insertar_plantilla(mundo)
    for cid in (mundo["ids"]["X1"], 999_999):  # X1 es de la empresa B
        r = await http.post(BASE, json=_cuerpo(p, modo="INDIVIDUAL", colaborador_id=cid), headers=h)
        assert r.status_code == 422, r.text
        assert ("colaborador_id", "COLABORADOR_NO_ENCONTRADO") in {
            (e["campo"], e["codigo"]) for e in r.json()["errores"]
        }
    # y la empresa B sí puede escribirle al suyo
    pb = insertar_plantilla(mundo, empresa=mundo["b"], nombre="pb")
    r = await http.post(
        BASE, json=_cuerpo(pb, modo="INDIVIDUAL", colaborador_id=mundo["ids"]["X1"]), headers=hb
    )
    assert r.status_code == 201


async def test_grupo_guardado_se_revisa_con_los_criterios_vivos_de_la_audiencia(http, h, mundo):
    crit = {
        "op": "Y",
        "items": [{"campo": "planta_id", "operador": "es", "valor": mundo["planta"]}],
    }
    a = (
        await http.post(
            "/api/v1/audiencias", json={"nombre": "Norte", "criterios": crit}, headers=h
        )
    ).json()
    p = insertar_plantilla(mundo)
    r = await http.post(BASE, json=_cuerpo(p, modo="GRUPO", audiencia_id=a["id"]), headers=h)
    nid = r.json()["id"]
    rev = await http.post(f"{BASE}/{nid}/revisar", headers=h)
    assert rev.json()["embudo"] == {
        "seleccionados": 5,
        "con_consentimiento": 4,
        "activos": 3,
        "celular_valido": 2,
    }
    d = (await http.get(f"{BASE}/{nid}", headers=h)).json()
    assert d["criterios"] == crit and d["audiencia_nombre"] == "Norte"
    assert d["contadores"]["seleccionados"] == 5 and d["contadores"]["excluidos"] == 3
    assert d["contadores"]["validos"] == 2 and d["revisada_en"]
    # duplicar copia el grupo; el duplicado se revisa de nuevo
    c = (await http.post(f"{BASE}/{nid}/duplicar", headers=h)).json()
    assert c["audiencia_id"] == a["id"] and c["revisada_en"] is None
    assert (await http.post(f"{BASE}/{c['id']}/revisar", headers=h)).status_code == 200
