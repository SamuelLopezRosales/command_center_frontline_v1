"""T-203: interfaces internas de colaboradores (INT-COL-01 a 05, 07 y 08)."""

import httpx
import psycopg
import pytest
from ayudantes_colaboradores import LLAVE_HMAC, cab, construir_app, emitir, interno
from cc_colaboradores.campos_cliente import CacheCampos, DefinicionCampo, OpcionCampo, StubCampos
from cc_colaboradores.servicios.internas import normalizar_celular
from cc_common.crypto import hmac_celular

pytestmark = pytest.mark.docker

CELULAR = "8112345678"


@pytest.fixture
async def entorno(motor, cifrador, datos):
    """Org, planta, campos extra (turno, correo, registro patronal, periodicidad) y dos colaboradores."""
    a = datos["a"]
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:

        def uno(sql, p=()):
            return c.execute(sql, p).fetchone()[0]

        org = uno(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social, rfc, registro_patronal, "
            "ciudad, nombre_firmante, logotipo_s3_key) VALUES (%s, 'ORG1', 'Acme SA', 'ACM010101AB1', "
            "'B9876543210', 'Monterrey', 'Laura Gómez', 'logotipos/1/1/x.png') RETURNING id",
            (a,),
        )
        planta = uno(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Norte') RETURNING id",
            (a,),
        )
        extra = {}
        for clave, codigo, tipo in (
            ("turno", "CAMP-0005", "LISTA"),
            ("correo", "CAMP-0006", "TEXTO"),
            ("registro_patronal", "CAMP-0007", "TEXTO"),
            ("periodicidad_sueldo", "CAMP-0008", "LISTA"),
        ):
            extra[clave] = uno(
                "INSERT INTO campos.campo_colaborador (empresa_id, nombre_campo, clave, codigo_interno, "
                "tipo_dato, orden) VALUES (%s, %s, %s, %s, %s, 2) RETURNING id",
                (a, clave, clave, codigo, tipo),
            )
        op_turno = uno(
            "INSERT INTO campos.opcion_campo (empresa_id, campo_id, etiqueta, valor, descripcion) "
            "VALUES (%s, %s, 'Matutino', 'MAT', 'Lunes a viernes de 7:00 a 15:00') RETURNING id",
            (a, extra["turno"]),
        )
        op_mensual = uno(
            "INSERT INTO campos.opcion_campo (empresa_id, campo_id, etiqueta, valor) "
            "VALUES (%s, %s, 'Mensual', 'MENSUAL') RETURNING id",
            (a, extra["periodicidad_sueldo"]),
        )
    cm = datos["campos"]
    defs = [
        DefinicionCampo(cm["nss"], "NSS", "nss", "CAMP-0001", "TEXTO", es_sensible=True),
        DefinicionCampo(
            cm["area"],
            "Área",
            "area",
            "CAMP-0002",
            "LISTA",
            opciones=(OpcionCampo(datos["opcion"], "Ventas", "VENTAS"),),
        ),
        DefinicionCampo(cm["sueldo"], "Sueldo", "sueldo", "CAMP-0003", "NUMERO", es_sensible=True),
        DefinicionCampo(
            extra["turno"],
            "Turno",
            "turno",
            "CAMP-0005",
            "LISTA",
            opciones=(
                OpcionCampo(
                    op_turno, "Matutino", "MAT", descripcion="Lunes a viernes de 7:00 a 15:00"
                ),
            ),
        ),
        DefinicionCampo(extra["correo"], "Correo", "correo", "CAMP-0006", "TEXTO"),
        DefinicionCampo(
            extra["registro_patronal"], "RP", "registro_patronal", "CAMP-0007", "TEXTO"
        ),
        DefinicionCampo(
            extra["periodicidad_sueldo"],
            "Periodicidad",
            "periodicidad_sueldo",
            "CAMP-0008",
            "LISTA",
            opciones=(OpcionCampo(op_mensual, "Mensual", "MENSUAL"),),
        ),
    ]
    app = construir_app(motor, cifrador, campos=CacheCampos(StubCampos({a: defs})))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as h:
        rh = cab(emitir("sub-a", a, datos["ua"]))

        async def alta(numero, celular, campos, consentimiento=True):
            r = await h.post(
                "/api/v1/colaboradores",
                json={
                    "numero_empleado": numero,
                    "nombres": "Ana",
                    "apellido_paterno": "Pérez",
                    "apellido_materno": "Luna",
                    "celular": celular,
                    "organizacion_id": org,
                    "planta_id": planta,
                    "fecha_ingreso": "2020-03-15",
                    "puesto": "Analista",
                    "tipo_empleado": "ADMINISTRATIVO",
                    "campos": campos,
                    "consentimiento": consentimiento,
                },
                headers=rh,
            )
            assert r.status_code == 201, r.text
            return r.json()["id"]

        con_nss = await alta(
            "E-1",
            CELULAR,
            {
                "CAMP-0001": "12345678901",
                "CAMP-0002": "VENTAS",
                "CAMP-0003": "9500",
                "CAMP-0008": "MENSUAL",
                "CAMP-0005": "MAT",
                "CAMP-0006": "ana@acme.com",
            },
        )
        sin_nss = await alta("E-2", "8119990000", {}, consentimiento=False)
        yield {"h": h, "a": a, "org": org, "con_nss": con_nss, "sin_nss": sin_nss, "datos": datos}


