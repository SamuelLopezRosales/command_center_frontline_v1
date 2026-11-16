"""T-106: INT-COL-06 (``audiencias:evaluar``) contra PostgreSQL con RLS."""

import httpx
import psycopg
import pytest
from ayudantes_colaboradores import StubCampos, construir_app, interno
from cc_colaboradores.campos_cliente import CacheCampos, DefinicionCampo, OpcionCampo

pytestmark = pytest.mark.docker

URL = "/internal/colaboradores/audiencias:evaluar"


def _ins(c, empresa, org, planta, numero, **kw):
    """Inserta un colaborador (SQL directo: sin cifrado real) y devuelve su id."""
    p = {
        "nombres": "Nombre",
        "paterno": f"Pat{numero}",
        "ingreso": "2020-01-01",
        "tipo": "OPERATIVO",
        "estatus": "ACTIVO",
        "consent": True,
        "invalido": False,
    } | kw
    return c.execute(
        """
        INSERT INTO colaboradores.colaborador
          (empresa_id, organizacion_id, planta_id, numero_empleado, nombres, apellido_paterno,
           apellido_materno, celular_cifrado, celular_hash, celular_ultimos4, celular_invalido,
           fecha_ingreso, puesto, tipo_empleado, estatus, fecha_baja, consentimiento_whatsapp)
        VALUES (%(e)s, %(o)s, %(pl)s, %(n)s, %(nombres)s, %(paterno)s, 'Mat', '\\x00'::bytea,
                sha256(convert_to(%(e)s::text || %(n)s, 'UTF8')), '1234', %(invalido)s, %(ingreso)s,
                'Puesto', %(tipo)s, %(estatus)s,
                CASE WHEN %(estatus)s = 'BAJA' THEN DATE '2026-01-01' END, %(consent)s)
        RETURNING id
        """,
        {"e": empresa, "o": org, "pl": planta, "n": numero, **p},
    ).fetchone()[0]


