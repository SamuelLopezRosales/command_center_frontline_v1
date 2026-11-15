"""T-202: alta, detalle, edición, baja, reactivación, consentimiento y elegibilidad (COL-02 a 07)."""

from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest
from ayudantes_colaboradores import cab, construir_app, emitir
from cc_colaboradores.campos_cliente import CacheCampos, DefinicionCampo, OpcionCampo, StubCampos
from cc_colaboradores.servicios import elegibilidad

pytestmark = pytest.mark.docker


def _defs(datos):
    c = datos["campos"]
    return [
        DefinicionCampo(
            c["nss"],
            "NSS",
            "nss",
            "CAMP-0001",
            "TEXTO",
            es_sensible=True,
            formato_validacion=r"\d{11}",
        ),
        DefinicionCampo(
            c["area"],
            "Área",
            "area",
            "CAMP-0002",
            "LISTA",
            obligatorio=True,
            opciones=(OpcionCampo(datos["opcion"], "Ventas", "VENTAS"),),
        ),
    ]


@pytest.fixture
async def http(motor, cifrador, datos):
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        datos["org"] = c.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORG1', 'Org') RETURNING id",
            (datos["a"],),
        ).fetchone()[0]
        datos["org_inactiva"] = c.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social, activa) "
            "VALUES (%s, 'VIEJA', 'Vieja', false) RETURNING id",
            (datos["a"],),
        ).fetchone()[0]
        datos["planta"] = c.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Norte') RETURNING id",
            (datos["a"],),
        ).fetchone()[0]
        datos["planta_b"] = c.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Sur B') RETURNING id",
            (datos["b"],),
        ).fetchone()[0]
    campos = CacheCampos(StubCampos({datos["a"]: _defs(datos)}))
    app = construir_app(motor, cifrador, campos=campos)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as h:
        yield h


def _h(datos, **extra):
    return {**cab(emitir("sub-a", datos["a"], datos["ua"])), **extra}


def _nuevo(datos, **cambios):
    base = {
        "numero_empleado": " e-100 ",
        "nombres": "José",
        "apellido_paterno": "Martínez",
        "apellido_materno": "Ruiz",
        "celular": "811-234-5678",
        "organizacion_id": datos["org"],
        "planta_id": datos["planta"],
        "fecha_ingreso": "15/01/2020",
        "puesto": "Operador",
        "tipo_empleado": "operativo",
        "campos": {"CAMP-0001": "12345678901", "CAMP-0002": "VENTAS"},
    }
    base.update(cambios)
    return base


def _bitacora(datos, accion=None):
    with psycopg.connect(datos["bd"].url_admin) as c:
        sql = "SELECT accion, colaborador_id, usuario_id, detalle FROM auditoria.bitacora WHERE entidad = 'colaborador'"
        if accion:
            return c.execute(sql + " AND accion = %s ORDER BY id", (accion,)).fetchall()
        return c.execute(sql + " ORDER BY id").fetchall()


async def _alta(http, datos, **cambios):
    r = await http.post("/api/v1/colaboradores", json=_nuevo(datos, **cambios), headers=_h(datos))
    assert r.status_code == 201, r.text
    return r


# ------------------------------------------------------------------ alta


async def test_alta_normaliza_y_registra(http, datos):
    r = await _alta(http, datos)
    c = r.json()
    assert c["numero_empleado"] == "E-100" and c["tipo_empleado"] == "OPERATIVO"
    assert c["celular"] == "******5678" and c["estatus"] == "ACTIVO"
    assert c["fecha_ingreso"] == "2020-01-15"
    assert c["campos"] == {"CAMP-0001": {"presente": True}, "CAMP-0002": datos["opcion"]}
    assert c["consentimiento"]["otorgado"] is False
    assert c["elegible"] is False and c["motivo_no_elegible"] == "SIN_CONSENTIMIENTO"  # CC-REQ-022
    assert r.headers["etag"].startswith('"')
    alta = _bitacora(datos, "ALTA")
    assert alta == [("ALTA", c["id"], datos["ua"], {"campos": ["CAMP-0001", "CAMP-0002"]})]
    assert "12345678901" not in str(_bitacora(datos)) and "8112345678" not in str(_bitacora(datos))


