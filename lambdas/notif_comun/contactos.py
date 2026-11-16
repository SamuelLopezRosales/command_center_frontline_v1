"""Cliente síncrono de INT-COL-05 (``contactos:resolver``) para las Lambdas de notificaciones.

Interfaz inyectable (``ResolverContactos``): el despachador y el respaldo por correo no dependen de
HTTP. ``StubContactos`` sirve a las pruebas; ``ContactosHttp`` llama a `colaboradores`.

**Contrato esperado** de ``contactos:resolver`` (ampliado en T-217, parte B)::

    POST /internal/colaboradores/contactos:resolver     (cabeceras: token interno, X-Empresa-Id)
    {"ids": [..hasta 500..], "proposito": "NOTIFICACION" | "CORREO",
     "variables": ["nombre_completo", ...]}
    -> {"items": [{"id": 12, "elegible": true, "motivo": null,
                   "celular": "...", "correo": "...",
                   "valores": {"nombre_completo": "..."}}]}

* ``variables`` son los ``campo`` de las variables de plantilla con origen ``COLABORADOR``; solo se
  devuelven variables **no sensibles**.
* ``celular`` solo con propósito de WhatsApp y ``correo`` solo con ``CORREO``; ambos solo a un
  elegible (ACTIVO y con consentimiento vigente, CC-REQ-157). Un no elegible trae ``motivo``
  (``SIN_CORREO``, ``ESTATUS_BAJA``, ``SIN_CONSENTIMIENTO``...).
* El resultado de este cliente es ``{colaborador_id: item}``; un id ausente se trata como
  ``NO_ENCONTRADO``. **Nunca** se registran celulares, correos ni valores (CC-REQ-162).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

LOTE_MAXIMO = 500


class ContactosNoDisponible(Exception):  # noqa: N818
    """`colaboradores` no respondió o rechazó la petición: el mensaje se reintenta."""


class ResolverContactos(Protocol):
    def resolver(
        self,
        empresa_id: int,
        ids: Sequence[int],
        proposito: str,
        variables: Sequence[str] = (),
    ) -> dict[int, dict[str, Any]]: ...


class StubContactos:
    """``datos[id] = {"elegible", "motivo", "celular", "correo", "valores"}``; los que no están se
    devuelven como no elegibles ``NO_ENCONTRADO`` (o con ``por_defecto(id)``, para pruebas con
    muchos ids). Solo entrega los ``valores`` pedidos y registra las llamadas (sin datos
    personales)."""

    def __init__(self, datos: dict[int, dict[str, Any]] | None = None, *, por_defecto=None) -> None:
        self.datos = datos or {}
        self.por_defecto = por_defecto
        self.llamadas: list[tuple[int, int, str, tuple[str, ...]]] = []
        self.error: Exception | None = None

    def resolver(self, empresa_id, ids, proposito, variables=()):
        if self.error:
            raise self.error
        self.llamadas.append((empresa_id, len(ids), proposito, tuple(variables)))
        pedidas = set(variables)
        salida: dict[int, dict[str, Any]] = {}
        for i in ids:
            if i in self.datos:
                item = self.datos[i]
            elif self.por_defecto is not None:
                item = self.por_defecto(i)
            else:
                item = {"elegible": False, "motivo": "NO_ENCONTRADO"}
            valores = {k: v for k, v in item.get("valores", {}).items() if k in pedidas}
            salida[i] = {"id": i, **item, "valores": valores}
        return salida


class ContactosHttp:
    def __init__(
        self,
        base_url: str,
        secreto: Callable[[], str],
        *,
        servicio: str = "notificaciones",
        cliente: Any | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        import httpx

        self._url = base_url.rstrip("/") + "/internal/colaboradores/contactos:resolver"
        self._secreto = secreto
        self._servicio = servicio
        self._http = cliente or httpx.Client(timeout=timeout_s)

    def resolver(self, empresa_id, ids, proposito, variables=()):
        import httpx
        from cc_common.internal_client import emitir_token_interno

        salida: dict[int, dict[str, Any]] = {}
        unicos = list(dict.fromkeys(ids))
        for i in range(0, len(unicos), LOTE_MAXIMO):
            lote = unicos[i : i + LOTE_MAXIMO]
            cuerpo: dict[str, Any] = {"ids": lote, "proposito": proposito}
            if variables:
                cuerpo["variables"] = list(variables)
            try:
                r = self._http.post(
                    self._url,
                    json=cuerpo,
                    headers={
                        "Authorization": "Bearer "
                        + emitir_token_interno(self._secreto(), self._servicio),
                        "X-Empresa-Id": str(empresa_id),
                    },
                )
            except httpx.HTTPError as exc:
                raise ContactosNoDisponible from exc
            if r.status_code != 200:
                raise ContactosNoDisponible(f"HTTP {r.status_code}")
            for item in r.json()["items"]:
                salida[int(item["id"])] = item
        for i in unicos:
            salida.setdefault(i, {"id": i, "elegible": False, "motivo": "NO_ENCONTRADO"})
        return salida