@pytest.fixture
def mundo(datos):
    """Empresa A: 2 plantas, 8 colaboradores y 4 campos propios; empresa B: 1 colaborador."""
    a, b = datos["a"], datos["b"]
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:

        def campo(codigo, tipo, sensible=False):
            return c.execute(
                "INSERT INTO campos.campo_colaborador (empresa_id, nombre_campo, clave, "
                "codigo_interno, tipo_dato, orden, es_sensible) VALUES (%s, %s, %s, %s, %s, 1, %s) "
                "RETURNING id",
                (a, codigo, "clave_" + codigo[-2:], codigo, tipo, sensible),
            ).fetchone()[0]

        puntos, ciudad, turno = campo("CAMP-0010", "NUMERO"), campo("CAMP-0011", "TEXTO"), None
        turno = campo("CAMP-0012", "SI_NO")
        org = c.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORG', 'Org') RETURNING id",
            (a,),
        ).fetchone()[0]
        norte = c.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Norte') RETURNING id",
            (a,),
        ).fetchone()[0]
        sur = c.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Sur') RETURNING id",
            (a,),
        ).fetchone()[0]
        hoy = "(now() AT TIME ZONE 'America/Mexico_City')::date"
        ids = {}
        # n1..n3 Norte; n4..n6 Sur; n7 sin consentimiento y en BAJA; n8 celular inválido
        ids["n1"] = _ins(c, a, org, norte, "N1", ingreso="2015-03-01", tipo="ADMINISTRATIVO")
        ids["n2"] = _ins(c, a, org, norte, "N2", ingreso="2023-06-01")
        ids["n3"] = _ins(c, a, org, norte, "N3", ingreso="2025-01-15")
        ids["n4"] = _ins(c, a, org, sur, "N4", ingreso="2018-09-09")
        ids["n5"] = _ins(c, a, org, sur, "N5", ingreso="2021-11-30")
        ids["n6"] = _ins(c, a, org, sur, "N6", ingreso="2022-02-02")
        ids["n7"] = _ins(c, a, org, sur, "N7", estatus="BAJA", consent=False)
        ids["n8"] = _ins(c, a, org, sur, "N8", invalido=True)
        # antigüedad exacta contra la fecha de hoy (años completos)
        for n, anios, dias in (("e5", 5, 0), ("e4", 5, 1), ("e6", 6, 1)):
            ids[n] = c.execute(
                "INSERT INTO colaboradores.colaborador (empresa_id, organizacion_id, planta_id, "
                "numero_empleado, nombres, apellido_paterno, apellido_materno, celular_cifrado, "
                "celular_hash, celular_ultimos4, fecha_ingreso, puesto, tipo_empleado, estatus, "
                "consentimiento_whatsapp) SELECT %s, %s, %s, %s, 'A', 'B', 'C', '\\x00'::bytea, "
                "sha256(convert_to(%s, 'UTF8')), '0000', "
                f"({hoy} - make_interval(years => %s) + make_interval(days => %s))::date, "
                "'P', 'OPERATIVO', 'ACTIVO', true RETURNING id",
                (a, org, norte, n.upper(), "x" + n, anios, dias),
            ).fetchone()[0]

        def valor(col, campo_id, **kw):
            cols = {"valor_texto": None, "valor_numero": None, "valor_fecha": None} | kw
            c.execute(
                "INSERT INTO colaboradores.valor_campo (empresa_id, colaborador_id, campo_id, "
                "valor_texto, valor_numero, valor_fecha, valor_opcion_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    a,
                    ids[col],
                    campo_id,
                    cols["valor_texto"],
                    cols["valor_numero"],
                    cols["valor_fecha"],
                    cols.get("valor_opcion_id"),
                ),
            )

        valor("n1", datos["campos"]["area"], valor_opcion_id=datos["opcion"])
        valor("n2", datos["campos"]["area"], valor_opcion_id=datos["opcion"])
        valor("n1", puntos, valor_numero=10)
        valor("n2", puntos, valor_numero=20)
        valor("n3", puntos, valor_numero=30)
        valor("n1", ciudad, valor_texto="Monterrey Centro")
        valor("n2", ciudad, valor_texto="Saltillo")
        valor("n1", turno, valor_texto="SI")
        valor("n2", turno, valor_texto="NO")
        valor("n1", datos["campos"]["antiguedad_fecha"], valor_fecha="2024-05-05")
        valor("n2", datos["campos"]["antiguedad_fecha"], valor_fecha="2025-05-05")
        # NSS sensible: solo cifrado, nunca en columnas tipadas
        c.execute(
            "INSERT INTO colaboradores.valor_campo (empresa_id, colaborador_id, campo_id, "
            "valor_cifrado) VALUES (%s, %s, %s, '\\x01'::bytea)",
            (a, ids["n1"], datos["campos"]["nss"]),
        )
        # empresa B
        org_b = c.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORGB', 'OrgB') RETURNING id",
            (b,),
        ).fetchone()[0]
        planta_b = c.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Norte') RETURNING id",
            (b,),
        ).fetchone()[0]
        ids["b1"] = _ins(c, b, org_b, planta_b, "B1")
    return {
        **datos,
        "ids": ids,
        "org": org,
        "norte": norte,
        "sur": sur,
        "puntos": puntos,
        "ciudad": ciudad,
        "turno": turno,
        "planta_b": planta_b,
    }


