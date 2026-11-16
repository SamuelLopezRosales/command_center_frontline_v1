"""T-108: plantillas de mensaje y cliente de Meta (NOT-07 a NOT-13) con el simulador de Meta.

Base real con RLS; la API de Meta es el simulador de `whatsapp` por ``httpx.MockTransport``.
"""

import uuid

import pytest
from ayudantes_notificaciones import sql
from cc_notificaciones import consumidores
from cc_notificaciones.meta import ErrorMeta, MetaPlantillasHttp, StubPlantillasMeta

pytestmark = pytest.mark.docker

BASE = "/api/v1/plantillas-mensaje"
CUERPO = {
    "nombre": "aviso_uniformes_v1",
    "categoria": "UTILITY",
    "idioma": "es_MX",
    "texto_con_variables": "Hola {{1}}, mañana se entregan uniformes en {{2}}.",
    "ejemplos": ["Ana", "Planta Apodaca"],
}


async def _crear(http, h, **cambios):
    r = await http.post(BASE, json={**CUERPO, **cambios}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _revision(http, h, pid):
    return await http.post(f"{BASE}/{pid}/enviar-revision", headers=h)


def _estado(datos, pid):
    return sql(
        datos,
        "SELECT estado_meta, id_plantilla_meta, motivo_rechazo FROM "
        "notificaciones.plantilla_mensaje WHERE id = %s",
        (pid,),
    )[0]


def _evento(nombre, estado, motivo=None, *, con_id=True):
    """Lo que escribe ``estados-entrega`` en el outbox y publica ``publicador_aws``."""
    e = {
        "tipo": "wa.plantilla_estado",
        "nombre": nombre,
        "estado_meta": estado,
        "motivo_rechazo": motivo,
    }
    if con_id:
        e["evento_id"] = str(uuid.uuid4())
    return e


# ------------------------------------------------------------------ alta, edición y validación


async def test_alta_en_borrador_con_cantidad_de_variables(http, h, datos):
    d = await _crear(http, h)
    assert d["estado_meta"] == "BORRADOR" and d["id_plantilla_meta"] is None
    assert d["cantidad_variables"] == 2 and d["ejemplos"] == CUERPO["ejemplos"]
    assert d["motivo_rechazo"] is None and d["idioma"] == "es_MX"
    assert (await http.get(f"{BASE}/{d['id']}", headers=h)).json()["id"] == d["id"]


@pytest.mark.parametrize(
    ("cambio", "campo", "codigo"),
    [
        ({"nombre": "Aviso Uniformes"}, "nombre", "NOMBRE_INVALIDO"),
        ({"nombre": "aviso-uniformes"}, "nombre", "NOMBRE_INVALIDO"),
        (
            {"texto_con_variables": "Hola {{1}} y {{3}}", "ejemplos": ["a", "b"]},
            "texto_con_variables",
            "VARIABLES_NO_CONSECUTIVAS",
        ),
        ({"ejemplos": ["solo uno"]}, "ejemplos", "EJEMPLOS_NO_COINCIDEN"),
        ({"categoria": "OTRA"}, "categoria", "VALOR_NO_PERMITIDO"),
        ({"canal": "WHATSAPP"}, "canal", "CAMPO_NO_PERMITIDO"),
    ],
)
async def test_alta_invalida_da_422_por_campo(http, h, cambio, campo, codigo):
    r = await http.post(BASE, json={**CUERPO, **cambio}, headers=h)
    assert r.status_code == 422, r.text
    assert (campo, codigo) in {(e["campo"], e["codigo"]) for e in r.json()["errores"]}


async def test_nombre_duplicado_en_la_empresa_da_409_y_en_otra_empresa_no(http, h, hb):
    await _crear(http, h)
    r = await http.post(BASE, json=CUERPO, headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "PLANTILLA_NOMBRE_DUPLICADO"
    assert (await http.post(BASE, json=CUERPO, headers=hb)).status_code == 201


async def test_edicion_solo_en_borrador_o_rechazada(http, h, datos):
    d = await _crear(http, h)
    r = await http.patch(
        f"{BASE}/{d['id']}",
        json={"texto_con_variables": "Aviso {{1}}", "ejemplos": ["x"]},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["cantidad_variables"] == 1
    assert (await _revision(http, h, d["id"])).status_code == 202  # EN_REVISION
    r = await http.patch(f"{BASE}/{d['id']}", json={"nombre": "otro"}, headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "ESTADO_INVALIDO"
    assert r.json()["detalle"]["estado_actual"] == "EN_REVISION"
    # la aprobada tampoco se edita
    await consumidores.manejar_evento(http_motor(http), _evento(CUERPO["nombre"], "APPROVED"))
    r = await http.patch(f"{BASE}/{d['id']}", json={"nombre": "otro"}, headers=h)
    assert r.status_code == 409 and r.json()["detalle"]["estado_actual"] == "APROBADA"


def http_motor(http):
    return http._transport.app.state.motor


async def test_patch_valida_el_resultado_completo(http, h):
    d = await _crear(http, h)
    r = await http.patch(f"{BASE}/{d['id']}", json={"nombre": "Mal Nombre"}, headers=h)
    assert r.status_code == 422
    # quitar una variable sin ajustar los ejemplos
    r = await http.patch(f"{BASE}/{d['id']}", json={"texto_con_variables": "Hola {{1}}"}, headers=h)
    assert r.status_code == 422 and r.json()["errores"][0]["codigo"] == "EJEMPLOS_NO_COINCIDEN"
    # un campo nulo no es "dejar igual"
    assert (
        await http.patch(f"{BASE}/{d['id']}", json={"nombre": None}, headers=h)
    ).status_code == 422


async def test_listado_con_filtro_y_cursor(http, h, hb):
    ids = [(await _crear(http, h, nombre=f"plantilla_{i}"))["id"] for i in range(3)]
    await _crear(http, hb, nombre="de_otra_empresa")
    p1 = (await http.get(BASE, params={"limite": 2}, headers=h)).json()
    assert [i["id"] for i in p1["items"]] == ids[::-1][:2] and p1["siguiente"]
    p2 = (await http.get(BASE, params={"limite": 2, "cursor": p1["siguiente"]}, headers=h)).json()
    assert [i["id"] for i in p2["items"]] == [ids[0]] and p2["siguiente"] is None
    assert (await http.get(BASE, params={"estado": "APROBADA"}, headers=h)).json()["items"] == []
    r = await http.get(BASE, params={"cursor": "###"}, headers=h)
    assert r.status_code == 422 and r.json()["errores"][0]["campo"] == "cursor"


# ------------------------------------------------------------------ revisión en Meta


async def test_enviar_a_revision_guarda_el_id_de_meta_y_pasa_a_en_revision(http, h, datos, sim):
    d = await _crear(http, h)
    r = await _revision(http, h, d["id"])
    assert r.status_code == 202, r.text
    assert r.json()["estado_meta"] == "EN_REVISION" and r.json()["id_plantilla_meta"].startswith(
        "TPL"
    )
    assert _estado(datos, d["id"])[:2] == ("EN_REVISION", r.json()["id_plantilla_meta"])
    en_meta = sim.plantillas[CUERPO["nombre"]]
    assert en_meta["category"] == "UTILITY" and en_meta["language"] == "es_MX"
    assert en_meta["texto"] == CUERPO["texto_con_variables"]
    assert en_meta["ejemplo"] == {"body_text": [["Ana", "Planta Apodaca"]]}
    # repetir no crea otra plantilla en Meta
    r2 = await _revision(http, h, d["id"])
    assert r2.status_code == 409 and r2.json()["codigo"] == "ESTADO_INVALIDO"
    assert len(sim.plantillas) == 1


async def test_enviar_a_revision_solo_desde_borrador_o_rechazada_y_de_la_propia_empresa(
    http, h, hb, datos
):
    d = await _crear(http, h)
    assert (await _revision(http, hb, d["id"])).status_code == 404  # RLS
    assert (await http.get(f"{BASE}/{d['id']}", headers=hb)).status_code == 404
    assert (await _revision(http, h, 999_999)).status_code == 404


async def test_un_error_de_meta_da_502_y_no_cambia_el_estado(http, h, datos, sim):
    d = await _crear(http, h)
    sim.siguientes = [(503, 131000)]
    r = await _revision(http, h, d["id"])
    assert r.status_code == 502 and r.json()["codigo"] == "ERROR_PROVEEDOR_META"
    assert _estado(datos, d["id"]) == ("BORRADOR", None, None)
    # error permanente (parámetro inválido): también 502, y el reintento posterior funciona
    sim.siguientes = [(400, 100)]
    assert (await _revision(http, h, d["id"])).status_code == 502
    assert (await _revision(http, h, d["id"])).status_code == 202
    assert _estado(datos, d["id"])[0] == "EN_REVISION"


async def test_credenciales_malas_dan_502_sin_filtrar_el_token(http, h, datos, sim):
    from cc_notificaciones.meta import CredencialesMeta

    async def malas():
        return CredencialesMeta("token-equivocado", sim.waba_id)

    http._transport.app.state.meta = MetaPlantillasHttp(malas, transporte=sim.transporte())
    d = await _crear(http, h)
    r = await _revision(http, h, d["id"])  # Meta responde 401
    assert r.status_code == 502 and r.json()["codigo"] == "ERROR_PROVEEDOR_META"
    assert "token" not in r.text.lower()
    assert _estado(datos, d["id"])[0] == "BORRADOR"


async def test_el_nombre_repetido_en_meta_da_502(http, h, hb, datos, sim):
    a = await _crear(http, h)
    b = await _crear(http, hb)  # misma cuenta de WhatsApp, mismo nombre
    assert (await _revision(http, h, a["id"])).status_code == 202
    assert (await _revision(http, hb, b["id"])).status_code == 502


# ------------------------------------------------------------------ aprobación y rechazo por evento


async def test_la_aprobacion_por_evento_actualiza_el_estado(http, h, datos):
    d = await _crear(http, h)
    await _revision(http, h, d["id"])
    motor = http_motor(http)
    ev = _evento(CUERPO["nombre"], "APPROVED")
    assert await consumidores.manejar_evento(motor, ev) is True
    assert _estado(datos, d["id"])[0] == "APROBADA"
    # el mismo evento otra vez (entrega al menos una vez): sin efecto
    assert await consumidores.manejar_evento(motor, ev) is False
    assert _estado(datos, d["id"])[0] == "APROBADA"
    assert sql(datos, "SELECT count(*) FROM notificaciones.evento_procesado")[0][0] == 1


async def test_el_rechazo_por_evento_guarda_el_motivo_y_permite_editar_y_reenviar(
    http, h, datos, sim
):
    d = await _crear(http, h)
    await _revision(http, h, d["id"])
    motor = http_motor(http)
    await consumidores.manejar_evento(
        motor, _evento(CUERPO["nombre"], "REJECTED", "INVALID_FORMAT")
    )
    assert _estado(datos, d["id"])[0] == "RECHAZADA"
    assert _estado(datos, d["id"])[2] == "INVALID_FORMAT"
    visto = (await http.get(f"{BASE}/{d['id']}", headers=h)).json()
    assert visto["estado_meta"] == "RECHAZADA" and visto["motivo_rechazo"] == "INVALID_FORMAT"

    # se edita el texto; nombre, categoría e idioma ya no cambian (Meta no lo permite)
    r = await http.patch(f"{BASE}/{d['id']}", json={"nombre": "otro_nombre"}, headers=h)
    assert r.status_code == 422 and r.json()["errores"][0]["codigo"] == "CAMPO_NO_EDITABLE"
    nuevo = {"texto_con_variables": "Hola {{1}}, hay uniformes.", "ejemplos": ["Ana"]}
    assert (await http.patch(f"{BASE}/{d['id']}", json=nuevo, headers=h)).status_code == 200

    # el reenvío actualiza la plantilla en Meta (no crea otra) y limpia el motivo
    r = await _revision(http, h, d["id"])
    assert r.status_code == 202 and r.json()["estado_meta"] == "EN_REVISION"
    assert r.json()["motivo_rechazo"] is None
    assert len(sim.plantillas) == 1
    assert sim.plantillas[CUERPO["nombre"]]["texto"] == nuevo["texto_con_variables"]


async def test_un_rechazo_sin_motivo_guarda_sin_motivo(http, h, datos):
    d = await _crear(http, h)
    await _revision(http, h, d["id"])
    await consumidores.manejar_evento(
        http_motor(http), _evento(CUERPO["nombre"], "REJECTED", "NONE", con_id=False)
    )
    assert _estado(datos, d["id"])[0] == "RECHAZADA" and _estado(datos, d["id"])[2] == "SIN_MOTIVO"


async def test_eventos_que_no_cambian_nada(http, h, hb, datos):
    d = await _crear(http, h)
    otra = await _crear(http, hb, nombre="otra_plantilla")
    motor = http_motor(http)
    # sin enviar a revisión: un aviso de Meta no la aprueba
    assert await consumidores.manejar_evento(motor, _evento(CUERPO["nombre"], "APPROVED")) is False
    assert _estado(datos, d["id"])[0] == "BORRADOR"
    await _revision(http, h, d["id"])
    for estado in ("PENDING", "PAUSED", "DISABLED", "FLAGGED", "", None):
        assert await consumidores.manejar_evento(motor, _evento(CUERPO["nombre"], estado)) is False
    assert (
        await consumidores.manejar_evento(motor, _evento("nombre_que_no_existe", "APPROVED"))
        is False
    )
    assert await consumidores.manejar_evento(motor, {"tipo": "wa.plantilla_estado"}) is False
    assert _estado(datos, d["id"])[0] == "EN_REVISION"
    # el evento de una plantilla no toca a las de otro nombre ni empresa
    await consumidores.manejar_evento(motor, _evento(CUERPO["nombre"], "APPROVED"))
    assert _estado(datos, d["id"])[0] == "APROBADA" and _estado(datos, otra["id"])[0] == "BORRADOR"
    # una vez aprobada, un rechazo tardío no la degrada
    await consumidores.manejar_evento(motor, _evento(CUERPO["nombre"], "REJECTED", "X"))
    assert _estado(datos, d["id"])[0] == "APROBADA"


async def test_los_tipos_desconocidos_no_se_descartan(http):
    with pytest.raises(consumidores.EventoNoManejado):
        await consumidores.manejar_evento(http_motor(http), {"tipo": "wa.tipo_desconocido"})


# ------------------------------------------------------------------ sincronizar y duplicar


async def test_sincronizar_respalda_al_webhook(http, h, datos, sim):
    d = await _crear(http, h)
    r = await http.post(f"{BASE}/{d['id']}/sincronizar", headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "ESTADO_INVALIDO"  # aún en borrador
    await _revision(http, h, d["id"])
    # Meta todavía no resolvió: sigue EN_REVISION
    r = await http.post(f"{BASE}/{d['id']}/sincronizar", headers=h)
    assert r.status_code == 202 and r.json()["estado_meta"] == "EN_REVISION"
    # se perdió el webhook: Meta ya aprobó
    sim.aprobar(CUERPO["nombre"])
    r = await http.post(f"{BASE}/{d['id']}/sincronizar", headers=h)
    assert r.status_code == 202 and r.json()["estado_meta"] == "APROBADA"
    assert _estado(datos, d["id"])[0] == "APROBADA"
    # ya resuelta: no vuelve a consultar ni cambia
    sim.rechazar(CUERPO["nombre"])
    r = await http.post(f"{BASE}/{d['id']}/sincronizar", headers=h)
    assert r.json()["estado_meta"] == "APROBADA"


async def test_sincronizar_trae_el_rechazo_con_su_motivo(http, h, datos, sim):
    d = await _crear(http, h)
    await _revision(http, h, d["id"])
    sim.rechazar(CUERPO["nombre"], "TAG_CONTENT_MISMATCH")
    r = await http.post(f"{BASE}/{d['id']}/sincronizar", headers=h)
    assert r.json()["estado_meta"] == "RECHAZADA"
    assert r.json()["motivo_rechazo"] == "TAG_CONTENT_MISMATCH"


async def test_sincronizar_con_error_de_meta_da_502(http, h, datos, sim):
    d = await _crear(http, h)
    await _revision(http, h, d["id"])
    sim.siguientes = [(500, 1)]
    r = await http.post(f"{BASE}/{d['id']}/sincronizar", headers=h)
    assert r.status_code == 502 and r.json()["codigo"] == "ERROR_PROVEEDOR_META"
    assert _estado(datos, d["id"])[0] == "EN_REVISION"


async def test_sincronizar_y_evento_juntos_no_chocan(http, h, datos, sim):
    d = await _crear(http, h)
    await _revision(http, h, d["id"])
    sim.aprobar(CUERPO["nombre"])
    await consumidores.manejar_evento(http_motor(http), _evento(CUERPO["nombre"], "APPROVED"))
    r = await http.post(f"{BASE}/{d['id']}/sincronizar", headers=h)
    assert r.json()["estado_meta"] == "APROBADA"


async def test_duplicar_crea_un_borrador_con_nombre_nuevo(http, h, hb, datos):
    d = await _crear(http, h)
    await _revision(http, h, d["id"])
    await consumidores.manejar_evento(http_motor(http), _evento(CUERPO["nombre"], "APPROVED"))
    c1 = await http.post(f"{BASE}/{d['id']}/duplicar", headers=h)
    assert c1.status_code == 201, c1.text
    c1 = c1.json()
    assert c1["estado_meta"] == "BORRADOR" and c1["id_plantilla_meta"] is None
    assert c1["nombre"] == "aviso_uniformes_v1_copia" and c1["id"] != d["id"]
    assert c1["texto_con_variables"] == CUERPO["texto_con_variables"]
    assert c1["ejemplos"] == CUERPO["ejemplos"] and c1["motivo_rechazo"] is None
    c2 = (await http.post(f"{BASE}/{d['id']}/duplicar", headers=h)).json()
    assert c2["nombre"] == "aviso_uniformes_v1_copia_2"
    assert (await http.post(f"{BASE}/{d['id']}/duplicar", headers=hb)).status_code == 404


async def test_sin_token_o_con_otra_empresa_no_hay_acceso(http, datos):
    assert (await http.get(BASE)).status_code == 401
    assert (await http.post(f"{BASE}/1/enviar-revision")).status_code == 401


# ------------------------------------------------------------------ el cliente de Meta solo


async def test_cliente_meta_clasifica_errores_y_oculta_credenciales(sim):
    from cc_notificaciones.meta import CredencialesMeta

    async def cred():
        return CredencialesMeta(sim.access_token, sim.waba_id)

    cliente = MetaPlantillasHttp(cred, transporte=sim.transporte())
    assert "token" not in repr(await cred()).lower().replace("access_token", "")
    sim.siguientes = [(429, 130429)]
    with pytest.raises(ErrorMeta) as e:
        await cliente.consultar(nombre="x", idioma="es_MX")
    assert e.value.motivo == "META_TRANSITORIO" and e.value.codigo == "130429"
    assert await cliente.consultar(nombre="no_existe", idioma="es_MX") is None


async def test_cliente_meta_sin_secreto_configurado_falla_como_error_de_meta():
    from cc_notificaciones.meta import cargador_credenciales

    cliente = MetaPlantillasHttp(cargador_credenciales(None, "us-east-1"))
    with pytest.raises(ErrorMeta) as e:
        await cliente.consultar(nombre="x", idioma="es_MX")
    assert e.value.motivo == "META_SIN_CREDENCIALES"


async def test_credenciales_se_leen_de_secrets_manager_por_id():
    import json

    from cc_notificaciones.meta import cargador_credenciales

    class FakeSecretos:
        llamadas = 0

        def get_secret_value(self, SecretId):  # noqa: N803
            self.llamadas += 1
            assert SecretId == "cc/test/meta"  # pragma: allowlist secret
            return {"SecretString": json.dumps({"access_token": "tkn", "waba_id": "W1"})}

    f = FakeSecretos()
    leer = cargador_credenciales("cc/test/meta", "us-east-1", cliente=f)
    c = await leer()
    assert (c.access_token, c.waba_id) == ("tkn", "W1")
    await leer()
    assert f.llamadas == 1  # en caché


async def test_stub_de_meta_para_local(http):
    s = StubPlantillasMeta()
    p = await s.crear(nombre="a", categoria="UTILITY", idioma="es_MX", texto="x", ejemplos=[])
    assert p.estado == "PENDING" and (await s.consultar(nombre="a", idioma="es_MX")).id == p.id
