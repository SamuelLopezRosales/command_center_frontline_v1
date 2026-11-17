"""T-218 (T-116): chat de RH (WAP-01 a WAP-05) con la base real (RLS) y `colaboradores` y
`notificaciones` de mentira. Lista por notificación y asignación con la ventana abierta o cerrada;
los mensajes se guardan y se leen cifrados; texto libre con la ventana cerrada da 409 y solo se
acepta una plantilla aprobada; la asignación valida que el usuario exista y sea de la empresa."""

import httpx
import pytest
from ayudantes_whatsapp import (
    CLIENTE,
    EMISOR,
    LLAVE_JWT,
    ColaboradoresFalso,
    KmsFalso,
    cab,
    crear_colaborador,
    crear_conversacion,
    crear_notificacion_enviada,
    crear_usuario,
    eventos,
    sql,
)
from cc_common.auth import VerificadorToken, rutas_sin_permiso
from cc_common.db import crear_motor
from cc_whatsapp.cifrado import Cifrador
from cc_whatsapp.clientes import StubNotificaciones
from cc_whatsapp.config import ConfigWhatsapp
from cc_whatsapp.main import crear_app

pytestmark = pytest.mark.docker

BASE = "/api/v1/conversaciones"
TEXTO = "Tu cita quedó para el lunes a las 9:00"


def plantilla(estado="APROBADA", texto="Hola {{1}}, tu cita es el {{2}}", nombre="aviso_cita"):
    return {"id": 5, "nombre": nombre, "estado_meta": estado, "idioma": "es_MX",
            "texto_con_variables": texto}  # fmt: skip


@pytest.fixture
async def mundo(datos, bd_migrada):
    """Empresas A y B, un usuario RH en cada una y el servicio con sus dobles."""
    with_b = sql(datos, "INSERT INTO identidad.empresa (razon_social) VALUES ('B') RETURNING id")
    datos["empresa_b"] = with_b[0][0]
    datos["usuario"] = crear_usuario(datos, datos["empresa"], "Ana RH")
    datos["usuario2"] = crear_usuario(datos, datos["empresa"], "Beto RH")
    datos["usuario_b"] = crear_usuario(datos, datos["empresa_b"], "Cris RH")
    datos["colaborador2"] = crear_colaborador(datos)
    motor = crear_motor(bd_migrada.url_rol("svc_whatsapp"))
    notificaciones = StubNotificaciones({(datos["empresa"], 5): plantilla()})
    cifrador = Cifrador(KmsFalso(), "llave-de-prueba")
    colaboradores = ColaboradoresFalso()
    app = crear_app(
        ConfigWhatsapp(
            cognito_emisor=EMISOR, cognito_client_id=CLIENTE, cola_salida_url="wa-salida.fifo"
        ),
        motor=motor,
        verificador=VerificadorToken(
            EMISOR, CLIENTE, resolver_llave=lambda _t: LLAVE_JWT.public_key()
        ),
        cifrador=cifrador, colaboradores=colaboradores, notificaciones=notificaciones,
    )  # fmt: skip
    datos["app"], datos["notificaciones"], datos["cifrador"] = app, notificaciones, cifrador
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        datos["http"] = c
        yield datos
    await motor.dispose()


@pytest.fixture
def h(mundo):
    return cab("sub-a", mundo["empresa"], mundo["usuario"])


@pytest.fixture
def hb(mundo):
    return cab("sub-b", mundo["empresa_b"], mundo["usuario_b"])


def salidas(datos) -> list[dict]:
    return eventos(datos, "mensaje_salida")


async def test_toda_ruta_declara_su_permiso_y_sin_permiso_no_entra(mundo, h):
    assert rutas_sin_permiso(mundo["app"]) == []
    c = mundo["http"]
    otro = cab("sub-x", mundo["empresa"], mundo["usuario"], rol="OTRO")
    for metodo, ruta, cuerpo in (
        ("GET", BASE, None),
        ("GET", f"{BASE}/1/mensajes", None),
        ("POST", f"{BASE}/1/mensajes", {"texto": "x"}),
        ("POST", f"{BASE}/1/mensajes/plantilla", {"plantilla_mensaje_id": 5, "variables": []}),
        ("PUT", f"{BASE}/1/asignacion", {"usuario_id": 1}),
    ):
        assert (await c.request(metodo, ruta, json=cuerpo)).status_code == 401
        r = await c.request(metodo, ruta, json=cuerpo, headers=otro)
        assert r.status_code == 403, (metodo, ruta)