@pytest.mark.parametrize(
    "falta",
    [
        "numero_empleado",
        "nombres",
        "apellido_paterno",
        "apellido_materno",
        "celular",
        "organizacion_id",
        "planta_id",
        "fecha_ingreso",
        "puesto",
        "tipo_empleado",
    ],
)
async def test_los_fijos_son_obligatorios(http, datos, falta):
    cuerpo = _nuevo(datos)
    del cuerpo[falta]
    r = await http.post("/api/v1/colaboradores", json=cuerpo, headers=_h(datos))
    assert r.status_code == 422
    assert {e["campo"] for e in r.json()["errores"]} == {falta}


@pytest.mark.parametrize(
    ("cambio", "campo"),
    [
        ({"celular": "+528112345678"}, "celular"),
        ({"celular": "81123"}, "celular"),
        ({"tipo_empleado": "EVENTUAL"}, "tipo_empleado"),
        ({"fecha_ingreso": "31/02/2020"}, "fecha_ingreso"),
        ({"campos": {"CAMP-0001": "123", "CAMP-0002": "VENTAS"}}, "campos.CAMP-0001"),
        ({"campos": {"CAMP-0001": "12345678901"}}, "campos.CAMP-0002"),
    ],
)
async def test_formatos_invalidos_422_sin_eco(http, datos, cambio, campo):
    r = await http.post("/api/v1/colaboradores", json=_nuevo(datos, **cambio), headers=_h(datos))
    assert r.status_code == 422
    assert campo in {e["campo"] for e in r.json()["errores"]}
    for v in ("+528112345678", "81123", "EVENTUAL"):
        assert v not in r.text


async def test_duplicados_409_con_su_codigo_y_sin_texto_de_postgres(http, datos):
    await _alta(http, datos)
    r = await http.post(
        "/api/v1/colaboradores", json=_nuevo(datos, numero_empleado="E-101"), headers=_h(datos)
    )
    assert r.status_code == 409 and r.json()["codigo"] == "CELULAR_DUPLICADO"
    r = await http.post(
        "/api/v1/colaboradores", json=_nuevo(datos, celular="8110000000"), headers=_h(datos)
    )
    assert r.status_code == 409 and r.json()["codigo"] == "NUMERO_EMPLEADO_DUPLICADO"
    assert "colaborador_empresa_id" not in r.text and "duplicate key" not in r.text


async def test_organizacion_inactiva_o_planta_de_otra_empresa(http, datos):
    r = await http.post(
        "/api/v1/colaboradores",
        json=_nuevo(datos, organizacion_id=datos["org_inactiva"]),
        headers=_h(datos),
    )
    assert r.status_code == 422 and r.json()["errores"][0]["codigo"] == "ORGANIZACION_NO_EXISTE"
    r = await http.post(
        "/api/v1/colaboradores", json=_nuevo(datos, planta_id=datos["planta_b"]), headers=_h(datos)
    )
    assert r.status_code == 422 and r.json()["errores"][0]["codigo"] == "PLANTA_NO_EXISTE"


async def test_alta_con_consentimiento_es_elegible(http, datos):
    c = (await _alta(http, datos, consentimiento=True)).json()
    assert c["consentimiento"]["otorgado"] and c["consentimiento"]["vigente"]
    assert c["elegible"] is True


# ------------------------------------------------------------------ detalle


async def test_detalle_enmascara_y_registra_consulta(http, datos):
    cid = (await _alta(http, datos)).json()["id"]
    r = await http.get(f"/api/v1/colaboradores/{cid}", headers=_h(datos))
    assert (
        r.json()["campos"]["CAMP-0001"] == {"presente": True}
        and r.json()["celular"] == "******5678"
    )
    assert (
        len(_bitacora(datos, "CONSULTA_DETALLE")) == 1
        and _bitacora(datos, "CONSULTA_SENSIBLE") == []
    )
    r = await http.get(f"/api/v1/colaboradores/{cid}?incluir_sensibles=true", headers=_h(datos))
    assert r.json()["campos"]["CAMP-0001"] == "12345678901" and r.json()["celular"] == "8112345678"
    (sensible,) = _bitacora(datos, "CONSULTA_SENSIBLE")
    assert sensible[3] == {"codigos_internos": ["celular", "CAMP-0001"]}
    assert "12345678901" not in str(sensible)


async def test_detalle_de_otra_empresa_404(http, datos):
    cid = (await _alta(http, datos)).json()["id"]
    r = await http.get(
        f"/api/v1/colaboradores/{cid}", headers=cab(emitir("sub-b", datos["b"], datos["ub"]))
    )
    assert r.status_code == 404


