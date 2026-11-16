"""T-109: CRUD de notificaciones, duplicar, destinatarios e indicadores (NOT-14 a 17, 21, 23, 24).

Base real con RLS. Las audiencias se evalúan con `colaboradores` simulado (el recorrido contra la
aplicación real está en ``test_notificaciones_individual_real.py``).
"""

import json
from datetime import UTC, datetime

import psycopg
import pytest
from ayudantes_notificaciones import (
    VARIABLES,
    insertar_destinatarios,
    insertar_plantilla,
    sql,
)
from cc_notificaciones.clientes import ItemAudiencia

pytestmark = pytest.mark.docker

BASE = "/api/v1/notificaciones"
CRITERIOS = {"op": "Y", "items": [{"campo": "planta_id", "operador": "es", "valor": 3}]}


@pytest.fixture
def plantilla(datos):
    return insertar_plantilla(datos)


def _cuerpo(plantilla, **cambios):
    base = {
        "titulo": "Entrega de uniformes",
        "modo": "CRITERIOS",
        "criterios": CRITERIOS,
        "plantilla_mensaje_id": plantilla,
        "variables": VARIABLES,
    }
    base.update(cambios)
    return {k: v for k, v in base.items() if v is not None}


async def _crear(http, h, plantilla, **cambios):
    r = await http.post(BASE, json=_cuerpo(plantilla, **cambios), headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _fila(datos, nid):
    return sql(
        datos,
        "SELECT estado, modo, audiencia_id, criterios_snapshot_json, variables_json, canal, "
        "zona_horaria, revisada_en, total_seleccionados FROM notificaciones.notificacion "
        "WHERE id = %s",
        (nid,),
    )[0]


def _codigos(r):
    return {(e["campo"], e["codigo"]) for e in r.json()["errores"]}


def _poner(datos, nid, **columnas):
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        for k, v in columnas.items():
            c.execute(f"UPDATE notificaciones.notificacion SET {k} = %s WHERE id = %s", (v, nid))  # noqa: S608


# ------------------------------------------------------------------ alta


async def test_alta_por_criterios_guarda_borrador_con_plantilla_y_variables(
    http, h, datos, plantilla
):
    d = await _crear(http, h, plantilla)
    assert d["estado"] == "BORRADOR" and d["modo"] == "CRITERIOS" and d["canal"] == "PLANTILLA_META"
    assert d["criterios"] == CRITERIOS and d["audiencia_id"] is None and d["colaborador_id"] is None
    assert d["plantilla"] == {
        "id": plantilla,
        "nombre": "aviso_uniformes_v1",
        "estado_meta": "APROBADA",
    }
    assert d["variables"] == VARIABLES
    assert d["vista_previa"] == "Hola {{nombre_completo}}, te esperamos el 13 nov 2026."
    assert d["zona_horaria"] == "America/Mexico_City" and d["respaldo_correo"] is False
    assert d["contadores"]["seleccionados"] == 0 and d["revisada_en"] is None
    assert [x["evento"] for x in d["linea_de_tiempo"]] == ["CREADA"]
    f = _fila(datos, d["id"])
    assert f[0] == "BORRADOR" and f[3] == CRITERIOS and f[5] == "PLANTILLA_META"


async def test_la_zona_horaria_se_valida_y_se_guarda(http, h, datos, plantilla):
    d = await _crear(http, h, plantilla, zona_horaria="America/Monterrey")
    assert d["zona_horaria"] == "America/Monterrey"
    r = await http.post(BASE, json=_cuerpo(plantilla, zona_horaria="Marte/Olimpo"), headers=h)
    assert r.status_code == 422 and ("zona_horaria", "ZONA_HORARIA_INVALIDA") in _codigos(r)


@pytest.mark.parametrize("estado", ["BORRADOR", "EN_REVISION", "RECHAZADA"])
async def test_solo_plantillas_aprobadas(http, h, datos, estado):
    p = insertar_plantilla(datos, nombre=f"p_{estado.lower()}", estado=estado)
    r = await http.post(BASE, json=_cuerpo(p), headers=h)
    assert r.status_code == 422, r.text
    assert r.json()["codigo"] == "PLANTILLA_META_NO_APROBADA"
    assert ("plantilla_mensaje_id", "PLANTILLA_META_NO_APROBADA") in _codigos(r)
    assert sql(datos, "SELECT count(*) FROM notificaciones.notificacion")[0][0] == 0


async def test_plantilla_inexistente_o_de_otra_empresa(http, h, datos):
    ajena = insertar_plantilla(datos, empresa=datos["b"], nombre="de_b")
    for pid in (999_999, ajena):
        r = await http.post(BASE, json=_cuerpo(pid), headers=h)
        assert r.status_code == 422 and (
            "plantilla_mensaje_id",
            "PLANTILLA_NO_ENCONTRADA",
        ) in _codigos(r)


@pytest.mark.parametrize("campo", ["mensaje", "texto", "texto_libre", "canal", "cuerpo"])
async def test_el_contrato_no_admite_texto_libre_ni_canal(http, h, plantilla, campo):
    r = await http.post(BASE, json=_cuerpo(plantilla, **{campo: "Hola a todos"}), headers=h)
    assert r.status_code == 422 and (campo, "CAMPO_NO_PERMITIDO") in _codigos(r)


async def test_el_esquema_openapi_no_tiene_texto_libre(http):
    from scripts.exportar_openapi import generar

    esquemas = json.loads(generar("notificaciones"))["components"]["schemas"]
    for nombre in ("NotificacionCrear", "NotificacionActualizar"):
        props = set(esquemas[nombre]["properties"])
        assert esquemas[nombre]["additionalProperties"] is False
        assert not props & {"mensaje", "texto", "canal", "texto_libre", "cuerpo"}
        assert "plantilla_mensaje_id" in props and "variables" in props


async def test_variables_validadas_contra_la_plantilla(http, h, plantilla):
    r = await http.post(BASE, json=_cuerpo(plantilla, variables={"1": VARIABLES["1"]}), headers=h)
    assert r.status_code == 422 and ("variables.2", "VARIABLE_FALTANTE") in _codigos(r)
    extra = {**VARIABLES, "3": VARIABLES["2"]}
    r = await http.post(BASE, json=_cuerpo(plantilla, variables=extra), headers=h)
    assert ("variables.3", "VARIABLE_NO_EXISTE") in _codigos(r)
    sensible = {**VARIABLES, "1": {"origen": "COLABORADOR", "campo": "CAMP-0001"}}
    r = await http.post(BASE, json=_cuerpo(plantilla, variables=sensible), headers=h)
    assert ("variables.1.campo", "CAMPO_SENSIBLE_NO_PERMITIDO") in _codigos(r)
    dinamico = {**VARIABLES, "1": {"origen": "COLABORADOR", "campo": "CAMP-0003"}}
    assert (
        await http.post(BASE, json=_cuerpo(plantilla, variables=dinamico), headers=h)
    ).status_code == 201
    mixta = {**VARIABLES, "1": {"origen": "FIJO", "campo": "x"}}
    assert (
        await http.post(BASE, json=_cuerpo(plantilla, variables=mixta), headers=h)
    ).status_code == 422


async def test_el_modo_exige_exactamente_su_audiencia(http, h, datos, plantilla):
    r = await http.post(BASE, json=_cuerpo(plantilla, criterios=None), headers=h)
    assert r.status_code == 422 and ("criterios", "AUDIENCIA_REQUERIDA") in _codigos(r)
    r = await http.post(BASE, json=_cuerpo(plantilla, colaborador_id=5), headers=h)
    assert ("colaborador_id", "AUDIENCIA_AMBIGUA") in _codigos(r)
    r = await http.post(BASE, json=_cuerpo(plantilla, modo="GRUPO", criterios=None), headers=h)
    assert ("audiencia_id", "AUDIENCIA_REQUERIDA") in _codigos(r)
    r = await http.post(BASE, json=_cuerpo(plantilla, modo="OTRO"), headers=h)
    assert r.status_code == 422
    assert sql(datos, "SELECT count(*) FROM notificaciones.notificacion")[0][0] == 0


async def test_criterios_en_linea_se_validan_con_el_catalogo(http, h, plantilla):
    sensible = {"op": "Y", "items": [{"campo": "CAMP-0001", "operador": "es", "valor": "x"}]}
    r = await http.post(BASE, json=_cuerpo(plantilla, criterios=sensible), headers=h)
    assert r.status_code == 422
    assert ("criterios.items.0.campo", "CAMPO_SENSIBLE_NO_FILTRABLE") in _codigos(r)
    r = await http.post(
        BASE, json=_cuerpo(plantilla, criterios={"op": "Y", "items": []}), headers=h
    )
    assert r.status_code == 422


async def test_modo_grupo_usa_una_audiencia_guardada_activa(http, h, hb, datos, plantilla):
    a = (
        await http.post(
            "/api/v1/audiencias", json={"nombre": "Norte", "criterios": CRITERIOS}, headers=h
        )
    ).json()
    d = await _crear(http, h, plantilla, modo="GRUPO", criterios=None, audiencia_id=a["id"])
    assert d["audiencia_id"] == a["id"] and d["audiencia_nombre"] == "Norte"
    assert d["criterios"] == CRITERIOS  # los de la audiencia
    assert _fila(datos, d["id"])[2] == a["id"]
    # inactiva
    await http.delete(f"/api/v1/audiencias/{a['id']}", headers=h)
    r = await http.post(
        BASE, json=_cuerpo(plantilla, modo="GRUPO", criterios=None, audiencia_id=a["id"]), headers=h
    )
    assert ("audiencia_id", "AUDIENCIA_INACTIVA") in _codigos(r)
    # de otra empresa o inexistente
    for aid in (a["id"], 999_999):
        pb = insertar_plantilla(datos, empresa=datos["b"], nombre=f"pb_{aid}")
        r = await http.post(
            BASE, json=_cuerpo(pb, modo="GRUPO", criterios=None, audiencia_id=aid), headers=hb
        )
        assert r.status_code == 422 and ("audiencia_id", "AUDIENCIA_NO_ENCONTRADA") in _codigos(r)


async def test_modo_individual_se_guarda_como_criterio_estable(
    http, h, datos, plantilla, colaboradores
):
    colaboradores.items[datos["a"]] = [ItemAudiencia(77, "Ana Pérez", "Apodaca", "1234", None)]
    d = await _crear(http, h, plantilla, modo="INDIVIDUAL", criterios=None, colaborador_id=77)
    crit = {"op": "Y", "items": [{"campo": "colaborador_id", "operador": "es", "valor": 77}]}
    assert d["modo"] == "INDIVIDUAL" and d["colaborador_id"] == 77 and d["criterios"] == crit
    assert _fila(datos, d["id"])[3] == crit
    assert (
        colaboradores.llamadas[-1]["criterios"] == crit
        and colaboradores.llamadas[-1]["solo_conteo"]
    )
    # colaborador inexistente (o de otra empresa): la evaluación da 0
    colaboradores.items[datos["a"]] = []
    r = await http.post(
        BASE,
        json=_cuerpo(plantilla, modo="INDIVIDUAL", criterios=None, colaborador_id=5),
        headers=h,
    )
    assert r.status_code == 422 and ("colaborador_id", "COLABORADOR_NO_ENCONTRADO") in _codigos(r)


# ------------------------------------------------------------------ edición


async def test_edicion_en_borrador(http, h, datos, plantilla):
    d = await _crear(http, h, plantilla)
    nuevas = {"1": {"origen": "FIJO", "valor": "equipo"}, "2": VARIABLES["2"]}
    r = await http.patch(
        f"{BASE}/{d['id']}",
        json={"titulo": "Otro título", "variables": nuevas, "respaldo_correo": True},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["titulo"] == "Otro título" and r.json()["respaldo_correo"] is True
    assert r.json()["variables"] == nuevas
    assert r.json()["vista_previa"] == "Hola equipo, te esperamos el 13 nov 2026."
    # otra plantilla aprobada con una sola variable exige variables acordes
    p2 = insertar_plantilla(datos, nombre="una_variable", texto="Aviso para {{1}}.")
    r = await http.patch(f"{BASE}/{d['id']}", json={"plantilla_mensaje_id": p2}, headers=h)
    assert r.status_code == 422 and ("variables.2", "VARIABLE_NO_EXISTE") in _codigos(r)
    r = await http.patch(
        f"{BASE}/{d['id']}",
        json={"plantilla_mensaje_id": p2, "variables": {"1": nuevas["1"]}},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["plantilla"]["id"] == p2
    # no se puede pasar a una no aprobada ni quedar vacío un campo
    pb = insertar_plantilla(datos, nombre="en_borrador", estado="BORRADOR", texto="Hola {{1}}")
    r = await http.patch(
        f"{BASE}/{d['id']}",
        json={"plantilla_mensaje_id": pb, "variables": {"1": nuevas["1"]}},
        headers=h,
    )
    assert r.status_code == 422 and r.json()["codigo"] == "PLANTILLA_META_NO_APROBADA"
    assert (
        await http.patch(f"{BASE}/{d['id']}", json={"titulo": None}, headers=h)
    ).status_code == 422
    assert (
        await http.patch(f"{BASE}/{d['id']}", json={"canal": "X"}, headers=h)
    ).status_code == 422


@pytest.mark.parametrize(
    "estado", ["PROGRAMADA", "ENVIANDO", "COMPLETADA", "CON_FALLAS", "CANCELADA"]
)
async def test_edicion_solo_en_borrador(http, h, datos, plantilla, estado):
    d = await _crear(http, h, plantilla)
    if estado == "PROGRAMADA":
        _poner(datos, d["id"], programada_para=datetime(2026, 12, 1, 15, tzinfo=UTC))
    _poner(datos, d["id"], estado=estado)
    r = await http.patch(f"{BASE}/{d['id']}", json={"titulo": "Nuevo"}, headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "ESTADO_INVALIDO"
    assert r.json()["detalle"] == {"estado_actual": estado, "estado_esperado": "BORRADOR"}


async def test_cambiar_la_audiencia_invalida_la_revision_pero_otros_cambios_no(
    http, h, datos, plantilla
):
    d = await _crear(http, h, plantilla)
    insertar_destinatarios(datos, d["id"], n=3)
    insertar_destinatarios(datos, d["id"], n=1, estado="EXCLUIDO")
    _poner(datos, d["id"], revisada_en=datetime(2026, 11, 17, tzinfo=UTC), total_seleccionados=4)
    # un cambio de título no toca la revisión
    await http.patch(f"{BASE}/{d['id']}", json={"titulo": "Nuevo título"}, headers=h)
    assert _fila(datos, d["id"])[7] is not None
    assert sql(datos, "SELECT count(*) FROM notificaciones.notificacion_destinatario")[0][0] == 4
    # cambiar los criterios sí
    otros = {"op": "Y", "items": [{"campo": "planta_id", "operador": "es", "valor": 9}]}
    r = await http.patch(f"{BASE}/{d['id']}", json={"criterios": otros}, headers=h)
    assert r.status_code == 200 and r.json()["criterios"] == otros
    assert r.json()["revisada_en"] is None and r.json()["contadores"]["seleccionados"] == 0
    f = _fila(datos, d["id"])
    assert f[7] is None and f[8] is None
    assert sql(datos, "SELECT count(*) FROM notificaciones.notificacion_destinatario")[0][0] == 0


async def test_cambiar_de_modo_exige_su_audiencia(http, h, datos, plantilla, colaboradores):
    d = await _crear(http, h, plantilla)
    r = await http.patch(f"{BASE}/{d['id']}", json={"modo": "INDIVIDUAL"}, headers=h)
    assert r.status_code == 422 and ("colaborador_id", "AUDIENCIA_REQUERIDA") in _codigos(r)
    colaboradores.items[datos["a"]] = [ItemAudiencia(5, "X", None, "0001", None)]
    r = await http.patch(
        f"{BASE}/{d['id']}", json={"modo": "INDIVIDUAL", "colaborador_id": 5}, headers=h
    )
    assert (
        r.status_code == 200
        and r.json()["colaborador_id"] == 5
        and r.json()["criterios"]["items"][0]["valor"] == 5
    )


# ------------------------------------------------------------------ listado y detalle


async def test_listado_por_pestanas_con_conteos_y_cursor(http, h, hb, datos, plantilla):
    ids = {}
    for i, estado in enumerate(
        ["BORRADOR", "BORRADOR", "ENVIANDO", "COMPLETADA", "CON_FALLAS", "CANCELADA"]
    ):
        d = await _crear(http, h, plantilla, titulo=f"N{i}")
        if estado != "BORRADOR":
            _poner(datos, d["id"], estado=estado)
        ids[i] = d["id"]
    prog = await _crear(http, h, plantilla, titulo="Prog")
    _poner(datos, prog["id"], programada_para=datetime(2026, 12, 1, 15, tzinfo=UTC))
    _poner(datos, prog["id"], estado="PROGRAMADA")
    pb = insertar_plantilla(datos, empresa=datos["b"], nombre="pb")
    await _crear(http, hb, pb, titulo="De B")

    envios = (await http.get(BASE, headers=h)).json()
    assert [i["estado"] for i in envios["items"]] == [
        "CANCELADA",
        "CON_FALLAS",
        "COMPLETADA",
        "ENVIANDO",
    ]
    assert envios["conteos"] == {"envios": 4, "programadas": 1, "borradores": 2}
    progs = (await http.get(BASE, params={"pestana": "programadas"}, headers=h)).json()
    assert [i["titulo"] for i in progs["items"]] == ["Prog"]
    bor = (await http.get(BASE, params={"pestana": "borradores"}, headers=h)).json()
    assert [i["titulo"] for i in bor["items"]] == ["N1", "N0"]
    # estado exacto
    r = (await http.get(BASE, params={"estado": "COMPLETADA"}, headers=h)).json()
    assert [i["titulo"] for i in r["items"]] == ["N3"]
    # cursor
    p1 = (await http.get(BASE, params={"limite": 3}, headers=h)).json()
    p2 = (await http.get(BASE, params={"limite": 3, "cursor": p1["siguiente"]}, headers=h)).json()
    assert len(p1["items"]) == 3 and len(p2["items"]) == 1 and p2["siguiente"] is None
    assert (await http.get(BASE, params={"pestana": "otra"}, headers=h)).status_code == 422
    # la otra empresa solo ve lo suyo
    assert [
        i["titulo"]
        for i in (await http.get(BASE, params={"pestana": "borradores"}, headers=hb)).json()[
            "items"
        ]
    ] == ["De B"]


async def test_detalle_con_contadores_acumulados_y_linea_de_tiempo(http, h, hb, datos, plantilla):
    d = await _crear(http, h, plantilla)
    insertar_destinatarios(datos, d["id"], n=2, estado="PENDIENTE")
    insertar_destinatarios(datos, d["id"], n=1, estado="EXCLUIDO")
    insertar_destinatarios(datos, d["id"], n=1, estado="ENVIADO")
    insertar_destinatarios(datos, d["id"], n=2, estado="ENTREGADO")
    insertar_destinatarios(datos, d["id"], n=1, estado="LEIDO")
    insertar_destinatarios(datos, d["id"], n=1, estado="RESPONDIO")
    insertar_destinatarios(datos, d["id"], n=1, estado="FALLIDO")
    _poner(datos, d["id"], revisada_en=datetime(2026, 11, 16, 20, 0, tzinfo=UTC))
    _poner(datos, d["id"], confirmada_en=datetime(2026, 11, 17, 16, 3, tzinfo=UTC))
    _poner(datos, d["id"], fecha_envio=datetime(2026, 11, 17, 16, 12, tzinfo=UTC))
    r = await http.get(f"{BASE}/{d['id']}", headers=h)
    assert r.status_code == 200
    c = r.json()["contadores"]
    assert c == {
        "seleccionados": 9,
        "excluidos": 1,
        "validos": 8,
        "enviados": 5,  # ENVIADO, 2 ENTREGADO, LEIDO, RESPONDIO
        "entregados": 4,
        "leidos": 2,
        "respondieron": 1,
        "fallidos": 1,
    }
    eventos = [x["evento"] for x in r.json()["linea_de_tiempo"]]
    assert set(eventos) == {"CREADA", "REVISADA", "CONFIRMADA", "ENVIADA"}
    tiempos = [x["en"] for x in r.json()["linea_de_tiempo"]]
    assert tiempos == sorted(tiempos)  # cronológica (PQ-17)
    assert (await http.get(f"{BASE}/{d['id']}", headers=hb)).status_code == 404
    assert (await http.get(f"{BASE}/999999", headers=h)).status_code == 404


# ------------------------------------------------------------------ destinatarios


async def test_destinatarios_con_celular_enmascarado(http, h, hb, datos, plantilla):
    d = await _crear(http, h, plantilla)
    insertar_destinatarios(datos, d["id"], n=5)
    insertar_destinatarios(datos, d["id"], n=2, estado="EXCLUIDO")
    r = await http.get(f"{BASE}/{d['id']}/destinatarios", headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 7
    ultimos = sql(
        datos,
        "SELECT celular_ultimos4 FROM notificaciones.notificacion_destinatario "
        "WHERE notificacion_id = %s ORDER BY id",
        (d["id"],),
    )
    for item, (u4,) in zip(items, ultimos, strict=True):
        assert item["celular_enmascarado"] == f"+52 •• •••• {u4}"
        assert set(item) >= {"nombre", "planta", "estado", "motivo_exclusion", "fecha_estado"}
    # el celular completo no existe: ni una cifra más de las 4 visibles en ningún campo
    assert "celular" not in {k for i in items for k in i} - {"celular_enmascarado"}
    mascaras = {i["celular_enmascarado"] for i in items}
    assert all(len(m.replace(" ", "")) == len("+52••••••") + 4 for m in mascaras)
    # filtro y cursor
    ex = (
        await http.get(f"{BASE}/{d['id']}/destinatarios", params={"estado": "EXCLUIDO"}, headers=h)
    ).json()
    assert len(ex["items"]) == 2 and all(
        i["motivo_exclusion"] == "SIN_CONSENTIMIENTO" for i in ex["items"]
    )
    p1 = (await http.get(f"{BASE}/{d['id']}/destinatarios", params={"limite": 4}, headers=h)).json()
    p2 = (
        await http.get(
            f"{BASE}/{d['id']}/destinatarios",
            params={"limite": 4, "cursor": p1["siguiente"]},
            headers=h,
        )
    ).json()
    assert len(p1["items"]) == 4 and len(p2["items"]) == 3 and p2["siguiente"] is None
    assert [i["id"] for i in p1["items"] + p2["items"]] == [i["id"] for i in items]
    # otra empresa y notificación inexistente
    assert (await http.get(f"{BASE}/{d['id']}/destinatarios", headers=hb)).status_code == 404
    assert (await http.get(f"{BASE}/999999/destinatarios", headers=h)).status_code == 404
    assert (
        await http.get(f"{BASE}/{d['id']}/destinatarios", params={"estado": "X"}, headers=h)
    ).status_code == 422


# ------------------------------------------------------------------ duplicar


async def test_duplicar_copia_plantilla_variables_y_criterios(http, h, hb, datos, plantilla):
    d = await _crear(http, h, plantilla, titulo="Entrega de uniformes", respaldo_correo=True)
    insertar_destinatarios(datos, d["id"], n=3)
    _poner(datos, d["id"], revisada_en=datetime(2026, 11, 17, tzinfo=UTC), estado="COMPLETADA")
    r = await http.post(f"{BASE}/{d['id']}/duplicar", headers=h)
    assert r.status_code == 201, r.text
    c = r.json()
    assert (
        c["id"] != d["id"]
        and c["estado"] == "BORRADOR"
        and c["titulo"] == "Entrega de uniformes (copia)"
    )
    assert c["plantilla"]["id"] == plantilla and c["variables"] == VARIABLES
    assert c["criterios"] == CRITERIOS and c["modo"] == "CRITERIOS" and c["respaldo_correo"] is True
    # sin revisión, destinatarios ni programación
    assert c["revisada_en"] is None and c["programada_para"] is None and c["fecha_envio"] is None
    assert c["contadores"]["seleccionados"] == 0 and c["confirmada_en"] is None
    # el original no cambia
    assert (await http.get(f"{BASE}/{d['id']}", headers=h)).json()["estado"] == "COMPLETADA"
    assert (await http.post(f"{BASE}/{d['id']}/duplicar", headers=hb)).status_code == 404


async def test_duplicar_una_audiencia_guardada_y_una_plantilla_ya_no_aprobada(
    http, h, datos, plantilla
):
    a = (
        await http.post(
            "/api/v1/audiencias", json={"nombre": "Norte", "criterios": CRITERIOS}, headers=h
        )
    ).json()
    d = await _crear(http, h, plantilla, modo="GRUPO", criterios=None, audiencia_id=a["id"])
    c = (await http.post(f"{BASE}/{d['id']}/duplicar", headers=h)).json()
    assert c["audiencia_id"] == a["id"] and c["modo"] == "GRUPO"
    sql(datos, "UPDATE notificaciones.plantilla_mensaje SET estado_meta = 'RECHAZADA'")
    r = await http.post(f"{BASE}/{d['id']}/duplicar", headers=h)
    assert r.status_code == 422 and r.json()["codigo"] == "PLANTILLA_META_NO_APROBADA"


# ------------------------------------------------------------------ indicadores


async def test_indicadores_del_mes_salen_del_servicio(http, h, hb, datos, plantilla, reloj):
    reloj.ahora = datetime(2026, 11, 17, 18, 0, tzinfo=UTC)

    async def notificacion(estado_dest, n, *, fecha_envio, titulo):
        d = await _crear(http, h, plantilla, titulo=titulo)
        insertar_destinatarios(datos, d["id"], n=n, estado=estado_dest)
        _poner(datos, d["id"], fecha_envio=fecha_envio, estado="COMPLETADA")
        return d

    nov = datetime(2026, 11, 5, 15, tzinfo=UTC)
    d = await notificacion("ENVIADO", 4, fecha_envio=nov, titulo="a")
    insertar_destinatarios(datos, d["id"], n=3, estado="ENTREGADO")
    insertar_destinatarios(datos, d["id"], n=2, estado="LEIDO")
    insertar_destinatarios(datos, d["id"], n=1, estado="RESPONDIO")
    insertar_destinatarios(datos, d["id"], n=2, estado="FALLIDO")
    insertar_destinatarios(datos, d["id"], n=5, estado="EXCLUIDO")
    insertar_destinatarios(datos, d["id"], n=5, estado="PENDIENTE")
    # otro mes: no cuenta
    await notificacion(
        "ENTREGADO", 7, fecha_envio=datetime(2026, 10, 31, 15, tzinfo=UTC), titulo="b"
    )
    # 05:00 UTC del 1 de diciembre sigue siendo noviembre en México (23:00 del 30): cuenta
    await notificacion(
        "ENVIADO", 2, fecha_envio=datetime(2026, 12, 1, 5, 0, tzinfo=UTC), titulo="c"
    )
    # despacho en curso (sin fecha_envio): cuenta por su confirmación
    en_curso = await _crear(http, h, plantilla, titulo="d")
    insertar_destinatarios(datos, en_curso["id"], n=3, estado="ENVIADO")
    _poner(
        datos,
        en_curso["id"],
        confirmada_en=datetime(2026, 11, 17, 17, tzinfo=UTC),
        estado="ENVIANDO",
    )
    # otra empresa
    pb = insertar_plantilla(datos, empresa=datos["b"], nombre="pb")
    nb = await _crear(http, hb, pb, titulo="b1")
    insertar_destinatarios(datos, nb["id"], empresa=datos["b"], n=50, estado="LEIDO")
    _poner(datos, nb["id"], fecha_envio=nov, estado="COMPLETADA")

    r = await http.get(f"{BASE}/indicadores", headers=h)
    assert r.status_code == 200, r.text
    i = r.json()
    # enviadas = 4 + 3 + 2 + 1 (a) + 2 (c) + 3 (d) = 15; entregadas = 3 + 2 + 1 = 6; leídas = 3
    assert i["mes"] == "2026-11"
    assert (i["enviadas"], i["entregadas"], i["leidas"], i["fallidas"]) == (15, 6, 3, 2)
    assert i["porcentaje_entregadas"] == 40.0 and i["porcentaje_leidas"] == 20.0
    assert i["conteos"] == {"envios": 4, "programadas": 0, "borradores": 0}
    # diciembre: la de las 05:00 UTC del 1 ya es de ese mes solo desde las 06:00 UTC
    reloj.ahora = datetime(2026, 12, 15, 18, 0, tzinfo=UTC)
    d2 = (await http.get(f"{BASE}/indicadores", headers=h)).json()
    assert d2["mes"] == "2026-12" and d2["enviadas"] == 0 and d2["porcentaje_entregadas"] == 0.0
    # la otra empresa ve solo lo suyo
    ib = (await http.get(f"{BASE}/indicadores", headers=hb)).json()
    assert ib["enviadas"] == 0
    reloj.ahora = datetime(2026, 11, 17, 18, 0, tzinfo=UTC)
    ib = (await http.get(f"{BASE}/indicadores", headers=hb)).json()
    assert ib["enviadas"] == 50 and ib["entregadas"] == 50 and ib["leidas"] == 50


async def test_sin_token_no_hay_acceso(http):
    for ruta in ("", "/indicadores", "/1", "/1/destinatarios"):
        assert (await http.get(BASE + ruta)).status_code == 401
    assert (await http.post(BASE, json={})).status_code == 401
    assert (await http.post(f"{BASE}/1/confirmar", json={"modo_envio": "AHORA"})).status_code == 401