# ------------------------------------------------------------------ WAP-01


async def test_lista_por_notificacion_asignacion_y_ventana(mundo, h):
    c = mundo["http"]
    c1, c2 = mundo["colaborador"], mundo["colaborador2"]
    abierta = crear_conversacion(mundo, c1, hace="2 hours")
    cerrada = crear_conversacion(mundo, c2, hace="30 hours")
    crear_notificacion_enviada(mundo, c1)  # la notificación 7 salió a c1
    sql(mundo, "UPDATE whatsapp.conversacion_whatsapp SET fecha_ultimo_mensaje = now() "
        "WHERE id = %s", (abierta,))  # fmt: skip

    todas = (await c.get(BASE, headers=h)).json()
    assert [i["id"] for i in todas["items"]] == [abierta, cerrada]
    por_id = {i["id"]: i for i in todas["items"]}
    assert por_id[abierta]["ventana_abierta"] is True
    assert por_id[cerrada]["ventana_abierta"] is False
    assert por_id[abierta]["colaborador_nombre"] == "Ana Pérez Ruiz"
    assert por_id[abierta]["ultima_notificacion_id"] == 7
    assert por_id[cerrada]["ultima_notificacion_id"] is None
    assert "celular" not in str(todas)

    r = (await c.get(BASE, params={"notificacion_id": 7}, headers=h)).json()
    assert [i["id"] for i in r["items"]] == [abierta]
    assert (await c.get(BASE, params={"notificacion_id": 8}, headers=h)).json()["items"] == []

    r = await c.put(
        f"{BASE}/{cerrada}/asignacion", json={"usuario_id": mundo["usuario2"]}, headers=h
    )
    assert r.status_code == 200
    r = (await c.get(BASE, params={"asignada_a": mundo["usuario2"]}, headers=h)).json()
    assert [i["id"] for i in r["items"]] == [cerrada]
    assert (await c.get(BASE, params={"estado": "CERRADA"}, headers=h)).json()["items"] == []
    assert len((await c.get(BASE, params={"estado": "ACTIVA"}, headers=h)).json()["items"]) == 2


async def test_la_lista_pagina_por_cursor(mundo, h):
    c = mundo["http"]
    ids = [crear_conversacion(mundo, mundo["colaborador"], hace="1 hour") for _ in range(1)]
    ids.append(crear_conversacion(mundo, mundo["colaborador2"], hace="1 hour"))
    p1 = (await c.get(BASE, params={"limite": 1}, headers=h)).json()
    assert len(p1["items"]) == 1 and p1["siguiente"]
    p2 = (await c.get(BASE, params={"limite": 1, "cursor": p1["siguiente"]}, headers=h)).json()
    assert len(p2["items"]) == 1 and p2["siguiente"] is None
    assert {p1["items"][0]["id"], p2["items"][0]["id"]} == set(ids)
    r = await c.get(BASE, params={"cursor": "no-es-un-cursor"}, headers=h)
    assert r.status_code == 422


async def test_el_nombre_es_opcional_si_colaboradores_falla(mundo, h):
    crear_conversacion(mundo, mundo["colaborador"])

    async def falla(*_a):
        raise RuntimeError("colaboradores caído")

    mundo["app"].state.colaboradores.nombre = falla
    r = await mundo["http"].get(BASE, headers=h)
    assert r.status_code == 200 and r.json()["items"][0]["colaborador_nombre"] is None


# ------------------------------------------------------------------ WAP-03 y WAP-02


