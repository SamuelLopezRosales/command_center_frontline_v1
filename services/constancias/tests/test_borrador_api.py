"""T-207 (T-077): borradores de plantilla en S3 (CON-07 y CON-08) con PostgreSQL y LocalStack."""

import asyncio
import json

import pytest
from ayudantes_constancias import CONTENIDO, canonico, publicar_version, sql

pytestmark = pytest.mark.docker

OTRO = {
    "esquema": 1,
    "pagina": {"tamano": "A4"},
    "bloques": [
        {
            "tipo": "parrafo",
            "alineacion": "centro",
            "contenido": [{"texto": "Otro", "tamano_pt": 14}],
        }
    ],
}


async def _plantilla(http, h, nombre="Constancia laboral"):
    r = await http.post("/api/v1/plantillas", json={"nombre": nombre}, headers=h)
    return r.json()


def _ruta(p):
    return f"/api/v1/plantillas/{p['id']}/borrador"


async def _put(http, h, p, contenido=CONTENIDO, if_match=None):
    cab = dict(h) | ({"If-Match": if_match} if if_match is not None else {})
    return await http.put(_ruta(p), json=contenido, headers=cab)


# ------------------------------------------------------------------ guardar y leer


async def test_guardar_el_borrador_deja_el_contenido_en_s3_y_ruta_y_hash_en_la_base(
    http, h, datos, s3_plantillas
):
    almacen, cliente, bucket = s3_plantillas
    p = await _plantilla(http, h)
    r = await _put(http, h, p)
    assert r.status_code == 200
    cuerpo, hash_ = canonico()
    assert r.json()["hash"] == hash_ and r.headers["etag"] == f'"{hash_}"'
    clave = f"plantillas/{datos['a']}/{p['id']}/borrador.json"
    # el objeto de S3 es exactamente la forma canónica y su hash es el registrado
    assert cliente.get_object(Bucket=bucket, Key=clave)["Body"].read() == cuerpo
    fila = sql(
        datos,
        "SELECT empresa_id, contenido_s3_key, hash_sha256, actualizado_por_usuario_id "
        "FROM constancias.borrador_plantilla WHERE plantilla_id = %s",
        (p["id"],),
    )
    assert fila == [(datos["a"], clave, hash_, datos["ua"])]
    # el contenido NO está en la base (solo la ruta y el hash)
    assert "hace constar" not in str(sql(datos, "SELECT * FROM constancias.borrador_plantilla"))
    assert (await http.get(f"/api/v1/plantillas/{p['id']}", headers=h)).json()[
        "tiene_borrador"
    ] is True


async def test_leer_el_borrador_devuelve_contenido_hash_y_etag(http, h):
    p = await _plantilla(http, h)
    guardado = (await _put(http, h, p)).json()
    r = await http.get(_ruta(p), headers=h)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["hash"] == guardado["hash"] == json.loads(r.headers["etag"])
    assert cuerpo["fecha_modificacion"] == guardado["fecha_modificacion"]
    assert (
        cuerpo["contenido"]["esquema"] == 1
        and cuerpo["contenido"]["bloques"][0]["tipo"] == "logotipo"
    )
    assert (
        cuerpo["contenido"]["pagina"]["tamano"] == "CARTA"
    )  # los valores por defecto se completan


async def test_sin_borrador_el_detalle_da_404_con_su_codigo(http, h):
    p = await _plantilla(http, h)
    r = await http.get(_ruta(p), headers=h)
    assert r.status_code == 404 and r.json()["codigo"] == "BORRADOR_NO_EXISTE"
    assert (await http.get("/api/v1/plantillas/999999/borrador", headers=h)).json()["codigo"] == (
        "RECURSO_NO_ENCONTRADO"
    )


async def test_guardar_registra_bitacora_sin_contenido_y_mueve_la_fecha_de_la_plantilla(
    http, h, datos
):
    p = await _plantilla(http, h)
    antes = (await http.get(f"/api/v1/plantillas/{p['id']}", headers=h)).json()[
        "fecha_modificacion"
    ]
    await _put(http, h, p)
    despues = (await http.get(f"/api/v1/plantillas/{p['id']}", headers=h)).json()[
        "fecha_modificacion"
    ]
    assert despues > antes
    bit = sql(
        datos,
        "SELECT accion, usuario_id, detalle FROM auditoria.bitacora WHERE accion = 'PLANTILLA_MODIFICADA'",
    )
    assert bit == [("PLANTILLA_MODIFICADA", datos["ua"], {"campos": ["borrador"]})]


