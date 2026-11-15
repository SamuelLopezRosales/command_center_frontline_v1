"""T-201: organizaciones, logotipo y plantas (COL-08 a COL-15) con PostgreSQL y LocalStack."""

import uuid

import httpx
import psycopg
import pytest
from ayudantes_colaboradores import cab, construir_app, emitir
from cc_colaboradores.almacenamiento import AlmacenS3

pytestmark = pytest.mark.docker

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 100


def _h(datos, empresa="a", usuario="ua", sub="sub-a"):
    return cab(emitir(sub, datos[empresa], datos[usuario] if usuario else None))


def _bitacora(datos, entidad):
    with psycopg.connect(datos["bd"].url_admin) as c:
        return c.execute(
            "SELECT accion, entidad_id, usuario_id, detalle FROM auditoria.bitacora "
            "WHERE entidad = %s ORDER BY id",
            (entidad,),
        ).fetchall()


ORG = {
    "clave": " org-1 ",
    "razon_social": "Acme SA de CV",
    "rfc": "acm010101ab1",
    "registro_patronal": "a1234567890",
    "nombre_firmante": "Laura Gómez",
    "correo_firmante": "Laura@Acme.com",
}


# ---------------------------------------------------------------- organizaciones


async def test_crear_listar_y_normalizar(cliente, datos):
    r = await cliente.post("/api/v1/organizaciones", json=ORG, headers=_h(datos))
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["clave"] == "ORG-1" and o["rfc"] == "ACM010101AB1"
    assert o["registro_patronal"] == "A1234567890" and o["correo_firmante"] == "laura@acme.com"
    assert o["activa"] is True and o["tiene_logotipo"] is False
    r = await cliente.get("/api/v1/organizaciones", headers=_h(datos))
    assert [x["clave"] for x in r.json()["items"]] == ["ORG-1"]
    assert _bitacora(datos, "organizacion") == [("CATALOGO_MODIFICADO", o["id"], datos["ua"], {})]


async def test_clave_unica_por_empresa(cliente, datos):
    assert (
        await cliente.post("/api/v1/organizaciones", json=ORG, headers=_h(datos))
    ).status_code == 201
    r = await cliente.post(
        "/api/v1/organizaciones", json={**ORG, "clave": "org-1"}, headers=_h(datos)
    )
    assert r.status_code == 409 and r.json()["codigo"] == "ORGANIZACION_DUPLICADA"
    assert "organizacion_empresa_id_clave_key" not in r.text
    # Otra empresa puede usar la misma clave.
    r = await cliente.post(
        "/api/v1/organizaciones", json=ORG, headers=_h(datos, "b", "ub", "sub-b")
    )
    assert r.status_code == 201


@pytest.mark.parametrize("rfc", ["AB010101AB", "ABCDE010101AB12", "1BC010101AB1"])
async def test_rfc_de_12_o_13_caracteres(cliente, datos, rfc):
    r = await cliente.post("/api/v1/organizaciones", json={**ORG, "rfc": rfc}, headers=_h(datos))
    assert r.status_code == 422 and rfc not in r.text
    assert r.json()["errores"][0]["campo"] == "rfc"


async def test_rfc_de_persona_moral_y_fisica(cliente, datos):
    for i, rfc in enumerate(("ACM010101AB1", "GOLA800101AB1")):
        r = await cliente.post(
            "/api/v1/organizaciones", json={**ORG, "clave": f"O{i}", "rfc": rfc}, headers=_h(datos)
        )
        assert r.status_code == 201


async def test_clave_inmutable_y_desactivar_en_lugar_de_borrar(cliente, datos):
    o = (await cliente.post("/api/v1/organizaciones", json=ORG, headers=_h(datos))).json()
    url = f"/api/v1/organizaciones/{o['id']}"
    r = await cliente.patch(url, json={"clave": "OTRA"}, headers=_h(datos))
    assert r.status_code == 422 and r.json()["errores"][0]["codigo"] == "CAMPO_NO_PERMITIDO"
    r = await cliente.patch(url, json={"activa": False, "ciudad": "Monterrey"}, headers=_h(datos))
    assert r.status_code == 200 and r.json()["activa"] is False and r.json()["clave"] == "ORG-1"
    assert (await cliente.delete(url, headers=_h(datos))).status_code == 405
    ultimo = _bitacora(datos, "organizacion")[-1]
    assert ultimo[3] == {"campos": ["activa", "ciudad"]}  # nombres de campos, sin valores
    r = await cliente.patch(url, json={"razon_social": None}, headers=_h(datos))
    assert r.status_code == 422
    activas = await cliente.get("/api/v1/organizaciones?solo_activas=true", headers=_h(datos))
    assert activas.json()["items"] == []