async def test_texto_con_ventana_abierta_se_guarda_cifrado_se_encola_y_se_lee(mundo, h):
    c = mundo["http"]
    conv = crear_conversacion(mundo, mundo["colaborador"], hace="1 hour")
    r = await c.post(f"{BASE}/{conv}/mensajes", json={"texto": TEXTO}, headers=h)
    assert r.status_code == 202, r.text
    mid = r.json()["mensaje_id"]
    [(blob, estado, origen, tipo, usuario, clave)] = sql(
        mundo,
        "SELECT contenido_cifrado, estado, origen_tipo, tipo, enviado_por_usuario_id, "
        "clave_idempotencia FROM whatsapp.mensaje_whatsapp WHERE id = %s",
        (mid,),
    )
    assert (estado, origen, tipo, usuario) == ("ENCOLADO", "CHAT", "TEXTO", mundo["usuario"])
    assert TEXTO.encode() not in bytes(blob)  # cifrado en la base
    [m] = salidas(mundo)  # el MensajeSalida que consume el enviador
    assert m["mensaje_uuid"] == str(clave) and m["origen_tipo"] == "CHAT"
    assert m["origen_id"] == conv and m["conversacion_id"] == conv
    assert m["colaborador_id"] == mundo["colaborador"] and m["empresa_id"] == mundo["empresa"]
    assert m["tipo"] == "TEXTO" and m["texto"] == TEXTO and m["proposito"] == "CHAT"
    assert m["max_intentos"] == 3
    [(grupo, dedup, destino)] = sql(
        mundo,
        "SELECT grupo, deduplicacion, destino FROM whatsapp.outbox WHERE tipo = 'mensaje_salida'",
    )
    assert (grupo, dedup, destino) == (str(mundo["colaborador"]), str(clave), "wa-salida.fifo")
    # bitácora: quién y qué conversación, sin contenido
    [(accion, uid, detalle)] = sql(
        mundo,
        "SELECT accion, usuario_id, detalle FROM auditoria.bitacora WHERE accion = 'MENSAJE_CHAT'",
    )
    assert uid == mundo["usuario"] and detalle["conversacion_id"] == conv
    assert TEXTO not in str(detalle)
    # WAP-02 lo descifra
    msgs = (await c.get(f"{BASE}/{conv}/mensajes", headers=h)).json()["items"]
    assert [(x["direccion"], x["contenido"], x["estado"]) for x in msgs] == [
        ("SALIENTE", TEXTO, "ENCOLADO")
    ]
    assert msgs[0]["enviado_por_usuario_id"] == mundo["usuario"]


async def test_un_mensaje_copiado_a_otra_fila_no_descifra(mundo, h):
    """El AAD liga el contenido a su ``clave_idempotencia`` y a su empresa."""
    c = mundo["http"]
    conv = crear_conversacion(mundo, mundo["colaborador"])
    a = (await c.post(f"{BASE}/{conv}/mensajes", json={"texto": TEXTO}, headers=h)).json()
    b = (await c.post(f"{BASE}/{conv}/mensajes", json={"texto": "otro"}, headers=h)).json()
    sql(
        mundo,
        "UPDATE whatsapp.mensaje_whatsapp SET contenido_cifrado = "
        "(SELECT contenido_cifrado FROM whatsapp.mensaje_whatsapp WHERE id = %s) WHERE id = %s",
        (a["mensaje_id"], b["mensaje_id"]),
    )
    msgs = {
        m["id"]: m["contenido"]
        for m in (await c.get(f"{BASE}/{conv}/mensajes", headers=h)).json()["items"]
    }
    assert msgs[a["mensaje_id"]] == TEXTO and msgs[b["mensaje_id"]] is None


