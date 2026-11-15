"""Cliente y token de las llamadas internas entre servicios (design.md §3.8, §11.1).

- Token interno: JWT HS256 de 60 segundos, firmado con ``cc/{env}/internal-auth``, con el
  servicio que llama (``iss``) y la audiencia ``cc-interno``.
- Tiempo máximo de 3 segundos por llamada.
- Hasta 2 reintentos con espera creciente, solo en métodos idempotentes (GET, PUT, DELETE,
  HEAD) y solo ante errores de red, tiempo agotado o respuestas 502, 503 y 504.
- Corte de circuito: tras 5 fallos seguidos, se abre 30 segundos y falla de inmediato.
- Propaga ``X-Correlation-Id``.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import jwt

from cc_common.errores import ErrorNoAutenticado, ErrorProveedor

AUDIENCIA = "cc-interno"
IDEMPOTENTES = frozenset({"GET", "PUT", "DELETE", "HEAD"})
REINTENTABLES_HTTP = frozenset({502, 503, 504})


def emitir_token_interno(secreto: str, servicio: str, ttl_s: int = 60, ahora=time.time) -> str:
    t = int(ahora())
    return jwt.encode(
        {"iss": servicio, "aud": AUDIENCIA, "iat": t, "exp": t + ttl_s, "jti": uuid.uuid4().hex},
        secreto,
        algorithm="HS256",
    )


def verificar_token_interno(
    token: str, secreto: str, permitidos: frozenset[str] | None = None
) -> str:
    """Devuelve el servicio que llama o lanza ``ErrorNoAutenticado``."""
    try:
        claims = jwt.decode(token, secreto, algorithms=["HS256"], audience=AUDIENCIA, leeway=5)
    except jwt.PyJWTError as exc:
        raise ErrorNoAutenticado() from exc
    servicio = str(claims.get("iss", ""))
    if not servicio or (permitidos is not None and servicio not in permitidos):
        raise ErrorNoAutenticado()
    return servicio


class CircuitoAbierto(ErrorProveedor):
    pass


class ClienteInterno:
    def __init__(
        self,
        base_url: str,
        *,
        servicio: str,
        secreto: Callable[[], str],
        transporte: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 3.0,
        reintentos: int = 2,
        espera_s: float = 0.2,
        umbral_fallos: int = 5,
        apertura_s: float = 30.0,
        reloj=time.monotonic,
    ) -> None:
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout_s, transport=transporte)
        self._servicio = servicio
        self._secreto = secreto
        self._reintentos = reintentos
        self._espera = espera_s
        self._umbral = umbral_fallos
        self._apertura = apertura_s
        self._reloj = reloj
        self._fallos = 0
        self._abierto_hasta = 0.0

    async def cerrar(self) -> None:
        await self._http.aclose()

    @property
    def circuito_abierto(self) -> bool:
        return self._reloj() < self._abierto_hasta

    def _registrar(self, exito: bool) -> None:
        if exito:
            self._fallos = 0
            return
        self._fallos += 1
        if self._fallos >= self._umbral:
            self._abierto_hasta = self._reloj() + self._apertura
            self._fallos = 0

    async def solicitar(
        self, metodo: str, ruta: str, *, correlacion_id: str | None = None, **kwargs: Any
    ) -> httpx.Response:
        metodo = metodo.upper()
        if self.circuito_abierto:
            raise CircuitoAbierto("CIRCUITO_ABIERTO")
        intentos = 1 + (self._reintentos if metodo in IDEMPOTENTES else 0)
        cabeceras = dict(kwargs.pop("headers", {}) or {})
        cabeceras["Authorization"] = (
            f"Bearer {emitir_token_interno(self._secreto(), self._servicio)}"
        )
        cabeceras["X-Correlation-Id"] = correlacion_id or uuid.uuid4().hex
        ultimo: Exception | None = None
        for intento in range(1, intentos + 1):
            try:
                r = await self._http.request(metodo, ruta, headers=cabeceras, **kwargs)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                ultimo = exc
            else:
                if r.status_code not in REINTENTABLES_HTTP:
                    self._registrar(r.status_code < 500)
                    return r
                ultimo = ErrorProveedor()
            if intento < intentos:
                await asyncio.sleep(self._espera * intento)
        self._registrar(False)
        raise ErrorProveedor() from ultimo


# ------------------------------------------------------------------ lado del servidor (T-203)


class LlamadaInterna:
    """Quién llama (servicio del token) y para qué empresa (``X-Empresa-Id``)."""

    __slots__ = ("empresa_id", "servicio")

    def __init__(self, servicio: str, empresa_id: int) -> None:
        self.servicio = servicio
        self.empresa_id = empresa_id


def requiere_servicio(*permitidos: str):
    """Dependencia de FastAPI para rutas ``/internal``: token interno de un servicio permitido y
    encabezado ``X-Empresa-Id`` (la empresa fija ``app.empresa_id`` y con ello la RLS).

    La app debe exponer ``app.state.secreto_interno``: una función sin argumentos que devuelve el
    secreto ``cc/{env}/internal-auth``. Se marca como ruta con permiso para ``rutas_sin_permiso``.
    """
    from fastapi import Depends, Header, Request

    from cc_common.auth import extraer_bearer
    from cc_common.errores import ErrorCampo, ErrorValidacion

    servicios = frozenset(permitidos)

    def _dependencia(
        request: Request,
        authorization: str | None = Header(default=None),
        x_empresa_id: str | None = Header(default=None),
    ) -> LlamadaInterna:
        servicio = verificar_token_interno(
            extraer_bearer(authorization), request.app.state.secreto_interno(), servicios
        )
        try:
            empresa_id = int(x_empresa_id or "")
        except ValueError:
            empresa_id = 0
        if empresa_id <= 0:
            raise ErrorValidacion(
                "EMPRESA_REQUERIDA",
                "Falta el encabezado X-Empresa-Id.",
                errores=[ErrorCampo("X-Empresa-Id", "REQUERIDO", "Falta la empresa.")],
            )
        return LlamadaInterna(servicio, empresa_id)

    # Con ``from __future__ import annotations`` FastAPI no resolvería ``Request`` (importado
    # aquí dentro): se le dan las anotaciones ya evaluadas.
    _dependencia.__annotations__ = {
        "request": Request,
        "authorization": str | None,
        "x_empresa_id": str | None,
        "return": LlamadaInterna,
    }
    _dependencia._permiso = f"interno:{','.join(sorted(servicios))}"  # type: ignore[attr-defined]
    return Depends(_dependencia)