def _bitacora_sensible(datos):
    with psycopg.connect(datos["bd"].url_admin) as c:
        return c.execute(
            "SELECT colaborador_id, origen, usuario_id, detalle FROM auditoria.bitacora "
            "WHERE accion = 'CONSULTA_SENSIBLE' ORDER BY id"
        ).fetchall()


# ------------------------------------------------------------------ seguridad de las rutas


@pytest.mark.parametrize(
    ("metodo", "ruta", "cuerpo"),
    [
        ("post", "/internal/colaboradores/buscar-por-celular", {"celular": CELULAR}),
        ("post", "/internal/colaboradores/1/desafio", {}),
        ("post", "/internal/colaboradores/1/verificar", {"dato": "1234"}),
        ("post", "/internal/colaboradores/1/datos-constancia", {"variables": ["puesto"]}),
        ("post", "/internal/colaboradores/contactos:resolver", {"ids": [1], "proposito": "CHAT"}),
        ("get", "/internal/colaboradores/1/resumen", None),
        ("get", "/internal/organizaciones/1", None),
    ],
)
async def test_sin_token_interno_401_y_token_de_usuario_no_sirve(entorno, metodo, ruta, cuerpo):
    h, a = entorno["h"], entorno["a"]
    kw = {"json": cuerpo} if cuerpo is not None else {}
    r = await getattr(h, metodo)(ruta, headers={"X-Empresa-Id": str(a)}, **kw)
    assert r.status_code == 401
    jwt_rh = {**cab(emitir("sub-a", a, entorno["datos"]["ua"])), "X-Empresa-Id": str(a)}
    r = await getattr(h, metodo)(ruta, headers=jwt_rh, **kw)
    assert r.status_code == 401


async def test_servicio_no_permitido_401_y_empresa_requerida(entorno):
    h, a = entorno["h"], entorno["a"]
    r = await h.post(
        "/internal/colaboradores/buscar-por-celular",
        json={"celular": CELULAR},
        headers=interno("notificaciones", a),
    )
    assert r.status_code == 401
    r = await h.post(
        "/internal/colaboradores/buscar-por-celular",
        json={"celular": CELULAR},
        headers=interno("whatsapp", None),
    )
    assert r.status_code == 422 and r.json()["codigo"] == "EMPRESA_REQUERIDA"


# ------------------------------------------------------------------ INT-COL-01


@pytest.mark.parametrize("formato", [CELULAR, "811 234 5678", "+52 81 1234 5678", "5218112345678"])
async def test_buscar_por_celular_normaliza(entorno, formato):
    r = await entorno["h"].post(
        "/internal/colaboradores/buscar-por-celular",
        json={"celular": formato},
        headers=interno("whatsapp", entorno["a"]),
    )
    b = r.json()
    assert b["encontrado"] and b["colaborador_id"] == entorno["con_nss"] and b["elegible"]
    assert b["celular_hash"] == hmac_celular(LLAVE_HMAC, CELULAR).hex()
    assert CELULAR not in r.text


async def test_buscar_no_registrado_devuelve_el_hash(entorno):
    for numero in ("8110000001", "123"):
        r = await entorno["h"].post(
            "/internal/colaboradores/buscar-por-celular",
            json={"celular": numero},
            headers=interno("whatsapp", entorno["a"]),
        )
        b = r.json()
        assert r.status_code == 200 and b["encontrado"] is False and len(b["celular_hash"]) == 64
        assert "colaborador_id" not in b or b["colaborador_id"] is None


async def test_buscar_en_otra_empresa_no_encuentra(entorno):
    r = await entorno["h"].post(
        "/internal/colaboradores/buscar-por-celular",
        json={"celular": CELULAR},
        headers=interno("whatsapp", entorno["datos"]["b"]),
    )
    assert r.json()["encontrado"] is False


