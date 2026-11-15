"""T-205: catálogo sembrado e interfaces internas (INT-CAM-01 e INT-CAM-02)."""

import pytest
from ayudantes_campos import interno, sql
from cc_campos import catalogo

pytestmark = pytest.mark.docker


async def _sembrar(http, datos, empresa="a", servicio="dashboard"):
    return await http.post(
        f"/internal/empresas/{datos[empresa]}/campos-sugeridos",
        headers=interno(servicio, datos[empresa]),
    )


async def test_la_siembra_crea_los_once_sugeridos_con_su_catalogo(http, datos):
    r = await _sembrar(http, datos)
    assert r.status_code == 201 and r.json() == {"creados": 11, "existentes": 0}
    filas = sql(
        datos,
        "SELECT clave, codigo_interno, tipo_dato, activo, es_sensible, es_sugerido, obligatorio, "
        "formato_validacion IS NOT NULL, orden FROM campos.campo_colaborador ORDER BY orden",
    )
    assert [f[0] for f in filas] == [s.clave for s in catalogo.SUGERIDOS]
    assert [f[1] for f in filas] == [f"CAMP-{i:04d}" for i in range(1, 12)]
    assert [f[8] for f in filas] == list(range(1, 12))
    por_clave = {f[0]: f for f in filas}
    assert por_clave["ruta_transporte"][3] is False  # nace inactivo
    assert all(f[3] for k, f in por_clave.items() if k != "ruta_transporte")
    assert sorted(k for k, f in por_clave.items() if f[4]) == ["curp", "nss", "rfc", "sueldo"]
    assert all(f[5] and not f[6] for f in filas)  # sugeridos y ninguno obligatorio
    assert por_clave["turno"][7] is False and por_clave["nss"][7] is True
    opciones = sql(
        datos,
        "SELECT o.etiqueta, o.valor, o.orden FROM campos.opcion_campo o "
        "JOIN campos.campo_colaborador c ON c.id = o.campo_id "
        "WHERE c.clave = 'periodicidad_sueldo' ORDER BY o.orden",
    )
    assert opciones == [
        ("Semanal", "SEMANAL", 1),
        ("Catorcenal", "CATORCENAL", 2),
        ("Quincenal", "QUINCENAL", 3),
        ("Mensual", "MENSUAL", 4),
    ]
    assert sql(datos, "SELECT count(*) FROM campos.opcion_campo") == [(4,)]
    assert sql(datos, "SELECT ultimo FROM campos.contador_campo") == [(11,)]
    bit = sql(datos, "SELECT accion, origen FROM auditoria.bitacora")
    assert bit == [("CAMPO_CREADO", "SISTEMA")] * 11
    ev = sql(datos, "SELECT payload->>'accion' FROM campos.outbox")
    assert ev == [("SEMBRADO",)]


async def test_la_siembra_es_idempotente(http, datos):
    await _sembrar(http, datos)
    antes = sql(datos, "SELECT id, codigo_interno FROM campos.campo_colaborador ORDER BY id")
    r = await _sembrar(http, datos)
    assert r.status_code == 201 and r.json() == {"creados": 0, "existentes": 11}
    assert (
        sql(datos, "SELECT id, codigo_interno FROM campos.campo_colaborador ORDER BY id") == antes
    )
    assert sql(datos, "SELECT count(*) FROM campos.opcion_campo") == [(4,)]
    assert sql(datos, "SELECT count(*) FROM campos.outbox") == [(1,)]  # sin cambios, sin evento


async def test_la_siembra_completa_lo_que_falta_sin_tocar_lo_editado(http, h, datos):
    await _sembrar(http, datos)
    cid = sql(datos, "SELECT id FROM campos.campo_colaborador WHERE clave = 'turno'")[0][0]
    await http.patch(
        f"/api/v1/campos/{cid}", json={"nombre_campo": "Horario", "activo": False}, headers=h
    )
    sql(datos, "DELETE FROM campos.campo_colaborador WHERE clave = 'correo'")
    r = await _sembrar(http, datos)
    assert r.json() == {"creados": 1, "existentes": 10}
    turno = sql(
        datos, "SELECT nombre_campo, activo FROM campos.campo_colaborador WHERE id = %s", (cid,)
    )
    assert turno == [("Horario", False)]  # la edición de RH se respeta


async def test_la_siembra_es_por_empresa(http, datos):
    await _sembrar(http, datos, "a")
    await _sembrar(http, datos, "b")
    cuentas = sql(
        datos,
        "SELECT empresa_id, count(*), min(codigo_interno), max(codigo_interno) "
        "FROM campos.campo_colaborador GROUP BY 1 ORDER BY 1",
    )
    assert cuentas == [
        (datos["a"], 11, "CAMP-0001", "CAMP-0011"),
        (datos["b"], 11, "CAMP-0001", "CAMP-0011"),
    ]


