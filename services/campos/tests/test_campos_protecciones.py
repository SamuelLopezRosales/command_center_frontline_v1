"""T-205: edición con protecciones, eliminación y reordenamiento (CAM-04 a CAM-06)."""

import pytest
from ayudantes_campos import sql
from cc_campos.clientes import PlantillaUso

pytestmark = pytest.mark.docker

BASE = {"nombre_campo": "Bono", "clave": "bono", "tipo_dato": "NUMERO"}


async def _crear(http, h, **cambios):
    r = await http.post("/api/v1/campos", json={**BASE, **cambios}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _patch(http, h, campo, **cuerpo):
    return await http.patch(f"/api/v1/campos/{campo['id']}", json=cuerpo, headers=h)


def _sugerido(datos, clave="area", tipo="LISTA", sensible=False):
    return sql(
        datos,
        "INSERT INTO campos.campo_colaborador (empresa_id, nombre_campo, clave, codigo_interno, "
        "tipo_dato, orden, es_sugerido, es_sensible) VALUES (%s, %s, %s, 'CAMP-0500', %s, 1, true, "
        "%s) RETURNING id",
        (datos["a"], clave.upper(), clave, tipo, sensible),
    )[0][0]


# ------------------------------------------------------------------ CAM-04


async def test_activar_desactivar_y_renombrar_no_piden_confirmacion(http, h, datos, constancias):
    campo = await _crear(http, h)
    constancias.usos["bono"] = [PlantillaUso(7, "Constancia")]  # aunque esté en uso
    r = await _patch(http, h, campo, activo=False, nombre_campo="Bono anual", obligatorio=True)
    assert r.status_code == 200
    c = r.json()
    assert (c["activo"], c["nombre_campo"], c["obligatorio"]) == (False, "Bono anual", True)
    assert c["codigo_interno"] == "CAMP-0001"  # el código no cambia (CC-REQ-046)
    r = await _patch(http, h, campo, activo=True)
    assert r.json()["activo"] is True


async def test_cada_cambio_registra_bitacora_y_evento_sin_valores(http, h, datos):
    campo = await _crear(http, h)
    await _patch(http, h, campo, nombre_campo="Nuevo nombre", activo=False)
    await _patch(http, h, campo, nombre_campo="Nuevo nombre")  # sin cambios: no registra
    bit = sql(
        datos,
        "SELECT accion, usuario_id, detalle FROM auditoria.bitacora "
        "WHERE accion = 'CAMPO_MODIFICADO'",
    )
    assert bit == [
        (
            "CAMPO_MODIFICADO",
            datos["ua"],
            {"campos": ["activo", "nombre_campo"], "codigos_internos": ["CAMP-0001"]},
        )
    ]
    acciones = sql(datos, "SELECT payload->>'accion' FROM campos.outbox ORDER BY id")
    assert acciones == [("CREADO",), ("MODIFICADO",)]


async def test_no_se_puede_cambiar_el_codigo_interno(http, h):
    campo = await _crear(http, h)
    r = await _patch(http, h, campo, codigo_interno="CAMP-9999")
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("cuerpo", "protegido"),
    [({"tipo_dato": "TEXTO"}, "tipo_dato"), ({"es_sensible": True}, "es_sensible")],
)
async def test_tipo_y_sensibilidad_no_cambian_con_valores(
    http, h, colaboradores, cuerpo, protegido
):
    campo = await _crear(http, h)
    colaboradores.con_valores.add(campo["id"])
    r = await _patch(http, h, campo, **cuerpo)
    assert r.status_code == 409 and r.json()["codigo"] == "CAMPO_TIPO_INMUTABLE"
    assert (await http.get(f"/api/v1/campos/{campo['id']}", headers=h)).json()[
        "tipo_dato"
    ] == "NUMERO"
    # sin valores, sí cambia
    colaboradores.con_valores.clear()
    assert (await _patch(http, h, campo, **cuerpo)).status_code == 200