def _defs(m):
    cs = m["campos"]
    return [
        DefinicionCampo(cs["nss"], "NSS", "nss", "CAMP-0001", "TEXTO", es_sensible=True),
        DefinicionCampo(
            cs["area"],
            "AREA",
            "area",
            "CAMP-0002",
            "LISTA",
            opciones=(OpcionCampo(m["opcion"], "Ventas", "VENTAS"),),
        ),
        DefinicionCampo(cs["sueldo"], "SUELDO", "sueldo", "CAMP-0003", "NUMERO", es_sensible=True),
        DefinicionCampo(cs["antiguedad_fecha"], "FECHA", "fecha", "CAMP-0004", "FECHA"),
        DefinicionCampo(m["puntos"], "PUNTOS", "puntos", "CAMP-0010", "NUMERO"),
        DefinicionCampo(m["ciudad"], "CIUDAD", "ciudad", "CAMP-0011", "TEXTO"),
        DefinicionCampo(m["turno"], "TURNO", "turno", "CAMP-0012", "SI_NO"),
    ]


@pytest.fixture
async def http(motor, cifrador, mundo):
    campos = CacheCampos(StubCampos({mundo["a"]: _defs(mundo), mundo["b"]: []}))
    app = construir_app(motor, cifrador, campos=campos)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _h(campo, operador, valor):
    return {"campo": campo, "operador": operador, "valor": valor}


def _y(*items):
    return {"op": "Y", "items": list(items)}


async def _evaluar(http, m, criterios, empresa="a", *, servicio="notificaciones", **extra):
    return await http.post(
        URL,
        json={"criterios": criterios, **extra},
        headers=interno(servicio, m[empresa]),
    )


async def _ids(http, m, criterios, **extra):
    r = await _evaluar(http, m, criterios, **extra)
    assert r.status_code == 200, r.text
    inv = {v: k for k, v in m["ids"].items()}
    return {inv[i["id"]] for i in r.json()["items"]}


async def test_fijos_por_planta_tipo_y_estatus(http, mundo):
    n, s = mundo["norte"], mundo["sur"]
    assert await _ids(http, mundo, _y(_h("planta_id", "es", s))) == {"n4", "n5", "n6", "n7", "n8"}
    assert await _ids(
        http, mundo, _y(_h("planta_id", "es", n), _h("tipo_empleado", "es", "ADMINISTRATIVO"))
    ) == {"n1"}
    assert await _ids(http, mundo, _y(_h("planta_id", "en", [s]), _h("estatus", "no_es", "BAJA"))) == {
        "n4", "n5", "n6", "n8",
    }  # fmt: skip
    assert await _ids(http, mundo, _y(_h("estatus", "es", "BAJA"))) == {"n7"}


async def test_listas_texto_numero_fecha_y_si_no(http, mundo):
    assert await _ids(http, mundo, _y(_h("CAMP-0002", "es", "VENTAS"))) == {"n1", "n2"}
    # no_es incluye a quien no tiene valor (todos menos n1 y n2)
    no_ventas = await _ids(http, mundo, _y(_h("CAMP-0002", "no_es", "VENTAS")))
    assert "n1" not in no_ventas and "n2" not in no_ventas and {"n3", "n4", "n7"} <= no_ventas
    assert len(no_ventas) == len(mundo["ids"]) - 1 - 2  # sin el colaborador de otra empresa
    assert await _ids(http, mundo, _y(_h("CAMP-0011", "contiene", "monterrey"))) == {"n1"}
    assert await _ids(http, mundo, _y(_h("CAMP-0011", "es", "saltillo"))) == {"n2"}
    assert "n3" in await _ids(http, mundo, _y(_h("CAMP-0011", "no_es", "Saltillo")))
    assert await _ids(http, mundo, _y(_h("CAMP-0010", ">=", 20))) == {"n2", "n3"}
    assert await _ids(http, mundo, _y(_h("CAMP-0010", "entre", [10, 20]))) == {"n1", "n2"}
    assert await _ids(http, mundo, _y(_h("CAMP-0010", "<", 20))) == {"n1"}
    assert await _ids(http, mundo, _y(_h("CAMP-0004", "antes", "2025-01-01"))) == {"n1"}
    assert await _ids(http, mundo, _y(_h("CAMP-0004", "entre", ["2024-01-01", "2025-12-31"]))) == {
        "n1",
        "n2",
    }
    assert await _ids(http, mundo, _y(_h("CAMP-0012", "es", True))) == {"n1"}
    assert await _ids(http, mundo, _y(_h("CAMP-0012", "es", False))) == {"n2"}


