"""T-208 (T-083): vista previa de una plantilla con los datos de un colaborador (CON-14)."""

from datetime import UTC, datetime

import pytest
from ayudantes_constancias import cab, crear_colaborador, emitir, sql
from cc_common.permisos import ROL_PERMISOS, Permiso
from cc_constancias.clientes import DefinicionCampo

pytestmark = pytest.mark.docker

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
FOLIO_MUESTRA = f"CG-{datetime.now(UTC).year}-0000"  # el año en México puede diferir solo el 31/12


def _defs():
    return [
        DefinicionCampo(1, "Área", "area", "CAMP-0001", "LISTA", orden=1),
        DefinicionCampo(2, "NSS", "nss", "CAMP-0002", "TEXTO", es_sensible=True, orden=2),
        DefinicionCampo(3, "Sueldo", "sueldo", "CAMP-0003", "NUMERO", es_sensible=True, orden=3),
        DefinicionCampo(4, "Periodicidad", "periodicidad_sueldo", "CAMP-0004", "LISTA", orden=4),
    ]


def doc(*nodos, logotipo=False):
    bloques = [{"tipo": "logotipo"}] if logotipo else []
    return {"esquema": 1, "bloques": [*bloques, {"tipo": "parrafo", "contenido": list(nodos)}]}


def v(*nombres):
    return [{"var": n} for n in nombres]


@pytest.fixture
def mundo(datos, campos, colaboradores):
    campos.por_empresa[datos["a"]] = _defs()
    colaborador = crear_colaborador(datos)
    colaboradores.valores[colaborador] = {
        "nombre_completo": "María Ramírez Ortiz",
        "puesto": "Operadora",
        "fecha_ingreso": "2021-03-15",
        "area": "Producción",
        "nss": "12345678901",
        "sueldo": "9500",
        "periodicidad_sueldo": "QUINCENAL",
    }
    colaboradores.resumenes[colaborador] = {"organizacion": {"id": 3}}
    colaboradores.organizaciones[3] = {"id": 3, "logotipo_s3_key": "logotipos/1/3/logo.png"}
    return {"colaborador": colaborador}


async def _plantilla(http, h, contenido, publicar=False):
    p = (await http.post("/api/v1/plantillas", json={"nombre": "Constancia"}, headers=h)).json()
    r = await http.put(f"/api/v1/plantillas/{p['id']}/borrador", json=contenido, headers=h)
    assert r.status_code == 200, r.text
    if publicar:
        r = await http.post(
            f"/api/v1/plantillas/{p['id']}/publicar", json={"confirmar_sensibles": True}, headers=h
        )
        assert r.status_code == 201, r.text
    return p


async def _previa(http, h, p, colaborador, **cuerpo):
    cuerpo = {"colaborador_id": colaborador} | (cuerpo or {"usar_borrador": True})
    return await http.post(f"/api/v1/plantillas/{p['id']}/vista-previa", json=cuerpo, headers=h)


async def test_la_vista_previa_rellena_la_plantilla_con_folio_de_muestra(http, h, mundo):
    p = await _plantilla(http, h, doc({"texto": "Constancia de "}, *v("nombre_completo", "area")))
    r = await _previa(http, h, p, mundo["colaborador"])
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["faltantes"] == [] and cuerpo["desconocidas"] == []
    html = cuerpo["html"]
    assert "María Ramírez Ortiz" in html and "Producción" in html
    assert f"Folio {FOLIO_MUESTRA}" in html and "@page" in html and "size: Letter" in html
    assert "VISTA-PREVIA-SIN-VALIDEZ" in html  # el QR de muestra no apunta a una constancia real
    assert "Content-Security-Policy" in html  # para el iframe con sandbox


async def test_las_variables_sin_valor_y_las_desconocidas_se_reportan(
    http, h, mundo, colaboradores
):
    p = await _plantilla(http, h, doc(*v("nombre_completo", "area", "fantasma", "puesto")))
    colaboradores.valores[mundo["colaborador"]].pop("area")
    r = await _previa(http, h, p, mundo["colaborador"])
    cuerpo = r.json()
    assert cuerpo["faltantes"] == ["area"] and cuerpo["desconocidas"] == ["fantasma"]
    assert '<span class="faltante">[area]</span>' in cuerpo["html"]
    assert '<span class="faltante">[fantasma]</span>' in cuerpo["html"]  # también se ve marcada


