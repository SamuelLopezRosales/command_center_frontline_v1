"""Conexión con Meta (``/api/v1/integraciones/meta``): router, secreto y prueba de conexión.

No necesita Docker ni AWS: el secreto es un cliente de Secrets Manager en memoria, el motor es un
doble que anota las sentencias (candado y bitácora) y Meta es el simulador de `whatsapp`.
"""

import json
import logging
from datetime import UTC, datetime

import httpx
import pytest
from ayudantes_integraciones_meta import (
    ACCESS_TOKEN,
    APP_SECRET,
    COMPLETO,
    PATRON_TOKEN_VERIFICACION,
    PHONE_NUMBER_ID,
    VALOR_INICIAL_CDK,
    VERIFY_TOKEN,
    WABA_ID,
    ClienteSecretosFalso,
    MotorFalso,
    sin_secretos,
)
from ayudantes_notificaciones import Reloj, cab, construir_app, emitir, simulador_meta
from cc_common.auth import rutas_sin_permiso
from cc_notificaciones.integracion_meta import AlmacenSecretsManager, ultimos4

URL = "/api/v1/integraciones/meta"
GENERAR = f"{URL}/verify-token:generar"
PROBAR = f"{URL}/probar"
USUARIO_ID = 5
OTRO_TOKEN = "EAAotroTokenQueMetaRechaza0123456789"  # pragma: allowlist secret
H = cab(emitir("sub-a", 1, USUARIO_ID))


@pytest.fixture(autouse=True)
def _registro(caplog):
    caplog.set_level(logging.DEBUG)


@pytest.fixture
def secretos():
    return ClienteSecretosFalso()


@pytest.fixture
def motor_falso():
    return MotorFalso()


@pytest.fixture
def sim():
    return simulador_meta().SimuladorMeta(
        access_token=ACCESS_TOKEN,
        app_secret=APP_SECRET,
        verify_token=VERIFY_TOKEN,
        phone_number_id=PHONE_NUMBER_ID,
        waba_id=WABA_ID,
    )


@pytest.fixture
def solicitudes_meta():
    return []


@pytest.fixture
def reloj_prueba():
    return Reloj(datetime(2026, 11, 17, 18, 0, tzinfo=UTC))


@pytest.fixture
def app(motor_falso, secretos, sim, solicitudes_meta, reloj_prueba):
    def responder(peticion: httpx.Request) -> httpx.Response:
        solicitudes_meta.append(peticion)
        return sim._responder(peticion)

    return construir_app(
        motor_falso,
        almacen_meta=AlmacenSecretsManager("cc/test/meta", "us-east-1", cliente=secretos),
        transporte_sonda_meta=httpx.MockTransport(responder),
        reloj=reloj_prueba,
    )


