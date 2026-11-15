"""T-210 (T-091): cargas hostiles en el renderizado y secretos fuera de los logs.

Corre en el host (no necesita Pango). La parte que genera PDF de verdad (SSRF y archivos locales)
está en ``test_pdf_rendimiento.py`` y corre en el contenedor.
"""

import logging

import pytest
from cc_constancias import contenido as c
from cc_constancias.render import html as r
from referencia import COLABORADOR, REFERENCIAS

HOSTILES = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    '<img src="file:///etc/passwd">',
    '<link rel="stylesheet" href="http://169.254.169.254/latest/meta-data/">',
    "{{nombre_completo}} {% raw %}{{ 7*7 }}{% endraw %} ${7*7}",
    "</p><iframe src='http://evil.test'></iframe>",
]


@pytest.mark.parametrize("hostil", HOSTILES)
def test_los_valores_hostiles_se_escapan_en_el_html(hostil):
    contenido = c.leer(REFERENCIAS["laboral"])
    valores = {v: COLABORADOR.get(v, "x") for v in c.variables_usadas(contenido)}
    valores["nombre_completo"] = hostil
    html = r.renderizar(contenido, r.DatosRender(valores, "CG-2026-0001", "A" * 22, "cc.test"))
    minusculas = html.lower()
    for peligro in ("<script", "<iframe", "<link", 'src="file:', "<img src=x"):
        assert peligro not in minusculas, peligro
    assert "&lt;" in html or "{{ 7*7 }}" in html  # el texto aparece como texto, no como marcado


def test_un_texto_fijo_con_marcado_se_rechaza_al_guardar_la_plantilla():
    from cc_common.errores import ErrorValidacion

    with pytest.raises(ErrorValidacion):
        c.leer({"esquema": 1, "bloques": [
            {"tipo": "parrafo", "contenido": [{"texto": "<script>alert(1)</script>"}]}]})  # fmt: skip


def test_el_servidor_no_registra_las_rutas_con_token():
    """uvicorn imprimiría ``/d/{token}`` en su registro de accesos: se desactiva."""
    from pathlib import Path

    dockerfile = Path(__file__).parents[1] / "Dockerfile"
    assert "--no-access-log" in dockerfile.read_text(encoding="utf-8")


@pytest.mark.docker
async def test_vista_previa_escapa_los_valores_hostiles(http, h, datos, campos, colaboradores):
    from ayudantes_constancias import crear_colaborador

    colaborador = crear_colaborador(datos)
    colaboradores.valores[colaborador] = {"nombre_completo": "<script>alert(1)</script>"}
    colaboradores.resumenes[colaborador] = {"organizacion": {"id": 0}}
    cuerpo = {"esquema": 1, "bloques": [
        {"tipo": "parrafo", "contenido": [{"var": "nombre_completo"}]}]}  # fmt: skip
    p = (await http.post("/api/v1/plantillas", json={"nombre": "Hostil"}, headers=h)).json()
    assert (
        await http.put(f"/api/v1/plantillas/{p['id']}/borrador", json=cuerpo, headers=h)
    ).status_code == 200
    r_ = await http.post(
        f"/api/v1/plantillas/{p['id']}/vista-previa",
        json={"colaborador_id": colaborador, "usar_borrador": True},
        headers=h,
    )
    assert r_.status_code == 200
    assert "<script>alert" not in r_.json()["html"] and "&lt;script&gt;" in r_.json()["html"]


@pytest.mark.docker
async def test_tokens_y_codigos_no_aparecen_en_los_logs(http_e, datos, s3_plantillas, caplog):
    from ayudantes_constancias import emitir_constancia, sql
    from ayudantes_emision import plantilla_activa
    from cc_constancias.servicios.entrega import nuevo_token

    cid = emitir_constancia(datos, plantilla_activa(datos, s3_plantillas[0]))
    token, huella = nuevo_token()
    sql(datos, "INSERT INTO constancias.token_descarga (empresa_id, constancia_id, token_hash, "
        "fecha_expira, generado_por) VALUES (%s, %s, %s, now() + interval '1 hour', 'BOT')",
        (datos["a"], cid, huella))  # fmt: skip
    codigo = sql(datos, "SELECT codigo_verificacion FROM constancias.constancia_generada "
                 "WHERE id = %s", (cid,))[0][0]  # fmt: skip
    caplog.set_level(logging.DEBUG)
    await http_e.get(f"/d/{token}")
    await http_e.post(f"/d/{token}/descargar")
    await http_e.post(f"/d/{token}/descargar")  # 410
    await http_e.get(f"/api/v1/publico/verificar/{codigo}")
    await http_e.get("/api/v1/publico/verificar/" + "B" * 22)
    propios = [
        r.getMessage() for r in caplog.records if not r.name.startswith("http")
    ]  # sin el cliente
    assert not any(token in m or codigo in m for m in propios)