async def test_texto_con_ventana_cerrada_da_409_y_no_deja_nada(mundo, h):
    c = mundo["http"]
    conv = crear_conversacion(mundo, mundo["colaborador"], hace="25 hours")
    r = await c.post(f"{BASE}/{conv}/mensajes", json={"texto": TEXTO}, headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "VENTANA_24H_CERRADA"
    assert TEXTO not in r.text
    assert sql(mundo, "SELECT count(*) FROM whatsapp.mensaje_whatsapp") == [(0,)]
    assert salidas(mundo) == []
    # sin ningún mensaje entrante, tampoco
    sin = crear_conversacion(mundo, mundo["colaborador2"], hace=None)
    r = await c.post(f"{BASE}/{sin}/mensajes", json={"texto": TEXTO}, headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "VENTANA_24H_CERRADA"


async def test_validaciones_del_texto_y_conversacion_inexistente(mundo, h):
    c = mundo["http"]
    conv = crear_conversacion(mundo, mundo["colaborador"])
    for texto in ("", "   ", "x" * 1001):
        r = await c.post(f"{BASE}/{conv}/mensajes", json={"texto": texto}, headers=h)
        assert r.status_code == 422, texto
    assert (
        await c.post(f"{BASE}/999999/mensajes", json={"texto": "x"}, headers=h)
    ).status_code == 404
    assert (await c.get(f"{BASE}/999999/mensajes", headers=h)).status_code == 404


async def test_el_hilo_trae_las_notificaciones_las_respuestas_y_no_el_bot(mundo, h):
    c = mundo["http"]
    conv = crear_conversacion(mundo, mundo["colaborador"])
    crear_notificacion_enviada(mundo, mundo["colaborador"])  # sin conversación: contexto
    sql(mundo, "INSERT INTO whatsapp.mensaje_whatsapp (empresa_id, conversacion_id, direccion, tipo, "
        "clave_idempotencia, estado, origen_tipo) VALUES (%s, %s, 'SALIENTE', 'TEXTO', "
        "gen_random_uuid(), 'ENVIADO', 'BOT')", (mundo["empresa"], conv))  # fmt: skip
    sql(mundo, "INSERT INTO whatsapp.mensaje_whatsapp (empresa_id, conversacion_id, direccion, tipo, "
        "clave_idempotencia, estado, origen_tipo) VALUES (%s, %s, 'ENTRANTE', 'TEXTO', "
        "gen_random_uuid(), 'RECIBIDO', 'BOT')", (mundo["empresa"], conv))  # fmt: skip
    await c.post(f"{BASE}/{conv}/mensajes", json={"texto": TEXTO}, headers=h)
    msgs = (await c.get(f"{BASE}/{conv}/mensajes", headers=h)).json()["items"]
    assert sorted((m["direccion"], m["origen_tipo"]) for m in msgs) == [
        ("ENTRANTE", "BOT"), ("SALIENTE", "CHAT"), ("SALIENTE", "NOTIFICACION"),
    ]  # fmt: skip
    p1 = (await c.get(f"{BASE}/{conv}/mensajes", params={"limite": 2}, headers=h)).json()
    p2 = (
        await c.get(
            f"{BASE}/{conv}/mensajes", params={"limite": 2, "cursor": p1["siguiente"]}, headers=h
        )
    ).json()
    assert len(p1["items"]) == 2 and len(p2["items"]) == 1 and p2["siguiente"] is None


# ------------------------------------------------------------------ WAP-04


async def test_plantilla_aprobada_con_ventana_cerrada_se_acepta(mundo, h):
    c = mundo["http"]
    conv = crear_conversacion(mundo, mundo["colaborador"], hace="40 hours")
    r = await c.post(
        f"{BASE}/{conv}/mensajes/plantilla",
        json={"plantilla_mensaje_id": 5, "variables": ["Ana", "lunes"]}, headers=h,
    )  # fmt: skip
    assert r.status_code == 202, r.text
    [m] = salidas(mundo)
    assert (
        m["tipo"] == "PLANTILLA" and m["plantilla"] == "aviso_cita" and m["origen_tipo"] == "CHAT"
    )
    assert m["variables"] == ["Ana", "lunes"] and m["proposito"] == "CHAT"
    assert "texto" not in m
    [(blob, tipo, nombre)] = sql(
        mundo, "SELECT contenido_cifrado, tipo, plantilla_meta FROM whatsapp.mensaje_whatsapp"
    )
    assert (tipo, nombre) == ("PLANTILLA", "aviso_cita") and b"Ana" not in bytes(blob)
    msgs = (await c.get(f"{BASE}/{conv}/mensajes", headers=h)).json()["items"]
    assert msgs[0]["contenido"] == "Hola Ana, tu cita es el lunes"
    assert mundo["notificaciones"].llamadas == [(mundo["empresa"], 5)]


@pytest.mark.parametrize(
    ("estado", "codigo"),
    [("EN_REVISION", "PLANTILLA_NO_APROBADA"), ("RECHAZADA", "PLANTILLA_NO_APROBADA"),
     ("BORRADOR", "PLANTILLA_NO_APROBADA")],
)  # fmt: skip
async def test_plantilla_no_aprobada_se_rechaza(mundo, h, estado, codigo):
    mundo["notificaciones"].plantillas[(mundo["empresa"], 5)] = plantilla(estado)
    conv = crear_conversacion(mundo, mundo["colaborador"])
    r = await mundo["http"].post(
        f"{BASE}/{conv}/mensajes/plantilla",
        json={"plantilla_mensaje_id": 5, "variables": ["a", "b"]}, headers=h,
    )  # fmt: skip
    assert r.status_code == 422 and r.json()["codigo"] == codigo
    assert salidas(mundo) == []


async def test_plantilla_inexistente_o_de_otra_empresa_o_con_variables_mal(mundo, h):
    c = mundo["http"]
    conv = crear_conversacion(mundo, mundo["colaborador"])
    r = await c.post(f"{BASE}/{conv}/mensajes/plantilla",
                     json={"plantilla_mensaje_id": 99, "variables": []}, headers=h)  # fmt: skip
    assert r.status_code == 422 and r.json()["codigo"] == "PLANTILLA_NO_ENCONTRADA"
    for variables in ([], ["solo una"], ["a", "b", "c"]):
        r = await c.post(f"{BASE}/{conv}/mensajes/plantilla",
                         json={"plantilla_mensaje_id": 5, "variables": variables}, headers=h)  # fmt: skip
        assert r.status_code == 422 and r.json()["codigo"] == "VARIABLES_INVALIDAS"
    assert salidas(mundo) == []


async def test_plantilla_con_nombre_se_envia_por_nombre_con_el_idioma_de_la_plantilla(mundo, h):
    c = mundo["http"]
    mundo["notificaciones"].plantillas[(mundo["empresa"], 5)] = {
        **plantilla(
            texto="Hello {{guest_name}}, we expect you at {{place}}. Bye {{guest_name}}.",
            nombre="vida_checkout_notice",
        ),
        "idioma": "en",
    }
    conv = crear_conversacion(mundo, mundo["colaborador"], hace="40 hours")
    r = await c.post(
        f"{BASE}/{conv}/mensajes/plantilla",
        json={
            "plantilla_mensaje_id": 5,
            "variables_nombradas": {"place": " Lobby ", "guest_name": "Juan"},
        },
        headers=h,
    )
    assert r.status_code == 202, r.text
    [m] = salidas(mundo)
    assert m["plantilla"] == "vida_checkout_notice" and m["idioma"] == "en"
    # valores en el orden de aparición en el texto, con la lista paralela de nombres
    assert m["variables_nombres"] == ["guest_name", "place"]
    assert m["variables"] == ["Juan", "Lobby"] and m["proposito"] == "CHAT"
    [(blob,)] = sql(mundo, "SELECT contenido_cifrado FROM whatsapp.mensaje_whatsapp")
    assert b"Juan" not in bytes(blob)  # el texto guardado va cifrado
    msgs = (await c.get(f"{BASE}/{conv}/mensajes", headers=h)).json()["items"]
    assert msgs[0]["contenido"] == "Hello Juan, we expect you at Lobby. Bye Juan."


async def test_plantilla_posicional_lleva_idioma_y_no_lleva_nombres(mundo, h):
    conv = crear_conversacion(mundo, mundo["colaborador"], hace="40 hours")
    r = await mundo["http"].post(
        f"{BASE}/{conv}/mensajes/plantilla",
        json={"plantilla_mensaje_id": 5, "variables": ["Ana", "lunes"]}, headers=h,
    )  # fmt: skip
    assert r.status_code == 202, r.text
    [m] = salidas(mundo)
    assert m["idioma"] == "es_MX" and "variables_nombres" not in m


async def test_plantilla_sin_variables_en_otro_idioma(mundo, h):
    mundo["notificaciones"].plantillas[(mundo["empresa"], 5)] = {
        **plantilla(texto="Hello World", nombre="hello_world"),
        "idioma": "en_US",
    }
    conv = crear_conversacion(mundo, mundo["colaborador"], hace="40 hours")
    r = await mundo["http"].post(
        f"{BASE}/{conv}/mensajes/plantilla", json={"plantilla_mensaje_id": 5}, headers=h
    )
    assert r.status_code == 202, r.text
    [m] = salidas(mundo)
    assert m["idioma"] == "en_US" and m["variables"] == [] and "variables_nombres" not in m


@pytest.mark.parametrize(
    ("cuerpo", "esperados"),
    [
        ({"variables": ["Juan"]}, {("variables", "NO_APLICA"),
                                    ("variables_nombradas.guest_name", "VARIABLE_FALTANTE")}),
        ({"variables_nombradas": {}}, {("variables_nombradas.guest_name", "VARIABLE_FALTANTE")}),
        ({"variables_nombradas": {"guest_name": "Juan", "otra": "x"}},
         {("variables_nombradas.otra", "VARIABLE_NO_EXISTE")}),
        ({"variables_nombradas": {"guest_name": "  "}},
         {("variables_nombradas.guest_name", "VALOR_INVALIDO")}),
        ({"variables_nombradas": {"guest_name": "dos\nlineas"}},
         {("variables_nombradas.guest_name", "VALOR_INVALIDO")}),
    ],
)  # fmt: skip
async def test_plantilla_con_nombre_valida_por_campo(mundo, h, cuerpo, esperados):
    mundo["notificaciones"].plantillas[(mundo["empresa"], 5)] = plantilla(
        texto="Hola {{guest_name}}.", nombre="vida_x"
    )
    conv = crear_conversacion(mundo, mundo["colaborador"], hace="40 hours")
    r = await mundo["http"].post(
        f"{BASE}/{conv}/mensajes/plantilla", json={"plantilla_mensaje_id": 5, **cuerpo}, headers=h
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VARIABLES_INVALIDAS", r.text
    assert {(e["campo"], e["codigo"]) for e in r.json()["errores"]} == esperados
    assert "Juan" not in r.text and salidas(mundo) == []


async def test_nombradas_a_una_plantilla_posicional_se_rechaza(mundo, h):
    conv = crear_conversacion(mundo, mundo["colaborador"], hace="40 hours")
    r = await mundo["http"].post(
        f"{BASE}/{conv}/mensajes/plantilla",
        json={"plantilla_mensaje_id": 5, "variables_nombradas": {"a": "x", "b": "y"}}, headers=h,
    )  # fmt: skip
    assert r.status_code == 422 and r.json()["codigo"] == "VARIABLES_INVALIDAS"
    assert salidas(mundo) == []


# ------------------------------------------------------------------ WAP-05


async def test_asignar_valida_que_el_usuario_exista_y_sea_de_la_empresa(mundo, h):
    c = mundo["http"]
    conv = crear_conversacion(mundo, mundo["colaborador"])
    r = await c.put(f"{BASE}/{conv}/asignacion", json={"usuario_id": mundo["usuario2"]}, headers=h)
    assert r.status_code == 200
    assert r.json()["asignada_a_usuario_id"] == mundo["usuario2"] and r.json()["fecha_asignacion"]
    [(uid, detalle)] = sql(
        mundo, "SELECT usuario_id, detalle FROM auditoria.bitacora WHERE accion = 'MODIFICACION'"
    )
    assert uid == mundo["usuario"] and detalle["campos"] == ["asignada_a_usuario_id"]
    for malo in (987654, mundo["usuario_b"]):  # inexistente y de la empresa B
        r = await c.put(f"{BASE}/{conv}/asignacion", json={"usuario_id": malo}, headers=h)
        assert r.status_code == 422 and r.json()["codigo"] == "USUARIO_NO_ENCONTRADO"
    assert (await c.put(f"{BASE}/999999/asignacion", json={"usuario_id": mundo["usuario"]},
                        headers=h)).status_code == 404  # fmt: skip
    # sigue asignada a quien estaba
    r = (await c.get(BASE, params={"asignada_a": mundo["usuario2"]}, headers=h)).json()
    assert [i["id"] for i in r["items"]] == [conv]


async def test_el_rol_del_servicio_no_lee_identidad_pero_la_funcion_si(mundo, bd_migrada):
    import psycopg

    with (
        psycopg.connect(bd_migrada.url_rol("svc_whatsapp", asincrona=False)) as con,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        con.execute("SELECT 1 FROM identidad.usuario")


# ------------------------------------------------------------------ aislamiento


async def test_otra_empresa_no_ve_ni_escribe_conversaciones_ajenas(mundo, h, hb):
    c = mundo["http"]
    conv = crear_conversacion(mundo, mundo["colaborador"])
    assert (await c.get(BASE, headers=hb)).json()["items"] == []
    for metodo, ruta, cuerpo in (
        ("GET", f"{BASE}/{conv}/mensajes", None),
        ("POST", f"{BASE}/{conv}/mensajes", {"texto": "x"}),
        ("PUT", f"{BASE}/{conv}/asignacion", {"usuario_id": mundo["usuario_b"]}),
    ):
        r = await c.request(metodo, ruta, json=cuerpo, headers=hb)
        assert r.status_code == 404, (metodo, ruta)
    assert salidas(mundo) == []
    # y la empresa A sí
    assert (await c.get(BASE, headers=h)).json()["items"][0]["id"] == conv
