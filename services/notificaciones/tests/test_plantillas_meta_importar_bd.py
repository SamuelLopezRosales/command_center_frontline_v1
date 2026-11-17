"""Importar plantillas aprobadas de Meta: ``GET /plantillas-mensaje/meta`` e ``importar``.

Base real con RLS; Meta es el simulador de `whatsapp`. Cubre importar, idempotencia (también ante
concurrencia), conflicto de nombre, plantillas no compatibles, que la fila salga de los datos de
Meta y no de los del cliente, aislamiento entre empresas, bitácora, uso en una notificación y el
evento ``wa.plantilla_estado`` de una plantilla importada que Meta pausa.
"""

import asyncio
import json
import logging

import pytest
from ayudantes_notificaciones import cab, emitir, insertar_plantilla, sql
from cc_common.errores import ErrorValidacion
from cc_notificaciones import consumidores
from cc_notificaciones.servicios import variables as variables_servicio

pytestmark = pytest.mark.docker

BASE = "/api/v1/plantillas-mensaje"
LISTA = f"{BASE}/meta"
IMPORTAR = f"{BASE}/importar"
BIENVENIDA = "bienvenida_colaborador"
ES = "es_MX"


@pytest.fixture(autouse=True)
def _registro(caplog):
    caplog.set_level(logging.DEBUG)


@pytest.fixture
def catalogo(sim):
    sim.cargar_catalogo_ejemplo()
    return sim


def pedir(*nombres, idioma=ES):
    return {"plantillas": [{"nombre": n, "idioma": idioma} for n in nombres]}


def locales(datos, empresa=None):
    return sql(
        datos,
        "SELECT id, nombre, categoria, idioma, texto_con_variables, estado_meta, "
        "id_plantilla_meta, ejemplos_json, creada_por_usuario_id, empresa_id "
        "FROM notificaciones.plantilla_mensaje "
        + ("WHERE empresa_id = %s " if empresa else "")
        + "ORDER BY id",
        (empresa,) if empresa else (),
    )


def por_nombre(r):
    return {i["nombre"]: i for i in r.json()["items"]}


# ------------------------------------------------------------------ listado