@pytest.fixture
async def cliente(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def guardar_todo(cliente, **cambios):
    r = await cliente.put(URL, json={**COMPLETO, **cambios}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------------------------- lectura
async def test_sin_configurar_con_el_valor_inicial_de_cdk(cliente):
    r = await cliente.get(URL, headers=H)
    assert r.status_code == 200
    assert r.json() == {
        "configurada": False,
        "waba_id": None,
        "phone_number_id": None,
        "api_version": "v21.0",
        "access_token": {"configurado": False, "ultimos4": None},
        "app_secret": {"configurado": False, "ultimos4": None},
        "verify_token": {"configurado": False},
        "actualizado_en": None,
        "actualizado_por_usuario_id": None,
    }
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("valor", [None, "", "   ", "CAMBIAR", "[1, 2]", '"texto"', "{no es json"])
async def test_un_secreto_vacio_o_que_no_es_json_cuenta_como_no_configurada(
    cliente, secretos, valor
):
    secretos.valor = valor
    r = await cliente.get(URL, headers=H)
    assert r.status_code == 200 and r.json()["configurada"] is False
    # Y al guardar se reemplaza con un JSON válido.
    await cliente.put(URL, json={"waba_id": WABA_ID}, headers=H)
    assert secretos.json["waba_id"] == WABA_ID


async def test_put_parcial_solo_cambia_lo_enviado_y_conserva_el_resto(
    cliente, secretos, reloj_prueba
):
    r = await cliente.put(
        URL, json={"waba_id": WABA_ID, "phone_number_id": PHONE_NUMBER_ID}, headers=H
    )
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["waba_id"] == WABA_ID and cuerpo["configurada"] is False
    assert cuerpo["actualizado_por_usuario_id"] == USUARIO_ID
    assert cuerpo["actualizado_en"].startswith("2026-11-17T18:00:00")

    r = await cliente.put(URL, json={"access_token": ACCESS_TOKEN}, headers=H)
    assert r.json()["waba_id"] == WABA_ID  # se conservó
    assert r.json()["access_token"] == {"configurado": True, "ultimos4": ACCESS_TOKEN[-4:]}
    # Solo claves conocidas: se descartan las del valor inicial de CDK.
    assert set(secretos.json) == {
        "waba_id",
        "phone_number_id",
        "access_token",
        "actualizado_en",
        "actualizado_por_usuario_id",
    }

    r = await cliente.put(
        URL,
        json={"app_secret": APP_SECRET, "verify_token": VERIFY_TOKEN, "api_version": "v22.0"},
        headers=H,
    )
    cuerpo = r.json()
    assert cuerpo["configurada"] is True and cuerpo["api_version"] == "v22.0"
    assert cuerpo["app_secret"] == {"configurado": True, "ultimos4": APP_SECRET[-4:]}
    assert cuerpo["verify_token"] == {"configurado": True}
    guardado = secretos.json
    assert {k: guardado[k] for k in COMPLETO} == COMPLETO
    assert guardado["api_version"] == "v22.0"
    assert (await cliente.get(URL, headers=H)).json() == cuerpo


async def test_un_valor_secreto_corto_no_revela_ni_los_ultimos_4(cliente, secretos):
    secretos.valor = json.dumps({"access_token": "corto12345", "app_secret": "x" * 11})
    cuerpo = (await cliente.get(URL, headers=H)).json()
    assert cuerpo["access_token"] == {"configurado": True, "ultimos4": None}
    assert cuerpo["app_secret"] == {"configurado": True, "ultimos4": None}
    assert ultimos4("a" * 12) == "aaaa" and ultimos4("a" * 11) is None and ultimos4(None) is None


async def test_el_mismo_valor_no_escribe_ni_registra_bitacora(cliente, secretos, motor_falso):
    await guardar_todo(cliente)
    escrituras, registros = len(secretos.escrituras), len(motor_falso.bitacora())
    r = await cliente.put(URL, json={"waba_id": WABA_ID, "access_token": ACCESS_TOKEN}, headers=H)
    assert r.status_code == 200
    assert len(secretos.escrituras) == escrituras and len(motor_falso.bitacora()) == registros


# ------------------------------------------------------------------------------ validaciones
CASOS_INVALIDOS = [
    ("waba_id", "WABA-MARCA-12"),
    ("waba_id", "1234567"),
    ("waba_id", "1" * 26),
    ("phone_number_id", "12345678MARCA"),
    ("phone_number_id", "+5218112345678"),
    ("api_version", "22.5"),
    ("api_version", "v99"),
    ("api_version", "vX.1MARCA"),
    ("access_token", "EAAcortoMARCA"),
    ("access_token", "EAA token con espacios dentro MARCA 0123456789"),
    ("access_token", "EAA" + "a" * 1001),
    ("app_secret", "0123456789abcdef0123456789abcde"),  # pragma: allowlist secret
    ("app_secret", "g" * 32),
    ("app_secret", "0123456789abcdef0123456789abcdef0"),  # pragma: allowlist secret
    ("verify_token", "cortoMARCA"),
    ("verify_token", "con espacios y ñ MARCA 1234567890"),
    ("verify_token", "a" * 129),
    *[
        (c, v)
        for c in (
            "waba_id",
            "phone_number_id",
            "api_version",
            "access_token",
            "app_secret",
            "verify_token",
        )
        for v in ("", "   ", None)
    ],
]


@pytest.mark.parametrize(("campo", "valor"), CASOS_INVALIDOS)
async def test_valores_invalidos_dan_422_sin_repetir_el_valor(
    cliente, secretos, motor_falso, campo, valor
):
    r = await cliente.put(URL, json={campo: valor}, headers=H)
    assert r.status_code == 422
    cuerpo = r.json()
    assert cuerpo["codigo"] == "VALIDACION_FALLIDA"
    assert [e["campo"] for e in cuerpo["errores"]] == [campo]
    if valor and valor.strip():
        assert valor not in r.text
    assert secretos.escrituras == [] and motor_falso.bitacora() == []


async def test_cuerpo_vacio_campos_extra_y_tipos_incorrectos_dan_422(cliente, secretos):
    assert (await cliente.put(URL, json={}, headers=H)).status_code == 422
    for cuerpo in (
        {"meta_api_base": "https://servidor-ajeno.test"},  # el servidor NO es editable
        {"waba_id": WABA_ID, "otro": "x"},
        {"waba_id": 12345678901},
        {"access_token": ["EAA" + "a" * 30]},
    ):
        r = await cliente.put(URL, json=cuerpo, headers=H)
        assert r.status_code == 422, cuerpo
        assert "servidor-ajeno" not in r.text and "aaaaaaaa" not in r.text
    assert secretos.escrituras == []


async def test_los_espacios_en_los_extremos_se_recortan(cliente, secretos):
    await cliente.put(URL, json={"access_token": f"  {ACCESS_TOKEN}\n"}, headers=H)
    assert secretos.json["access_token"] == ACCESS_TOKEN


# --------------------------------------------------------------------- secretos fuera de todo
async def test_ninguna_respuesta_ni_log_contiene_un_valor_secreto(cliente, caplog):
    textos = []
    r = await cliente.put(URL, json=COMPLETO, headers=H)
    textos.append(r.text)
    textos.append((await cliente.get(URL, headers=H)).text)
    textos.append((await cliente.post(PROBAR, headers=H)).text)
    # Un error con el token enviado también calla el valor.
    textos.append(
        (await cliente.put(URL, json={"access_token": ACCESS_TOKEN + " x"}, headers=H)).text
    )
    for t in textos:
        assert sin_secretos(t), t
    assert sin_secretos(caplog.text)
    for registro in caplog.records:
        assert sin_secretos(registro.getMessage()) and sin_secretos(str(registro.args))


async def test_la_bitacora_lleva_solo_nombres_de_campos(cliente, motor_falso):
    await cliente.put(URL, json=COMPLETO, headers=H)
    (registro,) = motor_falso.bitacora()
    assert registro["accion"] == "META_CONFIGURADA"
    assert registro["usuario_id"] == USUARIO_ID and registro["empresa_id"] == 1
    assert registro["detalle"] == {
        "campos": sorted(
            ["waba_id", "phone_number_id", "access_token", "app_secret", "verify_token"]
        )
    }
    assert sin_secretos(json.dumps(registro)) and WABA_ID not in json.dumps(registro)
    assert motor_falso.candados() == 1  # el guardado corre bajo el candado de asesoría


async def test_si_falla_secrets_manager_se_revierte_y_no_se_filtra(
    cliente, secretos, motor_falso, caplog
):
    secretos.falla_escritura = True
    r = await cliente.put(URL, json=COMPLETO, headers=H)
    assert r.status_code == 502 and r.json()["codigo"] == "ALMACEN_CREDENCIALES_NO_DISPONIBLE"
    assert motor_falso.revertidas == 1  # la bitácora no queda sin que el secreto se haya escrito
    assert sin_secretos(r.text) and sin_secretos(caplog.text)
    assert "cc/test/meta" not in r.text


# ---------------------------------------------------------------------------- verify token
async def test_generar_verify_token_se_devuelve_una_vez_y_el_get_no_lo_muestra(
    cliente, secretos, motor_falso
):
    r = await cliente.post(GENERAR, headers=H)
    assert r.status_code == 200
    assert set(r.json()) == {"verify_token"}
    token = r.json()["verify_token"]
    assert PATRON_TOKEN_VERIFICACION.match(token) and len(token) >= 32
    assert secretos.json["verify_token"] == token
    leido = await cliente.get(URL, headers=H)
    assert token not in leido.text and leido.json()["verify_token"] == {"configurado": True}
    otro = (await cliente.post(GENERAR, headers=H)).json()["verify_token"]
    assert otro != token and secretos.json["verify_token"] == otro
    assert [b["detalle"] for b in motor_falso.bitacora()] == [{"campos": ["verify_token"]}] * 2
    assert token not in json.dumps(motor_falso.bitacora())


# ------------------------------------------------------------------------------- permisos
async def test_sin_el_permiso_403_y_sin_token_401(cliente, secretos):
    sin_permiso = cab(emitir("sub-a", 1, USUARIO_ID, rol="OTRO"))
    for metodo, url, cuerpo in (
        ("GET", URL, None),
        ("PUT", URL, {"waba_id": WABA_ID}),
        ("POST", GENERAR, None),
        ("POST", PROBAR, None),
    ):
        r = await cliente.request(metodo, url, json=cuerpo, headers=sin_permiso)
        assert r.status_code == 403, (metodo, url)
        r = await cliente.request(metodo, url, json=cuerpo)
        assert r.status_code == 401, (metodo, url)
    assert secretos.escrituras == []


def test_todas_las_rutas_declaran_permiso(app):
    assert rutas_sin_permiso(app) == []
    rutas = {r for r in rutas_declaradas(app) if "integraciones" in r}
    assert len(rutas) == 4


def rutas_declaradas(app):
    from cc_common.auth import _aplanar

    return {
        f"{','.join(sorted(getattr(r, 'methods', [])))} {camino}"
        for camino, r in _aplanar(app.routes)
    }


def test_el_permiso_nuevo_es_de_rh_y_esta_en_el_catalogo():
    from cc_common.permisos import ROL_PERMISOS, Permiso, tiene_permiso

    assert Permiso.INTEGRACIONES_ADMINISTRAR.value == "integraciones:administrar"
    assert tiene_permiso("RH", Permiso.INTEGRACIONES_ADMINISTRAR)
    assert ROL_PERMISOS["RH"] == frozenset(Permiso)
    assert not tiene_permiso("OTRO", Permiso.INTEGRACIONES_ADMINISTRAR)


# --------------------------------------------------------------------------------- probar
RESULTADOS = ["token", "numero", "waba", "webhook"]


def _claves(cuerpo):
    return {x["clave"]: x["ok"] for x in cuerpo["resultados"]}


async def test_probar_sin_credenciales_es_422_meta_no_configurada(cliente, motor_falso):
    await cliente.put(URL, json={"waba_id": WABA_ID}, headers=H)
    r = await cliente.post(PROBAR, headers=H)
    assert r.status_code == 422
    assert r.json()["codigo"] == "META_NO_CONFIGURADA"
    assert [e["campo"] for e in r.json()["errores"]] == ["phone_number_id", "access_token"]
    assert [b["accion"] for b in motor_falso.bitacora()] == ["META_CONFIGURADA"]


async def test_probar_con_exito(cliente, sim, solicitudes_meta, motor_falso):
    await guardar_todo(cliente)
    r = await cliente.post(PROBAR, headers=H)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["ok"] is True and cuerpo["webhook_suscrito"] is True
    assert [x["clave"] for x in cuerpo["resultados"]] == RESULTADOS
    assert all(x["ok"] for x in cuerpo["resultados"])
    assert cuerpo["numero"] == {
        "nombre_verificado": sim.nombre_verificado,
        "numero_mostrado": sim.numero_mostrado,
        "calidad": sim.calidad,
    }
    assert sim.consultas == [
        f"/v21.0/{PHONE_NUMBER_ID}",
        f"/v21.0/{WABA_ID}",
        f"/v21.0/{WABA_ID}/subscribed_apps",
    ]
    # El token viaja solo en el encabezado, nunca en la URL.
    assert all(p.headers["authorization"] == f"Bearer {ACCESS_TOKEN}" for p in solicitudes_meta)
    assert all(ACCESS_TOKEN not in str(p.url) for p in solicitudes_meta)
    assert (
        solicitudes_meta[0].url.params["fields"]
        == "display_phone_number,verified_name,quality_rating"
    )
    assert solicitudes_meta[1].url.params["fields"] == "id,name"
    assert sin_secretos(r.text)
    assert motor_falso.bitacora()[-1] == {
        "accion": "META_PROBADA",
        "usuario_id": USUARIO_ID,
        "empresa_id": 1,
        "entidad": "integracion_meta",
        "detalle": {"estado_nuevo": "OK"},
    }


async def test_probar_usa_la_version_guardada(cliente, sim):
    await guardar_todo(cliente, api_version="v19.0")
    await cliente.post(PROBAR, headers=H)
    assert all(c.startswith("/v19.0/") for c in sim.consultas)


async def test_probar_token_invalido_190(cliente, sim, solicitudes_meta, motor_falso):
    await guardar_todo(cliente, access_token=OTRO_TOKEN)
    r = await cliente.post(PROBAR, headers=H)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["ok"] is False and cuerpo["numero"] is None and cuerpo["webhook_suscrito"] is None
    assert _claves(cuerpo) == dict.fromkeys(RESULTADOS, False)
    assert "rechazó el token" in cuerpo["resultados"][0]["detalle"]
    assert len(solicitudes_meta) == 1  # con el token rechazado no se sigue consultando
    assert "EAAotroToken" not in r.text
    assert motor_falso.bitacora()[-1]["detalle"] == {"estado_nuevo": "FALLO", "campos": RESULTADOS}


async def test_probar_permisos_insuficientes_10(cliente, sim):
    sim.fallos_consulta["numero"] = (403, 10)
    await guardar_todo(cliente)
    cuerpo = (await cliente.post(PROBAR, headers=H)).json()
    assert cuerpo["ok"] is False
    assert _claves(cuerpo) == {"token": False, "numero": False, "waba": True, "webhook": True}
    assert "whatsapp_business_messaging" in cuerpo["resultados"][0]["detalle"]


async def test_probar_waba_inexistente_100(cliente, sim):
    sim.fallos_consulta["waba"] = (400, 100)
    await guardar_todo(cliente)
    cuerpo = (await cliente.post(PROBAR, headers=H)).json()
    assert cuerpo["ok"] is False and cuerpo["webhook_suscrito"] is None
    assert _claves(cuerpo) == {"token": True, "numero": True, "waba": False, "webhook": False}
    assert "WABA ID" in cuerpo["resultados"][2]["detalle"]
    assert cuerpo["numero"]["nombre_verificado"] == sim.nombre_verificado


async def test_probar_phone_number_id_inexistente(cliente):
    await guardar_todo(cliente, phone_number_id="1111111111")
    cuerpo = (await cliente.post(PROBAR, headers=H)).json()
    assert _claves(cuerpo) == {"token": True, "numero": False, "waba": True, "webhook": True}
    assert "Phone Number ID" in cuerpo["resultados"][1]["detalle"]
    assert cuerpo["ok"] is False


@pytest.mark.parametrize(
    ("fallo", "texto"),
    [
        ("tiempo", "no respondió a tiempo"),
        ((429, 4), "limitó temporalmente"),
        ((503, 2), "no pudo responder"),
        ((418, 9999), "HTTP 418"),
    ],
)
async def test_probar_fallos_transitorios_no_son_500(cliente, sim, fallo, texto):
    sim.fallos_consulta["numero"] = fallo
    await guardar_todo(cliente)
    r = await cliente.post(PROBAR, headers=H)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["ok"] is False and _claves(cuerpo) == dict.fromkeys(RESULTADOS, False)
    assert texto in cuerpo["resultados"][0]["detalle"]
    assert sin_secretos(r.text)


async def test_probar_sin_app_suscrita_informa_el_webhook_aparte(cliente, sim):
    sim.apps_suscritas = []
    await guardar_todo(cliente)
    cuerpo = (await cliente.post(PROBAR, headers=H)).json()
    assert cuerpo["ok"] is True and cuerpo["webhook_suscrito"] is False
    assert _claves(cuerpo) == {"token": True, "numero": True, "waba": True, "webhook": False}


async def test_probar_la_red_caida_no_filtra_el_token(motor_falso, secretos, caplog):
    def cae(peticion):
        raise httpx.ConnectError(f"no hay ruta con {ACCESS_TOKEN}", request=peticion)

    app = construir_app(
        motor_falso,
        almacen_meta=AlmacenSecretsManager("cc/test/meta", "us-east-1", cliente=secretos),
        transporte_sonda_meta=httpx.MockTransport(cae),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        await guardar_todo(c)
        r = await c.post(PROBAR, headers=H)
    assert r.status_code == 200 and r.json()["ok"] is False
    assert "No se pudo contactar a Meta" in r.json()["resultados"][0]["detalle"]
    assert sin_secretos(r.text) and sin_secretos(caplog.text)


# -------------------------------------------------------------------- caché de credenciales
async def test_guardar_invalida_el_cache_de_credenciales_de_plantillas(
    motor_falso, secretos, reloj_prueba
):
    from cc_notificaciones.meta import MetaPlantillasHttp, cargador_credenciales

    cargador = cargador_credenciales("cc/test/meta", "us-east-1", cliente=secretos)
    meta = MetaPlantillasHttp(
        cargador, transporte=httpx.MockTransport(lambda _p: httpx.Response(200))
    )
    app = construir_app(
        motor_falso,
        meta=meta,
        almacen_meta=AlmacenSecretsManager("cc/test/meta", "us-east-1", cliente=secretos),
        reloj=reloj_prueba,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        await guardar_todo(c)
        assert (await cargador()).access_token == ACCESS_TOKEN  # queda en caché
        nuevo = "EAAtokenRotadoNuevo0123456789abcdef"  # pragma: allowlist secret
        await c.put(URL, json={"access_token": nuevo, "api_version": "v22.0"}, headers=H)
        cred = await cargador()
        assert (cred.access_token, cred.waba_id, cred.api_version) == (nuevo, WABA_ID, "v22.0")


# ------------------------------------------------------------------------------- contrato
def test_openapi_describe_las_cuatro_rutas_sin_ejemplos_con_valores(app):
    spec = app.openapi()
    rutas = {p: sorted(m) for p, m in spec["paths"].items() if "integraciones" in p}
    assert rutas == {
        URL: ["get", "put"],
        GENERAR: ["post"],
        PROBAR: ["post"],
    }
    texto = json.dumps({"paths": {p: spec["paths"][p] for p in rutas}})
    for prohibido in ("example", "EAA", ACCESS_TOKEN, APP_SECRET, VERIFY_TOKEN):
        assert prohibido not in texto
    actualizar = spec["components"]["schemas"]["ActualizarMeta"]
    assert actualizar["additionalProperties"] is False
    assert set(actualizar["properties"]) == {
        "waba_id",
        "phone_number_id",
        "api_version",
        "access_token",
        "app_secret",
        "verify_token",
    }
    assert "example" not in json.dumps(actualizar) and "examples" not in json.dumps(actualizar)


def test_el_estado_inicial_del_secreto_de_cdk_es_un_json_valido():
    assert isinstance(json.loads(VALOR_INICIAL_CDK), dict)
