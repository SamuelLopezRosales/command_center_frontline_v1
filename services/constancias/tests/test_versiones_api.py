"""T-208 (T-080 y T-081): validación, publicación, versiones y restauración (CON-09 a CON-13)
con PostgreSQL y LocalStack."""

import asyncio

import pytest
from ayudantes_constancias import canonico, sql
from cc_common.errores import ErrorDominio
from cc_constancias import contenido as esquema
from cc_constancias.clientes import DefinicionCampo
from cc_constancias.servicios import publicacion

pytestmark = pytest.mark.docker


def _defs():
    return [
        DefinicionCampo(1, "Área", "area", "CAMP-0001", "LISTA", orden=1),
        DefinicionCampo(2, "NSS", "nss", "CAMP-0002", "TEXTO", es_sensible=True, orden=2),
        DefinicionCampo(3, "Sueldo", "sueldo", "CAMP-0003", "NUMERO", es_sensible=True, orden=3),
        DefinicionCampo(4, "Periodicidad", "periodicidad_sueldo", "CAMP-0004", "LISTA", orden=4),
        DefinicionCampo(5, "Ruta", "ruta_transporte", "CAMP-0005", "TEXTO", activo=False, orden=5),
    ]


def doc(*variables: str, texto: str = "hola") -> dict:
    return {
        "esquema": 1,
        "bloques": [
            {
                "tipo": "parrafo",
                "contenido": [{"texto": texto}, *({"var": v} for v in variables)],
            }
        ],
    }


@pytest.fixture(autouse=True)
def definiciones(campos, datos):
    campos.por_empresa[datos["a"]] = _defs()


async def _plantilla(http, h, nombre="Constancia laboral"):
    return (await http.post("/api/v1/plantillas", json={"nombre": nombre}, headers=h)).json()


async def _borrador(http, h, p, contenido, if_match=None):
    cab = dict(h) | ({"If-Match": f'"{if_match}"'} if if_match else {})
    r = await http.put(f"/api/v1/plantillas/{p['id']}/borrador", json=contenido, headers=cab)
    assert r.status_code == 200, r.text
    return r.json()["hash"]


async def _publicar(http, h, p, **cuerpo):
    return await http.post(f"/api/v1/plantillas/{p['id']}/publicar", json=cuerpo or None, headers=h)


async def _estado(http, h, p):
    return (await http.get(f"/api/v1/plantillas/{p['id']}", headers=h)).json()


# ------------------------------------------------------------------ validar (CON-09)


async def test_validar_sin_borrador_da_404(http, h):
    p = await _plantilla(http, h)
    r = await http.post(f"/api/v1/plantillas/{p['id']}/borrador/validar", headers=h)
    assert r.status_code == 404 and r.json()["codigo"] == "BORRADOR_NO_EXISTE"


async def test_validar_un_borrador_limpio_no_trae_errores_ni_advertencias(http, h):
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("nombre_completo", "puesto", "area", "folio", "lugar"))
    r = await http.post(f"/api/v1/plantillas/{p['id']}/borrador/validar", headers=h)
    assert r.status_code == 200 and r.json() == {"errores": [], "advertencias": []}


async def test_validar_marca_variables_inexistentes_e_inactivas(http, h):
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("area", "fantasma", "ruta_transporte", "empresa", "fantasma"))
    r = await http.post(f"/api/v1/plantillas/{p['id']}/borrador/validar", headers=h)
    errores = [(e["codigo"], e["variables"]) for e in r.json()["errores"]]
    assert errores == [
        ("VARIABLE_INEXISTENTE", ["fantasma"]),
        ("VARIABLE_INEXISTENTE", ["empresa"]),
        ("VARIABLE_INACTIVA", ["ruta_transporte"]),
    ]


async def test_validar_advierte_de_sensibles_y_cuenta_colaboradores_sin_valor(
    http, h, colaboradores
):
    colaboradores.vacios = {"CAMP-0001": 0, "CAMP-0002": 2, "CAMP-0003": 1}
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("area", "nss", "sueldo_letra", "puesto"))
    r = await http.post(f"/api/v1/plantillas/{p['id']}/borrador/validar", headers=h)
    cuerpo = r.json()
    assert cuerpo["errores"] == []
    por_codigo = {a["codigo"]: a for a in cuerpo["advertencias"]}
    assert por_codigo["VARIABLES_SENSIBLES"]["variables"] == ["nss", "sueldo_letra"]
    vacios = [a for a in cuerpo["advertencias"] if a["codigo"] == "COLABORADORES_SIN_VALOR"]
    assert [(a["variables"], a["total"], a["mensaje"]) for a in vacios] == [
        (["nss"], 2, "2 colaboradores sin NSS."),
        (["sueldo"], 1, "1 colaborador sin Sueldo."),  # las derivadas piden sueldo y periodicidad
    ]
    # un solo lote a INT-COL-09, con los campos usados y sin repetir
    assert colaboradores.llamadas_faltantes == [
        ["CAMP-0001", "CAMP-0002", "CAMP-0003", "CAMP-0004"]
    ]


