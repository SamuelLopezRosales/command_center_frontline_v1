"""Renderizador del contenido de una plantilla a HTML (design.md §5.1, §5.4; CC-REQ-060 a 063, 080).

El mismo HTML sirve para la vista previa y para el PDF. Reglas de seguridad:

- Solo se generan las etiquetas ``p``, ``strong``, ``em``, ``u``, ``span``, ``br``, ``img`` y
  ``div`` (más la estructura del documento); no hay forma de que el contenido agregue otras.
- Todo texto y todo valor de variable se **escapa**: un puesto con ``<script>`` queda como texto.
- Los estilos salen de enteros y colores validados otra vez aquí, aunque el esquema ya los exigió
  (un contenido viejo guardado en S3 no se vuelve vector de inyección).
- El logotipo y el QR van como URI ``data:``: el documento no pide ningún recurso externo, y su
  ``Content-Security-Policy`` lo impide también en el ``iframe`` de la vista previa.
- Folio, dominio y código de verificación se validan antes de entrar al CSS.

El pie con folio, QR y paginación se declara en ``@page`` (se ve en el PDF); un pie equivalente
para pantalla cubre la vista previa del navegador, que no dibuja los cuadros de margen.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup, escape

from cc_constancias.contenido import (
    BloqueLogotipo,
    BloqueParrafo,
    ContenidoPlantilla,
    NodoSalto,
    NodoTexto,
    NodoVariable,
)
from cc_constancias.render.qr import qr_data_uri, url_verificacion

PLANTILLAS = Path(__file__).parent / "plantillas_base"
FOLIO = re.compile(r"^CG-\d{4}-\d{4,}$")
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
DATA_URI = re.compile(r"^data:image/(png|jpeg);base64,[A-Za-z0-9+/=]+$")
FUENTES = '"Liberation Sans", "Helvetica Neue", Arial, sans-serif'
ALINEACION = {
    "izquierda": "left",
    "centro": "center",
    "derecha": "right",
    "justificado": "justify",
}
TAMANOS = {"CARTA": "Letter", "A4": "A4"}
MARGEN_INFERIOR_MINIMO_CM = 2.4  # cabe el pie con folio, paginación y QR
VARIABLE_QR = "qr_verificacion"

ETIQUETAS_PERMITIDAS = frozenset({"p", "strong", "em", "u", "span", "br", "img", "div"})

_entorno = Environment(
    loader=FileSystemLoader(str(PLANTILLAS)), autoescape=True, trim_blocks=True, lstrip_blocks=True
)


class VariableSinValor(Exception):  # noqa: N818
    """Faltan valores de variables. Lleva los nombres, nunca valores."""

    def __init__(self, nombres: list[str]) -> None:
        super().__init__("variables sin valor")
        self.nombres = nombres


@dataclass(frozen=True)
class DatosRender:
    valores: Mapping[str, str]
    folio: str
    codigo_verificacion: str
    dominio: str
    logotipo_data_uri: str | None = None
    vista_previa: bool = False  # tolera faltantes (los marca) y muestra el marcador del logotipo


# ------------------------------------------------------------------ piezas


def _estilo_nodo(n: NodoTexto | NodoVariable) -> str:
    partes: list[str] = []
    if n.tamano_pt is not None:
        partes.append(f"font-size: {int(n.tamano_pt)}pt")
    if n.color is not None:
        if not COLOR.match(n.color):
            raise ValueError("color inválido")
        partes.append(f"color: {n.color}")
    return "; ".join(partes)


def _con_marcas(interior: Markup, n: NodoTexto | NodoVariable) -> Markup:
    if n.negrita:
        interior = Markup("<strong>{}</strong>").format(interior)
    if n.cursiva:
        interior = Markup("<em>{}</em>").format(interior)
    if n.subrayado:
        interior = Markup("<u>{}</u>").format(interior)
    estilo = _estilo_nodo(n)
    if estilo:
        interior = Markup('<span style="{}">{}</span>').format(estilo, interior)
    return interior


def _nodo(n, datos: DatosRender, qr_uri: str, faltan: list[str]) -> Markup:
    if isinstance(n, NodoSalto):
        return Markup("<br>")
    if isinstance(n, NodoTexto):
        return _con_marcas(escape(n.texto), n)
    assert isinstance(n, NodoVariable)
    if n.var == VARIABLE_QR:  # el QR de verificación como imagen dentro del texto
        return Markup(
            '<img class="qr" alt="Código QR de verificación" src="{}" style="width: 2.5cm">'
        ).format(qr_uri)
    valor = datos.valores.get(n.var)
    if valor is None or not str(valor).strip():
        if n.var not in faltan:
            faltan.append(n.var)
        if datos.vista_previa:
            return _con_marcas(Markup('<span class="faltante">[{}]</span>').format(n.var), n)
        return Markup("")
    return _con_marcas(escape(str(valor)), n)


def _bloque(b, datos: DatosRender, qr_uri: str, faltan: list[str]) -> Markup:
    if isinstance(b, BloqueLogotipo):
        alinear = ALINEACION[b.alineacion]
        ancho = float(b.ancho_cm)
        if datos.logotipo_data_uri:
            if not DATA_URI.match(datos.logotipo_data_uri):
                raise ValueError("logotipo inválido")
            return Markup(
                '<div class="logotipo" style="text-align: {}"><img alt="Logotipo" src="{}" '
                'style="width: {:.1f}cm"></div>'
            ).format(alinear, datos.logotipo_data_uri, ancho)
        if datos.vista_previa:
            return Markup(
                '<div class="logotipo" style="text-align: {}">'
                '<div class="marcador">[Logotipo de la organización]</div></div>'
            ).format(alinear)
        return Markup("")  # una organización sin logotipo no lo muestra
    assert isinstance(b, BloqueParrafo)
    interior = Markup("").join(_nodo(n, datos, qr_uri, faltan) for n in b.contenido)
    if not b.contenido:
        return Markup('<p class="vacio" style="text-align: {}">&nbsp;</p>').format(
            ALINEACION[b.alineacion]
        )
    return Markup('<p style="text-align: {}">{}</p>').format(ALINEACION[b.alineacion], interior)


def _css(contenido: ContenidoPlantilla, folio: str, url: str, qr_uri: str) -> str:
    if '"' in qr_uri or "\\" in qr_uri or "\n" in qr_uri:
        raise ValueError("QR inválido")
    m = contenido.pagina.margenes_cm
    inferior = max(float(m.inf), MARGEN_INFERIOR_MINIMO_CM)
    tamano = TAMANOS[contenido.pagina.tamano]
    return f"""