async def test_grupos_y_o(http, mundo):
    criterios = {
        "op": "O",
        "items": [
            _h("CAMP-0010", "=", 30),
            {
                "op": "Y",
                "items": [_h("planta_id", "es", mundo["sur"]), _h("estatus", "es", "BAJA")],
            },
        ],
    }
    assert await _ids(http, mundo, criterios) == {"n3", "n7"}


async def test_antiguedad_en_anios_completos_con_make_interval(http, mundo):
    # e5 ingresó hoy hace 5 años exactos (cumple 5), e4 un día después (4 años), e6 6 años menos 1 día
    # (en realidad ya cumplió 5 y le falta 1 día para los 6: no cumple 6).
    assert {"e5", "e6"} <= await _ids(http, mundo, _y(_h("antiguedad_anios", ">=", 5)))
    assert "e4" not in await _ids(http, mundo, _y(_h("antiguedad_anios", ">=", 5)))
    assert await _ids(
        http, mundo, _y(_h("antiguedad_anios", "=", 5), _h("planta_id", "es", mundo["norte"]))
    ) == {"e5", "e6"}
    assert "e4" in await _ids(http, mundo, _y(_h("antiguedad_anios", "=", 4)))
    assert "e5" not in await _ids(http, mundo, _y(_h("antiguedad_anios", "<", 5)))
    assert "e4" in await _ids(http, mundo, _y(_h("antiguedad_anios", "<", 5)))
    assert "e5" in await _ids(http, mundo, _y(_h("antiguedad_anios", "<=", 5)))
    assert "e5" not in await _ids(http, mundo, _y(_h("antiguedad_anios", ">", 5)))


async def test_solo_conteo_devuelve_el_total_sin_items(http, mundo):
    r = await _evaluar(http, mundo, _y(_h("planta_id", "es", mundo["sur"])), solo_conteo=True)
    d = r.json()
    assert r.status_code == 200 and d["total"] == 5 and d["items"] == []
    assert d["embudo"] == {
        "seleccionados": 5, "con_consentimiento": 4, "activos": 4, "celular_valido": 3,
    }  # fmt: skip


async def test_un_cambio_de_planta_cambia_el_resultado_en_la_siguiente_evaluacion(http, mundo):
    criterios = _y(_h("planta_id", "es", mundo["norte"]), _h("CAMP-0010", ">=", 0))
    antes = await _ids(http, mundo, criterios)
    assert "n1" in antes
    with psycopg.connect(mundo["bd"].url_admin, autocommit=True) as c:
        c.execute(
            "UPDATE colaboradores.colaborador SET planta_id = %s WHERE id = %s",
            (mundo["sur"], mundo["ids"]["n1"]),
        )
    despues = await _ids(http, mundo, criterios)
    assert despues == antes - {"n1"}


async def test_items_con_motivo_unico_datos_minimos_y_sin_celular_completo(http, mundo):
    r = await _evaluar(http, mundo, _y(_h("planta_id", "es", mundo["sur"])))
    por_id = {i["id"]: i for i in r.json()["items"]}
    n7, n8, n4 = (por_id[mundo["ids"][k]] for k in ("n7", "n8", "n4"))
    # n7: sin consentimiento y en BAJA: un solo motivo, el primero en el orden
    assert n7["motivo_exclusion"] == "SIN_CONSENTIMIENTO"
    assert n8["motivo_exclusion"] == "SIN_CELULAR_VALIDO" and n4["motivo_exclusion"] is None
    assert set(n4) == {"id", "nombre", "planta_nombre", "celular_ultimos4", "motivo_exclusion"}
    assert n4["nombre"] == "Nombre Pat" + "N4 Mat" and n4["planta_nombre"] == "Sur"
    assert n4["celular_ultimos4"] == "1234"
    assert "celular" not in r.text.replace("celular_ultimos4", "").replace("celular_valido", "")


