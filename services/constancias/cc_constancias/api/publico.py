"""Rutas públicas: verificación por QR (CON-19) y descarga por enlace (CON-20, CON-21).

Sin autenticación de usuario (``ruta_publica``). No revelan si un código o token existe más de lo
necesario, no se guardan en caché ni se indexan, y no filtran el token por ``Referer``.
"""

from __future__ import annotations

import re
from datetime import datetime
from html import escape

from cc_common.auth import ruta_publica
from cc_common.db import transaccion
from cc_common.errores import ErrorDominio, ErrorNoEncontrado
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import text

from cc_constancias.dependencias import firmador, motor
from cc_constancias.servicios import entrega as servicio

router = APIRouter(tags=["publico"])

CODIGO = re.compile(r"^[A-Za-z0-9_-]{22,64}$")
VIGENCIA_COLABORADOR_S = 60
CABECERAS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
}


def es_ruta_publica(ruta: str) -> bool:
    return ruta.startswith("/d/") or ruta.startswith("/api/v1/publico/")


def _enlace_no_vigente() -> ErrorDominio:
    return ErrorDominio(
        codigo="ENLACE_NO_VIGENTE",
        mensaje_publico="El enlace ya se usó o venció. Solicita la constancia de nuevo.",
        http=410,
    )


class Verificacion(BaseModel):
    nombre: str
    folio: str
    fecha_emision: datetime
    estado: str


@router.get(
    "/api/v1/publico/verificar/{codigo}",
    response_model=Verificacion,
    summary="Verifica una constancia por el código del QR (CON-19)",
    dependencies=[ruta_publica()],
)
async def verificar(codigo: str, response: Response, m=Depends(motor)) -> Verificacion:
    response.headers.update(CABECERAS)
    if not CODIGO.match(codigo):
        raise ErrorNoEncontrado()
    async with transaccion(m, None) as conn:
        r = await conn.execute(
            text("SELECT * FROM constancias.verificar_constancia(:c)"), {"c": codigo}
        )
        f = r.mappings().first()
    if f is None or f["folio"] is None:
        raise ErrorNoEncontrado()
    return Verificacion(
        nombre=f["nombre"], folio=f["folio"], fecha_emision=f["fecha"], estado=f["estado"]
    )


_PAGINA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><meta name="referrer" content="no-referrer">
<title>Tu constancia</title></head>
<body style="font-family:sans-serif;max-width:28rem;margin:3rem auto;padding:0 1rem">
<h1>Tu constancia está lista</h1>
<p>Este enlace sirve una sola vez. Toca el botón para descargarla.</p>
<form method="post" action="/d/{token}/descargar">
<button type="submit" style="font-size:1.1rem;padding:.7rem 1.2rem">Descargar constancia</button>
</form></body></html>"""


@router.get(
    "/d/{token}",
    response_class=HTMLResponse,
    summary="Página de descarga; no consume el enlace (CON-20)",
    dependencies=[ruta_publica()],
)
async def pagina(token: str, request: Request, m=Depends(motor)) -> HTMLResponse:
    estado = await servicio.estado_token(m, token)
    if estado is None:
        raise ErrorNoEncontrado()
    if estado != "VIGENTE":
        raise _enlace_no_vigente()
    return HTMLResponse(_PAGINA.format(token=escape(token)))


@router.post(
    "/d/{token}/descargar",
    status_code=302,
    summary="Consume el enlace y redirige al PDF firmado (CON-21)",
    dependencies=[ruta_publica()],
    response_class=Response,
)
async def descargar(token: str, m=Depends(motor), f=Depends(firmador)) -> RedirectResponse:
    consumido = await servicio.consumir_token(m, token)
    if consumido is None:
        if await servicio.estado_token(m, token) is None:
            raise ErrorNoEncontrado()
        raise _enlace_no_vigente()
    url = f.firmar(consumido["pdf_s3_key"], VIGENCIA_COLABORADOR_S)
    return RedirectResponse(url.url, status_code=302)
