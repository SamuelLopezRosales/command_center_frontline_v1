"""T-105: audiencias guardadas (NOT-01 a NOT-06) con base real y RLS."""

import pytest
from ayudantes_notificaciones import sql
from cc_notificaciones.clientes import Embudo, ItemAudiencia

pytestmark = pytest.mark.docker


def _h(campo, operador, valor):
    return {"campo": campo, "operador": operador, "valor": valor}


def _y(*items):
    return {"op": "Y", "items": list(items)}


CRITERIOS = _y(
    _h("planta_id", "es", 3),
    {"op": "O", "items": [_h("CAMP-0002", "es", "VENTAS"), _h("antiguedad_anios", ">=", 5)]},
)


async def _crear(http, h, nombre="Operativos Norte", criterios=CRITERIOS):
    return await http.post(
        "/api/v1/audiencias", json={"nombre": nombre, "criterios": criterios}, headers=h
    )


async def test_crear_y_leer_detalle(http, h, datos):
    r = await _crear(http, h)
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["nombre"] == "Operativos Norte" and a["activa"] is True
    assert a["criterios"] == CRITERIOS and a["creada_por_usuario_id"] == datos["ua"]
    d = await http.get(f"/api/v1/audiencias/{a['id']}", headers=h)
    assert d.status_code == 200 and d.json() == a


async def test_los_criterios_se_validan_contra_el_catalogo(http, h):
    casos = {
        "CAMP-0001": "CAMPO_SENSIBLE_NO_FILTRABLE",  # sensible
        "CAMP-0004": "CAMPO_DESCONOCIDO",  # inactivo
        "CAMP-9999": "CAMPO_DESCONOCIDO",  # no existe
        "organizacion_id; DROP": "CAMPO_DESCONOCIDO",
    }
    for campo, codigo in casos.items():
        r = await _crear(http, h, "X", _y(_h(campo, "es", "x")))
        assert r.status_code == 422, campo
        assert r.json()["errores"][0]["codigo"] == codigo
        assert r.json()["errores"][0]["campo"] == "criterios.items.0.campo"
    # operador fuera de la lista cerrada del tipo
    r = await _crear(http, h, "X", _y(_h("CAMP-0003", "contiene", 1)))
    assert r.json()["errores"][0]["codigo"] == "OPERADOR_NO_PERMITIDO"
    r = await _crear(http, h, "X", _y(_h("CAMP-0002", "es", "OLD")))  # opción inactiva
    assert r.json()["errores"][0]["codigo"] == "OPCION_DESCONOCIDA"
    r = await _crear(http, h, "X", _y(_h("CAMP-0003", "=", "no es número")))
    assert r.status_code == 422 and "no es número" not in r.text
    # sin criterios y sin estructura
    assert (await _crear(http, h, "X", {"op": "Y", "items": []})).status_code == 422
    assert (await _crear(http, h, "X", {})).status_code == 422
    assert (
        await http.post("/api/v1/audiencias", json={"nombre": "X"}, headers=h)
    ).status_code == 422
    assert (
        await http.post(
            "/api/v1/audiencias", json={"nombre": "", "criterios": CRITERIOS}, headers=h
        )
    ).status_code == 422
    assert (
        await http.post(
            "/api/v1/audiencias",
            json={"nombre": "X", "criterios": CRITERIOS, "activa": False},
            headers=h,
        )
    ).status_code == 422


async def test_hasta_20_criterios(http, h):
    veinte = _y(*[_h("planta_id", "es", i + 1) for i in range(20)])
    assert (await _crear(http, h, "Veinte", veinte)).status_code == 201
    veintiuno = _y(*[_h("planta_id", "es", i + 1) for i in range(21)])
    r = await _crear(http, h, "Veintiuno", veintiuno)
    assert r.status_code == 422 and r.json()["errores"][0]["codigo"] == "DEMASIADOS_CRITERIOS"


async def test_nombre_unico_entre_activas_sin_distinguir_mayusculas(http, h, hb):
    assert (await _crear(http, h, "Operativos")).status_code == 201
    r = await _crear(http, h, "  OPERATIVOS ")
    assert r.status_code == 409 and r.json()["codigo"] == "AUDIENCIA_NOMBRE_DUPLICADO"
    assert r.json()["errores"][0]["campo"] == "nombre"
    # otra empresa puede usar el mismo nombre (sus campos son otros: criterio solo con fijos)
    r = await http.post(
        "/api/v1/audiencias",
        json={"nombre": "Operativos", "criterios": _y(_h("planta_id", "es", 1))},
        headers=hb,
    )
    assert r.status_code == 201


