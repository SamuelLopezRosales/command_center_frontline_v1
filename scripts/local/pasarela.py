"""Pasarela local (puerto 8000) y proveedor de identidad de DESARROLLO.

Hace dos cosas, solo para el stack local:

1. Reenvía por prefijo de ruta a cada servicio, como lo hará el balanceador (ALB) en AWS.
   ``/internal/*`` nunca se expone.
2. Hace de proveedor de identidad: publica ``/.well-known/jwks.json`` con una llave RSA local
   (``.local/idp_llave.pem``, generada una vez y nunca versionada) y emite tokens de acceso con
   los mismos claims que ``cognito-pre-token``. Así los servicios validan los tokens SIN cambiar
   su código: solo se les apunta ``CC_COGNITO_EMISOR`` a esta pasarela.

El proveedor se niega a arrancar si ``CC_AMBIENTE`` no es exactamente ``local``. Este módulo vive
en ``scripts/`` y no entra en ninguna imagen ni paquete que se despliegue en AWS.

    uvicorn scripts.local.pasarela:crear_app --factory --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from scripts.local import constantes as c

# Prefijo de ruta -> servicio. Se evalúa en orden: gana el primero que coincide por segmentos
# completos (``/api/v1/plantillas`` coincide con ``/api/v1/plantillas/7`` pero no con ``/x``).
# ``/api/v1/constancias/historial`` es del dashboard; el resto de ``/api/v1/constancias`` es de
# constancias (igual que las reglas del ALB).
RUTAS: tuple[tuple[str, str], ...] = (
    ("/api/v1/constancias/historial", "dashboard"),
    ("/api/v1/constancias", "constancias"),
    ("/api/v1/plantillas", "constancias"),
    ("/api/v1/publico", "constancias"),
    ("/d", "constancias"),
    ("/api/v1/colaboradores", "colaboradores"),
    ("/api/v1/cargas", "colaboradores"),
    ("/api/v1/organizaciones", "colaboradores"),
    ("/api/v1/plantas", "colaboradores"),
    ("/api/v1/campos", "campos"),
    ("/api/v1/dashboard", "dashboard"),
    ("/api/v1/usuarios", "dashboard"),
    ("/api/v1/sesion", "dashboard"),
    ("/api/v1/bitacora", "dashboard"),
)
SALTO_A_SALTO = frozenset(
    {"host", "connection", "keep-alive", "transfer-encoding", "te", "upgrade", "content-length"}
)
VIGENCIA_TOKEN_S = 8 * 3600  # solo desarrollo: una jornada sin renovar
CODIGO_TOTP = re.compile(r"^\d{6}$")


def destino(ruta: str) -> str | None:
    """Servicio al que corresponde la ruta, o ``None`` (incluye ``/internal``)."""
    if ruta == "/internal" or ruta.startswith("/internal/"):
        return None
    for prefijo, servicio in RUTAS:
        if ruta == prefijo or ruta.startswith(prefijo + "/"):
            return servicio
    return None


def _b64(n: int) -> str:
    crudo = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(crudo).rstrip(b"=").decode()


class ProveedorIdentidad:
    """Llave RSA local, JWKS y emisión de tokens de acceso de desarrollo."""

    def __init__(self, archivo_llave: Path, archivo_usuarios: Path) -> None:
        self._archivo_usuarios = archivo_usuarios
        archivo_llave.parent.mkdir(parents=True, exist_ok=True)
        if archivo_llave.exists():
            self._llave = serialization.load_pem_private_key(archivo_llave.read_bytes(), None)
        else:
            self._llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            archivo_llave.write_bytes(
                self._llave.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
        numeros = self._llave.public_key().public_numbers()
        self.kid = "local-" + _b64(numeros.n)[:12]
        self._jwk = {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": self.kid,
            "n": _b64(numeros.n),
            "e": _b64(numeros.e),
        }
        self._sesiones: dict[str, tuple[dict, float]] = {}

    def jwks(self) -> dict:
        return {"keys": [self._jwk]}

    def _usuarios(self) -> list[dict]:
        if not self._archivo_usuarios.exists():
            return []
        return json.loads(self._archivo_usuarios.read_text(encoding="utf-8"))

    def verificar_credenciales(self, correo: str, contrasena: str) -> dict | None:
        usuario = next(
            (u for u in self._usuarios() if u["correo"].lower() == correo.strip().lower()), None
        )
        # La comparación es en tiempo constante aunque sea una contraseña de desarrollo.
        ok = secrets.compare_digest(contrasena.encode(), c.CONTRASENA_DEV.encode())
        return usuario if usuario and ok else None

    def abrir_sesion(self, usuario: dict) -> str:
        ahora = time.monotonic()
        self._sesiones = {k: v for k, v in self._sesiones.items() if v[1] > ahora}
        sesion = secrets.token_urlsafe(24)
        self._sesiones[sesion] = (usuario, ahora + 300)
        return sesion

    def cerrar_sesion(self, sesion: str) -> dict | None:
        datos = self._sesiones.pop(sesion, None)
        return datos[0] if datos and datos[1] > time.monotonic() else None

    def emitir(self, usuario: dict, ttl_s: int = VIGENCIA_TOKEN_S) -> str:
        ahora = int(time.time())
        claims = {
            "sub": usuario["sub"],
            "iss": c.EMISOR,
            "client_id": c.CLIENT_ID,
            "token_use": "access",
            "iat": ahora,
            "exp": ahora + ttl_s,
            "jti": uuid.uuid4().hex,
            "empresa_id": str(usuario["empresa_id"]),
            "rol": usuario.get("rol", "RH"),
            "usuario_id": str(usuario["usuario_id"]),
        }
        return jwt.encode(claims, self._llave, algorithm="RS256", headers={"kid": self.kid})


def _error(estado: int, codigo: str) -> JSONResponse:
    return JSONResponse({"codigo": codigo}, status_code=estado)


def crear_app(
    *,
    urls: dict[str, str] | None = None,
    archivo_llave: Path | None = None,
    archivo_usuarios: Path | None = None,
    transporte: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    if os.environ.get("CC_AMBIENTE") != "local":
        raise RuntimeError(
            "La pasarela local y su proveedor de identidad de desarrollo solo corren con "
            "CC_AMBIENTE=local."
        )
    servicios = urls or {
        nombre: f"http://127.0.0.1:{puerto}" for nombre, puerto in c.PUERTOS_SERVICIOS.items()
    }
    idp = ProveedorIdentidad(
        archivo_llave or c.ARCHIVO_LLAVE_IDP, archivo_usuarios or c.ARCHIVO_USUARIOS
    )
    cliente = httpx.AsyncClient(timeout=60.0, transport=transporte, follow_redirects=False)

    @asynccontextmanager
    async def ciclo(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await cliente.aclose()

    app = FastAPI(
        title="Pasarela local", docs_url=None, redoc_url=None, openapi_url=None, lifespan=ciclo
    )
    app.state.idp = idp

    @app.get("/salud")
    async def salud() -> dict[str, str]:
        return {"estado": "ok", "servicio": "pasarela-local"}

    @app.get("/.well-known/jwks.json")
    async def jwks() -> dict:
        return idp.jwks()

    # --- Acceso de desarrollo (lo usa frontend/src/shared/sesion/authLocal.ts) ---
    @app.post("/api/dev/auth/iniciar")
    async def iniciar(request: Request) -> JSONResponse:
        datos = await _json(request)
        usuario = idp.verificar_credenciales(
            str(datos.get("correo", "")), str(datos.get("contrasena", ""))
        )
        if usuario is None:
            return _error(401, "CREDENCIALES")
        return JSONResponse({"paso": "TOTP", "sesion": idp.abrir_sesion(usuario)})

    @app.post("/api/dev/auth/totp")
    async def totp(request: Request) -> JSONResponse:
        datos = await _json(request)
        if not CODIGO_TOTP.match(str(datos.get("codigo", ""))):
            return _error(401, "CODIGO_INVALIDO")
        usuario = idp.cerrar_sesion(str(datos.get("sesion", "")))
        if usuario is None:
            return _error(401, "SESION_VENCIDA")
        return JSONResponse({"access_token": idp.emitir(usuario), "expira_en": VIGENCIA_TOKEN_S})

    @app.api_route(
        "/{ruta:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    )
    async def reenviar(ruta: str, request: Request) -> Response:
        camino = "/" + ruta
        servicio = destino(camino)
        if servicio is None:
            return _error(404, "NO_ENCONTRADO")
        cabeceras = {k: v for k, v in request.headers.items() if k.lower() not in SALTO_A_SALTO}
        cabeceras["x-forwarded-for"] = request.client.host if request.client else "127.0.0.1"
        try:
            r = await cliente.request(
                request.method,
                servicios[servicio] + camino,
                params=request.query_params.multi_items(),
                headers=cabeceras,
                content=await request.body(),
            )
        except httpx.TransportError:
            return _error(502, f"SERVICIO_NO_DISPONIBLE:{servicio}")
        salida = {
            k: v
            for k, v in r.headers.items()
            if k.lower() not in SALTO_A_SALTO | {"content-encoding"}
        }
        return Response(content=r.content, status_code=r.status_code, headers=salida)

    return app


async def _json(request: Request) -> dict:
    try:
        datos = await request.json()
    except ValueError:
        return {}
    return datos if isinstance(datos, dict) else {}