async def test_buscar_sin_consentimiento_no_es_elegible(entorno):
    r = await entorno["h"].post(
        "/internal/colaboradores/buscar-por-celular",
        json={"celular": "8119990000"},
        headers=interno("whatsapp", entorno["a"]),
    )
    b = r.json()
    assert b["encontrado"] and b["elegible"] is False and b["motivo"] == "SIN_CONSENTIMIENTO"


def test_normalizar_celular():
    assert normalizar_celular("+52 1 81 1234 5678") == CELULAR
    assert normalizar_celular("52 81 1234 5678") == CELULAR
    assert normalizar_celular("1234") is None and normalizar_celular("") is None


# ------------------------------------------------------------------ INT-COL-02 y 03


async def test_desafio_elige_nss_o_fecha(entorno):
    h, a = entorno["h"], entorno["a"]
    r = await h.post(
        f"/internal/colaboradores/{entorno['con_nss']}/desafio", headers=interno("whatsapp", a)
    )
    assert r.json() == {"tipo": "NSS_ULTIMOS4"}
    r = await h.post(
        f"/internal/colaboradores/{entorno['sin_nss']}/desafio", headers=interno("whatsapp", a)
    )
    assert r.json() == {"tipo": "FECHA_INGRESO_DDMM"}
    r = await h.post("/internal/colaboradores/999999/desafio", headers=interno("whatsapp", a))
    assert r.status_code == 404


@pytest.mark.parametrize(
    ("dato", "valido"), [("8901", True), ("8900", False), ("12345678901", False), ("x", False)]
)
async def test_verificar_nss_sin_devolver_el_dato(entorno, dato, valido):
    r = await entorno["h"].post(
        f"/internal/colaboradores/{entorno['con_nss']}/verificar",
        json={"dato": dato},
        headers=interno("whatsapp", entorno["a"]),
    )
    assert r.json() == {"valido": valido}
    assert "12345678901" not in r.text and "8901" not in r.text.replace(f'"{dato}"', "")
    (registro,) = _bitacora_sensible(entorno["datos"])
    assert registro[1:] == ("SISTEMA", None, {"codigos_internos": ["CAMP-0001"]})


@pytest.mark.parametrize(
    ("dato", "valido"), [("15/03", True), ("1503", True), ("15-03", True), ("16/03", False)]
)
async def test_verificar_fecha_de_ingreso(entorno, dato, valido):
    r = await entorno["h"].post(
        f"/internal/colaboradores/{entorno['sin_nss']}/verificar",
        json={"dato": dato},
        headers=interno("whatsapp", entorno["a"]),
    )
    assert r.json() == {"valido": valido}


# ------------------------------------------------------------------ INT-COL-04


async def test_datos_constancia_valores_faltantes_y_bitacora(entorno):
    pedidas = [
        "nombre_completo",
        "puesto",
        "fecha_ingreso",
        "planta",
        "organizacion.razon_social",
        "organizacion.rfc",
        "lugar",
        "organizacion.cargo_firmante",
        "registro_patronal",
        "horario",
        "area",
        "nss",
        "sueldo",
        "periodicidad_sueldo",
    ]
    r = await entorno["h"].post(
        f"/internal/colaboradores/{entorno['con_nss']}/datos-constancia",
        json={"variables": pedidas},
        headers=interno("constancias", entorno["a"]),
    )
    assert r.status_code == 200, r.text
    d = r.json()
    v = d["valores"]
    assert v["nombre_completo"] == "Ana Pérez Luna" and v["fecha_ingreso"] == "2020-03-15"
    assert (
        v["planta"] == "Norte"
        and v["lugar"] == "Monterrey"
        and v["organizacion.rfc"] == "ACM010101AB1"
    )
    assert v["registro_patronal"] == "B9876543210"  # del colaborador no hay: el de su organización
    assert v["horario"] == "Lunes a viernes de 7:00 a 15:00"
    assert v["area"] == "Ventas" and v["periodicidad_sueldo"] == "MENSUAL"
    assert v["nss"] == "12345678901" and v["sueldo"] == "9500"
    assert d["faltantes"] == ["organizacion.cargo_firmante"]
    (registro,) = _bitacora_sensible(entorno["datos"])
    assert registro[1] == "SISTEMA" and registro[3] == {
        "codigos_internos": ["CAMP-0001", "CAMP-0003"]
    }
    assert "12345678901" not in str(registro)


async def test_datos_constancia_sin_sensibles_no_registra(entorno):
    r = await entorno["h"].post(
        f"/internal/colaboradores/{entorno['con_nss']}/datos-constancia",
        json={"variables": ["puesto", "area"]},
        headers=interno("constancias", entorno["a"]),
    )
    assert r.json()["faltantes"] == [] and _bitacora_sensible(entorno["datos"]) == []


