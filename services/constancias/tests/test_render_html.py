"""T-208 (T-082): renderizador de HTML, logotipo y QR (sin WeasyPrint ni base de datos)."""

import base64
import re
from html.parser import HTMLParser
from urllib.parse import unquote

import pytest
import segno
import zxingcpp
from cc_constancias import contenido as c
from cc_constancias.render import html as r
from cc_constancias.render.logotipo import CargadorLogotipo, tipo_de
from cc_constancias.render.qr import qr_data_uri, url_verificacion
from PIL import Image

CODIGO = "ABCDEFGHIJKLMNOPQRSTUV"
DOMINIO = "cc.ejemplo.com"
FOLIO = "CG-2026-0001"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
URI_PNG = "data:image/png;base64," + base64.b64encode(PNG).decode()


def doc(*bloques, **pagina):
    return c.leer({"esquema": 1, "pagina": pagina or {}, "bloques": list(bloques)})


def parrafo(*nodos, **extra):
    return {"tipo": "parrafo", "contenido": list(nodos)} | extra


def datos(valores=None, **kw):
    base = {
        "valores": valores or {},
        "folio": FOLIO,
        "codigo_verificacion": CODIGO,
        "dominio": DOMINIO,
    }
    return r.DatosRender(**(base | kw))


class _Etiquetas(HTMLParser):
    def __init__(self):
        super().__init__()
        self.etiquetas: set[str] = set()
        self.atributos: list[tuple[str, str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        self.etiquetas.add(tag)
        self.atributos += [(tag, k, v) for k, v in attrs]


def etiquetas(html: str) -> _Etiquetas:
    p = _Etiquetas()
    p.feed(html)
    return p


# ------------------------------------------------------------------ etiquetas y escape


def test_solo_se_generan_las_etiquetas_permitidas():
    contenido = doc(
        {"tipo": "logotipo"},
        parrafo(
            {"texto": "a", "negrita": True, "cursiva": True, "subrayado": True, "tamano_pt": 12},
            {"var": "x", "color": "#112233"},
            {"salto": True},
            {"var": "qr_verificacion"},
        ),
        parrafo(),
    )
    html = r.renderizar(contenido, datos({"x": "v"}, logotipo_data_uri=URI_PNG))
    estructura = {"html", "head", "meta", "title", "style", "body"}
    assert etiquetas(html).etiquetas <= estructura | r.ETIQUETAS_PERMITIDAS
    assert {"p", "strong", "em", "u", "span", "br", "img", "div"} <= etiquetas(html).etiquetas
    # los únicos atributos son de presentación; ninguno es un manejador de eventos o un enlace
    permitidos = {"class", "style", "src", "alt", "lang", "charset", "content", "http-equiv"}
    assert {a for _, a, _ in etiquetas(html).atributos} <= permitidos
    assert "<script" not in html and "<a " not in html and "<iframe" not in html


@pytest.mark.parametrize(
    "valor",
    [
        "<script>alert(1)</script>",
        '"><img src=x onerror=alert(1)>',
        "</p><h1>inyectado</h1>",
        "a & b <i>",
        "{{nombre}}",
    ],
)
def test_un_valor_con_html_queda_escapado(valor):
    html = r.renderizar(doc(parrafo({"var": "puesto"})), datos({"puesto": valor}))
    cuerpo = html.split("<body>")[1].split('<div class="pie-pantalla">')[0]
    assert "<script" not in cuerpo and "<h1" not in cuerpo and "<i>" not in cuerpo
    assert "onerror" not in {a for _, a, _ in etiquetas(html).atributos}
    assert "&lt;" in cuerpo or valor == "{{nombre}}"
    assert (
        etiquetas(html).etiquetas
        <= {"html", "head", "meta", "title", "style", "body"} | r.ETIQUETAS_PERMITIDAS
    )


def test_el_texto_literal_de_la_plantilla_tambien_se_escapa():
    # el esquema ya rechaza el HTML, pero un contenido viejo en S3 no debe poder inyectarlo
    contenido = c.ContenidoPlantilla.model_construct(
        esquema=1,
        pagina=c.Pagina(),
        bloques=[
            c.BloqueParrafo.model_construct(
                tipo="parrafo",
                alineacion="izquierda",
                contenido=[c.NodoTexto.model_construct(texto="<script>x</script>")],
            )
        ],
    )
    html = r.renderizar(contenido, datos())
    assert "<script>x" not in html and "&lt;script&gt;x&lt;/script&gt;" in html


def test_los_estilos_se_revalidan_aunque_el_esquema_ya_lo_hiciera():
    malo = c.NodoTexto.model_construct(
        texto="x", color="red; background:url(http://x)", tamano_pt=12
    )
    contenido = c.ContenidoPlantilla.model_construct(
        esquema=1,
        pagina=c.Pagina(),
        bloques=[
            c.BloqueParrafo.model_construct(
                tipo="parrafo", alineacion="izquierda", contenido=[malo]
            )
        ],
    )
    with pytest.raises(ValueError, match="color"):
        r.renderizar(contenido, datos())


def test_marcas_alineacion_y_saltos():
    html = r.renderizar(
        doc(
            parrafo(
                {"texto": "uno", "negrita": True, "color": "#1F3A5F", "tamano_pt": 14},
                {"salto": True},
                {"texto": "dos", "cursiva": True, "subrayado": True},
                alineacion="derecha",
            ),
            parrafo(alineacion="justificado"),
        ),
        datos(),
    )
    assert '<p style="text-align: right">' in html
    assert '<span style="font-size: 14pt; color: #1F3A5F"><strong>uno</strong></span>' in html
    assert "<br>" in html and "<u><em>dos</em></u>" in html
    assert '<p class="vacio" style="text-align: justify">&nbsp;</p>' in html


# ------------------------------------------------------------------ variables sin valor


def test_un_valor_faltante_impide_generar_y_lista_solo_nombres():
    contenido = doc(parrafo({"var": "nss"}, {"var": "rfc"}, {"var": "nss"}, {"var": "puesto"}))
    with pytest.raises(r.VariableSinValor) as exc:
        r.renderizar(contenido, datos({"puesto": "Op", "rfc": "  "}))
    assert exc.value.nombres == ["nss", "rfc"]
    assert "Op" not in str(exc.value)


def test_en_la_vista_previa_los_faltantes_se_marcan():
    html = r.renderizar(doc(parrafo({"var": "nss", "negrita": True})), datos(vista_previa=True))
    assert '<span class="faltante">[nss]</span>' in html and "<strong>" in html


# ------------------------------------------------------------------ logotipo


def test_el_logotipo_se_incrusta_como_data_uri_y_no_pide_recursos_externos():
    html = r.renderizar(
        doc({"tipo": "logotipo", "alineacion": "centro", "ancho_cm": 4}),
        datos(logotipo_data_uri=URI_PNG),
    )
    assert f'src="{URI_PNG}"' in html and "width: 4.0cm" in html and "text-align: center" in html
    fuentes = [v for t, a, v in etiquetas(html).atributos if a == "src"]
    assert fuentes and all(v.startswith("data:") for v in fuentes)
    assert "http-equiv" in html and "default-src 'none'" in html and "img-src data:" in html


@pytest.mark.parametrize(
    "uri",
    [
        "javascript:alert(1)",
        "http://ejemplo.com/logo.png",
        "data:text/html;base64,PHNjcmlwdD4=",
        'data:image/png;base64,AAAA" onerror="x',
        "file:///etc/passwd",
    ],
)
def test_un_logotipo_que_no_es_una_imagen_data_se_rechaza(uri):
    with pytest.raises(ValueError, match="logotipo"):
        r.renderizar(doc({"tipo": "logotipo"}), datos(logotipo_data_uri=uri))


def test_sin_logotipo_se_omite_y_en_la_vista_previa_hay_marcador():
    bloque = {"tipo": "logotipo"}
    assert '<img alt="Logotipo"' not in r.renderizar(doc(bloque), datos())
    assert "[Logotipo de la organización]" not in r.renderizar(doc(bloque), datos())
    assert "[Logotipo de la organización]" in r.renderizar(doc(bloque), datos(vista_previa=True))


class _Almacen:
    def __init__(self, objetos):
        self.objetos = objetos
        self.lecturas = 0

    async def leer(self, clave):
        self.lecturas += 1
        return self.objetos.get(clave)


async def test_el_cargador_lee_s3_valida_el_tipo_y_cachea_diez_minutos():
    reloj = {"t": 0.0}
    almacen = _Almacen({"logo.png": PNG, "logo.jpg": JPG})
    cargador = CargadorLogotipo(almacen, ttl_s=600, reloj=lambda: reloj["t"])
    uri = await cargador.data_uri("logo.png")
    assert uri == URI_PNG and base64.b64decode(uri.split(",")[1]) == PNG
    assert (await cargador.data_uri("logo.png")) == uri and almacen.lecturas == 1  # caché
    reloj["t"] = 599
    await cargador.data_uri("logo.png")
    assert almacen.lecturas == 1
    reloj["t"] = 601
    await cargador.data_uri("logo.png")
    assert almacen.lecturas == 2  # venció
    assert (await cargador.data_uri("logo.jpg")).startswith("data:image/jpeg;base64,")


async def test_el_cargador_no_incrusta_lo_que_no_es_png_o_jpeg_ni_lo_demasiado_grande():
    almacen = _Almacen(
        {
            "svg": b"<svg onload='alert(1)'></svg>",
            "html": b"<html><script>x</script></html>",
            "grande": PNG + b"\x00" * 2000,
        }
    )
    cargador = CargadorLogotipo(almacen, maximo=1000)
    for clave in ("svg", "html", "grande", "no-existe", None, ""):
        assert await cargador.data_uri(clave) is None, clave
    assert (
        tipo_de(PNG) == "image/png" and tipo_de(JPG) == "image/jpeg" and tipo_de(b"GIF89a") is None
    )


# ------------------------------------------------------------------ QR y pie de página


def _matriz_del_svg(uri: str) -> Image.Image:
    """Rasteriza el SVG del QR (segno lo escribe como trazos ``h`` horizontales) para decodificarlo."""
    svg = unquote(uri.split(",", 1)[1])
    trazo = re.search(r"\sd='([^']+)'", svg).group(1)
    lado = int(re.search(r"width='(\d+)'", svg).group(1)) // 2  # escala 2
    modulo, borde = 8, 4
    img = Image.new("L", ((lado + 2 * borde) * modulo,) * 2, 255)
    x = y = 0.0
    for orden, args in re.findall(r"([Mmh])([^Mmh]*)", trazo):
        n = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", args)]
        if orden == "M":
            x, y = n
        elif orden == "m":
            x, y = x + n[0], y + n[1]
        else:  # h: cubre ``n`` módulos a partir de x en la fila int(y)
            fila = int(y)
            for col in range(int(x), int(x + n[0])):
                px, py = (col + borde) * modulo, (fila + borde) * modulo
                img.paste(0, (px, py, px + modulo, py + modulo))
            x += n[0]
    return img


def test_el_qr_del_pie_se_decodifica_a_la_url_de_verificacion():
    html = r.renderizar(doc(parrafo({"texto": "x"})), datos())
    esperado = f"https://{DOMINIO}/v/{CODIGO}"
    assert url_verificacion(DOMINIO, CODIGO) == esperado
    pie = re.search(r'<img class="qr-pie"[^>]*src="([^"]+)"', html).group(1)
    leidos = zxingcpp.read_barcodes(_matriz_del_svg(pie))
    assert [x.text for x in leidos] == [esperado]  # decodificado desde el HTML, no regenerado
    assert pie == qr_data_uri(esperado) and segno.make(esperado, error="m").error == "M"


def test_el_qr_tambien_va_en_el_cuadro_de_margen_del_pdf():
    html = r.renderizar(doc(parrafo({"texto": "x"})), datos())
    margen = re.search(r'@bottom-right \{\s*content: url\("([^"]+)"\)', html).group(1)
    assert [x.text for x in zxingcpp.read_barcodes(_matriz_del_svg(margen))] == [
        f"https://{DOMINIO}/v/{CODIGO}"
    ]


def test_la_variable_qr_dibuja_el_qr_dentro_del_texto():
    html = r.renderizar(doc(parrafo({"var": "qr_verificacion"})), datos())
    assert 'class="qr"' in html


def test_el_html_trae_page_carta_y_pie_con_folio_qr_y_paginacion():
    html = r.renderizar(doc(parrafo({"texto": "x"})), datos())
    assert "@page" in html and "size: Letter" in html
    assert 'content: "Folio CG-2026-0001"' in html and f"/v/{CODIGO}" in html
    assert 'content: "Página " counter(page) " de " counter(pages)' in html
    assert "@bottom-left" in html and "@bottom-center" in html and "@bottom-right" in html
    assert "Folio CG-2026-0001" in html.split('<div class="pie-pantalla">')[1]  # pie en pantalla
    assert '<html lang="es">' in html


def test_tamano_y_margenes_de_la_pagina():
    html = r.renderizar(
        doc(parrafo(), tamano="A4", margenes_cm={"sup": 3, "inf": 1, "izq": 2, "der": 4}), datos()
    )
    # el margen inferior se sube a 2.4 cm: ahí caben el folio y el QR del pie
    assert "size: A4" in html and "margin: 3.00cm 4.00cm 2.40cm 2.00cm" in html
    html = r.renderizar(doc(parrafo(), margenes_cm={"inf": 3.5}), datos())
    assert "size: Letter" in html and "3.50cm" in html


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("folio", 'CG-2026-0001"; } body { display:none'),
        ("folio", "CG-26-1"),
        ("folio", "../../etc"),
        ("dominio", "ejemplo.com/ruta"),
        ("dominio", 'a.com"; x'),
        ("dominio", "a b.com"),
        ("codigo_verificacion", "corto"),
        ("codigo_verificacion", 'ABCDEFGHIJKLMNOPQRSTUV"</style>'),
    ],
)
def test_folio_dominio_y_codigo_se_validan_antes_de_entrar_al_css(campo, valor):
    with pytest.raises(ValueError):
        r.renderizar(doc(parrafo()), datos(**{campo: valor}))