# ------------------------------------------------------------------ If-Match


async def test_sobre_un_borrador_existente_if_match_es_obligatorio_y_debe_coincidir(http, h):
    p = await _plantilla(http, h)
    primero = (await _put(http, h, p)).json()
    r = await _put(http, h, p, OTRO)  # sin If-Match
    assert r.status_code == 428 and r.json()["codigo"] == "PRECONDICION_REQUERIDA"
    r = await _put(http, h, p, OTRO, if_match='"' + "0" * 64 + '"')
    assert r.status_code == 412 and r.json()["codigo"] == "VERSION_DESACTUALIZADA"
    # nada cambió
    assert (await http.get(_ruta(p), headers=h)).json()["hash"] == primero["hash"]
    # con el ETag leído sí
    r = await _put(http, h, p, OTRO, if_match=f'"{primero["hash"]}"')
    assert r.status_code == 200 and r.json()["hash"] == canonico(OTRO)[1] != primero["hash"]
    # el ETag viejo ya no sirve: no se pisa la edición ajena
    r = await _put(http, h, p, CONTENIDO, if_match=f'"{primero["hash"]}"')
    assert r.status_code == 412


@pytest.mark.parametrize("forma", ["{h}", '"{h}"', 'W/"{h}"', '  "{h}"  '])
async def test_if_match_acepta_el_etag_con_o_sin_comillas_y_debil(http, h, forma):
    p = await _plantilla(http, h)
    hash_ = (await _put(http, h, p)).json()["hash"]
    r = await _put(http, h, p, OTRO, if_match=forma.format(h=hash_))
    assert r.status_code == 200, forma


async def test_if_match_sobre_un_borrador_que_no_existe_da_412(http, h, datos):
    p = await _plantilla(http, h)
    r = await _put(http, h, p, if_match='"' + "a" * 64 + '"')
    assert r.status_code == 412
    assert sql(datos, "SELECT count(*) FROM constancias.borrador_plantilla") == [(0,)]


async def test_dos_guardados_simultaneos_con_el_mismo_etag_solo_uno_gana(http, h, datos):
    p = await _plantilla(http, h)
    base = (await _put(http, h, p)).json()["hash"]
    a = {"esquema": 1, "bloques": [{"tipo": "parrafo", "contenido": [{"texto": "A"}]}]}
    b = {"esquema": 1, "bloques": [{"tipo": "parrafo", "contenido": [{"texto": "B"}]}]}
    ra, rb = await asyncio.gather(
        _put(http, h, p, a, if_match=base), _put(http, h, p, b, if_match=base)
    )
    assert sorted([ra.status_code, rb.status_code]) == [200, 412]
    ganador = a if ra.status_code == 200 else b
    leido = (await http.get(_ruta(p), headers=h)).json()
    assert leido["hash"] == canonico(ganador)[1]


