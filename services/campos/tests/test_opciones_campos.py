"""T-205: opciones de los campos de lista (CAM-07 a CAM-09)."""

import pytest
from ayudantes_campos import sql

pytestmark = pytest.mark.docker


async def _campo(http, h, tipo="LISTA", clave="turno"):
    r = await http.post(
        "/api/v1/campos",
        json={"nombre_campo": clave.title(), "clave": clave, "tipo_dato": tipo},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _opcion(http, h, campo, **cuerpo):
    return await http.post(f"/api/v1/campos/{campo['id']}/opciones", json=cuerpo, headers=h)


async def test_solo_los_campos_de_lista_aceptan_opciones(http, h):
    texto = await _campo(http, h, tipo="TEXTO", clave="notas")
    r = await _opcion(http, h, texto, etiqueta="A", valor="A")
    assert r.status_code == 422 and r.json()["codigo"] == "CAMPO_NO_ES_LISTA"
    assert (await http.get(f"/api/v1/campos/{texto['id']}/opciones", headers=h)).status_code == 422
    assert (await http.get("/api/v1/campos/999999/opciones", headers=h)).status_code == 404
    assert (await _opcion(http, h, {"id": 999999}, etiqueta="A", valor="A")).status_code == 404


async def test_alta_normaliza_el_valor_y_ordena(http, h):
    campo = await _campo(http, h)
    a = (await _opcion(http, h, campo, etiqueta="Matutino", valor="matutino")).json()
    b = (await _opcion(http, h, campo, etiqueta="Vespertino", valor="VESPERTINO")).json()
    assert a["valor"] == "MATUTINO" and (a["orden"], b["orden"]) == (1, 2) and a["activo"] is True
    lista = (await http.get(f"/api/v1/campos/{campo['id']}/opciones", headers=h)).json()["items"]
    assert [o["valor"] for o in lista] == ["MATUTINO", "VESPERTINO"]
    detalle = (await http.get(f"/api/v1/campos/{campo['id']}", headers=h)).json()
    assert [o["etiqueta"] for o in detalle["opciones"]] == ["Matutino", "Vespertino"]


@pytest.mark.parametrize("valor", ["con espacio", "con-guion", "", "Ñ", "A" * 41])
async def test_valor_con_formato_invalido(http, h, valor):
    campo = await _campo(http, h)
    r = await _opcion(http, h, campo, etiqueta="X", valor=valor)
    assert r.status_code == 422, valor


async def test_valor_y_etiqueta_unicos_por_campo(http, h):
    campo = await _campo(http, h)
    otro = await _campo(http, h, clave="area")
    await _opcion(http, h, campo, etiqueta="Producción", valor="PRODUCCION")
    r = await _opcion(http, h, campo, etiqueta="Otra", valor="PRODUCCION")
    assert r.status_code == 409 and r.json()["codigo"] == "OPCION_DUPLICADA"
    r = await _opcion(http, h, campo, etiqueta=" producción ", valor="PROD2")  # sin acento ni caso
    assert r.status_code == 409 and r.json()["codigo"] == "OPCION_DUPLICADA"
    # en otro campo sí se puede repetir
    assert (
        await _opcion(http, h, otro, etiqueta="Producción", valor="PRODUCCION")
    ).status_code == 201


async def test_la_descripcion_guarda_el_horario_de_un_turno(http, h):
    campo = await _campo(http, h)
    o = (
        await _opcion(
            http, h, campo, etiqueta="Matutino", valor="MATUTINO", descripcion="6:00 a 14:00"
        )
    ).json()
    assert o["descripcion"] == "6:00 a 14:00"
    r = await http.patch(
        f"/api/v1/campos/{campo['id']}/opciones/{o['id']}",
        json={"descripcion": "7:00 a 15:00", "etiqueta": "Turno matutino", "orden": 5},
        headers=h,
    )
    assert r.status_code == 200
    assert (r.json()["descripcion"], r.json()["etiqueta"], r.json()["orden"]) == (
        "7:00 a 15:00",
        "Turno matutino",
        5,
    )


async def test_el_valor_no_cambia(http, h, datos):
    campo = await _campo(http, h)
    o = (await _opcion(http, h, campo, etiqueta="A", valor="A")).json()
    r = await http.patch(
        f"/api/v1/campos/{campo['id']}/opciones/{o['id']}", json={"valor": "B"}, headers=h
    )
    assert r.status_code == 422  # el valor no es editable
    with pytest.raises(Exception, match="no se modifica"):
        sql(datos, "UPDATE campos.opcion_campo SET valor = 'B' WHERE id = %s", (o["id"],))


async def test_desactivar_una_opcion_no_borra_nada_y_la_conserva_en_la_lista(http, h, datos):
    campo = await _campo(http, h)
    o = (await _opcion(http, h, campo, etiqueta="Vieja", valor="VIEJA")).json()
    # un valor histórico que usa la opción (la tabla vive en `colaboradores`)
    sql(
        datos,
        "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
        "VALUES (%s, 'O', 'O')",
        (datos["a"],),
    )
    r = await http.patch(
        f"/api/v1/campos/{campo['id']}/opciones/{o['id']}", json={"activo": False}, headers=h
    )
    assert r.status_code == 200 and r.json()["activo"] is False
    lista = (await http.get(f"/api/v1/campos/{campo['id']}/opciones", headers=h)).json()["items"]
    assert [(x["valor"], x["activo"]) for x in lista] == [("VIEJA", False)]
    assert sql(datos, "SELECT count(*) FROM campos.opcion_campo") == [(1,)]
    # no hay endpoint para borrar una opción
    r = await http.delete(f"/api/v1/campos/{campo['id']}/opciones/{o['id']}", headers=h)
    assert r.status_code == 405


async def test_cambios_de_opciones_registran_bitacora_y_evento(http, h, datos):
    campo = await _campo(http, h)
    o = (await _opcion(http, h, campo, etiqueta="A", valor="A")).json()
    await http.patch(
        f"/api/v1/campos/{campo['id']}/opciones/{o['id']}", json={"activo": False}, headers=h
    )
    await http.patch(  # sin cambios: no registra
        f"/api/v1/campos/{campo['id']}/opciones/{o['id']}", json={"activo": False}, headers=h
    )
    bit = sql(
        datos,
        "SELECT accion, entidad, detalle FROM auditoria.bitacora WHERE entidad = 'opcion_campo' "
        "ORDER BY id",
    )
    assert bit == [
        (
            "CAMPO_MODIFICADO",
            "opcion_campo",
            {"campos": ["opciones"], "codigos_internos": ["CAMP-0001"]},
        ),
        (
            "CAMPO_MODIFICADO",
            "opcion_campo",
            {"campos": ["activo"], "codigos_internos": ["CAMP-0001"]},
        ),
    ]
    assert sql(
        datos, "SELECT count(*) FROM campos.outbox WHERE payload->>'accion' = 'MODIFICADO'"
    ) == [(2,)]


async def test_otra_empresa_no_ve_ni_edita_opciones(http, h, hb):
    campo = await _campo(http, h)
    o = (await _opcion(http, h, campo, etiqueta="A", valor="A")).json()
    assert (await http.get(f"/api/v1/campos/{campo['id']}/opciones", headers=hb)).status_code == 404
    assert (await _opcion(http, hb, campo, etiqueta="B", valor="B")).status_code == 404
    r = await http.patch(
        f"/api/v1/campos/{campo['id']}/opciones/{o['id']}", json={"activo": False}, headers=hb
    )
    assert r.status_code == 404
    r = await http.patch(
        f"/api/v1/campos/{campo['id']}/opciones/999999", json={"activo": False}, headers=h
    )
    assert r.status_code == 404