async def test_un_valor_con_html_sale_escapado_en_la_vista_previa(http, h, mundo, colaboradores):
    colaboradores.valores[mundo["colaborador"]]["puesto"] = "<script>alert(1)</script>"
    p = await _plantilla(http, h, doc(*v("puesto")))
    html = (await _previa(http, h, p, mundo["colaborador"])).json()["html"]
    assert "<script>alert" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html


# ------------------------------------------------------------------ fuente: versión o borrador


async def test_la_vista_previa_de_una_version_publicada_o_del_borrador(http, h, mundo):
    p = await _plantilla(http, h, doc({"texto": "Versión uno "}, *v("puesto")), publicar=True)
    nuevo = doc({"texto": "Borrador nuevo "}, *v("puesto"))
    borrador = (await http.get(f"/api/v1/plantillas/{p['id']}/borrador", headers=h)).json()["hash"]
    await http.put(
        f"/api/v1/plantillas/{p['id']}/borrador",
        json=nuevo,
        headers=h | {"If-Match": f'"{borrador}"'},
    )
    de_version = (await _previa(http, h, p, mundo["colaborador"], version=1)).json()["html"]
    de_borrador = (await _previa(http, h, p, mundo["colaborador"], usar_borrador=True)).json()[
        "html"
    ]
    assert "Versión uno" in de_version and "Borrador nuevo" not in de_version
    assert "Borrador nuevo" in de_borrador and "Versión uno" not in de_borrador


@pytest.mark.parametrize(
    "cuerpo",
    [{}, {"version": 1, "usar_borrador": True}, {"version": 0}, {"usar_borrador": False}],
)
async def test_hay_que_elegir_exactamente_una_fuente(http, h, mundo, cuerpo):
    p = await _plantilla(http, h, doc(*v("puesto")), publicar=True)
    r = await http.post(
        f"/api/v1/plantillas/{p['id']}/vista-previa",
        json={"colaborador_id": mundo["colaborador"]} | cuerpo,
        headers=h,
    )
    assert r.status_code == 422


async def test_404_si_no_hay_borrador_version_plantilla_o_colaborador(http, h, hb, mundo):
    p = (await http.post("/api/v1/plantillas", json={"nombre": "Vacía"}, headers=h)).json()
    r = await _previa(http, h, p, mundo["colaborador"])
    assert r.status_code == 404 and r.json()["codigo"] == "BORRADOR_NO_EXISTE"
    ok = await _plantilla(http, h, doc(*v("puesto")), publicar=True)
    assert (await _previa(http, h, ok, mundo["colaborador"], version=9)).status_code == 404
    assert (await _previa(http, h, ok, 987654)).status_code == 404  # colaborador inexistente
    assert (await _previa(http, hb, ok, mundo["colaborador"])).status_code == 404  # otra empresa
    assert (await _previa(http, h, {"id": 999999}, mundo["colaborador"])).status_code == 404
    await http.delete(f"/api/v1/plantillas/{ok['id']}", headers=h)
    assert (await _previa(http, h, ok, mundo["colaborador"])).status_code == 404


# ------------------------------------------------------------------ datos sensibles


async def test_con_datos_sensibles_registra_consulta_sensible_sin_valores(http, h, datos, mundo):
    p = await _plantilla(http, h, doc(*v("nombre_completo", "nss", "sueldo_letra")))
    r = await _previa(http, h, p, mundo["colaborador"])
    assert r.status_code == 200
    html = r.json()["html"]
    assert "12345678901" in html and "DIECINUEVE MIL PESOS 00/100 MN" in html
    bit = sql(
        datos,
        "SELECT usuario_id, colaborador_id, entidad, entidad_id, origen, detalle "
        "FROM auditoria.bitacora WHERE accion = 'CONSULTA_SENSIBLE'",
    )
    assert bit == [
        (
            datos["ua"],
            mundo["colaborador"],
            "colaborador",
            mundo["colaborador"],
            "USUARIO",
            {"codigos_internos": ["CAMP-0002", "CAMP-0003"], "plantilla_id": p["id"]},
        )
    ]
    assert "12345678901" not in str(sql(datos, "SELECT detalle FROM auditoria.bitacora"))


