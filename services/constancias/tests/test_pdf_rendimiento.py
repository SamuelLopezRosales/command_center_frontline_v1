"""T-210 (T-090, T-091): rendimiento del PDF y aislamiento del renderizador.

Necesita Pango: corre en el contenedor con ``scripts/probar_pdf.ps1 -Recursos`` (1 vCPU y 2 GB,
como el worker en producción). No necesita base de datos.
"""

import http.server
import statistics
import threading
import time

import pytest
from cc_constancias.render.pdf import disponible, html_a_pdf
from test_pdf import _html, _texto

pytestmark = [
    pytest.mark.pdf,
    pytest.mark.skipif(not disponible(), reason="WeasyPrint no carga: use scripts/probar_pdf.ps1"),
]

GENERACIONES = 100
PRESUPUESTO_P95_S = 5.0


async def test_cien_generaciones_con_p95_menor_a_5_segundos():
    htmls = [(await _html(n))[0] for n in ("laboral", "guarderia", "consulado")]
    html_a_pdf(htmls[0])  # calentamiento: carga de fuentes
    tiempos = []
    for i in range(GENERACIONES):
        t = time.perf_counter()
        pdf = html_a_pdf(htmls[i % 3])
        tiempos.append(time.perf_counter() - t)
        assert pdf.startswith(b"%PDF")
    tiempos.sort()
    p95 = tiempos[int(len(tiempos) * 0.95) - 1]
    print(  # noqa: T201 - la medición se lee en la salida del contenedor
        f"\nMEDICION_PDF generaciones={GENERACIONES} p50={statistics.median(tiempos):.3f}s "
        f"p95={p95:.3f}s max={tiempos[-1]:.3f}s"
    )
    assert p95 < PRESUPUESTO_P95_S


class _Cuenta(http.server.BaseHTTPRequestHandler):
    visitas: list[str] = []  # noqa: RUF012

    def do_GET(self):  # noqa: N802
        _Cuenta.visitas.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


async def test_el_renderizador_no_sale_a_la_red_ni_lee_archivos_locales(tmp_path):
    servidor = http.server.HTTPServer(("127.0.0.1", 0), _Cuenta)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    secreto = tmp_path / "secreto.txt"
    secreto.write_text("CONTENIDO-LOCAL-PRIVADO")
    url = f"http://127.0.0.1:{servidor.server_port}"
    html = (
        "<html><head>"
        f"<link rel='stylesheet' href='{url}/estilo.css'>"
        f"<style>@import url('{url}/importado.css'); p {{ background: url('{url}/fondo.png') }}"
        "</style></head><body>"
        f"<img src='{url}/imagen.png'><img src='file://{secreto}'>"
        f"<iframe src='file://{secreto}'></iframe><object data='file://{secreto}'></object>"
        "<p>Texto visible</p></body></html>"
    )
    try:
        pdf = html_a_pdf(html)  # los recursos que no se pueden leer se omiten; no falla
    finally:
        servidor.shutdown()
    assert _Cuenta.visitas == []  # ninguna petición salió hacia el servidor
    texto = _texto(pdf)
    assert "Texto visible" in texto and "CONTENIDO-LOCAL-PRIVADO" not in texto


async def test_valores_hostiles_salen_como_texto_en_el_pdf():
    hostil = "<script>alert(1)</script><img src='file:///etc/passwd'>"
    html, _ = await _html("laboral", valores={**(await _valores()), "nombre_completo": hostil})
    texto = _texto(html_a_pdf(html))
    assert "<script>alert(1)</script>" in texto.replace(
        " ", ""
    )  # visible como texto, no ejecutado ni interpretado
    assert "root:" not in texto


async def _valores():
    from referencia import COLABORADOR

    return dict(COLABORADOR)