async def test_la_siembra_exige_servicio_permitido_y_empresa_coherente(http, datos):
    r = await _sembrar(http, datos, servicio="notificaciones")  # no está permitido
    assert r.status_code == 401
    r = await http.post(f"/internal/empresas/{datos['a']}/campos-sugeridos")
    assert r.status_code == 401
    r = await http.post(
        f"/internal/empresas/{datos['b']}/campos-sugeridos",
        headers=interno("bootstrap", datos["a"]),
    )
    assert r.status_code == 422 and r.json()["codigo"] == "EMPRESA_NO_COINCIDE"
    r = await http.post(
        f"/internal/empresas/{datos['a']}/campos-sugeridos", headers=interno("dashboard", None)
    )
    assert r.status_code == 422 and r.json()["codigo"] == "EMPRESA_REQUERIDA"
    assert sql(datos, "SELECT count(*) FROM campos.campo_colaborador") == [(0,)]


async def test_los_sugeridos_sembrados_no_se_eliminan_pero_se_desactivan(http, h, datos):
    await _sembrar(http, datos)
    cid = sql(datos, "SELECT id FROM campos.campo_colaborador WHERE clave = 'nss'")[0][0]
    assert (await http.delete(f"/api/v1/campos/{cid}", headers=h)).status_code == 409
    assert (
        await http.patch(f"/api/v1/campos/{cid}", json={"activo": False}, headers=h)
    ).status_code == 200


async def test_int_cam_01_devuelve_solo_los_activos_con_sus_opciones(http, h, datos):
    await _sembrar(http, datos)
    r = await http.get("/internal/campos", headers=interno("colaboradores", datos["a"]))
    assert r.status_code == 200
    campos = r.json()["campos"]
    claves = [c["clave"] for c in campos]
    assert "ruta_transporte" not in claves and len(campos) == 10  # inactivo fuera
    periodicidad = next(c for c in campos if c["clave"] == "periodicidad_sueldo")
    assert [o["valor"] for o in periodicidad["opciones"]] == [
        "SEMANAL",
        "CATORCENAL",
        "QUINCENAL",
        "MENSUAL",
    ]
    nss = next(c for c in campos if c["clave"] == "nss")
    assert nss["es_sensible"] is True and nss["formato_validacion"] == r"^\d{11}$"
    assert nss["codigo_interno"].startswith("CAMP-") and nss["opciones"] == []


async def test_int_cam_01_incluye_opciones_inactivas_y_excluye_eliminados(http, h, datos):
    await _sembrar(http, datos)
    turno = sql(datos, "SELECT id FROM campos.campo_colaborador WHERE clave = 'turno'")[0][0]
    r = await http.post(
        f"/api/v1/campos/{turno}/opciones", json={"etiqueta": "Noche", "valor": "NOCHE"}, headers=h
    )
    await http.patch(
        f"/api/v1/campos/{turno}/opciones/{r.json()['id']}", json={"activo": False}, headers=h
    )
    creado = (
        await http.post(
            "/api/v1/campos",
            json={"nombre_campo": "Temp", "clave": "temp", "tipo_dato": "TEXTO"},
            headers=h,
        )
    ).json()
    await http.delete(f"/api/v1/campos/{creado['id']}", headers=h)

    campos = (
        await http.get("/internal/campos", headers=interno("constancias", datos["a"]))
    ).json()["campos"]
    assert "temp" not in [c["clave"] for c in campos]
    opciones = next(c for c in campos if c["clave"] == "turno")["opciones"]
    assert [(o["valor"], o["activo"]) for o in opciones] == [("NOCHE", False)]  # con su bandera

    # con incluir_inactivos también salen los desactivados (conservan sus valores)
    todos = (
        await http.get(
            "/internal/campos?incluir_inactivos=true", headers=interno("constancias", datos["a"])
        )
    ).json()["campos"]
    assert "ruta_transporte" in [c["clave"] for c in todos] and "temp" not in [
        c["clave"] for c in todos
    ]


async def test_int_cam_01_es_por_empresa_y_exige_token(http, datos):
    await _sembrar(http, datos, "a")
    r = await http.get("/internal/campos", headers=interno("colaboradores", datos["b"]))
    assert r.json() == {"campos": []}
    assert (await http.get("/internal/campos")).status_code == 401
    assert (
        await http.get("/internal/campos", headers=interno("desconocido", datos["a"]))
    ).status_code == 401
