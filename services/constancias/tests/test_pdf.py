"""T-208 (T-083): PDF con WeasyPrint de las tres plantillas de referencia.

Necesita Pango, que no está en Windows: se omite donde WeasyPrint no carga y corre en el
contenedor con ``scripts/probar_pdf.ps1`` (``pytest -m pdf``). No necesita base de datos.
"""

import io
import time
from datetime import UTC, datetime

import pytest
from ayudantes_resolucion import definiciones_referencia
from cc_constancias import contenido as c
from cc_constancias.clientes import StubColaboradores
from cc_constancias.render import html as r
from cc_constancias.render.pdf import crear_fetcher, disponible, html_a_pdf
from cc_constancias.render.resolutor_variables import resolver
from referencia import COLABORADOR, REFERENCIAS

pytestmark = [
    pytest.mark.pdf,
    pytest.mark.skipif(not disponible(), reason="WeasyPrint no carga: use scripts/probar_pdf.ps1"),
]

AHORA = datetime(2026, 11, 15, 3, 0, tzinfo=UTC)  # en México todavía es el 14 de noviembre
FOLIO = "CG-2026-0001"
CODIGO = "ABCDEFGHIJKLMNOPQRSTUV"
DOMINIO = "cc.ejemplo.com"


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (31, 58, 95)).save(buf, "PNG")
    return buf.getvalue()


async def _html(nombre: str, *, logotipo=None, ahora=AHORA, valores=None):
    contenido = c.leer(REFERENCIAS[nombre])
    res = await resolver(
        StubColaboradores({1: valores or COLABORADOR}),
        empresa_id=1,
        colaborador_id=1,
        variables=c.variables_usadas(contenido),
        definiciones=definiciones_referencia(),
        sistema={"folio": FOLIO},
        ahora=ahora,
    )
    assert res.faltantes == [] and res.desconocidas == [], (res.faltantes, res.desconocidas)
    return r.renderizar(
        contenido,
        r.DatosRender(res.valores, FOLIO, CODIGO, DOMINIO, logotipo_data_uri=logotipo),
    ), res


def _leer(pdf: bytes):
    from pypdf import PdfReader

    return PdfReader(io.BytesIO(pdf))


def _texto(pdf: bytes) -> str:
    return " ".join(" ".join(p.extract_text().split()) for p in _leer(pdf).pages)


@pytest.mark.parametrize("nombre", ["laboral", "guarderia", "consulado"])
async def test_las_tres_plantillas_de_referencia_generan_un_pdf_carta_que_se_abre(nombre):
    html, res = await _html(nombre)
    pdf = html_a_pdf(html)
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    lector = _leer(pdf)
    assert len(lector.pages) == 1
    ancho, alto = (float(x) for x in lector.pages[0].mediabox[2:])
    assert (round(ancho), round(alto)) == (612, 792)  # Carta en puntos
    texto = _texto(pdf)
    assert "{{" not in texto and "}}" not in texto  # no quedó ninguna variable sin sustituir
    assert "María Fernanda Ramírez Ortiz" in texto and "Empresa Ejemplo, S.A. de C.V." in texto
    assert "A0000000000" in texto and "Lic. Nombre Apellido" in texto
    assert "c.c.p. Expediente del Colaborador." in texto
    # el pie: folio, URL de verificación y paginación
    assert f"Folio {FOLIO}" in texto and f"https://{DOMINIO}/v/{CODIGO}" in texto
    assert "Página 1 de 1" in texto
    assert res.factores_version == "1"


async def test_la_laboral_trae_los_datos_sensibles_y_las_derivadas_calculadas():
    html, _ = await _html("laboral")
    texto = _texto(html_a_pdf(html))
    assert "12345678901" in texto and "RAOM900101AB1" in texto
    assert "$19,000.00 (DIECINUEVE MIL PESOS 00/100 MN)" in texto  # 9,500 quincenal × 2
    assert "15 de marzo de 2021" in texto  # fecha de ingreso en texto largo
    assert "Monterrey, 14 de noviembre de 2026." in texto  # fecha de emisión en México, no UTC