async def test_datos_constancia_variable_desconocida_422_y_solo_constancias(entorno):
    r = await entorno["h"].post(
        f"/internal/colaboradores/{entorno['con_nss']}/datos-constancia",
        json={"variables": ["inventada"]},
        headers=interno("constancias", entorno["a"]),
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VARIABLE_DESCONOCIDA"
    r = await entorno["h"].post(
        f"/internal/colaboradores/{entorno['con_nss']}/datos-constancia",
        json={"variables": ["nss"]},
        headers=interno("whatsapp", entorno["a"]),
    )
    assert r.status_code == 401


# ------------------------------------------------------------------ INT-COL-05


async def test_resolver_contactos_aplica_elegibilidad(entorno):
    ids = [entorno["con_nss"], entorno["sin_nss"], 999999]
    r = await entorno["h"].post(
        "/internal/colaboradores/contactos:resolver",
        json={"ids": ids, "proposito": "NOTIFICACION", "variables": ["nombre_completo"]},
        headers=interno("notificaciones", entorno["a"]),
    )
    items = {i["id"]: i for i in r.json()["items"]}
    assert items[entorno["con_nss"]]["elegible"] and items[entorno["con_nss"]]["celular"] == CELULAR
    assert items[entorno["con_nss"]]["valores"] == {"nombre_completo": "Ana Pérez Luna"}
    assert items[entorno["con_nss"]]["correo"] is None
    assert items[entorno["sin_nss"]] == {
        "id": entorno["sin_nss"],
        "elegible": False,
        "motivo": "SIN_CONSENTIMIENTO",
        "celular": None,
        "correo": None,
        "valores": {},
    }
    assert items[999999]["motivo"] == "NO_ENCONTRADO"
    assert "8119990000" not in r.text


async def test_correo_solo_con_proposito_correo(entorno):
    r = await entorno["h"].post(
        "/internal/colaboradores/contactos:resolver",
        json={"ids": [entorno["con_nss"]], "proposito": "CORREO"},
        headers=interno("notificaciones", entorno["a"]),
    )
    (item,) = r.json()["items"]
    assert item["correo"] == "ana@acme.com" and item["celular"] is None


async def test_baja_no_es_elegible_aunque_se_pida(entorno):
    h, a = entorno["h"], entorno["a"]
    rh = cab(emitir("sub-a", a, entorno["datos"]["ua"]))
    await h.post(
        f"/api/v1/colaboradores/{entorno['con_nss']}/baja",
        json={"fecha_baja": "2026-10-01"},
        headers=rh,
    )
    r = await h.post(
        "/internal/colaboradores/contactos:resolver",
        json={"ids": [entorno["con_nss"]], "proposito": "CONSTANCIA"},
        headers=interno("constancias", a),
    )
    (item,) = r.json()["items"]
    assert item["elegible"] is False and item["motivo"] == "BAJA" and item["celular"] is None


async def test_resolver_valida_lote_y_proposito(entorno):
    h, a = entorno["h"], entorno["a"]
    r = await h.post(
        "/internal/colaboradores/contactos:resolver",
        json={"ids": list(range(1, 502)), "proposito": "CHAT"},
        headers=interno("whatsapp", a),
    )
    assert r.status_code == 422
    r = await h.post(
        "/internal/colaboradores/contactos:resolver",
        json={"ids": [1], "proposito": "SPAM"},
        headers=interno("whatsapp", a),
    )
    assert r.status_code == 422


# ------------------------------------------------------------------ INT-COL-07 y 08


async def test_resumen_sin_datos_sensibles(entorno):
    r = await entorno["h"].get(
        f"/internal/colaboradores/{entorno['con_nss']}/resumen",
        headers=interno("whatsapp", entorno["a"]),
    )
    b = r.json()
    assert b["nombre_completo"] == "Ana Pérez Luna" and b["celular_ultimos4"] == "5678"
    assert b["organizacion"]["clave"] == "ORG1" and b["consentimiento_vigente"] is True
    assert CELULAR not in r.text and "12345678901" not in r.text


async def test_organizacion_para_constancias(entorno):
    h, a = entorno["h"], entorno["a"]
    r = await h.get(f"/internal/organizaciones/{entorno['org']}", headers=interno("constancias", a))
    assert (
        r.json()["razon_social"] == "Acme SA"
        and r.json()["logotipo_s3_key"] == "logotipos/1/1/x.png"
    )
    r = await h.get(
        f"/internal/organizaciones/{entorno['org']}",
        headers=interno("constancias", entorno["datos"]["b"]),
    )
    assert r.status_code == 404