async def test_sin_cambios_no_registra(cliente, datos):
    o = (await cliente.post("/api/v1/organizaciones", json=ORG, headers=_h(datos))).json()
    r = await cliente.patch(
        f"/api/v1/organizaciones/{o['id']}",
        json={"razon_social": "Acme SA de CV"},
        headers=_h(datos),
    )
    assert r.status_code == 200 and len(_bitacora(datos, "organizacion")) == 1


async def test_otra_empresa_recibe_404(cliente, datos):
    o = (await cliente.post("/api/v1/organizaciones", json=ORG, headers=_h(datos))).json()
    r = await cliente.patch(
        f"/api/v1/organizaciones/{o['id']}",
        json={"ciudad": "X"},
        headers=_h(datos, "b", "ub", "sub-b"),
    )
    assert r.status_code == 404
    r = await cliente.get("/api/v1/organizaciones", headers=_h(datos, "b", "ub", "sub-b"))
    assert r.json()["items"] == []


async def test_escribir_exige_el_claim_usuario_id(cliente, datos):
    r = await cliente.post("/api/v1/organizaciones", json=ORG, headers=_h(datos, usuario=None))
    assert r.status_code == 401
    assert (
        await cliente.get("/api/v1/organizaciones", headers=_h(datos, usuario=None))
    ).status_code == 200


async def test_sin_token_401(cliente):
    assert (await cliente.get("/api/v1/organizaciones")).status_code == 401


# ---------------------------------------------------------------- plantas


async def test_plantas_nombre_unico_sin_mayusculas_y_solo_desactivar(cliente, datos):
    r = await cliente.post("/api/v1/plantas", json={"nombre": "Planta Norte"}, headers=_h(datos))
    assert r.status_code == 201
    p = r.json()
    r = await cliente.post("/api/v1/plantas", json={"nombre": "  planta NORTE "}, headers=_h(datos))
    assert r.status_code == 409 and r.json()["codigo"] == "PLANTA_DUPLICADA"
    r = await cliente.patch(f"/api/v1/plantas/{p['id']}", json={"activa": False}, headers=_h(datos))
    assert r.status_code == 200 and r.json()["activa"] is False
    assert (
        await cliente.delete(f"/api/v1/plantas/{p['id']}", headers=_h(datos))
    ).status_code == 405
    r = await cliente.get("/api/v1/plantas?solo_activas=true", headers=_h(datos))
    assert r.json()["items"] == []
    acciones = [f[0] for f in _bitacora(datos, "planta")]
    assert acciones == ["CATALOGO_MODIFICADO", "CATALOGO_MODIFICADO"]


async def test_renombrar_planta_a_un_nombre_existente(cliente, datos):
    a = (await cliente.post("/api/v1/plantas", json={"nombre": "Norte"}, headers=_h(datos))).json()
    await cliente.post("/api/v1/plantas", json={"nombre": "Sur"}, headers=_h(datos))
    r = await cliente.patch(f"/api/v1/plantas/{a['id']}", json={"nombre": "SUR"}, headers=_h(datos))
    assert r.status_code == 409 and r.json()["codigo"] == "PLANTA_DUPLICADA"


# ---------------------------------------------------------------- logotipo (LocalStack)