# ------------------------------------------------------------------ edición


async def test_edicion_exige_if_match_y_detecta_concurrencia(http, datos):
    r = await _alta(http, datos)
    cid, etag = r.json()["id"], r.headers["etag"]
    url = f"/api/v1/colaboradores/{cid}"
    r = await http.patch(url, json={"puesto": "Supervisor"}, headers=_h(datos))
    assert r.status_code == 428
    r = await http.patch(
        url, json={"puesto": "Supervisor"}, headers=_h(datos, **{"If-Match": etag})
    )
    assert r.status_code == 200 and r.json()["puesto"] == "Supervisor"
    nuevo = r.headers["etag"]
    assert nuevo != etag
    r = await http.patch(url, json={"puesto": "Otro"}, headers=_h(datos, **{"If-Match": etag}))
    assert r.status_code == 412 and r.json()["codigo"] == "VERSION_DESACTUALIZADA"


async def test_edicion_no_cambia_numero_ni_estatus_y_registra_nombres(http, datos):
    r = await _alta(http, datos)
    cid, etag = r.json()["id"], r.headers["etag"]
    url = f"/api/v1/colaboradores/{cid}"
    for prohibido in ({"numero_empleado": "X"}, {"estatus": "BAJA"}):
        r = await http.patch(url, json=prohibido, headers=_h(datos, **{"If-Match": etag}))
        assert r.status_code == 422 and r.json()["errores"][0]["codigo"] == "CAMPO_NO_PERMITIDO"
    r = await http.patch(
        url,
        json={
            "celular": "8117777777",
            "nombres": "José Luis",
            "campos": {"CAMP-0001": "98765432109"},
        },
        headers=_h(datos, **{"If-Match": etag}),
    )
    assert r.status_code == 200 and r.json()["celular"] == "******7777"
    (mod,) = _bitacora(datos, "MODIFICACION")
    assert mod[3] == {"campos": ["CAMP-0001", "celular", "nombres"]}
    assert "98765432109" not in str(mod) and "8117777777" not in str(mod)
    r = await http.get(f"{url}?incluir_sensibles=true", headers=_h(datos))
    assert r.json()["celular"] == "8117777777" and r.json()["campos"]["CAMP-0001"] == "98765432109"


async def test_edicion_sin_cambios_no_registra(http, datos):
    r = await _alta(http, datos)
    url = f"/api/v1/colaboradores/{r.json()['id']}"
    r = await http.patch(
        url, json={"puesto": "Operador"}, headers=_h(datos, **{"If-Match": r.headers["etag"]})
    )
    assert r.status_code == 200 and _bitacora(datos, "MODIFICACION") == []


# ------------------------------------------------------------------ baja, reactivación, consentimiento


async def test_baja_conserva_y_no_se_repite(http, datos):
    cid = (await _alta(http, datos, consentimiento=True)).json()["id"]
    r = await http.post(
        f"/api/v1/colaboradores/{cid}/baja", json={"fecha_baja": "2026-10-31"}, headers=_h(datos)
    )
    assert r.status_code == 200
    c = r.json()
    assert c["estatus"] == "BAJA" and c["fecha_baja"] == "2026-10-31"
    assert c["elegible"] is False and c["motivo_no_elegible"] == "BAJA"
    r = await http.post(
        f"/api/v1/colaboradores/{cid}/baja", json={"fecha_baja": "2026-11-01"}, headers=_h(datos)
    )
    assert r.status_code == 409 and r.json()["codigo"] == "ESTADO_INVALIDO"
    with psycopg.connect(datos["bd"].url_admin) as conn:
        assert conn.execute("SELECT count(*) FROM colaboradores.colaborador").fetchone()[0] == 1
    assert _bitacora(datos, "BAJA")[0][3] == {"estado_anterior": "ACTIVO", "estado_nuevo": "BAJA"}


async def test_baja_antes_del_ingreso_422(http, datos):
    cid = (await _alta(http, datos)).json()["id"]
    r = await http.post(
        f"/api/v1/colaboradores/{cid}/baja", json={"fecha_baja": "2019-01-01"}, headers=_h(datos)
    )
    assert r.status_code == 422