async def test_validar_no_cuenta_lo_que_es_error_ni_llama_si_no_hay_campos(http, h, colaboradores):
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("nombre_completo", "folio", "organizacion.rfc"))
    r = await http.post(f"/api/v1/plantillas/{p['id']}/borrador/validar", headers=h)
    assert r.json() == {"errores": [], "advertencias": []}
    assert colaboradores.llamadas_faltantes == []  # nada que contar
    await _borrador(
        http, h, p, doc("fantasma", "ruta_transporte"), if_match=(await _hash(http, h, p))
    )
    await http.post(f"/api/v1/plantillas/{p['id']}/borrador/validar", headers=h)
    assert colaboradores.llamadas_faltantes == []  # ni las inexistentes ni las inactivas


async def _hash(http, h, p):
    return (await http.get(f"/api/v1/plantillas/{p['id']}/borrador", headers=h)).json()["hash"]


async def test_si_colaboradores_no_responde_validar_da_502_pero_publicar_no_lo_necesita(
    http, h, colaboradores
):
    from cc_common.errores import ErrorProveedor

    async def cae(*_a, **_k):
        raise ErrorProveedor()

    colaboradores.faltantes_contar = cae
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("area"))
    assert (
        await http.post(f"/api/v1/plantillas/{p['id']}/borrador/validar", headers=h)
    ).status_code == 502
    assert (await _publicar(http, h, p)).status_code == 201


async def test_validar_es_por_empresa(http, h, hb):
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("area"))
    assert (
        await http.post(f"/api/v1/plantillas/{p['id']}/borrador/validar", headers=hb)
    ).status_code == 404


# ------------------------------------------------------------------ publicar (CON-10)


async def test_una_variable_inexistente_o_inactiva_impide_publicar(http, h, datos):
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("area", "fantasma", "ruta_transporte"))
    r = await _publicar(http, h, p)
    assert r.status_code == 422 and r.json()["codigo"] == "PLANTILLA_VARIABLE_INVALIDA"
    assert [(e["campo"], e["codigo"]) for e in r.json()["errores"]] == [
        ("variables.fantasma", "VARIABLE_INEXISTENTE"),
        ("variables.ruta_transporte", "VARIABLE_INACTIVA"),
    ]
    assert sql(datos, "SELECT count(*) FROM constancias.version_plantilla") == [(0,)]
    assert (await _estado(http, h, p))["activa"] is False


async def test_las_variables_sensibles_piden_confirmacion(http, h, datos):
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("nss", "sueldo_mensual", "area"))
    r = await _publicar(http, h, p)
    assert (
        r.status_code == 409 and r.json()["codigo"] == "PLANTILLA_SENSIBLES_REQUIERE_CONFIRMACION"
    )
    assert r.json()["detalle"] == {"campos": ["nss", "sueldo_mensual"]}
    assert sql(datos, "SELECT count(*) FROM constancias.version_plantilla") == [(0,)]
    r = await _publicar(http, h, p, confirmar_sensibles=False)
    assert r.status_code == 409
    r = await _publicar(http, h, p, confirmar_sensibles=True)
    assert r.status_code == 201 and r.json()["numero"] == 1