async def test_sin_datos_sensibles_no_registra_consulta_sensible(http, h, datos, mundo):
    p = await _plantilla(http, h, doc(*v("nombre_completo", "area")))
    assert (await _previa(http, h, p, mundo["colaborador"])).status_code == 200
    assert sql(
        datos, "SELECT count(*) FROM auditoria.bitacora WHERE accion = 'CONSULTA_SENSIBLE'"
    ) == [(0,)]


async def test_quien_no_puede_ver_sensibles_no_obtiene_la_vista_previa_con_ellos(
    http, datos, mundo, monkeypatch
):
    monkeypatch.setitem(ROL_PERMISOS, "EDITOR", frozenset({Permiso.PLANTILLAS_EDITAR}))
    editor = cab(emitir("sub-a", datos["a"], datos["ua"], rol="EDITOR"))
    rh = cab(emitir("sub-a", datos["a"], datos["ua"]))
    con = await _plantilla(http, rh, doc(*v("nss")))
    sin = (
        await http.post("/api/v1/plantillas", json={"nombre": "Sin sensibles"}, headers=rh)
    ).json()
    await http.put(f"/api/v1/plantillas/{sin['id']}/borrador", json=doc(*v("puesto")), headers=rh)
    r = await _previa(http, editor, con, mundo["colaborador"])
    assert r.status_code == 403 and "12345678901" not in r.text
    assert (await _previa(http, editor, sin, mundo["colaborador"])).status_code == 200
    assert sql(
        datos, "SELECT count(*) FROM auditoria.bitacora WHERE accion = 'CONSULTA_SENSIBLE'"
    ) == [(0,)]


# ------------------------------------------------------------------ logotipo


async def test_el_logotipo_de_la_organizacion_se_incrusta_desde_s3(http, h, mundo, s3_plantillas):
    almacen, cliente, bucket = s3_plantillas
    cliente.put_object(Bucket=bucket, Key="logotipos/1/3/logo.png", Body=PNG)
    p = await _plantilla(http, h, doc(*v("puesto"), logotipo=True))
    html = (await _previa(http, h, p, mundo["colaborador"])).json()["html"]
    assert "data:image/png;base64," in html and "[Logotipo de la organización]" not in html


async def test_sin_logotipo_en_s3_o_sin_organizacion_con_logo_hay_marcador(
    http, h, mundo, colaboradores
):
    p = await _plantilla(http, h, doc(*v("puesto"), logotipo=True))
    html = (await _previa(http, h, p, mundo["colaborador"])).json()["html"]  # objeto ausente
    assert "[Logotipo de la organización]" in html and "data:image/png" not in html
    colaboradores.organizaciones[3] = {"id": 3, "logotipo_s3_key": None}
    html = (await _previa(http, h, p, mundo["colaborador"])).json()["html"]
    assert "[Logotipo de la organización]" in html


async def test_sin_bloque_de_logotipo_no_se_consulta_la_organizacion(http, h, mundo, colaboradores):
    async def no_debe_llamarse(*_a, **_k):
        raise AssertionError("no hacía falta consultar la organización")

    colaboradores.resumen = no_debe_llamarse
    colaboradores.organizacion = no_debe_llamarse
    p = await _plantilla(http, h, doc(*v("puesto")))
    assert (await _previa(http, h, p, mundo["colaborador"])).status_code == 200


async def test_si_la_organizacion_no_responde_la_vista_previa_con_logotipo_da_502(
    http, h, mundo, colaboradores
):
    from cc_common.errores import ErrorProveedor

    async def cae(*_a, **_k):
        raise ErrorProveedor()

    colaboradores.organizacion = cae
    p = await _plantilla(http, h, doc(*v("puesto"), logotipo=True))
    assert (await _previa(http, h, p, mundo["colaborador"])).status_code == 502


async def test_requiere_sesion(http, mundo):
    r = await http.post(
        "/api/v1/plantillas/1/vista-previa", json={"colaborador_id": 1, "usar_borrador": True}
    )
    assert r.status_code == 401