async def test_tipo_de_un_campo_sugerido_no_cambia_nunca(http, h, datos):
    cid = _sugerido(datos)
    r = await http.patch(f"/api/v1/campos/{cid}", json={"tipo_dato": "TEXTO"}, headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "CAMPO_TIPO_INMUTABLE"
    # renombrar y desactivar un sugerido sí se puede
    r = await http.patch(
        f"/api/v1/campos/{cid}", json={"nombre_campo": "Área operativa", "activo": False}, headers=h
    )
    assert r.status_code == 200 and r.json()["activo"] is False


async def test_la_clave_de_un_sugerido_no_cambia(http, h, datos):
    cid = _sugerido(datos)
    r = await http.patch(f"/api/v1/campos/{cid}", json={"clave": "zona"}, headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "CAMPO_SUGERIDO_CLAVE_INMUTABLE"


async def test_cambiar_la_clave_de_un_campo_en_uso_pide_confirmacion(http, h, constancias):
    campo = await _crear(http, h)
    constancias.usos["bono"] = [PlantillaUso(7, "Constancia laboral"), PlantillaUso(9, "Otra")]
    r = await _patch(http, h, campo, clave="bono_anual")
    assert r.status_code == 409 and r.json()["codigo"] == "CLAVE_EN_USO_REQUIERE_CONFIRMACION"
    detalle = r.json()["detalle"]
    assert detalle["total"] == 2
    assert detalle["plantillas"] == [
        {"id": 7, "nombre": "Constancia laboral"},
        {"id": 9, "nombre": "Otra"},
    ]
    assert (await http.get(f"/api/v1/campos/{campo['id']}", headers=h)).json()["clave"] == "bono"
    # con confirmar=true no se bloquea (PQ-17)
    r = await _patch(http, h, campo, clave="bono_anual", confirmar=True)
    assert r.status_code == 200 and r.json()["clave"] == "bono_anual"


async def test_cambiar_la_clave_de_un_campo_sin_uso_no_pide_confirmacion(http, h):
    campo = await _crear(http, h)
    r = await _patch(http, h, campo, clave="bono_anual")
    assert r.status_code == 200


async def test_clave_reservada_o_repetida_al_editar(http, h):
    uno = await _crear(http, h)
    await _crear(http, h, clave="otro", nombre_campo="Otro")
    r = await _patch(http, h, uno, clave="puesto")
    assert r.status_code == 422 and r.json()["codigo"] == "CLAVE_RESERVADA"
    r = await _patch(http, h, uno, clave="otro")
    assert r.status_code == 409 and r.json()["codigo"] == "CLAVE_DUPLICADA"


async def test_formato_al_editar_y_campos_no_nulos(http, h):
    campo = await _crear(http, h, tipo_dato="TEXTO", clave="texto_x")
    r = await _patch(http, h, campo, formato_validacion="(?=a)")
    assert r.status_code == 422
    assert (await _patch(http, h, campo, formato_validacion=r"^\d+$")).status_code == 200
    assert (await _patch(http, h, campo, formato_validacion=None)).json()[
        "formato_validacion"
    ] is None
    assert (await _patch(http, h, campo, nombre_campo=None)).status_code == 422
    assert (
        await http.patch("/api/v1/campos/999999", json={"activo": False}, headers=h)
    ).status_code == 404


async def test_otra_empresa_no_puede_editar(http, h, hb):
    campo = await _crear(http, h)
    r = await http.patch(f"/api/v1/campos/{campo['id']}", json={"activo": False}, headers=hb)
    assert r.status_code == 404


# ------------------------------------------------------------------ CAM-05


async def test_un_sugerido_no_se_elimina(http, h, datos):
    cid = _sugerido(datos)
    r = await http.delete(f"/api/v1/campos/{cid}", headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "CAMPO_SUGERIDO_NO_ELIMINABLE"


async def test_un_campo_con_valores_no_se_elimina_pero_se_desactiva(http, h, colaboradores):
    campo = await _crear(http, h)
    colaboradores.con_valores.add(campo["id"])
    r = await http.delete(f"/api/v1/campos/{campo['id']}", headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "CAMPO_CON_VALORES"
    assert (await _patch(http, h, campo, activo=False)).status_code == 200  # conserva los valores


async def test_un_personalizado_sin_valores_se_marca_eliminado(http, h, datos):
    campo = await _crear(http, h)
    r = await http.delete(f"/api/v1/campos/{campo['id']}", headers=h)
    assert r.status_code == 204
    fila = sql(
        datos,
        "SELECT eliminado, activo FROM campos.campo_colaborador WHERE id = %s",
        (campo["id"],),
    )
    assert fila == [(True, False)]  # no se borra la fila
    assert (await http.get(f"/api/v1/campos/{campo['id']}", headers=h)).status_code == 404
    assert (await http.get("/api/v1/campos", headers=h)).json()["dinamicos"] == []
    assert (await http.delete(f"/api/v1/campos/{campo['id']}", headers=h)).status_code == 404
    assert (await _patch(http, h, campo, activo=True)).status_code == 404
    # la clave de un campo eliminado no se reutiliza
    r = await http.post("/api/v1/campos", json=BASE, headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "CLAVE_DUPLICADA"
    acciones = [a[0] for a in sql(datos, "SELECT accion FROM auditoria.bitacora ORDER BY id")]
    assert acciones == ["CAMPO_CREADO", "CAMPO_ELIMINADO"]


async def test_otra_empresa_no_puede_eliminar(http, h, hb):
    campo = await _crear(http, h)
    assert (await http.delete(f"/api/v1/campos/{campo['id']}", headers=hb)).status_code == 404
    assert (await http.get(f"/api/v1/campos/{campo['id']}", headers=h)).status_code == 200


# ------------------------------------------------------------------ CAM-06


async def test_reordenar_conserva_los_valores_y_el_resto_de_los_datos(http, h, datos):
    a = await _crear(http, h, clave="a_campo", nombre_campo="A")
    b = await _crear(http, h, clave="b_campo", nombre_campo="B")
    c = await _crear(http, h, clave="c_campo", nombre_campo="C")
    r = await http.put(
        "/api/v1/campos/orden",
        json=[
            {"id": c["id"], "orden": 1},
            {"id": a["id"], "orden": 2},
            {"id": b["id"], "orden": 3},
        ],
        headers=h,
    )
    assert r.status_code == 204
    lista = (await http.get("/api/v1/campos", headers=h)).json()["dinamicos"]
    assert [x["clave"] for x in lista] == ["c_campo", "a_campo", "b_campo"]
    assert [x["codigo_interno"] for x in lista] == ["CAMP-0003", "CAMP-0001", "CAMP-0002"]
    bit = sql(datos, "SELECT detalle FROM auditoria.bitacora WHERE accion = 'CAMPO_MODIFICADO'")
    assert bit == [({"campos": ["orden"], "totales": {"campos": 3}},)]


async def test_reordenar_con_un_campo_inexistente_no_cambia_nada(http, h):
    a = await _crear(http, h, clave="a_campo", nombre_campo="A")
    r = await http.put(
        "/api/v1/campos/orden",
        json=[{"id": a["id"], "orden": 9}, {"id": 999999, "orden": 1}],
        headers=h,
    )
    assert r.status_code == 422 and r.json()["codigo"] == "CAMPO_NO_EXISTE"
    assert (await http.get(f"/api/v1/campos/{a['id']}", headers=h)).json()["orden"] == 1


async def test_reordenar_validaciones_de_entrada(http, h):
    a = await _crear(http, h)
    for cuerpo in (
        [],
        [{"id": a["id"], "orden": 1}, {"id": a["id"], "orden": 2}],
        [{"id": a["id"], "orden": -1}],
        [{"id": a["id"]}],
    ):
        r = await http.put("/api/v1/campos/orden", json=cuerpo, headers=h)
        assert r.status_code == 422, cuerpo


async def test_reordenar_no_toca_campos_de_otra_empresa(http, h, hb):
    a = await _crear(http, h)
    r = await http.put("/api/v1/campos/orden", json=[{"id": a["id"], "orden": 5}], headers=hb)
    assert r.status_code == 422
    assert (await http.get(f"/api/v1/campos/{a['id']}", headers=h)).json()["orden"] == 1