async def test_publicar_guarda_el_contenido_en_s3_con_su_hash_y_activa_la_plantilla(
    http, h, datos, s3_plantillas
):
    _, cliente, bucket = s3_plantillas
    p = await _plantilla(http, h)
    contenido = doc("nombre_completo", "area")
    hash_borrador = await _borrador(http, h, p, contenido)
    r = await _publicar(http, h, p)
    assert r.status_code == 201
    v = r.json()
    cuerpo, hash_ = canonico(contenido)
    assert (v["numero"], v["hash"], v["vigente"]) == (1, hash_, True) == (1, hash_borrador, True)
    clave = f"plantillas/{datos['a']}/{p['id']}/v1.json"
    assert cliente.get_object(Bucket=bucket, Key=clave)["Body"].read() == cuerpo
    fila = sql(
        datos,
        "SELECT empresa_id, numero, contenido_s3_key, hash_sha256, creada_por_usuario_id "
        "FROM constancias.version_plantilla",
    )
    assert fila == [(datos["a"], 1, clave, hash_, datos["ua"])]
    estado = await _estado(http, h, p)  # la primera publicación activa la plantilla
    assert (estado["activa"], estado["estado"], estado["version"]) == (True, "ACTIVA", 1)
    bit = sql(
        datos,
        "SELECT usuario_id, detalle FROM auditoria.bitacora WHERE accion = 'PLANTILLA_PUBLICADA'",
    )
    assert bit == [(datos["ua"], {"plantilla_id": p["id"], "version": 1})]
    # el borrador sigue ahí: el editor puede seguir trabajando sobre la siguiente versión
    assert (await http.get(f"/api/v1/plantillas/{p['id']}/borrador", headers=h)).status_code == 200


async def test_las_publicaciones_siguientes_numeran_y_no_reactivan(http, h, datos):
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("area"))
    assert (await _publicar(http, h, p)).json()["numero"] == 1
    await http.patch(f"/api/v1/plantillas/{p['id']}", json={"activa": False}, headers=h)
    await _borrador(http, h, p, doc("area", "puesto"), if_match=await _hash(http, h, p))
    v2 = (await _publicar(http, h, p)).json()
    assert v2["numero"] == 2 and v2["hash"] == canonico(doc("area", "puesto"))[1]
    estado = await _estado(http, h, p)
    assert (estado["activa"], estado["estado"], estado["version"]) == (False, "INACTIVA", 2)


async def test_una_version_publicada_no_se_puede_modificar_en_la_base(http, h, datos):
    import psycopg

    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("area"))
    await _publicar(http, h, p)
    for consulta in (
        "UPDATE constancias.version_plantilla SET hash_sha256 = repeat('a', 64)",
        "UPDATE constancias.version_plantilla SET numero = 9",
        "DELETE FROM constancias.version_plantilla",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            sql(datos, consulta)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):  # tampoco con el rol del servicio
        with psycopg.connect(
            datos["bd"].url_rol("svc_constancias", asincrona=False), autocommit=True
        ) as c:
            c.execute("SELECT set_config('app.empresa_id', %s, false)", (str(datos["a"]),))
            c.execute("UPDATE constancias.version_plantilla SET hash_sha256 = repeat('b', 64)")


async def test_publicar_sin_borrador_ajena_o_eliminada(http, h, hb):
    p = await _plantilla(http, h)
    r = await _publicar(http, h, p)
    assert r.status_code == 404 and r.json()["codigo"] == "BORRADOR_NO_EXISTE"
    await _borrador(http, h, p, doc("area"))
    assert (await _publicar(http, hb, p)).status_code == 404
    await http.delete(f"/api/v1/plantillas/{p['id']}", headers=h)
    assert (await _publicar(http, h, p)).status_code == 404
    assert (await _publicar(http, h, {"id": 999999})).status_code == 404


async def test_publicar_rechaza_cuerpos_con_campos_extra(http, h):
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("area"))
    assert (await _publicar(http, h, p, confirmar=True)).status_code == 422


async def test_si_el_borrador_cambia_mientras_se_valida_no_se_publica_lo_no_revisado(
    http, h, datos, motor, s3_plantillas
):
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("area"))
    from cc_common.auth import UsuarioActual

    u = UsuarioActual(sub="sub-a", empresa_id=datos["a"], rol="RH", usuario_id=datos["ua"])
    cuerpo, hash_ = canonico(doc("area"))
    with pytest.raises(ErrorDominio) as exc:
        await publicacion._crear_version(
            motor, s3_plantillas[0], u, p["id"], cuerpo, hash_, None, borrador_esperado="0" * 64
        )
    assert exc.value.http == 412 and exc.value.codigo == "VERSION_DESACTUALIZADA"
    assert sql(datos, "SELECT count(*) FROM constancias.version_plantilla") == [(0,)]