async def test_lista_lo_de_meta_con_compatibilidad_ordenado_y_sin_cache(http, h, catalogo):
    r = await http.get(LISTA, headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    d = r.json()
    assert d["truncado"] is False
    nombres = [i["nombre"] for i in d["items"]]
    assert nombres == sorted(nombres) and len(nombres) == 6
    items = por_nombre(r)
    b = items[BIENVENIDA]
    assert b == {
        "nombre": BIENVENIDA,
        "idioma": ES,
        "categoria": "UTILITY",
        "estado_meta": "APPROVED",
        "id_plantilla_meta": "800000000000001",
        "texto": "Hola {{1}}, te damos la bienvenida a {{2}}. Tu primer día es el {{3}}.",
        "num_variables": 3,
        "compatible": True,
        "codigo_incompatible": None,
        "motivo_incompatible": None,
        "advertencias": b["advertencias"],
        "ya_importada": False,
        "nombre_en_uso": False,
    }
    assert len(b["advertencias"]) == 1  # pie de página
    esperados = {
        "bienvenida_con_boton": "TIENE_BOTONES",
        "bienvenida_con_imagen": "TIENE_ENCABEZADO",
        "bienvenida_nombrada": "VARIABLES_CON_NOMBRE",
        "bienvenida_rechazada": "ESTADO_NO_APROBADO",
        "bienvenida_pausada": "ESTADO_NO_APROBADO",
    }
    for nombre, codigo in esperados.items():
        assert items[nombre]["compatible"] is False, nombre
        assert items[nombre]["codigo_incompatible"] == codigo, nombre
        assert items[nombre]["motivo_incompatible"], nombre
    assert items["bienvenida_pausada"]["estado_meta"] == "PAUSED"
    assert "pausada" in items["bienvenida_pausada"]["motivo_incompatible"]
    assert items["bienvenida_con_imagen"]["categoria"] == "MARKETING"


async def test_el_listado_no_trae_credenciales_ni_las_registra(http, h, catalogo, caplog):
    r = await http.get(LISTA, headers=h)
    assert catalogo.access_token not in r.text and catalogo.access_token not in caplog.text
    assert catalogo.waba_id not in r.text


async def test_marca_ya_importada_por_id_y_nombre_en_uso(http, h, datos, catalogo):
    r = await http.post(IMPORTAR, json=pedir(BIENVENIDA), headers=h)
    assert r.status_code == 200, r.text
    # una local con el nombre de otra de Meta pero sin su id
    insertar_plantilla(datos, nombre="bienvenida_con_boton", estado="BORRADOR")
    items = por_nombre(await http.get(LISTA, headers=h))
    assert items[BIENVENIDA]["ya_importada"] is True and not items[BIENVENIDA]["nombre_en_uso"]
    assert items["bienvenida_con_boton"]["ya_importada"] is False
    assert items["bienvenida_con_boton"]["nombre_en_uso"] is True
    assert items["bienvenida_pausada"]["ya_importada"] is False


async def test_el_listado_trunca_como_dice_el_cliente(http, h, sim):
    for i in range(520):
        sim.agregar_catalogo(f"p_{i:04d}", cuerpo="Hola")
    d = (await http.get(LISTA, headers=h)).json()
    assert d["truncado"] is True and len(d["items"]) == 500


# ------------------------------------------------------------------ importar


async def test_importa_una_compatible_con_los_datos_de_meta(http, h, datos, catalogo):
    r = await http.post(IMPORTAR, json=pedir(BIENVENIDA), headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    (item,) = r.json()["items"]
    assert item["resultado"] == "IMPORTADA" and item["motivo"] is None
    assert (item["nombre"], item["idioma"]) == (BIENVENIDA, ES) and item["plantilla_id"]
    (f,) = locales(datos)
    assert f[0] == item["plantilla_id"]
    assert f[1:9] == (
        BIENVENIDA,
        "UTILITY",
        ES,
        "Hola {{1}}, te damos la bienvenida a {{2}}. Tu primer día es el {{3}}.",
        "APROBADA",
        "800000000000001",
        ["Ana", "Planta Apodaca", "lunes"],
        datos["ua"],
    )
    # aparece en el catálogo local y queda aprobada y lista para usarse
    d = (await http.get(f"{BASE}/{item['plantilla_id']}", headers=h)).json()
    assert d["estado_meta"] == "APROBADA" and d["cantidad_variables"] == 3
    assert d["id_plantilla_meta"] == "800000000000001" and d["motivo_rechazo"] is None


async def test_la_fila_sale_de_meta_y_no_de_lo_que_manda_el_cliente(http, h, datos, catalogo):
    # El cliente no puede mandar texto, categoría ni estado: el contrato lo prohíbe...
    for extra in (
        {"texto_con_variables": "Texto falso {{1}}"},
        {"categoria": "MARKETING"},
        {"estado_meta": "APROBADA"},
        {"id_plantilla_meta": "999"},
    ):
        cuerpo = {"plantillas": [{"nombre": BIENVENIDA, "idioma": ES, **extra}]}
        r = await http.post(IMPORTAR, json=cuerpo, headers=h)
        assert r.status_code == 422, extra
        assert (next(iter(extra)), "CAMPO_NO_PERMITIDO") in {
            (e["campo"].split(".")[-1], e["codigo"]) for e in r.json()["errores"]
        }
    assert locales(datos) == []
    # ...y si Meta cambia el texto entre el listado y la importación, manda lo de Meta.
    catalogo.catalogo_meta[0]["components"][0]["text"] = "Hola {{1}}, ¡bienvenido!"
    catalogo.catalogo_meta[0]["components"][0]["example"] = {"body_text": [["Luis"]]}
    r = await http.post(IMPORTAR, json=pedir(BIENVENIDA), headers=h)
    assert r.json()["items"][0]["resultado"] == "IMPORTADA"
    (f,) = locales(datos)
    assert f[4] == "Hola {{1}}, ¡bienvenido!" and f[7] == ["Luis"]


async def test_importar_dos_veces_no_cambia_nada_ni_falla(http, h, datos, catalogo):
    primera = (await http.post(IMPORTAR, json=pedir(BIENVENIDA), headers=h)).json()["items"][0]
    antes = locales(datos)
    r = await http.post(IMPORTAR, json=pedir(BIENVENIDA), headers=h)
    assert r.status_code == 200
    (item,) = r.json()["items"]
    assert item["resultado"] == "YA_EXISTIA" and item["motivo"] is None
    assert item["plantilla_id"] == primera["plantilla_id"]
    assert locales(datos) == antes
    assert (
        len(
            sql(
                datos,
                "SELECT 1 FROM auditoria.bitacora WHERE accion = 'PLANTILLA_MENSAJE_IMPORTADA'",
            )
        )
        == 1
    )


async def test_dos_importaciones_simultaneas_crean_una_sola_fila(http, h, datos, catalogo):
    respuestas = await asyncio.gather(
        *(http.post(IMPORTAR, json=pedir(BIENVENIDA), headers=h) for _ in range(5))
    )
    assert all(r.status_code == 200 for r in respuestas)
    resultados = sorted(r.json()["items"][0]["resultado"] for r in respuestas)
    assert resultados == ["IMPORTADA"] + ["YA_EXISTIA"] * 4
    assert len(locales(datos)) == 1
    assert (
        len(
            sql(
                datos,
                "SELECT 1 FROM auditoria.bitacora WHERE accion = 'PLANTILLA_MENSAJE_IMPORTADA'",
            )
        )
        == 1
    )


async def test_cada_elemento_va_por_separado_y_se_reporta(http, h, datos, catalogo):
    cuerpo = pedir(
        "bienvenida_con_boton",
        BIENVENIDA,
        "bienvenida_con_imagen",
        "bienvenida_nombrada",
        "bienvenida_rechazada",
        "bienvenida_pausada",
        "no_existe_en_meta",
    )
    r = await http.post(IMPORTAR, json=cuerpo, headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["nombre"] for i in items] == [p["nombre"] for p in cuerpo["plantillas"]]
    por = {i["nombre"]: i for i in items}
    assert por[BIENVENIDA]["resultado"] == "IMPORTADA"
    esperados = {
        "bienvenida_con_boton": "TIENE_BOTONES",
        "bienvenida_con_imagen": "TIENE_ENCABEZADO",
        "bienvenida_nombrada": "VARIABLES_CON_NOMBRE",
        "bienvenida_rechazada": "ESTADO_NO_APROBADO",
        "bienvenida_pausada": "ESTADO_NO_APROBADO",
        "no_existe_en_meta": "NO_ENCONTRADA_EN_META",
    }
    for nombre, codigo in esperados.items():
        assert por[nombre]["resultado"] == "OMITIDA", nombre
        assert por[nombre]["codigo"] == codigo and por[nombre]["motivo"], nombre
        assert por[nombre]["plantilla_id"] is None
    assert [f[1] for f in locales(datos)] == [BIENVENIDA]  # lo demás no se tocó


async def test_nombre_en_uso_con_otro_id_se_omite_sin_pisar_lo_local(http, h, datos, catalogo):
    local = insertar_plantilla(
        datos, nombre=BIENVENIDA, texto="Texto local {{1}}", estado="APROBADA"
    )
    r = await http.post(IMPORTAR, json=pedir(BIENVENIDA), headers=h)
    (item,) = r.json()["items"]
    assert item["resultado"] == "OMITIDA" and item["codigo"] == "NOMBRE_EN_USO"
    assert "Ya existe una plantilla local" in item["motivo"]
    (f,) = locales(datos)
    assert f[0] == local and f[4] == "Texto local {{1}}" and f[6] == f"TPL-{BIENVENIDA}"


async def test_mismo_nombre_en_otro_idioma_no_se_importa_por_el_idioma_de_envio(
    http, h, datos, sim
):
    sim.agregar_catalogo("aviso_general", id_="800000000000010", idioma=ES)
    sim.agregar_catalogo("aviso_general", id_="800000000000011", idioma="en_US")
    items = (await http.get(LISTA, headers=h)).json()["items"]
    por_idioma = {i["idioma"]: i for i in items if i["nombre"] == "aviso_general"}
    assert por_idioma[ES]["compatible"] and not por_idioma["en_US"]["compatible"]
    assert por_idioma["en_US"]["codigo_incompatible"] == "IDIOMA_NO_ENVIABLE"
    r = await http.post(IMPORTAR, json=pedir("aviso_general", idioma="en_US"), headers=h)
    assert r.json()["items"][0]["resultado"] == "OMITIDA"
    r = await http.post(IMPORTAR, json=pedir("aviso_general"), headers=h)
    assert r.json()["items"][0]["resultado"] == "IMPORTADA"
    assert [f[3] for f in locales(datos)] == [ES]


async def test_aislamiento_entre_empresas(http, h, hb, datos, catalogo):
    await http.post(IMPORTAR, json=pedir(BIENVENIDA), headers=h)
    # La empresa B no ve como importada la de A y puede importar la suya (única por empresa).
    assert por_nombre(await http.get(LISTA, headers=hb))[BIENVENIDA]["ya_importada"] is False
    rb = await http.post(IMPORTAR, json=pedir(BIENVENIDA), headers=hb)
    assert rb.json()["items"][0]["resultado"] == "IMPORTADA"
    assert [f[9] for f in locales(datos)] == [datos["a"], datos["b"]]
    assert por_nombre(await http.get(LISTA, headers=h))[BIENVENIDA]["ya_importada"] is True
    # y cada una ve solo lo suyo en el catálogo local
    ids_a = {p["id"] for p in (await http.get(BASE, headers=h)).json()["items"]}
    ids_b = {p["id"] for p in (await http.get(BASE, headers=hb)).json()["items"]}
    assert len(ids_a) == 1 and len(ids_b) == 1 and ids_a.isdisjoint(ids_b)
    assert (await http.get(f"{BASE}/{next(iter(ids_b))}", headers=h)).status_code == 404


async def test_sin_el_permiso_403_y_sin_token_401(http, datos, catalogo):
    sin_permiso = cab(emitir("sub-a", datos["a"], datos["ua"], rol="OTRO"))
    for metodo, url, cuerpo in (("GET", LISTA, None), ("POST", IMPORTAR, pedir(BIENVENIDA))):
        r = await http.request(metodo, url, json=cuerpo, headers=sin_permiso)
        assert r.status_code == 403, url
        r = await http.request(metodo, url, json=cuerpo)
        assert r.status_code == 401, url
    assert locales(datos) == []


async def test_validacion_del_cuerpo(http, h, datos, catalogo):
    r = await http.post(IMPORTAR, json={"plantillas": []}, headers=h)
    assert r.status_code == 422
    muchas = {"plantillas": [{"nombre": f"p_{i}", "idioma": ES} for i in range(51)]}
    assert (await http.post(IMPORTAR, json=muchas, headers=h)).status_code == 422
    justas = {"plantillas": [{"nombre": f"p_{i}", "idioma": ES} for i in range(50)]}
    r = await http.post(IMPORTAR, json=justas, headers=h)
    assert r.status_code == 200 and len(r.json()["items"]) == 50
    assert (await http.post(IMPORTAR, json={}, headers=h)).status_code == 422
    assert (
        await http.post(IMPORTAR, json={"plantillas": [{"nombre": "a"}]}, headers=h)
    ).status_code == 422
    assert (
        await http.post(IMPORTAR, json={"plantillas": [], "x": 1}, headers=h)
    ).status_code == 422


# ------------------------------------------------------------------ bitácora


async def test_bitacora_solo_con_ids_y_sin_credenciales(http, h, datos, catalogo, caplog):
    r = await http.post(IMPORTAR, json=pedir(BIENVENIDA, "bienvenida_pausada"), headers=h)
    nuevo = r.json()["items"][0]["plantilla_id"]
    filas = sql(
        datos,
        "SELECT empresa_id, usuario_id, accion, entidad, entidad_id, origen, detalle::text "
        "FROM auditoria.bitacora WHERE accion = 'PLANTILLA_MENSAJE_IMPORTADA'",
    )
    assert len(filas) == 1  # la omitida no deja registro
    empresa, usuario, accion, entidad, entidad_id, origen, detalle = filas[0]
    assert (empresa, usuario, entidad, entidad_id, origen) == (
        datos["a"],
        datos["ua"],
        "plantilla_mensaje",
        nuevo,
        "USUARIO",
    )
    assert json.loads(detalle) == {"plantilla_id": nuevo, "estado_nuevo": "APROBADA"}
    todo = detalle + caplog.text
    for secreto in (catalogo.access_token, "Hola {{1}}", "te damos la bienvenida"):
        assert secreto not in todo


# ------------------------------------------------------------------ uso en una notificación


async def test_una_importada_se_usa_tal_cual_en_una_notificacion(http, h, datos, catalogo):
    pid = (await http.post(IMPORTAR, json=pedir(BIENVENIDA), headers=h)).json()["items"][0][
        "plantilla_id"
    ]
    vars3 = {
        "1": {"origen": "COLABORADOR", "campo": "nombre_completo"},
        "2": {"origen": "COLABORADOR", "campo": "planta"},
        "3": {"origen": "FIJO", "valor": "lunes 17 de noviembre"},
    }
    cuerpo = {
        "titulo": "Bienvenida a nuevos ingresos",
        "modo": "CRITERIOS",
        "criterios": {"op": "Y", "items": [{"campo": "planta_id", "operador": "es", "valor": 3}]},
        "plantilla_mensaje_id": pid,
        "variables": vars3,
    }
    r = await http.post("/api/v1/notificaciones", json=cuerpo, headers=h)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["plantilla"] == {"id": pid, "nombre": BIENVENIDA, "estado_meta": "APROBADA"}
    assert d["variables"] == vars3
    assert (
        "{{nombre_completo}}" in d["vista_previa"] and "lunes 17 de noviembre" in d["vista_previa"]
    )
    # el número de variables se valida contra el texto importado
    faltante = {**cuerpo, "variables": {"1": vars3["1"], "2": vars3["2"]}}
    r = await http.post("/api/v1/notificaciones", json=faltante, headers=h)
    assert r.status_code == 422
    assert ("variables.3", "VARIABLE_FALTANTE") in {
        (e["campo"], e["codigo"]) for e in r.json()["errores"]
    }
    de_mas = {**cuerpo, "variables": {**vars3, "4": vars3["3"]}}
    r = await http.post("/api/v1/notificaciones", json=de_mas, headers=h)
    assert ("variables.4", "VARIABLE_NO_EXISTE") in {
        (e["campo"], e["codigo"]) for e in r.json()["errores"]
    }


def test_variables_valida_contra_el_texto_importado():
    texto = "Hola {{1}}, te damos la bienvenida a {{2}}. Tu primer día es el {{3}}."
    ok = {
        "1": {"origen": "COLABORADOR", "campo": "nombre_completo"},
        "2": {"origen": "FIJO", "valor": "Apodaca"},
        "3": {"origen": "FIJO", "valor": "lunes"},
    }
    variables_servicio.validar(ok, texto)
    with pytest.raises(ErrorValidacion):
        variables_servicio.validar({"1": ok["1"]}, texto)


# ------------------------------------------------------------------ eventos de estado


async def test_meta_pausa_una_importada_el_evento_no_la_cambia_y_se_deja_en_el_log(
    http, h, datos, motor, catalogo, caplog
):
    pid = (await http.post(IMPORTAR, json=pedir(BIENVENIDA), headers=h)).json()["items"][0][
        "plantilla_id"
    ]
    for estado in ("PAUSED", "DISABLED"):
        caplog.clear()
        evento = {
            "tipo": "wa.plantilla_estado",
            "nombre": BIENVENIDA,
            "estado_meta": estado,
            "motivo_rechazo": None,
        }
        assert await consumidores.manejar_evento(motor, evento) is False
        assert f"estado de Meta {estado}" in caplog.text
        assert BIENVENIDA not in caplog.text  # solo el estado, sin nombre ni texto
    estado_local = sql(
        datos, "SELECT estado_meta FROM notificaciones.plantilla_mensaje WHERE id = %s", (pid,)
    )
    # Riesgo documentado: sigue APROBADA aunque Meta la haya pausado o deshabilitado.
    assert estado_local == [("APROBADA",)]


async def test_con_el_sustituto_local_se_ve_y_se_importa_sin_llamar_a_meta(motor, h, datos):
    """``CC_META_PLANTILLAS_STUB`` en local: datos de ejemplo coherentes, sin red."""
    import httpx
    from ayudantes_notificaciones import construir_app
    from cc_notificaciones.meta import StubPlantillasMeta

    stub = StubPlantillasMeta()
    app = construir_app(motor, meta=stub)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        d = (await c.get(LISTA, headers=h)).json()
        compatibles = [i["nombre"] for i in d["items"] if i["compatible"]]
        assert compatibles == [BIENVENIDA]
        r = await c.post(IMPORTAR, json=pedir(BIENVENIDA), headers=h)
        assert r.json()["items"][0]["resultado"] == "IMPORTADA"
        d = (await c.get(LISTA, headers=h)).json()
        assert {i["nombre"] for i in d["items"] if i["ya_importada"]} == {BIENVENIDA}
    assert stub.listados == 3 and stub.creadas == []
