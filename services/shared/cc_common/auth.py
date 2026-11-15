"""Autenticación con tokens de acceso de Cognito y autorización por permisos (design.md §11).

El autorizador JWT de API Gateway valida el token en el borde; FastAPI lo vuelve a validar
aquí (doble validación, §11.1): firma, emisor, ``client_id``, expiración, ``token_use`` y la
presencia de ``empresa_id`` y ``rol`` (los agrega el trigger ``cognito-pre-token``).

Cada ruta declara su permiso con ``requiere_permiso`` o se marca explícitamente como pública
con ``ruta_publica``; ``rutas_sin_permiso`` permite probar que ninguna ruta quede sin declarar.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any

import jwt

from cc_common.errores import ErrorNoAutenticado, ErrorProhibido
from cc_common.permisos import Permiso, tiene_permiso

RUTAS_EXENTAS = frozenset({"/salud", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})


@dataclass(frozen=True)
class UsuarioActual:
    sub: str
    empresa_id: int
    rol: str
    jti: str | None = None
    usuario_id: int | None = None  # claim de cognito-pre-token (design.md §11.1)


class VerificadorToken:
    """Valida tokens de acceso de un grupo de usuarios de Cognito.

    ``resolver_llave`` recibe el token y devuelve la llave pública; en producción es
    ``jwt.PyJWKClient(f"{emisor}/.well-known/jwks.json")`` (con caché).
    """

    def __init__(
        self,
        emisor: str,
        client_id: str,
        resolver_llave: Callable[[str], Any] | None = None,
        tolerancia_s: int = 30,
    ) -> None:
        self._emisor = emisor.rstrip("/")
        self._client_id = client_id
        self._tolerancia = tolerancia_s
        if resolver_llave is None:
            cliente = jwt.PyJWKClient(f"{self._emisor}/.well-known/jwks.json", cache_keys=True)
            resolver_llave = lambda t: cliente.get_signing_key_from_jwt(t).key  # noqa: E731
        self._resolver = resolver_llave

    def verificar(self, token: str) -> UsuarioActual:
        try:
            llave = self._resolver(token)
            claims = jwt.decode(
                token,
                llave,
                algorithms=["RS256"],
                issuer=self._emisor,
                leeway=self._tolerancia,
                options={"require": ["exp", "iat", "iss", "sub", "token_use"], "verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise ErrorNoAutenticado() from exc
        if claims.get("token_use") != "access" or claims.get("client_id") != self._client_id:
            raise ErrorNoAutenticado()
        try:
            empresa_id = int(claims["empresa_id"])
            rol = str(claims["rol"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ErrorNoAutenticado() from exc
        crudo_usuario = claims.get("usuario_id")
        try:
            usuario_id = int(crudo_usuario) if crudo_usuario is not None else None
        except (TypeError, ValueError) as exc:
            raise ErrorNoAutenticado() from exc
        if usuario_id is not None and usuario_id <= 0:
            raise ErrorNoAutenticado()
        return UsuarioActual(
            sub=str(claims["sub"]),
            empresa_id=empresa_id,
            rol=rol,
            jti=claims.get("jti"),
            usuario_id=usuario_id,
        )


def requerir_usuario_id(usuario: UsuarioActual) -> int:
    """El id numérico del usuario RH, para la bitácora y llaves foráneas (claim ``usuario_id``).

    Lo agrega ``cognito-pre-token``. Un token sin el claim (emitido antes del cambio) obliga a
    iniciar sesión de nuevo.
    """
    if usuario.usuario_id is None:
        raise ErrorNoAutenticado()
    return usuario.usuario_id


def extraer_bearer(autorizacion: str | None) -> str:
    if not autorizacion or not autorizacion.lower().startswith("bearer "):
        raise ErrorNoAutenticado()
    return autorizacion.split(" ", 1)[1].strip()


def requiere_permiso(permiso: Permiso, obtener_usuario: Callable[..., UsuarioActual]):
    """Dependencia de FastAPI: exige un usuario autenticado con el permiso indicado."""
    from fastapi import Depends

    def _dependencia(usuario: UsuarioActual = Depends(obtener_usuario)) -> UsuarioActual:  # noqa: B008
        if not tiene_permiso(usuario.rol, permiso):
            raise ErrorProhibido()
        return usuario

    _dependencia._permiso = permiso  # type: ignore[attr-defined]
    return Depends(_dependencia)


def ruta_publica():
    """Marca explícita de ruta sin autenticación de usuario (por ejemplo, verificación por QR)."""
    from fastapi import Depends

    def _publica() -> None:
        return None

    _publica._publica = True  # type: ignore[attr-defined]
    return Depends(_publica)


def _marcas(dependencias: Iterable[Any]) -> bool:
    for dep in dependencias:
        llamada = getattr(dep, "call", None)
        if getattr(llamada, "_permiso", None) is not None or getattr(llamada, "_publica", False):
            return True
        if _marcas(getattr(dep, "dependencies", [])):
            return True
    return False


def _aplanar(rutas: Iterable[Any], prefijo: str = "") -> Iterator[tuple[str, Any]]:
    """Recorre las rutas incluso dentro de routers incluidos.

    FastAPI reciente (0.16x) no copia las rutas de ``include_router`` a ``app.routes``: las deja
    agrupadas en un objeto con ``original_router`` y el prefijo en ``include_context``. Sin este
    recorrido, ``rutas_sin_permiso`` no vería ninguna ruta de los servicios.
    """
    for ruta in rutas:
        original = getattr(ruta, "original_router", None)
        if original is not None:
            contexto = getattr(ruta, "include_context", None)
            hijo = prefijo + (getattr(contexto, "prefix", "") or "")
            yield from _aplanar(original.routes, hijo)
        else:
            yield prefijo + getattr(ruta, "path", ""), ruta


def rutas_sin_permiso(app: Any) -> list[str]:
    """Rutas de la app que no declaran permiso ni se marcan como públicas."""
    faltantes = []
    for camino, ruta in _aplanar(app.routes):
        dependiente = getattr(ruta, "dependant", None)
        if dependiente is None or camino in RUTAS_EXENTAS:
            continue
        if not _marcas(dependiente.dependencies):
            metodos = ",".join(sorted(getattr(ruta, "methods", []) or []))
            faltantes.append(f"{metodos} {camino}")
    return faltantes