async def test_reactivar_exige_consentimiento(http, datos):
    cid = (await _alta(http, datos)).json()["id"]
    await http.post(
        f"/api/v1/colaboradores/{cid}/baja", json={"fecha_baja": "2026-10-31"}, headers=_h(datos)
    )
    r = await http.post(f"/api/v1/colaboradores/{cid}/reactivar", json={}, headers=_h(datos))
    assert r.status_code == 422 and r.json()["codigo"] == "CONSENTIMIENTO_REQUERIDO"
    r = await http.post(
        f"/api/v1/colaboradores/{cid}/reactivar", json={"consentimiento": True}, headers=_h(datos)
    )
    assert r.status_code == 200
    c = r.json()
    assert c["estatus"] == "ACTIVO" and c["fecha_baja"] is None and c["elegible"] is True
    r = await http.post(
        f"/api/v1/colaboradores/{cid}/reactivar", json={"consentimiento": True}, headers=_h(datos)
    )
    assert r.status_code == 409


async def test_reactivar_con_consentimiento_vigente_previo(http, datos):
    cid = (await _alta(http, datos, consentimiento=True)).json()["id"]
    await http.post(
        f"/api/v1/colaboradores/{cid}/baja", json={"fecha_baja": "2026-10-31"}, headers=_h(datos)
    )
    r = await http.post(f"/api/v1/colaboradores/{cid}/reactivar", json={}, headers=_h(datos))
    assert r.status_code == 200 and r.json()["estatus"] == "ACTIVO"


async def test_consentimiento_otorgar_retirar_y_vencido(http, datos):
    cid = (await _alta(http, datos)).json()["id"]
    url = f"/api/v1/colaboradores/{cid}/consentimiento"
    futuro = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    r = await http.put(url, json={"otorgado": True, "vigente_hasta": futuro}, headers=_h(datos))
    assert r.status_code == 200 and r.json()["elegible"] is True
    r = await http.put(url, json={"otorgado": False}, headers=_h(datos))
    assert r.json()["elegible"] is False and r.json()["motivo_no_elegible"] == "SIN_CONSENTIMIENTO"
    pasado = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    r = await http.put(url, json={"otorgado": True, "vigente_hasta": pasado}, headers=_h(datos))
    assert r.status_code == 422
    # Vencido por el paso del tiempo (se simula en la base).
    await http.put(url, json={"otorgado": True, "vigente_hasta": futuro}, headers=_h(datos))
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as conn:
        conn.execute(
            "UPDATE colaboradores.colaborador SET consentimiento_vigente_hasta = now() - interval '1 day' WHERE id = %s",
            (cid,),
        )
    r = await http.get(f"/api/v1/colaboradores/{cid}", headers=_h(datos))
    assert (
        r.json()["elegible"] is False and r.json()["motivo_no_elegible"] == "CONSENTIMIENTO_VENCIDO"
    )


def test_elegibilidad_reglas():
    hoy = datetime.now(UTC)
    base = {
        "estatus": "ACTIVO",
        "consentimiento_whatsapp": True,
        "consentimiento_vigente_hasta": None,
    }
    assert elegibilidad.evaluar(base).elegible
    assert elegibilidad.evaluar({**base, "estatus": "BAJA"}).motivo == "BAJA"
    assert (
        elegibilidad.evaluar({**base, "consentimiento_whatsapp": False}).motivo
        == "SIN_CONSENTIMIENTO"
    )
    vencido = {**base, "consentimiento_vigente_hasta": hoy - timedelta(seconds=1)}
    assert elegibilidad.evaluar(vencido).motivo == "CONSENTIMIENTO_VENCIDO"
    invalido = {**base, "celular_invalido": True}
    assert elegibilidad.evaluar(invalido, "CONSTANCIA").motivo == "CELULAR_INVALIDO"
    assert elegibilidad.evaluar(invalido, "CORREO").elegible
    with pytest.raises(ValueError):
        elegibilidad.evaluar(base, "OTRO")


async def test_escrituras_exigen_usuario_id_y_sensibles_permiso(http, datos):
    sin_usuario = cab(emitir("sub-a", datos["a"], None))
    r = await http.post("/api/v1/colaboradores", json=_nuevo(datos), headers=sin_usuario)
    assert r.status_code == 401
    cid = (await _alta(http, datos)).json()["id"]
    otro_rol = cab(emitir("sub-a", datos["a"], datos["ua"], rol="LECTOR"))
    r = await http.get(f"/api/v1/colaboradores/{cid}?incluir_sensibles=true", headers=otro_rol)
    assert r.status_code == 403
