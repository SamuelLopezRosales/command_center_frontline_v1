"""PDF a partir del HTML con WeasyPrint (design.md §5.4, D-06; CC-NFR-001).

WeasyPrint necesita librerías nativas (Pango): corre en el contenedor de `worker-pdf` y no en una
Lambda. En una máquina sin esas librerías ``disponible()`` devuelve ``False`` y las pruebas de PDF
se omiten (``scripts/probar_pdf.ps1`` las corre en un contenedor Linux).

Aislamiento (SSRF): el ``url_fetcher`` solo admite ``data:``. Cualquier ``http``, ``https``,
``file`` o ``ftp`` que apareciera en el HTML se rechaza y el recurso no se incluye.
"""

from __future__ import annotations

from typing import Any

PROTOCOLOS_PERMITIDOS = ("data",)


def disponible() -> bool:
    try:
        import weasyprint  # noqa: F401
    except OSError:  # faltan Pango/GObject
        return False
    except ImportError:
        return False
    return True


def crear_fetcher() -> Any:
    """Fetcher que solo resuelve ``data:`` y no sigue redirecciones."""
    from weasyprint.urls import URLFetcher

    return URLFetcher(allowed_protocols=PROTOCOLOS_PERMITIDOS, allow_redirects=False)


def html_a_pdf(html: str) -> bytes:
    """Convierte el HTML (con ``@page`` Carta y pie con folio y QR) en PDF."""
    from weasyprint import HTML

    return HTML(string=html, url_fetcher=crear_fetcher()).write_pdf()
