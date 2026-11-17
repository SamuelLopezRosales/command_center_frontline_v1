"""Cliente de la API de plantillas de Meta (design.md §3.6 NOT-11/13, §7.5; CC-REQ-117).

Solo maneja **plantillas** (``/{waba_id}/message_templates``); el envío de mensajes vive en
`whatsapp` y este servicio no importa ``cc_whatsapp``. Se copió el patrón de ``cc_whatsapp.meta``
(``httpx`` con transporte inyectable, errores clasificados por código) y la lógica de plantillas
es propia.

- Las credenciales (``access_token`` y ``waba_id``) se leen de Secrets Manager por su
  identificador (``CC_META_SECRETO_ID``) y se guardan 5 minutos; nunca de variables de entorno ni
  de los logs. ``CredencialesMeta`` oculta el token en su ``repr``.
- Un fallo de Meta (red, 4xx, 5xx, respuesta rara) se vuelve ``ErrorMeta`` y el servicio lo
  traduce a 502 ``ERROR_PROVEEDOR_META``. Solo se conserva el motivo y el código; el texto del
  error de Meta no se registra.
- El estado se devuelve tal como lo manda Meta (``PENDING``, ``APPROVED``, ``REJECTED``...); la
  traducción a los estados propios la hace ``servicios/plantillas.py``.
- Los códigos y la forma exacta de editar una plantilla rechazada se confirman al vincular la
  cuenta (PQ-07).
- ``listar`` (importar plantillas ya aprobadas) es solo lectura y pagina con el cursor
  ``paging.cursors.after``. **Nunca sigue la URL ``paging.next``**: Graph la arma con su propio
  servidor y a veces con el token dentro; el servidor al que se manda el token es solo
  ``CC_META_API_BASE``. Trae a lo más ``MAX_PLANTILLAS_LISTADO`` (500) plantillas por consulta; si
  hay más, el resultado va marcado como ``truncado``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


class ErrorMeta(Exception):  # noqa: N818
    def __init__(self, motivo: str, *, codigo: str | None = None, estado_http: int | None = None):
        super().__init__(motivo)
        self.motivo = motivo
        self.codigo = codigo
        self.estado_http = estado_http


@dataclass(frozen=True)
class CredencialesMeta:
    access_token: str = field(repr=False)
    waba_id: str
    api_version: str | None = None  # del secreto; si falta, manda ``CC_META_API_VERSION``


@dataclass(frozen=True)
class PlantillaMeta:
    id: str
    estado: str  # estado de Meta: PENDING, APPROVED, REJECTED...
    motivo_rechazo: str | None = None


# Tope de plantillas que trae un listado (5 páginas de 100). Una cuenta con más se marca truncada.
MAX_PLANTILLAS_LISTADO = 500
PAGINA_LISTADO = 100
CAMPOS_LISTADO = "id,name,language,category,status,components,parameter_format"


@dataclass(frozen=True)
class PlantillaListada:
    """Una plantilla tal como la devuelve Meta (sin interpretar): ``estado`` y ``categoria`` en
    mayúsculas; ``componentes`` es la lista cruda de Meta (solo se lee, nunca se registra)."""

    id: str
    nombre: str
    idioma: str
    categoria: str
    estado: str
    componentes: tuple[dict[str, Any], ...] = ()
    formato_parametros: str | None = None


@dataclass(frozen=True)
class ListadoMeta:
    items: tuple[PlantillaListada, ...]
    truncado: bool = False


class ClientePlantillasMeta(Protocol):
    async def crear(
        self, *, nombre: str, categoria: str, idioma: str, texto: str, ejemplos: list[str]
    ) -> PlantillaMeta: ...

    async def actualizar(self, id_meta: str, *, texto: str, ejemplos: list[str]) -> None: ...

    async def consultar(self, *, nombre: str, idioma: str) -> PlantillaMeta | None: ...

    async def listar(self, *, maximo: int = MAX_PLANTILLAS_LISTADO) -> ListadoMeta: ...

    async def obtener(self, *, nombre: str, idioma: str) -> PlantillaListada | None: ...


def _texto(valor: Any) -> str | None:
    return valor.strip() if isinstance(valor, str) and valor.strip() else None


def interpretar_plantilla(t: Any) -> PlantillaListada | None:
    """Una entrada de ``data`` de Meta como ``PlantillaListada``; ``None`` si no trae id, nombre o
    idioma (una respuesta rara no rompe el listado: esa entrada se descarta)."""
    if not isinstance(t, dict):
        return None
    crudo_id = t.get("id")
    id_ = str(crudo_id).strip() if isinstance(crudo_id, str | int) else ""
    nombre, idioma = _texto(t.get("name")), _texto(t.get("language"))
    if not id_ or not nombre or not idioma:
        return None
    componentes = t.get("components")
    return PlantillaListada(
        id=id_,
        nombre=nombre,
        idioma=idioma,
        categoria=str(t.get("category") or "").upper(),
        estado=str(t.get("status") or "").upper(),
        componentes=tuple(c for c in componentes if isinstance(c, dict))
        if isinstance(componentes, list)
        else (),
        formato_parametros=_texto(t.get("parameter_format")),
    )


def componente_cuerpo(texto: str, ejemplos: list[str]) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {"type": "BODY", "text": texto}
    if ejemplos:
        cuerpo["example"] = {"body_text": [list(ejemplos)]}
    return cuerpo


def _motivo(valor: Any) -> str | None:
    if not isinstance(valor, str) or not valor.strip() or valor.strip().upper() == "NONE":
        return None
    return valor.strip()[:500]


def _cuerpo_ejemplo(texto: str, *ejemplos: str) -> dict[str, Any]:
    c: dict[str, Any] = {"type": "BODY", "text": texto}
    if ejemplos:
        c["example"] = {"body_text": [list(ejemplos)]}
    return c


# Datos de ejemplo del sustituto sin red (solo local): una compatible y una por cada motivo típico.
PLANTILLAS_EJEMPLO_STUB: tuple[PlantillaListada, ...] = (
    PlantillaListada(
        "900000000000001",
        "bienvenida_colaborador",
        "es_MX",
        "UTILITY",
        "APPROVED",
        (
            _cuerpo_ejemplo(
                "Hola {{1}}, te damos la bienvenida a {{2}}. Tu primer día es el {{3}}.",
                "Ana",
                "Planta Apodaca",
                "lunes 17 de noviembre",
            ),
            {"type": "FOOTER", "text": "Recursos Humanos"},
        ),
        "POSITIONAL",
    ),
    PlantillaListada(
        "900000000000002",
        "bienvenida_con_boton",
        "es_MX",
        "UTILITY",
        "APPROVED",
        (
            _cuerpo_ejemplo("Bienvenido {{1}}. Conoce tu primer día.", "Ana"),
            {
                "type": "BUTTONS",
                "buttons": [{"type": "URL", "text": "Ver guía", "url": "https://x"}],
            },
        ),
        "POSITIONAL",
    ),
    PlantillaListada(
        "900000000000003",
        "bienvenida_con_imagen",
        "es_MX",
        "MARKETING",
        "APPROVED",
        (
            {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["h"]}},
            _cuerpo_ejemplo("Bienvenido a la familia."),
        ),
        "POSITIONAL",
    ),
    PlantillaListada(
        "900000000000004",
        "bienvenida_nombrada",
        "es_MX",
        "UTILITY",
        "APPROVED",
        (_cuerpo_ejemplo("Hola {{nombre}}, bienvenido."),),
        "NAMED",
    ),
    PlantillaListada(
        "900000000000005",
        "bienvenida_rechazada",
        "es_MX",
        "MARKETING",
        "REJECTED",
        (_cuerpo_ejemplo("Hola {{1}}, ¡bienvenido!", "Ana"),),
        "POSITIONAL",
    ),
    PlantillaListada(
        "900000000000006",
        "bienvenida_pausada",
        "es_MX",
        "UTILITY",
        "PAUSED",
        (_cuerpo_ejemplo("Hola {{1}}, ya eres parte del equipo.", "Ana"),),
        "POSITIONAL",
    ),
)


class MetaPlantillasHttp:
    def __init__(
        self,
        credenciales: Callable[[], Awaitable[CredencialesMeta]],
        *,
        base: str = "https://graph.facebook.com",
        version: str = "v21.0",
        timeout_s: float = 10.0,
        transporte: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._credenciales = credenciales
        self._base = base.rstrip("/")
        self._version = version
        self._http = httpx.AsyncClient(timeout=timeout_s, transport=transporte)

    def invalidar_cache(self) -> None:
        """Olvida las credenciales guardadas: la siguiente llamada vuelve a leer el secreto (se usa
        al guardar desde la pantalla de integraciones; otros procesos esperan a su vencimiento)."""
        invalidar = getattr(self._credenciales, "invalidar", None)
        if callable(invalidar):
            invalidar()

    async def _llamar(
        self, metodo: str, ruta: str, *, json_: Any = None, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        try:
            cred = await self._credenciales()
            version = cred.api_version or self._version
            r = await self._http.request(
                metodo,
                f"{self._base}/{version}/{ruta.format(waba=cred.waba_id)}",
                json=json_,
                params=params,
                headers={"Authorization": f"Bearer {cred.access_token}"},
            )
        except ErrorMeta:
            raise
        except httpx.HTTPError as exc:  # tiempo agotado, conexión
            raise ErrorMeta("META_TRANSITORIO") from exc
        except Exception as exc:  # secreto ilegible o incompleto
            raise ErrorMeta("META_SIN_CREDENCIALES") from exc
        try:
            datos = r.json()
        except ValueError:
            datos = {}
        if r.status_code != 200 or not isinstance(datos, dict):
            error = datos.get("error", {}) if isinstance(datos, dict) else {}
            codigo = str(error.get("code")) if error.get("code") is not None else None
            transitorio = r.status_code == 429 or r.status_code >= 500
            raise ErrorMeta(
                "META_TRANSITORIO" if transitorio else f"META_{codigo or r.status_code}",
                codigo=codigo,
                estado_http=r.status_code,
            )
        return datos

    async def crear(
        self, *, nombre: str, categoria: str, idioma: str, texto: str, ejemplos: list[str]
    ) -> PlantillaMeta:
        d = await self._llamar(
            "POST",
            "{waba}/message_templates",
            json_={
                "name": nombre,
                "language": idioma,
                "category": categoria,
                "components": [componente_cuerpo(texto, ejemplos)],
            },
        )
        if not d.get("id"):
            raise ErrorMeta("META_RESPUESTA_INVALIDA")
        return PlantillaMeta(str(d["id"]), str(d.get("status") or "PENDING").upper())

    async def actualizar(self, id_meta: str, *, texto: str, ejemplos: list[str]) -> None:
        d = await self._llamar(
            "POST", id_meta, json_={"components": [componente_cuerpo(texto, ejemplos)]}
        )
        if d.get("success") is False:
            raise ErrorMeta("META_RESPUESTA_INVALIDA")

    async def consultar(self, *, nombre: str, idioma: str) -> PlantillaMeta | None:
        d = await self._llamar(
            "GET",
            "{waba}/message_templates",
            params={
                "name": nombre,
                "language": idioma,
                "fields": "id,name,status,language,rejected_reason",
            },
        )
        for t in d.get("data") or []:
            if isinstance(t, dict) and t.get("name") == nombre and t.get("id"):
                return PlantillaMeta(
                    str(t["id"]),
                    str(t.get("status") or "PENDING").upper(),
                    _motivo(t.get("rejected_reason")),
                )
        return None

    async def listar(self, *, maximo: int = MAX_PLANTILLAS_LISTADO) -> ListadoMeta:
        """Lee todas las páginas de ``/{waba}/message_templates`` (solo lectura). Sigue
        ``paging.cursors.after`` mientras Meta diga que hay ``paging.next``; no usa esa URL."""
        items: list[PlantillaListada] = []
        vistos: set[str] = set()
        cursor: str | None = None
        for _ in range(maximo // PAGINA_LISTADO + 2):  # tope de páginas: nunca un ciclo infinito
            params = {"fields": CAMPOS_LISTADO, "limit": str(PAGINA_LISTADO)}
            if cursor:
                params["after"] = cursor
            d = await self._llamar("GET", "{waba}/message_templates", params=params)
            if not isinstance(d.get("data"), list):  # no es un listado: no se toma por "vacío"
                raise ErrorMeta("META_RESPUESTA_INVALIDA")
            for crudo in d["data"]:
                t = interpretar_plantilla(crudo)
                if t is not None and t.id not in vistos:
                    vistos.add(t.id)
                    items.append(t)
            paging = d.get("paging")
            paging = paging if isinstance(paging, dict) else {}
            cursores = paging.get("cursors")
            siguiente = _texto(cursores.get("after")) if isinstance(cursores, dict) else None
            hay_mas = bool(paging.get("next")) and siguiente is not None and siguiente != cursor
            if len(items) > maximo:
                return ListadoMeta(tuple(items[:maximo]), truncado=True)
            if not hay_mas:
                return ListadoMeta(tuple(items))
            cursor = siguiente
        return ListadoMeta(tuple(items[:maximo]), truncado=True)

    async def obtener(self, *, nombre: str, idioma: str) -> PlantillaListada | None:
        """Una plantilla por nombre e idioma exactos (solo lectura)."""
        d = await self._llamar(
            "GET",
            "{waba}/message_templates",
            params={
                "name": nombre,
                "language": idioma,
                "fields": CAMPOS_LISTADO,
                "limit": str(PAGINA_LISTADO),
            },
        )
        if not isinstance(d.get("data"), list):
            raise ErrorMeta("META_RESPUESTA_INVALIDA")
        for crudo in d["data"]:
            t = interpretar_plantilla(crudo)
            if t is not None and t.nombre == nombre and t.idioma == idioma:
                return t
        return None


class StubPlantillasMeta:
    """Sustituto sin red (pruebas y local sin cuenta): acepta todo y deja las plantillas en
    ``PENDING``; sirve ``estado`` para simular la consulta de sincronización."""

    def __init__(self) -> None:
        self.creadas: list[dict[str, Any]] = []
        self.actualizadas: list[str] = []
        self.estados: dict[str, PlantillaMeta] = {}
        self.error: ErrorMeta | None = None
        # Lo que "tiene" Meta para el listado (importar plantillas aprobadas): datos de ejemplo
        # coherentes para ver la pantalla en local; las pruebas lo reemplazan.
        self.catalogo: list[PlantillaListada] = list(PLANTILLAS_EJEMPLO_STUB)
        self.listados = 0

    async def crear(
        self, *, nombre: str, categoria: str, idioma: str, texto: str, ejemplos: list[str]
    ) -> PlantillaMeta:
        if self.error:
            raise self.error
        self.creadas.append({"nombre": nombre, "categoria": categoria, "idioma": idioma})
        p = PlantillaMeta(f"STUB-{len(self.creadas)}", "PENDING")
        self.estados[nombre] = p
        return p

    async def actualizar(self, id_meta: str, *, texto: str, ejemplos: list[str]) -> None:
        if self.error:
            raise self.error
        self.actualizadas.append(id_meta)

    async def consultar(self, *, nombre: str, idioma: str) -> PlantillaMeta | None:
        if self.error:
            raise self.error
        return self.estados.get(nombre)

    async def listar(self, *, maximo: int = MAX_PLANTILLAS_LISTADO) -> ListadoMeta:
        if self.error:
            raise self.error
        self.listados += 1
        return ListadoMeta(tuple(self.catalogo[:maximo]), truncado=len(self.catalogo) > maximo)

    async def obtener(self, *, nombre: str, idioma: str) -> PlantillaListada | None:
        if self.error:
            raise self.error
        return next((t for t in self.catalogo if t.nombre == nombre and t.idioma == idioma), None)


def cargador_credenciales(
    secreto_id: str | None, region: str, *, cliente: Any | None = None, ttl_s: float = 300.0
) -> Callable[[], Awaitable[CredencialesMeta]]:
    """Lee ``cc/{env}/meta`` (JSON con ``access_token`` y ``waba_id``; ``api_version`` opcional) y
    lo guarda ``ttl_s`` (5 minutos). Un valor vacío o ausente es "sin credenciales". La función
    devuelta tiene ``invalidar()`` para olvidar lo guardado."""
    estado: dict[str, Any] = {"cred": None, "hasta": 0.0}

    async def leer() -> CredencialesMeta:
        if estado["cred"] is None or time.monotonic() > estado["hasta"]:
            if not secreto_id:
                raise ErrorMeta("META_SIN_CREDENCIALES")
            import asyncio

            from cc_common.recursos import leer_secreto

            crudo = await asyncio.to_thread(leer_secreto, secreto_id, region, cliente)
            try:
                datos = json.loads(crudo)
            except ValueError:
                datos = None
            if not isinstance(datos, dict):
                raise ErrorMeta("META_SIN_CREDENCIALES")
            token, waba = datos.get("access_token"), datos.get("waba_id")
            if not (isinstance(token, str) and token and isinstance(waba, str) and waba):
                raise ErrorMeta("META_SIN_CREDENCIALES")
            version = datos.get("api_version")
            estado["cred"] = CredencialesMeta(
                token, waba, version if isinstance(version, str) and version else None
            )
            estado["hasta"] = time.monotonic() + ttl_s
        return estado["cred"]

    def invalidar() -> None:
        estado["cred"] = None
        estado["hasta"] = 0.0

    leer.invalidar = invalidar  # type: ignore[attr-defined]
    return leer
