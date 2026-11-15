"""T-207 (T-076): CRUD de plantillas de constancia (CON-01 a CON-06) con PostgreSQL y LocalStack."""

import pytest
from ayudantes_constancias import (
    CONTENIDO,
    cab,
    canonico,
    emitir,
    emitir_constancia,
    publicar_version,
    sql,
)

pytestmark = pytest.mark.docker


async def _crear(http, h, nombre="Constancia laboral", **extra):
    r = await http.post("/api/v1/plantillas", json={"nombre": nombre, **extra}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _guardar_borrador(http, h, plantilla, contenido=None, if_match=None):
    cabeceras = dict(h) | ({"If-Match": if_match} if if_match else {})
    r = await http.put(
        f"/api/v1/plantillas/{plantilla['id']}/borrador",
        json=contenido or CONTENIDO,
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text
    return r


# ------------------------------------------------------------------ alta (CON-02)


async def test_la_plantilla_nace_inactiva_y_sin_version(http, h, datos):
    p = await _crear(http, h, descripcion="Antigüedad y puesto")
    assert p["estado"] == "BORRADOR" and p["activa"] is False
    assert p["version"] is None and p["tiene_borrador"] is False and p["emitidas"] == 0
    assert p["nombre"] == "Constancia laboral" and p["descripcion"] == "Antigüedad y puesto"
    fila = sql(
        datos,
        "SELECT empresa_id, activa, eliminada FROM constancias.plantilla_constancia WHERE id = %s",
        (p["id"],),
    )
    assert fila == [(datos["a"], False, False)]
    bit = sql(datos, "SELECT accion, entidad, usuario_id FROM auditoria.bitacora")
    assert bit == [("PLANTILLA_CREADA", "plantilla_constancia", datos["ua"])]


async def test_nombre_unico_por_empresa_sin_distinguir_mayusculas(http, h, hb):
    await _crear(http, h, "Constancia laboral")
    for nombre in ("Constancia laboral", "CONSTANCIA LABORAL", "  constancia laboral "):
        r = await http.post("/api/v1/plantillas", json={"nombre": nombre}, headers=h)
        assert r.status_code == 409 and r.json()["codigo"] == "NOMBRE_DUPLICADO", nombre
    # otra empresa puede usar el mismo nombre
    assert (
        await http.post("/api/v1/plantillas", json={"nombre": "Constancia laboral"}, headers=hb)
    ).status_code == 201


@pytest.mark.parametrize(
    "cuerpo",
    [{}, {"nombre": ""}, {"nombre": "   "}, {"nombre": "x" * 121}, {"nombre": "A", "activa": True},
     {"nombre": "A", "descripcion": "d" * 501}, {"nombre": None}],
)  # fmt: skip
async def test_alta_con_datos_invalidos(http, h, cuerpo):
    r = await http.post("/api/v1/plantillas", json=cuerpo, headers=h)
    assert r.status_code == 422, cuerpo


async def test_requiere_sesion_rol_y_usuario(http, datos):
    assert (await http.get("/api/v1/plantillas")).status_code == 401
    otro = cab(emitir("sub-a", datos["a"], datos["ua"], rol="OTRO"))
    assert (await http.get("/api/v1/plantillas", headers=otro)).status_code == 403
    sin_usuario = cab(emitir("sub-a", datos["a"], None))
    r = await http.post("/api/v1/plantillas", json={"nombre": "X"}, headers=sin_usuario)
    assert r.status_code in (401, 403)
    assert sql(datos, "SELECT count(*) FROM constancias.plantilla_constancia") == [(0,)]


# ------------------------------------------------------------------ listado y detalle (CON-01, 03)


async def test_listado_con_version_emitidas_y_estado(http, h, datos, s3_plantillas):
    almacen = s3_plantillas[0]
    laboral = await _crear(http, h, "Constancia laboral")
    guarderia = await _crear(http, h, "Constancia guardería")
    await _crear(http, h, "Constancia de ingresos")
    for plantilla, versiones in ((laboral, 3), (guarderia, 1)):
        for n in range(1, versiones + 1):
            publicar_version(datos, almacen, plantilla["id"], n)
    emitir_constancia(datos, laboral["id"], 3, n=1)
    emitir_constancia(datos, laboral["id"], 1, n=2)
    emitir_constancia(datos, guarderia["id"], 1, n=3)
    # la laboral se activa; la guardería queda desactivada con versión
    assert (
        await http.patch(f"/api/v1/plantillas/{laboral['id']}", json={"activa": True}, headers=h)
    ).status_code == 200
    await _guardar_borrador(http, h, laboral)

    r = await http.get("/api/v1/plantillas", headers=h)
    assert r.status_code == 200
    items = {i["nombre"]: i for i in r.json()["items"]}
    la = items["Constancia laboral"]
    assert (la["estado"], la["version"], la["emitidas"], la["tiene_borrador"]) == (
        "ACTIVA",
        3,
        2,
        True,
    )
    g = items["Constancia guardería"]
    assert (g["estado"], g["version"], g["emitidas"], g["activa"]) == ("INACTIVA", 1, 1, False)
    i = items["Constancia de ingresos"]
    assert (i["estado"], i["version"], i["emitidas"]) == ("BORRADOR", None, 0)
    # la más recientemente modificada va primero
    assert r.json()["items"][0]["nombre"] == "Constancia laboral"


async def test_listado_y_detalle_son_por_empresa(http, h, hb):
    p = await _crear(http, h)
    assert (await http.get("/api/v1/plantillas", headers=hb)).json() == {"items": []}
    assert (await http.get(f"/api/v1/plantillas/{p['id']}", headers=hb)).status_code == 404
    assert (await http.get(f"/api/v1/plantillas/{p['id']}", headers=h)).json()["id"] == p["id"]
    assert (await http.get("/api/v1/plantillas/999999", headers=h)).status_code == 404


# ------------------------------------------------------------------ edición (CON-04)


async def test_activar_sin_version_da_409_y_con_version_funciona(http, h, datos, s3_plantillas):
    p = await _crear(http, h)
    r = await http.patch(f"/api/v1/plantillas/{p['id']}", json={"activa": True}, headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "PLANTILLA_SIN_VERSION"
    assert sql(datos, "SELECT activa FROM constancias.plantilla_constancia") == [(False,)]
    publicar_version(datos, s3_plantillas[0], p["id"], 1)
    r = await http.patch(f"/api/v1/plantillas/{p['id']}", json={"activa": True}, headers=h)
    assert r.status_code == 200 and (r.json()["estado"], r.json()["activa"]) == ("ACTIVA", True)
    r = await http.patch(f"/api/v1/plantillas/{p['id']}", json={"activa": False}, headers=h)
    assert (r.json()["estado"], r.json()["activa"]) == (
        "INACTIVA",
        False,
    )  # desactivar siempre se puede


async def test_renombrar_cambiar_descripcion_y_conflicto(http, h, datos):
    uno = await _crear(http, h, "Uno", descripcion="d")
    dos = await _crear(http, h, "Dos")
    r = await http.patch(
        f"/api/v1/plantillas/{uno['id']}",
        json={"nombre": "Uno bis", "descripcion": None},
        headers=h,
    )
    assert r.status_code == 200 and (r.json()["nombre"], r.json()["descripcion"]) == (
        "Uno bis",
        None,
    )
    r = await http.patch(f"/api/v1/plantillas/{dos['id']}", json={"nombre": "uno BIS"}, headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "NOMBRE_DUPLICADO"
    # un cambio de forma sin efecto no registra nada ni mueve la fecha
    antes = (await http.get(f"/api/v1/plantillas/{uno['id']}", headers=h)).json()
    r = await http.patch(f"/api/v1/plantillas/{uno['id']}", json={"nombre": "Uno bis"}, headers=h)
    assert r.json()["fecha_modificacion"] == antes["fecha_modificacion"]
    bit = sql(datos, "SELECT detalle FROM auditoria.bitacora WHERE accion = 'PLANTILLA_MODIFICADA'")
    assert bit == [({"campos": ["descripcion", "nombre"]},)]  # nombres de campos, sin valores


@pytest.mark.parametrize("cuerpo", [{"nombre": None}, {"activa": None}, {"nombre": ""}, {"x": 1}])
async def test_edicion_invalida(http, h, cuerpo):
    p = await _crear(http, h)
    assert (
        await http.patch(f"/api/v1/plantillas/{p['id']}", json=cuerpo, headers=h)
    ).status_code == 422


async def test_otra_empresa_no_puede_editar(http, h, hb):
    p = await _crear(http, h)
    r = await http.patch(f"/api/v1/plantillas/{p['id']}", json={"nombre": "Robada"}, headers=hb)
    assert r.status_code == 404
    assert (await http.get(f"/api/v1/plantillas/{p['id']}", headers=h)).json()[
        "nombre"
    ] == "Constancia laboral"


# ------------------------------------------------------------------ duplicar (CON-05)


async def test_duplicar_copia_el_borrador_a_un_borrador_nuevo(http, h, datos, s3_plantillas):
    origen = await _crear(http, h, "Constancia laboral", descripcion="Original")
    contenido = {
        "esquema": 1,
        "bloques": [
            {"tipo": "parrafo", "contenido": [{"texto": "Borrador propio", "negrita": True}]}
        ],
    }
    await _guardar_borrador(http, h, origen, contenido)
    r = await http.post(f"/api/v1/plantillas/{origen['id']}/duplicar", headers=h)
    assert r.status_code == 201, r.text
    copia = r.json()
    assert copia["id"] != origen["id"] and copia["nombre"] == "Constancia laboral (copia)"
    assert (copia["estado"], copia["activa"], copia["version"], copia["emitidas"]) == (
        "BORRADOR", False, None, 0)  # fmt: skip
    assert copia["descripcion"] == "Original" and copia["tiene_borrador"] is True
    cuerpo, hash_ = canonico(contenido)
    # el contenido se copió a un objeto propio y el borrador del origen no cambió
    llaves = sql(
        datos,
        "SELECT plantilla_id, contenido_s3_key, hash_sha256 FROM constancias.borrador_plantilla ORDER BY plantilla_id",
    )
    assert len(llaves) == 2 and llaves[0][2] == llaves[1][2] == hash_
    assert llaves[1][1] == f"plantillas/{datos['a']}/{copia['id']}/borrador.json"
    assert await s3_plantillas[0].leer(llaves[1][1]) == cuerpo
    leido = (await http.get(f"/api/v1/plantillas/{copia['id']}/borrador", headers=h)).json()
    assert (
        leido["hash"] == hash_
        and leido["contenido"]["bloques"][0]["contenido"][0]["negrita"] is True
    )
    # la plantilla duplicada es independiente
    otro = {"esquema": 1, "bloques": []}
    await _guardar_borrador(http, h, copia, otro, if_match=hash_)
    assert (await http.get(f"/api/v1/plantillas/{origen['id']}/borrador", headers=h)).json()[
        "hash"
    ] == hash_
    bit = sql(
        datos,
        "SELECT detalle FROM auditoria.bitacora WHERE accion = 'PLANTILLA_CREADA' ORDER BY id",
    )
    assert bit == [({},), ({"plantilla_id": origen["id"]},)]


async def test_duplicar_sin_borrador_usa_la_ultima_version(http, h, datos, s3_plantillas):
    origen = await _crear(http, h)
    viejo = {"esquema": 1, "bloques": [{"tipo": "logotipo"}]}
    publicar_version(datos, s3_plantillas[0], origen["id"], 1, viejo)
    publicar_version(datos, s3_plantillas[0], origen["id"], 2, CONTENIDO)
    copia = (await http.post(f"/api/v1/plantillas/{origen['id']}/duplicar", headers=h)).json()
    assert (copia["version"], copia["estado"], copia["tiene_borrador"]) == (None, "BORRADOR", True)
    assert (await http.get(f"/api/v1/plantillas/{copia['id']}/borrador", headers=h)).json()[
        "hash"
    ] == canonico()[1]
    # las versiones no se copian
    assert sql(
        datos,
        "SELECT count(*) FROM constancias.version_plantilla WHERE plantilla_id = %s",
        (copia["id"],),
    ) == [(0,)]


async def test_duplicar_prefiere_el_borrador_a_la_version_publicada(http, h, datos, s3_plantillas):
    origen = await _crear(http, h)
    publicar_version(datos, s3_plantillas[0], origen["id"], 1, CONTENIDO)
    nuevo = {
        "esquema": 1,
        "bloques": [{"tipo": "parrafo", "contenido": [{"texto": "más reciente"}]}],
    }
    await _guardar_borrador(http, h, origen, nuevo)
    copia = (await http.post(f"/api/v1/plantillas/{origen['id']}/duplicar", headers=h)).json()
    assert (await http.get(f"/api/v1/plantillas/{copia['id']}/borrador", headers=h)).json()[
        "hash"
    ] == canonico(nuevo)[1]


async def test_duplicar_una_plantilla_vacia_y_nombres_sucesivos(http, h):
    origen = await _crear(http, h, "Base")
    nombres = []
    for _ in range(3):
        r = await http.post(f"/api/v1/plantillas/{origen['id']}/duplicar", headers=h)
        assert r.status_code == 201
        nombres.append(r.json()["nombre"])
    assert nombres == ["Base (copia)", "Base (copia 2)", "Base (copia 3)"]
    assert r.json()["tiene_borrador"] is False  # nada que copiar


async def test_duplicar_un_nombre_largo_cabe_en_120(http, h):
    origen = await _crear(http, h, "N" * 120)
    copia = (await http.post(f"/api/v1/plantillas/{origen['id']}/duplicar", headers=h)).json()
    assert len(copia["nombre"]) <= 120 and copia["nombre"].endswith(" (copia)")


async def test_duplicar_de_otra_empresa_o_inexistente_da_404(http, h, hb):
    p = await _crear(http, h)
    assert (
        await http.post(f"/api/v1/plantillas/{p['id']}/duplicar", headers=hb)
    ).status_code == 404
    assert (await http.post("/api/v1/plantillas/999999/duplicar", headers=h)).status_code == 404


# ------------------------------------------------------------------ eliminar (CON-06)


async def test_eliminar_es_logico_y_no_toca_las_constancias_emitidas(http, h, datos, s3_plantillas):
    p = await _crear(http, h)
    publicar_version(datos, s3_plantillas[0], p["id"], 1)
    await http.patch(f"/api/v1/plantillas/{p['id']}", json={"activa": True}, headers=h)
    constancia = emitir_constancia(datos, p["id"], 1)
    r = await http.delete(f"/api/v1/plantillas/{p['id']}", headers=h)
    assert r.status_code == 204 and r.content == b""
    # la fila sigue, oculta y desactivada; nada más cambió
    assert sql(datos, "SELECT eliminada, activa FROM constancias.plantilla_constancia") == [
        (True, False)
    ]
    assert sql(datos, "SELECT count(*) FROM constancias.version_plantilla") == [(1,)]
    assert sql(datos, "SELECT id, estado_vigencia FROM constancias.constancia_generada") == [
        (constancia, "VIGENTE")
    ]
    assert (await http.get("/api/v1/plantillas", headers=h)).json() == {"items": []}
    assert (await http.get(f"/api/v1/plantillas/{p['id']}", headers=h)).status_code == 404
    assert (
        await http.patch(f"/api/v1/plantillas/{p['id']}", json={"activa": True}, headers=h)
    ).status_code == 404
    assert (await http.delete(f"/api/v1/plantillas/{p['id']}", headers=h)).status_code == 404
    assert (await http.post(f"/api/v1/plantillas/{p['id']}/duplicar", headers=h)).status_code == 404
    assert sql(datos, "SELECT accion FROM auditoria.bitacora ORDER BY id")[-1] == (
        "PLANTILLA_ELIMINADA",
    )


async def test_el_nombre_de_una_plantilla_eliminada_queda_libre(http, h):
    p = await _crear(http, h, "Reutilizable")
    await http.delete(f"/api/v1/plantillas/{p['id']}", headers=h)
    otra = await _crear(http, h, "Reutilizable")
    assert otra["id"] != p["id"]


async def test_otra_empresa_no_puede_eliminar(http, h, hb):
    p = await _crear(http, h)
    assert (await http.delete(f"/api/v1/plantillas/{p['id']}", headers=hb)).status_code == 404
    assert (await http.get(f"/api/v1/plantillas/{p['id']}", headers=h)).status_code == 200


async def test_una_version_publicada_no_se_puede_modificar_ni_borrar_en_la_base(
    datos, s3_plantillas
):
    import psycopg

    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        p = c.execute(
            "INSERT INTO constancias.plantilla_constancia (empresa_id, nombre) VALUES (%s, 'X') RETURNING id",
            (datos["a"],),
        ).fetchone()[0]
    publicar_version(datos, s3_plantillas[0], p, 1)
    for consulta in (
        "UPDATE constancias.version_plantilla SET numero = 9",
        "DELETE FROM constancias.version_plantilla",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            sql(datos, consulta)
