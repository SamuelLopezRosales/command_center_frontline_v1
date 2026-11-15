"""T-209 (T-086 a T-088): enlace de un solo uso, verificación pública, descarga y reenvío."""

import base64
import hashlib
import re
import time
from urllib.parse import parse_qs, urlparse

import pytest
from ayudantes_constancias import emitir_constancia, sql
from ayudantes_emision import plantilla_activa, salidas
from cc_constancias.entrega.estrategia import Entrega, estrategia_por_modo
from cc_constancias.servicios.entrega import nuevo_token
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

pytestmark = pytest.mark.docker


@pytest.fixture
def emitida(datos, s3_plantillas):
    pid = plantilla_activa(datos, s3_plantillas[0])
    return emitir_constancia(datos, pid)


def token_nuevo(datos, cid, expira="now() + interval '1 hour'") -> str:
    token, h = nuevo_token()
    sql(datos, "INSERT INTO constancias.token_descarga (empresa_id, constancia_id, token_hash, "
        f"fecha_expira, generado_por) VALUES (%s, %s, %s, {expira}, 'BOT')",
        (datos["a"], cid, h))  # fmt: skip
    return token


def comprobar_firma(url: str, llave, segundos: int, clave: str):
    """La firma verifica con la clave pública y la caducidad es la pedida."""
    u = urlparse(url)
    q = parse_qs(u.query)
    assert u.netloc == "cdn.prueba.test" and u.path == f"/{clave}" and q["Key-Pair-Id"] == ["KPAR1"]
    expira = int(q["Expires"][0])
    assert abs(expira - (time.time() + segundos)) < 30
    politica = (
        f'{{"Statement":[{{"Resource":"https://cdn.prueba.test/{clave}","Condition":'
        f'{{"DateLessThan":{{"AWS:EpochTime":{expira}}}}}}}]}}'
    )
    firma = base64.b64decode(q["Signature"][0].translate(str.maketrans("-_~", "+=/")))
    llave.public_key().verify(firma, politica.encode(), padding.PKCS1v15(), hashes.SHA1())  # noqa: S303


# ------------------------------------------------------------------ CON-20 y CON-21


async def test_la_pagina_no_consume_y_la_descarga_funciona_una_sola_vez(
    http_e, datos, emitida, llave_cloudfront
):
    token = token_nuevo(datos, emitida)
    for _ in range(2):  # una vista previa de enlace no lo gasta
        r = await http_e.get(f"/d/{token}")
        assert r.status_code == 200 and f'action="/d/{token}/descargar"' in r.text
        assert r.headers["cache-control"] == "no-store"
        assert "noindex" in r.headers["x-robots-tag"]
        assert r.headers["referrer-policy"] == "no-referrer"

    r = await http_e.post(f"/d/{token}/descargar")
    assert r.status_code == 302
    comprobar_firma(r.headers["location"], llave_cloudfront, 60, "constancias/x.pdf")
    usado = sql(datos, "SELECT usado_en FROM constancias.token_descarga WHERE token_hash = %s",
                (hashlib.sha256(token.encode()).digest(),))  # fmt: skip
    assert usado[0][0] is not None
    for r in (await http_e.post(f"/d/{token}/descargar"), await http_e.get(f"/d/{token}")):
        assert r.status_code == 410 and r.json()["codigo"] == "ENLACE_NO_VIGENTE"


async def test_token_vencido_inexistente_o_mal_formado(http_e, datos, emitida):
    vencido = token_nuevo(datos, emitida, expira="now() - interval '1 second'")
    assert (await http_e.get(f"/d/{vencido}")).status_code == 410
    assert (await http_e.post(f"/d/{vencido}/descargar")).status_code == 410
    desconocido, _ = nuevo_token()
    assert (await http_e.get(f"/d/{desconocido}")).status_code == 404
    assert (await http_e.post(f"/d/{desconocido}/descargar")).status_code == 404
    assert (await http_e.get("/d/corto")).status_code == 404


async def test_modo_adjunto_manda_el_pdf_sin_token():
    e = Entrega(1, 2, 3, 4, 5, "CG-2026-0001", "constancias/1/2026/CG-2026-0001.pdf")
    adjunto = estrategia_por_modo("adjunto")
    m = adjunto.mensaje(e, None, "d.test")
    assert not adjunto.requiere_token and m["tipo"] == "CONSTANCIA_ADJUNTO"
    assert m["pdf_s3_key"] == e.pdf_s3_key and "enlace" not in m
    enlace = estrategia_por_modo("enlace")
    assert enlace.requiere_token and enlace.mensaje(e, "T" * 43, "d.test")["enlace"].endswith(
        "/d/" + "T" * 43
    )
    with pytest.raises(ValueError, match="modo"):
        estrategia_por_modo("paloma")