@page {{
  size: {tamano};
  margin: {float(m.sup):.2f}cm {float(m.der):.2f}cm {inferior:.2f}cm {float(m.izq):.2f}cm;
  @bottom-left {{
    content: "Folio {folio}" "\\A" "Verifique en {url}";
    white-space: pre-line; word-break: break-all; width: 55%;
    font: 7.5pt {FUENTES}; color: #444; vertical-align: top; padding-top: 0.25cm;
  }}
  @bottom-center {{
    content: "Página " counter(page) " de " counter(pages);
    font: 8pt {FUENTES}; color: #444; vertical-align: top; padding-top: 0.25cm;
  }}
  @bottom-right {{
    content: url("{qr_uri}");
    width: 18%; vertical-align: top; text-align: right; padding-top: 0.15cm;
  }}
}}
html {{ font-family: {FUENTES}; }}
body {{ font-size: 11pt; line-height: 1.35; color: #000; margin: 0; }}
p {{ margin: 0 0 0.6em 0; }}
p.vacio {{ min-height: 1.35em; }}
.logotipo {{ margin: 0 0 1em 0; }}
.logotipo img {{ height: auto; }}
.marcador {{ border: 1px dashed #888; color: #666; font-size: 9pt; padding: 0.6em 1em;
  display: inline-block; }}
.faltante {{ background: #fde2e2; color: #9b1c1c; border-radius: 2px; }}
.pie-pantalla {{ display: none; }}
@media screen {{
  body {{ max-width: 21.6cm; margin: 0 auto; padding: 2.5cm; background: #fff; }}
  .pie-pantalla {{ display: flex; align-items: center; justify-content: space-between;
    margin-top: 2cm; padding-top: 0.4cm; border-top: 1px solid #ccc; font-size: 8pt; color: #444; }}
}}
"""


# ------------------------------------------------------------------ API


def renderizar(contenido: ContenidoPlantilla, datos: DatosRender) -> str:
    """Documento HTML completo. Con valores sin resolver y sin ``vista_previa`` lanza
    ``VariableSinValor``; con ``vista_previa`` los deja marcados."""
    if not FOLIO.match(datos.folio):
        raise ValueError("folio inválido")
    url = url_verificacion(datos.dominio, datos.codigo_verificacion)
    qr_uri = qr_data_uri(url)
    faltan: list[str] = []
    cuerpo = Markup("\n").join(_bloque(b, datos, qr_uri, faltan) for b in contenido.bloques)
    if faltan and not datos.vista_previa:
        raise VariableSinValor(faltan)
    return _entorno.get_template("documento.html.j2").render(
        css=_css(contenido, datos.folio, url, qr_uri),
        cuerpo=cuerpo,
        folio=datos.folio,
        url=url,
        qr_uri=qr_uri,
    )