async def test_la_guarderia_usa_el_horario_y_la_consulado_la_curp():
    texto_g = _texto(html_a_pdf((await _html("guarderia"))[0]))
    assert "9:00 am a 07:00 pm de lunes a viernes" in texto_g
    texto_c = _texto(html_a_pdf((await _html("consulado"))[0]))
    assert (
        "RAOM900101MNLMRR05" in texto_c and "$19,000.00 (DIECINUEVE MIL PESOS 00/100 MN)" in texto_c
    )


async def test_el_pdf_incluye_el_logotipo_embebido():
    import base64

    uri = "data:image/png;base64," + base64.b64encode(_png()).decode()
    html, _ = await _html("laboral", logotipo=uri)
    con = _leer(html_a_pdf(html)).pages[0]
    sin = _leer(html_a_pdf((await _html("laboral"))[0])).pages[0]
    assert len(list(con.images)) == len(list(sin.images)) + 1


async def test_un_valor_con_html_no_inyecta_nada_en_el_pdf():
    valores = COLABORADOR | {"puesto": "<b>Jefe</b><script>alert(1)</script>"}
    html, _ = await _html("laboral", valores=valores)
    assert "<script>alert" not in html
    assert "<b>Jefe</b><script>alert(1)</script>" in _texto(html_a_pdf(html))  # texto literal


def test_el_fetcher_solo_admite_data_y_rechaza_http_https_file_y_ftp():
    f = crear_fetcher()
    for url in (
        "http://ejemplo.com/logo.png",
        "https://ejemplo.com/hoja.css",
        "file:///etc/passwd",
        "file:///C:/Windows/win.ini",
        "ftp://ejemplo.com/x",
        "gopher://ejemplo.com/",
    ):
        with pytest.raises(ValueError, match="disallowed protocol"):
            f.fetch(url)
    resp = f.fetch("data:text/plain;base64,aG9sYQ==")
    assert resp.read() == b"hola"


def test_un_html_con_recursos_externos_no_los_descarga_ni_los_incluye():
    peligroso = (
        "<html><head><link rel='stylesheet' href='http://127.0.0.1:9/hoja.css'>"
        "<style>@import url('file:///etc/passwd'); p { background: url(http://127.0.0.1:9/f.png) }"
        "</style></head><body><p>texto</p>"
        "<img src='file:///etc/hostname'><img src='http://127.0.0.1:9/x.png'></body></html>"
    )
    inicio = time.perf_counter()
    pdf = html_a_pdf(peligroso)
    assert time.perf_counter() - inicio < 5  # no esperó ninguna conexión
    pagina = _leer(pdf).pages[0]
    assert "texto" in pagina.extract_text() and list(pagina.images) == []


async def test_un_documento_largo_pagina_y_numera_el_pie():
    largo = c.leer(
        {
            "esquema": 1,
            "bloques": [{"tipo": "parrafo", "contenido": [{"texto": "Línea de relleno. " * 40}]}]
            * 40,
        }
    )
    html = r.renderizar(largo, r.DatosRender({}, FOLIO, CODIGO, DOMINIO))
    lector = _leer(html_a_pdf(html))
    n = len(lector.pages)
    assert n >= 3
    assert f"Página {n} de {n}" in " ".join(lector.pages[-1].extract_text().split())
    assert all(f"Folio {FOLIO}" in p.extract_text() for p in lector.pages)


async def test_el_tamano_a4_se_respeta():
    contenido = c.leer({"esquema": 1, "pagina": {"tamano": "A4"}, "bloques": [{"tipo": "parrafo"}]})
    pdf = html_a_pdf(r.renderizar(contenido, r.DatosRender({}, FOLIO, CODIGO, DOMINIO)))
    ancho, alto = (float(x) for x in _leer(pdf).pages[0].mediabox[2:])
    assert (round(ancho), round(alto)) == (595, 842)


async def test_generar_una_constancia_de_una_pagina_cabe_en_el_presupuesto_de_cinco_segundos():
    """CC-NFR-001: menos de 5 s por constancia. Aquí solo el render (sin S3 ni base de datos)."""
    html, _ = await _html("laboral")
    html_a_pdf(html)  # la primera vez carga fuentes y Pango
    tiempos = []
    for _ in range(5):
        inicio = time.perf_counter()
        html_a_pdf(html)
        tiempos.append(time.perf_counter() - inicio)
    print(f"\n[T-208] PDF de una página: máx {max(tiempos):.2f} s, media {sum(tiempos) / 5:.2f} s")
    assert max(tiempos) < 5