# ------------------------------------------------------------------ CON-16 a CON-18


async def test_detalle_solo_de_la_propia_empresa(http_e, h, hb, emitida):
    r = await http_e.get(f"/api/v1/constancias/{emitida}", headers=h)
    assert r.status_code == 200 and r.json()["estado_entrega"] == "PENDIENTE"
    assert r.json()["plantilla_nombre"] == "Constancia" and r.json()["version"] == 1
    assert (await http_e.get(f"/api/v1/constancias/{emitida}", headers=hb)).status_code == 404


async def test_descarga_de_rh_exige_entrega_y_dura_24_horas(
    http_e, h, datos, emitida, llave_cloudfront
):
    r = await http_e.post(f"/api/v1/constancias/{emitida}/descarga", headers=h)
    assert r.status_code == 409 and r.json()["codigo"] == "CONSTANCIA_PENDIENTE"
    sql(datos, "UPDATE constancias.constancia_generada SET estado_entrega = 'ENTREGADA' "
        "WHERE id = %s", (emitida,))  # fmt: skip
    r = await http_e.post(f"/api/v1/constancias/{emitida}/descarga", headers=h)
    assert r.status_code == 200
    comprobar_firma(r.json()["url"], llave_cloudfront, 24 * 3600, "constancias/x.pdf")
    bit = sql(datos, "SELECT usuario_id FROM auditoria.bitacora "
              "WHERE accion = 'CONSTANCIA_DESCARGADA' AND entidad_id = %s", (emitida,))  # fmt: skip
    assert bit == [(datos["ua"],)]


async def test_reenvio_solo_con_entrega_fallida_y_token_nuevo(http_e, h, hb, datos, emitida):
    r = await http_e.post(f"/api/v1/constancias/{emitida}/reenviar", headers=h)
    assert r.status_code == 409  # PENDIENTE
    sql(datos, "UPDATE constancias.constancia_generada SET estado_entrega = 'FALLIDA' "
        "WHERE id = %s", (emitida,))  # fmt: skip
    assert (await http_e.post(f"/api/v1/constancias/{emitida}/reenviar",
                              headers=hb)).status_code == 404  # fmt: skip
    r = await http_e.post(f"/api/v1/constancias/{emitida}/reenviar", headers=h)
    assert r.status_code == 202
    assert sql(datos, "SELECT estado_entrega FROM constancias.constancia_generada WHERE id = %s",
               (emitida,)) == [("PENDIENTE",)]  # fmt: skip
    tokens = sql(datos, "SELECT generado_por, usuario_id FROM constancias.token_descarga "
                 "WHERE constancia_id = %s", (emitida,))  # fmt: skip
    assert tokens == [("RH_REENVIO", datos["ua"])]
    [msg] = salidas(datos, "CONSTANCIA_REENVIO")
    assert re.search(r"/d/[A-Za-z0-9_-]{43}$", msg["enlace"])
    bit = sql(datos, "SELECT usuario_id FROM auditoria.bitacora "
              "WHERE accion = 'CONSTANCIA_REENVIADA'")  # fmt: skip
    assert bit == [(datos["ua"],)]
    again = await http_e.post(f"/api/v1/constancias/{emitida}/reenviar", headers=h)
    assert again.status_code == 409  # ya volvió a PENDIENTE


# ------------------------------------------------------------------ CON-19


async def test_verificacion_publica_sin_datos_sensibles_y_404_uniforme(http_e, datos, emitida):
    codigo = sql(datos, "SELECT codigo_verificacion FROM constancias.constancia_generada "
                 "WHERE id = %s", (emitida,))[0][0]  # fmt: skip
    r = await http_e.get(f"/api/v1/publico/verificar/{codigo}")
    assert r.status_code == 200
    assert set(r.json()) == {"nombre", "folio", "fecha_emision", "estado"}
    assert r.json()["estado"] == "VIGENTE" and r.json()["folio"] == "CG-2026-0001"
    assert r.headers["cache-control"] == "no-store" and "noindex" in r.headers["x-robots-tag"]
    sql(datos, "UPDATE constancias.constancia_generada SET estado_vigencia = 'CANCELADA', "
        "fecha_cancelacion = now(), motivo_cancelacion = 'x' WHERE id = %s", (emitida,))  # fmt: skip
    assert (await http_e.get(f"/api/v1/publico/verificar/{codigo}")).json()["estado"] == "CANCELADA"

    inexistente = await http_e.get("/api/v1/publico/verificar/" + "A" * 22)
    malformado = await http_e.get("/api/v1/publico/verificar/a b")
    assert inexistente.status_code == malformado.status_code == 404
    assert inexistente.json()["codigo"] == malformado.json()["codigo"]
    assert inexistente.headers["cache-control"] == "no-store"