async def test_delete_desactiva_y_libera_el_nombre(http, h, datos):
    a = (await _crear(http, h, "Temporal")).json()
    r = await http.delete(f"/api/v1/audiencias/{a['id']}", headers=h)
    assert r.status_code == 204
    # no se borra: la fila sigue, con activa = false
    assert sql(datos, "SELECT activa FROM notificaciones.audiencia WHERE id = %s", (a["id"],)) == [
        (False,)
    ]
    assert (await http.get(f"/api/v1/audiencias/{a['id']}", headers=h)).json()["activa"] is False
    assert (
        await http.delete(f"/api/v1/audiencias/{a['id']}", headers=h)
    ).status_code == 204  # idempotente
    # el nombre queda libre entre las activas
    assert (await _crear(http, h, "temporal")).status_code == 201
    # y reactivar la vieja choca con la nueva
    r = await http.patch(f"/api/v1/audiencias/{a['id']}", json={"activa": True}, headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "AUDIENCIA_NOMBRE_DUPLICADO"
    assert (await http.delete("/api/v1/audiencias/999999", headers=h)).status_code == 404


async def test_listado_por_estado_y_paginacion(http, h):
    ids = []
    for i in range(5):
        ids.append((await _crear(http, h, f"Aud {i}")).json()["id"])
    await http.delete(f"/api/v1/audiencias/{ids[0]}", headers=h)
    activas = (await http.get("/api/v1/audiencias", headers=h)).json()
    assert [a["id"] for a in activas["items"]] == ids[:0:-1] and activas["siguiente"] is None
    inactivas = (await http.get("/api/v1/audiencias?estado=inactivas", headers=h)).json()
    assert [a["id"] for a in inactivas["items"]] == [ids[0]]
    assert len((await http.get("/api/v1/audiencias?estado=todas", headers=h)).json()["items"]) == 5
    vistos, cursor = [], None
    for _ in range(5):
        url = "/api/v1/audiencias?estado=todas&limite=2" + (f"&cursor={cursor}" if cursor else "")
        p = (await http.get(url, headers=h)).json()
        vistos += [a["id"] for a in p["items"]]
        cursor = p["siguiente"]
        if not cursor:
            break
    assert vistos == sorted(ids, reverse=True)
    assert (await http.get("/api/v1/audiencias?cursor=basura", headers=h)).status_code == 422


async def test_patch_nombre_criterios_y_validaciones(http, h):
    a = (await _crear(http, h, "Original")).json()
    otra = (await _crear(http, h, "Otra")).json()
    nuevos = _y(_h("estatus", "es", "ACTIVO"))
    r = await http.patch(
        f"/api/v1/audiencias/{a['id']}",
        json={"nombre": "Renombrada", "criterios": nuevos},
        headers=h,
    )
    assert (
        r.status_code == 200
        and r.json()["nombre"] == "Renombrada"
        and r.json()["criterios"] == nuevos
    )
    r = await http.patch(f"/api/v1/audiencias/{a['id']}", json={"nombre": "OTRA"}, headers=h)
    assert r.status_code == 409
    r = await http.patch(
        f"/api/v1/audiencias/{a['id']}",
        json={"criterios": _y(_h("CAMP-0001", "es", "x"))},
        headers=h,
    )
    assert r.status_code == 422
    r = await http.patch(f"/api/v1/audiencias/{a['id']}", json={"nombre": None}, headers=h)
    assert r.status_code == 422
    r = await http.patch(f"/api/v1/audiencias/{otra['id']}", json={}, headers=h)
    assert r.status_code == 200 and r.json()["nombre"] == "Otra"
    assert (
        await http.patch("/api/v1/audiencias/999999", json={"nombre": "Z"}, headers=h)
    ).status_code == 404


async def test_aislamiento_por_empresa(http, h, hb):
    a = (await _crear(http, h, "Solo de A")).json()
    assert (await http.get(f"/api/v1/audiencias/{a['id']}", headers=hb)).status_code == 404
    assert (
        await http.patch(f"/api/v1/audiencias/{a['id']}", json={"nombre": "Hack"}, headers=hb)
    ).status_code == 404
    assert (await http.delete(f"/api/v1/audiencias/{a['id']}", headers=hb)).status_code == 404
    assert (await http.get("/api/v1/audiencias?estado=todas", headers=hb)).json()["items"] == []
    assert (await http.get(f"/api/v1/audiencias/{a['id']}", headers=h)).json()["activa"] is True
    # los campos de A no existen en el catálogo de B
    r = await http.post(
        "/api/v1/audiencias",
        json={"nombre": "X", "criterios": _y(_h("CAMP-0003", ">", 1))},
        headers=hb,
    )
    assert r.status_code == 422


async def test_sin_token_401_y_rol_sin_permiso_403(http, datos):
    from ayudantes_notificaciones import cab, emitir

    assert (await http.get("/api/v1/audiencias")).status_code == 401
    otro = cab(emitir("sub-x", datos["a"], datos["ua"], rol="INVITADO"))
    assert (await http.get("/api/v1/audiencias", headers=otro)).status_code == 403
    assert (
        await http.post(
            "/api/v1/audiencias/previsualizar", json={"criterios": CRITERIOS}, headers=otro
        )
    ).status_code == 403


async def test_previsualizar_devuelve_solo_el_total_y_cero_sin_colaboradores(
    http, h, colaboradores, datos
):
    r = await http.post(
        "/api/v1/audiencias/previsualizar", json={"criterios": CRITERIOS}, headers=h
    )
    assert r.status_code == 200 and r.json() == {"total": 0}
    assert colaboradores.llamadas[-1]["solo_conteo"] is True
    colaboradores.items[datos["a"]] = [
        ItemAudiencia(i, f"Persona {i}", "Norte", "1234", None) for i in range(1, 8)
    ]
    r = await http.post(
        "/api/v1/audiencias/previsualizar", json={"criterios": CRITERIOS}, headers=h
    )
    assert r.json() == {"total": 7}
    assert isinstance(Embudo(0, 0, 0, 0), Embudo)
    # criterios inválidos: 422 sin llamar a colaboradores
    llamadas = len(colaboradores.llamadas)
    r = await http.post(
        "/api/v1/audiencias/previsualizar",
        json={"criterios": _y(_h("CAMP-0001", "es", "1"))},
        headers=h,
    )
    assert r.status_code == 422 and len(colaboradores.llamadas) == llamadas