async def test_cincuenta_publicaciones_simultaneas_no_repiten_numero(http, h, datos, s3_plantillas):
    _, cliente, bucket = s3_plantillas
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("area", "nombre_completo"))
    respuestas = await asyncio.gather(*[_publicar(http, h, p) for _ in range(50)])
    assert [r.status_code for r in respuestas] == [201] * 50
    numeros = sorted(r.json()["numero"] for r in respuestas)
    assert numeros == list(range(1, 51))  # sin huecos ni repetidos
    assert sql(
        datos,
        "SELECT count(*), count(DISTINCT numero), max(numero) FROM constancias.version_plantilla",
    ) == [(50, 50, 50)]
    claves = {
        o["Key"]
        for o in cliente.list_objects_v2(
            Bucket=bucket, Prefix=f"plantillas/{datos['a']}/{p['id']}/v"
        )["Contents"]
    }
    assert claves == {f"plantillas/{datos['a']}/{p['id']}/v{n}.json" for n in range(1, 51)}
    estado = await _estado(http, h, p)
    assert (estado["version"], estado["activa"]) == (50, True)


# ------------------------------------------------------------------ versiones (CON-11 y CON-12)


async def test_listado_de_versiones_de_la_mas_nueva_a_la_mas_vieja(http, h):
    p = await _plantilla(http, h)
    r = await http.get(f"/api/v1/plantillas/{p['id']}/versiones", headers=h)
    assert r.status_code == 200 and r.json() == {"items": []}
    hash_ = await _borrador(http, h, p, doc("area"))
    for i in range(3):
        await _publicar(http, h, p)
        if i < 2:
            hash_ = await _borrador(http, h, p, doc("area", texto=f"v{i}"), if_match=hash_)
    items = (await http.get(f"/api/v1/plantillas/{p['id']}/versiones", headers=h)).json()["items"]
    assert [(i["numero"], i["vigente"]) for i in items] == [(3, True), (2, False), (1, False)]
    assert len({i["hash"] for i in items}) == 3 and all(len(i["hash"]) == 64 for i in items)


async def test_detalle_de_una_version_trae_su_contenido(http, h):
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("area", texto="Contenido uno"))
    await _publicar(http, h, p)
    r = await http.get(f"/api/v1/plantillas/{p['id']}/versiones/1", headers=h)
    assert r.status_code == 200
    v = r.json()
    assert (v["numero"], v["vigente"]) == (1, True)
    assert v["contenido"]["bloques"][0]["contenido"][0] == {"texto": "Contenido uno"}
    assert (
        await http.get(f"/api/v1/plantillas/{p['id']}/versiones/9", headers=h)
    ).status_code == 404
    assert (await http.get("/api/v1/plantillas/999999/versiones/1", headers=h)).status_code == 404


async def test_versiones_son_por_empresa_y_detectan_un_objeto_alterado(
    http, h, hb, datos, s3_plantillas
):
    _, cliente, bucket = s3_plantillas
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("area"))
    await _publicar(http, h, p)
    for ruta in ("versiones", "versiones/1"):
        assert (
            await http.get(f"/api/v1/plantillas/{p['id']}/{ruta}", headers=hb)
        ).status_code == 404
    clave = f"plantillas/{datos['a']}/{p['id']}/v1.json"
    cliente.put_object(Bucket=bucket, Key=clave, Body=b'{"esquema":1,"alterado":true}')
    r = await http.get(f"/api/v1/plantillas/{p['id']}/versiones/1", headers=h)
    assert r.status_code == 500 and r.json()["codigo"] == "CONTENIDO_INCONSISTENTE"


# ------------------------------------------------------------------ restaurar (CON-13)


async def _con_dos_versiones(http, h):
    p = await _plantilla(http, h)
    a, b = doc("area", texto="primera"), doc("puesto", texto="segunda")
    hash_ = await _borrador(http, h, p, a)
    await _publicar(http, h, p)
    await _borrador(http, h, p, b, if_match=hash_)
    await _publicar(http, h, p)
    return p, a, b