@pytest.fixture
def s3(localstack):
    import boto3
    from botocore.config import Config

    cliente = boto3.client(
        "s3",
        endpoint_url=localstack,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    bucket = f"cc-prueba-{uuid.uuid4().hex[:10]}"
    cliente.create_bucket(Bucket=bucket)
    return bucket, cliente


@pytest.fixture
async def cliente_s3(motor, cifrador, s3):
    bucket, c = s3
    app = construir_app(motor, cifrador, almacen=AlmacenS3(bucket, c))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as h:
        yield h, c, bucket


async def _org(cliente, datos):
    return (await cliente.post("/api/v1/organizaciones", json=ORG, headers=_h(datos))).json()


async def _subir(cliente, datos, org_id, contenido, content_type="image/png", declarado=None):
    r = await cliente.post(
        f"/api/v1/organizaciones/{org_id}/logotipo",
        json={"content_type": content_type, "tamano": declarado or len(contenido)},
        headers=_h(datos),
    )
    assert r.status_code == 200, r.text
    u = r.json()
    async with httpx.AsyncClient(timeout=60) as externo:
        put = await externo.put(u["url"], content=contenido, headers={"Content-Type": content_type})
    assert put.status_code == 200, put.text
    return u["s3_key"]


async def test_logotipo_png_y_jpg_se_asignan(cliente_s3, datos):
    cliente, _, _ = cliente_s3
    o = await _org(cliente, datos)
    for contenido, tipo in ((PNG, "image/png"), (JPG, "image/jpeg")):
        clave = await _subir(cliente, datos, o["id"], contenido, tipo)
        assert clave.startswith(f"logotipos/{datos['a']}/{o['id']}/")
        r = await cliente.post(
            f"/api/v1/organizaciones/{o['id']}/logotipo/confirmar",
            json={"s3_key": clave},
            headers=_h(datos),
        )
        assert r.status_code == 200 and r.json()["tiene_logotipo"] is True
    with psycopg.connect(datos["bd"].url_admin) as c:
        guardada = c.execute(
            "SELECT logotipo_s3_key FROM colaboradores.organizacion WHERE id = %s", (o["id"],)
        ).fetchone()[0]
    assert guardada == clave and guardada.endswith(".jpg")


async def test_logotipo_con_tipo_real_distinto_se_rechaza(cliente_s3, datos):
    cliente, _, _ = cliente_s3
    o = await _org(cliente, datos)
    clave = await _subir(cliente, datos, o["id"], b"<svg>no es png</svg>", "image/png")
    r = await cliente.post(
        f"/api/v1/organizaciones/{o['id']}/logotipo/confirmar",
        json={"s3_key": clave},
        headers=_h(datos),
    )
    assert r.status_code == 422 and r.json()["codigo"] == "LOGOTIPO_TIPO_INVALIDO"


async def test_logotipo_mayor_a_1_mb_se_rechaza(cliente_s3, datos):
    cliente, _, _ = cliente_s3
    o = await _org(cliente, datos)
    r = await cliente.post(
        f"/api/v1/organizaciones/{o['id']}/logotipo",
        json={"content_type": "image/png", "tamano": 1_048_577},
        headers=_h(datos),
    )
    assert r.status_code == 422 and r.json()["codigo"] == "LOGOTIPO_DEMASIADO_GRANDE"
    # Declara poco y sube más: la confirmación mide el objeto real.
    grande = PNG + b"\x00" * 1_048_576
    clave = await _subir(cliente, datos, o["id"], grande, declarado=100)
    r = await cliente.post(
        f"/api/v1/organizaciones/{o['id']}/logotipo/confirmar",
        json={"s3_key": clave},
        headers=_h(datos),
    )
    assert r.status_code == 422 and r.json()["codigo"] == "LOGOTIPO_DEMASIADO_GRANDE"


async def test_logotipo_tipo_declarado_no_permitido(cliente_s3, datos):
    cliente, _, _ = cliente_s3
    o = await _org(cliente, datos)
    r = await cliente.post(
        f"/api/v1/organizaciones/{o['id']}/logotipo",
        json={"content_type": "image/gif", "tamano": 10},
        headers=_h(datos),
    )
    assert r.status_code == 422 and r.json()["codigo"] == "LOGOTIPO_TIPO_INVALIDO"


async def test_logotipo_clave_fuera_de_su_prefijo_o_inexistente(cliente_s3, datos):
    cliente, _, _ = cliente_s3
    o = await _org(cliente, datos)
    url = f"/api/v1/organizaciones/{o['id']}/logotipo/confirmar"
    for clave in (
        f"logotipos/{datos['b']}/{o['id']}/x.png",
        f"logotipos/{datos['a']}/999/x.png",
        f"logotipos/{datos['a']}/{o['id']}/../../otra.png",
        "plantillas/1/borrador.json",
    ):
        r = await cliente.post(url, json={"s3_key": clave}, headers=_h(datos))
        assert r.status_code == 422 and r.json()["codigo"] == "LOGOTIPO_CLAVE_INVALIDA", clave
    r = await cliente.post(
        url, json={"s3_key": f"logotipos/{datos['a']}/{o['id']}/nada.png"}, headers=_h(datos)
    )
    assert r.status_code == 422 and r.json()["codigo"] == "LOGOTIPO_NO_ENCONTRADO"


async def test_logotipo_de_organizacion_de_otra_empresa_404(cliente_s3, datos):
    cliente, _, _ = cliente_s3
    o = await _org(cliente, datos)
    r = await cliente.post(
        f"/api/v1/organizaciones/{o['id']}/logotipo",
        json={"content_type": "image/png", "tamano": 10},
        headers=_h(datos, "b", "ub", "sub-b"),
    )
    assert r.status_code == 404