async def test_paginacion_por_cursor(http, mundo):
    criterios = _y(_h("planta_id", "es", mundo["sur"]))
    vistos, cursor = [], None
    for _ in range(10):
        r = await _evaluar(
            http, mundo, criterios, limite=2, **({"cursor": cursor} if cursor else {})
        )
        d = r.json()
        assert d["total"] == 5
        vistos += [i["id"] for i in d["items"]]
        cursor = d["siguiente_cursor"]
        if not cursor:
            break
    assert vistos == sorted(vistos) and len(vistos) == len(set(vistos)) == 5
    malo = await _evaluar(http, mundo, criterios, cursor="no-es-un-cursor")
    assert malo.status_code == 422


async def test_aislamiento_por_empresa(http, mundo):
    # la empresa B no ve a A aunque pida el id de planta de A, y A no ve a B
    r = await _evaluar(http, mundo, _y(_h("planta_id", "es", mundo["norte"])), empresa="b")
    assert r.status_code == 200 and r.json()["total"] == 0
    r = await _evaluar(http, mundo, _y(_h("planta_id", "es", mundo["planta_b"])), empresa="b")
    assert [i["id"] for i in r.json()["items"]] == [mundo["ids"]["b1"]]
    r = await _evaluar(http, mundo, _y(_h("planta_id", "es", mundo["planta_b"])))
    assert r.json()["total"] == 0
    # los campos de A no existen para B
    r = await _evaluar(http, mundo, _y(_h("CAMP-0010", ">", 0)), empresa="b")
    assert r.status_code == 422


async def test_rechazos_422_campos_sensibles_inyeccion_y_zona(http, mundo):
    r = await _evaluar(http, mundo, _y(_h("CAMP-0001", "es", "123")))  # NSS, sensible
    assert r.status_code == 422
    assert r.json()["errores"][0]["codigo"] == "CAMPO_SENSIBLE_NO_FILTRABLE"
    r = await _evaluar(http, mundo, _y(_h("celular_hash", "es", "x")))
    assert r.status_code == 422 and r.json()["errores"][0]["codigo"] == "CAMPO_DESCONOCIDO"
    r = await _evaluar(
        http, mundo, _y(_h("CAMP-0011", "es", "x'; DROP TABLE colaboradores.colaborador; --"))
    )
    assert r.status_code == 200 and r.json()["total"] == 0
    r = await _evaluar(http, mundo, _y(_h("CAMP-0011", "contiene", "%' OR '1'='1")))
    assert r.json()["total"] == 0
    # la tabla sigue ahí y con los mismos datos
    r = await _evaluar(http, mundo, _y(_h("estatus", "es", "ACTIVO")), solo_conteo=True)
    assert r.json()["total"] >= 9
    r = await _evaluar(http, mundo, _y(_h("estatus", "es", "ACTIVO")), zona_horaria="No/Existe")
    assert r.status_code == 422 and r.json()["errores"][0]["codigo"] == "ZONA_INVALIDA"
    r = await _evaluar(
        http,
        mundo,
        _y(_h("estatus", "es", "ACTIVO")),
        zona_horaria="Pacific/Auckland",
        solo_conteo=True,
    )
    assert r.status_code == 200


async def test_solo_notificaciones_puede_llamar_y_exige_empresa(http, mundo):
    body = {"criterios": _y(_h("estatus", "es", "ACTIVO"))}
    for servicio in ("whatsapp", "constancias", "campos"):
        r = await http.post(URL, json=body, headers=interno(servicio, mundo["a"]))
        assert r.status_code == 401
    r = await http.post(URL, json=body, headers=interno("notificaciones", None))
    assert r.status_code == 422
    r = await http.post(URL, json=body)
    assert r.status_code == 401