async def test_restaurar_crea_la_version_siguiente_con_el_contenido_elegido(
    http, h, datos, s3_plantillas
):
    _, cliente, bucket = s3_plantillas
    p, a, b = await _con_dos_versiones(http, h)
    antes = sql(
        datos,
        "SELECT numero, contenido_s3_key, hash_sha256, fecha_creacion "
        "FROM constancias.version_plantilla ORDER BY numero",
    )
    borrador_antes = await _hash(http, h, p)
    r = await http.post(f"/api/v1/plantillas/{p['id']}/versiones/1/restaurar", headers=h)
    assert r.status_code == 201, r.text
    v = r.json()
    assert (v["numero"], v["hash"], v["vigente"]) == (3, canonico(a)[1], True)
    clave3 = f"plantillas/{datos['a']}/{p['id']}/v3.json"
    assert cliente.get_object(Bucket=bucket, Key=clave3)["Body"].read() == canonico(a)[0]
    # las versiones anteriores no cambiaron ni en la base ni en S3
    despues = sql(
        datos,
        "SELECT numero, contenido_s3_key, hash_sha256, fecha_creacion "
        "FROM constancias.version_plantilla WHERE numero < 3 ORDER BY numero",
    )
    assert despues == antes
    for n, contenido in ((1, a), (2, b)):
        objeto = cliente.get_object(
            Bucket=bucket, Key=f"plantillas/{datos['a']}/{p['id']}/v{n}.json"
        )
        assert objeto["Body"].read() == canonico(contenido)[0]
    # la vista de versiones y el borrador reflejan lo esperado
    items = (await http.get(f"/api/v1/plantillas/{p['id']}/versiones", headers=h)).json()["items"]
    assert [(i["numero"], i["vigente"]) for i in items] == [(3, True), (2, False), (1, False)]
    assert await _hash(http, h, p) == borrador_antes  # el borrador no se toca
    bit = sql(
        datos,
        "SELECT detalle FROM auditoria.bitacora WHERE accion = 'PLANTILLA_PUBLICADA' ORDER BY id",
    )
    assert bit[-1] == ({"plantilla_id": p["id"], "version": 3},)


async def test_restaurar_no_cambia_si_la_plantilla_esta_activa_y_no_pide_confirmar_sensibles(
    http, h
):
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("nss"))
    await _publicar(http, h, p, confirmar_sensibles=True)
    await http.patch(f"/api/v1/plantillas/{p['id']}", json={"activa": False}, headers=h)
    r = await http.post(f"/api/v1/plantillas/{p['id']}/versiones/1/restaurar", headers=h)
    assert r.status_code == 201 and r.json()["numero"] == 2
    assert (await _estado(http, h, p))["activa"] is False


async def test_restaurar_falla_si_una_variable_dejo_de_existir_o_se_desactivo(
    http, h, campos, datos
):
    p = await _plantilla(http, h)
    await _borrador(http, h, p, doc("area", "nss"))
    await _publicar(http, h, p, confirmar_sensibles=True)
    # `area` se desactiva y `nss` se elimina: ya no son variables válidas
    campos.por_empresa[datos["a"]] = [
        DefinicionCampo(1, "Área", "area", "CAMP-0001", "LISTA", activo=False)
    ]
    r = await http.post(f"/api/v1/plantillas/{p['id']}/versiones/1/restaurar", headers=h)
    assert r.status_code == 422 and r.json()["codigo"] == "PLANTILLA_VARIABLE_INVALIDA"
    assert [(e["campo"], e["codigo"]) for e in r.json()["errores"]] == [
        ("variables.nss", "VARIABLE_INEXISTENTE"),
        ("variables.area", "VARIABLE_INACTIVA"),
    ]
    assert sql(datos, "SELECT count(*) FROM constancias.version_plantilla") == [(1,)]


async def test_restaurar_version_inexistente_ajena_o_de_plantilla_eliminada(http, h, hb):
    p, _, _ = await _con_dos_versiones(http, h)
    assert (
        await http.post(f"/api/v1/plantillas/{p['id']}/versiones/9/restaurar", headers=h)
    ).status_code == 404
    assert (
        await http.post(f"/api/v1/plantillas/{p['id']}/versiones/1/restaurar", headers=hb)
    ).status_code == 404
    await http.delete(f"/api/v1/plantillas/{p['id']}", headers=h)
    assert (
        await http.post(f"/api/v1/plantillas/{p['id']}/versiones/1/restaurar", headers=h)
    ).status_code == 404


async def test_restaurar_dos_veces_seguidas_numera_sin_repetir(http, h):
    p, _, _ = await _con_dos_versiones(http, h)
    r = await asyncio.gather(
        *[
            http.post(f"/api/v1/plantillas/{p['id']}/versiones/1/restaurar", headers=h)
            for _ in range(5)
        ]
    )
    assert sorted(x.json()["numero"] for x in r) == [3, 4, 5, 6, 7]


def test_el_esquema_de_cada_version_guardada_se_puede_volver_a_leer():
    cuerpo, hash_ = canonico(doc("area"))
    assert esquema.hash_de(cuerpo) == hash_ and esquema.leer(cuerpo).bloques