async def test_guardar_el_mismo_contenido_es_idempotente(http, h, datos, s3_plantillas):
    p = await _plantilla(http, h)
    uno = (await _put(http, h, p)).json()
    bit_antes = sql(
        datos, "SELECT count(*) FROM auditoria.bitacora WHERE accion = 'PLANTILLA_MODIFICADA'"
    )
    # el mismo contenido con otro orden de claves y espacios da el mismo hash y no escribe nada
    r = await http.put(
        _ruta(p),
        content=json.dumps(dict(reversed(list(CONTENIDO.items()))), indent=4),
        headers=h | {"If-Match": f'"{uno["hash"]}"', "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json() == uno  # misma fecha: no hubo escritura
    assert (
        sql(datos, "SELECT count(*) FROM auditoria.bitacora WHERE accion = 'PLANTILLA_MODIFICADA'")
        == bit_antes
    )


# ------------------------------------------------------------------ rechazos 422 y 413


@pytest.mark.parametrize(
    ("contenido", "codigo"),
    [
        ({"esquema": 1, "bloques": [{"tipo": "html", "contenido": "<b>x</b>"}]}, "HTML_NO_PERMITIDO"),
        ({"esquema": 1, "bloques": [{"tipo": "parrafo", "contenido": [{"texto": "<script>x</script>"}]}]}, "HTML_NO_PERMITIDO"),
        ({"esquema": 1, "bloques": [{"tipo": "parrafo", "contenido": [{"texto": "x", "html": "<i>"}]}]}, "HTML_NO_PERMITIDO"),
        ({"esquema": 1, "bloques": [{"tipo": "parrafo", "contenido": [{"texto": "x", "color": "azul"}]}]}, "COLOR_INVALIDO"),
        ({"esquema": 1, "bloques": [{"tipo": "parrafo", "contenido": [{"texto": "x", "tamano_pt": 7}]}]}, "TAMANO_FUERA_DE_RANGO"),
        ({"esquema": 1, "bloques": [{"tipo": "parrafo", "contenido": [{"texto": "x", "tamano_pt": 49}]}]}, "TAMANO_FUERA_DE_RANGO"),
        ({"esquema": 2, "bloques": []}, "VALOR_NO_PERMITIDO"),
        ({"bloques": []}, "REQUERIDO"),
    ],
)  # fmt: skip
async def test_un_contenido_invalido_se_rechaza_con_422_y_no_toca_el_borrador(
    http, h, contenido, codigo
):
    p = await _plantilla(http, h)
    base = (await _put(http, h, p)).json()["hash"]
    r = await _put(http, h, p, contenido, if_match=f'"{base}"')
    assert r.status_code == 422
    cuerpo = r.json()
    assert cuerpo["codigo"] == "CONTENIDO_INVALIDO"
    assert codigo in [e["codigo"] for e in cuerpo["errores"]]
    assert (await http.get(_ruta(p), headers=h)).json()["hash"] == base


async def test_json_mal_formado_da_422_y_el_error_no_repite_lo_recibido(http, h):
    p = await _plantilla(http, h)
    r = await http.put(
        _ruta(p),
        content=b'{"esquema": 1, "token": "SECRETO-123"',
        headers=h | {"Content-Type": "application/json"},
    )
    assert r.status_code == 422 and "SECRETO-123" not in r.text
    r = await http.put(
        _ruta(p),
        content=b'{"esquema": 1, "color": "SECRETO-123"}',
        headers=h | {"Content-Type": "application/json"},
    )
    assert r.status_code == 422 and "SECRETO-123" not in r.text


def _grande(bytes_aprox: int) -> dict:
    nodos = [{"texto": "x" * 40}] * 50
    n = max(1, bytes_aprox // (50 * 56))
    return {"esquema": 1, "bloques": [{"tipo": "parrafo", "contenido": nodos}] * min(n, 200)}


async def test_mas_de_512_kb_da_413_antes_de_analizar(http, h, datos):
    p = await _plantilla(http, h)
    cuerpo = json.dumps({"esquema": 1, "relleno": "x" * (512 * 1024)}).encode()
    assert len(cuerpo) > 512 * 1024
    r = await http.put(_ruta(p), content=cuerpo, headers=h | {"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["codigo"] == "CONTENIDO_DEMASIADO_GRANDE"
    assert r.json()["detalle"] == {"limite": 512 * 1024}
    assert sql(datos, "SELECT count(*) FROM constancias.borrador_plantilla") == [(0,)]


async def test_413_tambien_sin_content_length(http, h):
    """Un cuerpo en trozos (sin ``Content-Length``) se corta al pasar el límite."""
    p = await _plantilla(http, h)

    async def trozos():
        for _ in range(130):
            yield b" " * 4096  # 520 KB de espacios en blanco

    r = await http.put(_ruta(p), content=trozos(), headers=h | {"Content-Type": "application/json"})
    assert r.status_code == 413


async def test_un_contenido_grande_pero_dentro_del_limite_se_guarda(http, h):
    p = await _plantilla(http, h)
    grande = _grande(400 * 1024)
    cuerpo = json.dumps(grande)
    assert 300 * 1024 < len(cuerpo) < 512 * 1024
    r = await http.put(_ruta(p), content=cuerpo, headers=h | {"Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    leido = await http.get(_ruta(p), headers=h)
    assert len(leido.json()["contenido"]["bloques"]) == len(grande["bloques"])


async def test_si_la_forma_canonica_pasa_del_limite_tambien_es_413(http, h, datos):
    """Los valores por defecto que se completan engordan el contenido: el límite aplica a lo
    que se guarda, no solo a lo que se recibe."""
    import httpx
    from ayudantes_constancias import construir_app

    p = await _plantilla(http, h)
    compacto = {"esquema": 1, "bloques": [{"tipo": "logotipo"}] * 100}
    crudo = json.dumps(compacto, separators=(",", ":"))
    limite = 4000
    assert len(crudo) < limite < len(canonico(compacto)[0])  # cabe tal cual, no ya completado
    pequena = construir_app(
        http._transport.app.state.motor,
        almacen=http._transport.app.state.almacen,
        contenido_max_bytes=limite,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=pequena), base_url="http://t"
    ) as c:
        r = await c.put(_ruta(p), content=crudo, headers=h | {"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["detalle"] == {"limite": limite}
    assert sql(datos, "SELECT count(*) FROM constancias.borrador_plantilla") == [(0,)]


# ------------------------------------------------------------------ aislamiento y ciclo de vida


async def test_otra_empresa_no_lee_ni_escribe_el_borrador(http, h, hb, datos):
    p = await _plantilla(http, h)
    hash_ = (await _put(http, h, p)).json()["hash"]
    assert (await http.get(_ruta(p), headers=hb)).status_code == 404
    assert (await _put(http, hb, p, OTRO)).status_code == 404
    assert (await _put(http, hb, p, OTRO, if_match=f'"{hash_}"')).status_code == 404
    assert (await http.get(_ruta(p), headers=h)).json()["hash"] == hash_
    assert sql(datos, "SELECT count(*) FROM constancias.borrador_plantilla") == [(1,)]


async def test_una_plantilla_eliminada_no_tiene_borrador_accesible(http, h):
    p = await _plantilla(http, h)
    await _put(http, h, p)
    await http.delete(f"/api/v1/plantillas/{p['id']}", headers=h)
    assert (await http.get(_ruta(p), headers=h)).status_code == 404
    assert (await _put(http, h, p, OTRO)).status_code == 404


async def test_el_borrador_no_se_publica_ni_crea_versiones(http, h, datos):
    p = await _plantilla(http, h)
    await _put(http, h, p)
    assert sql(datos, "SELECT count(*) FROM constancias.version_plantilla") == [(0,)]
    r = await http.patch(f"/api/v1/plantillas/{p['id']}", json={"activa": True}, headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "PLANTILLA_SIN_VERSION"  # CC-REQ-064


async def test_el_borrador_convive_con_las_versiones_publicadas(http, h, datos, s3_plantillas):
    p = await _plantilla(http, h)
    publicar_version(datos, s3_plantillas[0], p["id"], 1)
    r = await _put(http, h, p, OTRO)
    assert r.status_code == 200
    detalle = (await http.get(f"/api/v1/plantillas/{p['id']}", headers=h)).json()
    assert (detalle["version"], detalle["tiene_borrador"]) == (1, True)


async def test_si_el_objeto_de_s3_no_coincide_con_el_hash_no_se_entrega(
    http, h, s3_plantillas, datos
):
    almacen, cliente, bucket = s3_plantillas
    p = await _plantilla(http, h)
    await _put(http, h, p)
    clave = f"plantillas/{datos['a']}/{p['id']}/borrador.json"
    cliente.put_object(Bucket=bucket, Key=clave, Body=b'{"esquema":1,"alterado":true}')
    r = await http.get(_ruta(p), headers=h)
    assert r.status_code == 500 and r.json()["codigo"] == "BORRADOR_INCONSISTENTE"
    cliente.delete_object(Bucket=bucket, Key=clave)
    assert (await http.get(_ruta(p), headers=h)).status_code == 500  # objeto perdido: igual
