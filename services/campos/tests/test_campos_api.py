"""T-205: listado, alta y detalle de campos (CAM-01 a CAM-03) con PostgreSQL real."""

import pytest
from ayudantes_campos import sql
from cc_campos.clientes import PlantillaUso

pytestmark = pytest.mark.docker

NUEVO = {
    "nombre_campo": "Bono de productividad",
    "clave": "bono_productividad",
    "tipo_dato": "NUMERO",
    "es_sensible": True,
}


async def _crear(http, h, **cambios):
    r = await http.post("/api/v1/campos", json={**NUEVO, **cambios}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def test_listado_trae_los_once_fijos_como_lista_estatica(http, h):
    r = await http.get("/api/v1/campos", headers=h)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["dinamicos"] == []
    assert len(cuerpo["fijos"]) == 11
    assert [f["clave"] for f in cuerpo["fijos"]][:2] == ["numero_empleado", "nombres"]
    assert all(f["obligatorio"] for f in cuerpo["fijos"])


async def test_codigo_interno_por_contador_y_empresa(http, h, hb):
    uno = await _crear(http, h)
    dos = await _crear(http, h, clave="otro_campo", nombre_campo="Otro")
    otra = await _crear(http, hb, clave="bono_productividad")  # misma clave en otra empresa
    assert (uno["codigo_interno"], dos["codigo_interno"]) == ("CAMP-0001", "CAMP-0002")
    assert otra["codigo_interno"] == "CAMP-0001"
    assert (uno["orden"], dos["orden"]) == (1, 2)
    assert uno["es_sugerido"] is False and uno["activo"] is True and uno["opciones"] == []


async def test_el_contador_no_deja_huecos_si_el_alta_falla(http, h):
    await _crear(http, h)
    r = await http.post("/api/v1/campos", json=NUEVO, headers=h)  # clave repetida
    assert r.status_code == 409 and r.json()["codigo"] == "CLAVE_DUPLICADA"
    siguiente = await _crear(http, h, clave="siguiente", nombre_campo="Siguiente")
    assert siguiente["codigo_interno"] == "CAMP-0002"


@pytest.mark.parametrize(
    "clave",
    ["1bono", "a", "con-guion", "con espacio", "x" * 42, "ñandu"],
)
async def test_clave_con_patron_invalido(http, h, clave):
    r = await http.post("/api/v1/campos", json={**NUEVO, "clave": clave}, headers=h)
    assert r.status_code == 422, clave


@pytest.mark.parametrize(
    "clave",
    ["nombre_completo", "puesto", "planta", "fecha_ingreso", "organizacion", "folio", "horario"],
)
async def test_clave_reservada(http, h, clave):
    r = await http.post("/api/v1/campos", json={**NUEVO, "clave": clave}, headers=h)
    assert r.status_code == 422 and r.json()["codigo"] == "CLAVE_RESERVADA"


async def test_la_clave_se_normaliza_a_minusculas(http, h):
    assert (await _crear(http, h, clave="  Bono_Mensual "))["clave"] == "bono_mensual"


async def test_formato_se_prueba_con_re2_y_se_limita(http, h):
    ok = await _crear(http, h, tipo_dato="TEXTO", formato_validacion=r"^\d{4}$", es_sensible=False)
    assert ok["formato_validacion"] == r"^\d{4}$"
    for formato, codigo in (
        (r"(?=a)b", "FORMATO_INVALIDO"),  # lookahead: re2 no lo admite
        (r"(a)\1", "FORMATO_INVALIDO"),  # referencia hacia atrás
        ("(", "FORMATO_INVALIDO"),
        ("a" * 201, "DEMASIADO_LARGO"),
    ):
        r = await http.post(
            "/api/v1/campos",
            json={**NUEVO, "clave": "campo_x", "tipo_dato": "TEXTO", "formato_validacion": formato},
            headers=h,
        )
        assert r.status_code == 422, formato
        assert r.json()["errores"][0]["codigo"] == codigo or r.json()["codigo"] == codigo
    # un patrón "catastrófico" para motores con retroceso es lineal en re2 y se acepta
    assert (
        await _crear(
            http,
            h,
            clave="lineal",
            tipo_dato="TEXTO",
            formato_validacion=r"^(a+)+$",
            es_sensible=False,
        )
    )["formato_validacion"]
    # el formato solo aplica a texto y número
    r = await http.post(
        "/api/v1/campos",
        json={**NUEVO, "clave": "fecha_x", "tipo_dato": "FECHA", "formato_validacion": r"\d+"},
        headers=h,
    )
    assert r.status_code == 422 and r.json()["codigo"] == "FORMATO_NO_APLICA"


async def test_filtros_de_pestanas_y_estado(http, h, datos):
    await _crear(http, h)
    await _crear(http, h, clave="otro", nombre_campo="Otro")
    sql(
        datos,
        "INSERT INTO campos.campo_colaborador (empresa_id, nombre_campo, clave, codigo_interno, "
        "tipo_dato, orden, es_sugerido, activo) VALUES (%s, 'Área', 'area', 'CAMP-0099', 'LISTA', "
        "0, true, false)",
        (datos["a"],),
    )

    async def claves(**params):
        r = await http.get("/api/v1/campos", params=params, headers=h)
        return [c["clave"] for c in r.json()["dinamicos"]]

    assert await claves() == ["area", "bono_productividad", "otro"]  # por orden
    assert await claves(tipo="sugeridos") == ["area"]
    assert await claves(tipo="personalizados") == ["bono_productividad", "otro"]
    assert await claves(estado="inactivos") == ["area"]
    assert await claves(estado="activos", tipo="todos") == ["bono_productividad", "otro"]
    assert (await http.get("/api/v1/campos?tipo=raros", headers=h)).status_code == 422


async def test_listado_trae_el_uso_en_plantillas_y_tolera_que_constancias_falle(
    http, h, constancias
):
    await _crear(http, h)
    constancias.usos["bono_productividad"] = [
        PlantillaUso(1, "Constancia"),
        PlantillaUso(2, "Otra"),
    ]
    r = await http.get("/api/v1/campos", headers=h)
    assert r.json()["dinamicos"][0]["usada_en_plantillas"] == 2
    assert constancias.llamadas[-1] == (1, ["bono_productividad"])  # una sola consulta por lote

    from cc_common.errores import ErrorProveedor

    async def falla(*_a, **_k):
        raise ErrorProveedor()

    constancias.uso_de_variables = falla
    r = await http.get("/api/v1/campos", headers=h)
    assert r.status_code == 200 and r.json()["dinamicos"][0]["usada_en_plantillas"] is None


async def test_detalle_y_404(http, h, hb):
    campo = await _crear(http, h)
    r = await http.get(f"/api/v1/campos/{campo['id']}", headers=h)
    assert r.status_code == 200 and r.json()["codigo_interno"] == "CAMP-0001"
    assert (await http.get("/api/v1/campos/999999", headers=h)).status_code == 404
    # la otra empresa no ve el campo
    assert (await http.get(f"/api/v1/campos/{campo['id']}", headers=hb)).status_code == 404
    assert (await http.get("/api/v1/campos", headers=hb)).json()["dinamicos"] == []


async def test_alta_registra_bitacora_y_evento(http, h, datos):
    campo = await _crear(http, h)
    bit = sql(datos, "SELECT accion, entidad_id, usuario_id, detalle FROM auditoria.bitacora")
    assert bit == [("CAMPO_CREADO", campo["id"], datos["ua"], {"codigos_internos": ["CAMP-0001"]})]
    ev = sql(datos, "SELECT destino_tipo, tipo, payload FROM campos.outbox")
    assert ev == [
        (
            "EVENTBRIDGE",
            "campo.actualizado",
            {"empresa_id": datos["a"], "campo_id": campo["id"], "accion": "CREADO"},
        )
    ]


async def test_requiere_sesion_y_usuario(http, datos):
    assert (await http.get("/api/v1/campos")).status_code == 401
    from ayudantes_campos import cab, emitir

    sin_usuario = cab(emitir("sub-a", datos["a"], None))
    r = await http.post("/api/v1/campos", json=NUEVO, headers=sin_usuario)
    assert r.status_code in (401, 403)
