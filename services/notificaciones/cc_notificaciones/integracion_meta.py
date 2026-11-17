"""Credenciales de Meta (WhatsApp Cloud API) guardadas en Secrets Manager (integraciones/Meta).

El secreto ``cc/{env}/meta`` es **un solo JSON para toda la instalación** (una cuenta de Meta, una
empresa) y lo leen varios componentes con las claves de siempre::

    {"app_secret", "verify_token", "access_token", "waba_id", "phone_number_id"}

A esas se agregan tres claves **opcionales** que los demás lectores ignoran (leen por clave, no
iteran): ``api_version`` (versión de la Graph API; si falta, manda ``CC_META_API_VERSION``),
``actualizado_en`` (ISO 8601 UTC) y ``actualizado_por_usuario_id``. Nada de esto va a la base de
datos, a los logs ni a las respuestas: la API solo expone los últimos 4 caracteres de los dos
secretos largos (y ni eso si miden menos de 12) y si hay un ``verify_token``.

- Un valor inicial que no es JSON, no es un objeto o trae solo cadenas vacías (el valor que crea
  ``CcSecurity`` y que se ha cargado a mano) equivale a "no configurada"; al guardar se reemplaza
  con un JSON válido. Al guardar se reescribe **solo con las claves conocidas** (las claves
  heredadas del valor inicial, ``token`` y ``graph_version``, y ``_marcador`` se descartan).
- ``meta_api_base`` (el servidor al que se envía el token) **no** vive aquí ni es editable por la
  API: es configuración del despliegue (``CC_META_API_BASE``). Permitir cambiarlo mandaría el
  access token a cualquier servidor.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from cc_common.errores import ErrorProveedor

log = logging.getLogger("cc.notificaciones.integracion_meta")

# Formatos (se validan en el cuerpo del PUT; los mensajes nunca repiten el valor recibido).
RE_ID_META = re.compile(r"^[0-9]{8,25}\Z")
RE_VERSION = re.compile(r"^v[0-9]{1,2}\.[0-9]{1,2}\Z")
RE_ACCESS_TOKEN = re.compile(r"^[\x21-\x7e]{20,1000}\Z")  # ASCII imprimible, sin espacios
RE_APP_SECRET = re.compile(r"^[0-9a-fA-F]{32}\Z")  # el App Secret de Meta mide 32 hex
RE_VERIFY_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,128}\Z")

CLAVES_SECRETO = (
    "waba_id",
    "phone_number_id",
    "api_version",
    "access_token",
    "app_secret",
    "verify_token",
)
CLAVES_OBLIGATORIAS = ("waba_id", "phone_number_id", "access_token", "app_secret", "verify_token")
MINIMO_PARA_ENMASCARAR = 12


def ultimos4(valor: str | None) -> str | None:
    """Los últimos 4 caracteres, o ``None`` si el valor mide menos de 12 (no se revela nada)."""
    if not valor or len(valor) < MINIMO_PARA_ENMASCARAR:
        return None
    return valor[-4:]


class AlmacenMeta(Protocol):
    """Lectura y escritura del JSON del secreto (síncrono; el servicio lo corre en un hilo)."""

    def leer(self) -> dict[str, Any]: ...

    def escribir(self, datos: dict[str, Any]) -> None: ...


def interpretar(crudo: str | bytes | None) -> dict[str, Any]:
    """JSON del secreto como diccionario; cualquier otra cosa (vacío, texto, lista) es ``{}``."""
    if not crudo:
        return {}
    try:
        datos = json.loads(crudo)
    except (ValueError, TypeError):
        return {}
    return datos if isinstance(datos, dict) else {}


@dataclass(frozen=True)
class MetaGuardada:
    """Lo guardado, ya normalizado: solo cadenas no vacías. Los secretos no salen en ``repr``."""

    waba_id: str | None = None
    phone_number_id: str | None = None
    api_version: str | None = None
    access_token: str | None = field(default=None, repr=False)
    app_secret: str | None = field(default=None, repr=False)
    verify_token: str | None = field(default=None, repr=False)
    actualizado_en: datetime | None = None
    actualizado_por_usuario_id: int | None = None

    @property
    def configurada(self) -> bool:
        return all(getattr(self, c) for c in CLAVES_OBLIGATORIAS)

    @classmethod
    def de_json(cls, datos: dict[str, Any]) -> MetaGuardada:
        def cadena(clave: str) -> str | None:
            v = datos.get(clave)
            return v if isinstance(v, str) and v.strip() else None

        en = None
        if isinstance(datos.get("actualizado_en"), str):
            try:
                en = datetime.fromisoformat(datos["actualizado_en"])
            except ValueError:
                en = None
        quien = datos.get("actualizado_por_usuario_id")
        return cls(
            waba_id=cadena("waba_id"),
            phone_number_id=cadena("phone_number_id"),
            api_version=cadena("api_version"),
            access_token=cadena("access_token"),
            app_secret=cadena("app_secret"),
            verify_token=cadena("verify_token"),
            actualizado_en=en,
            actualizado_por_usuario_id=quien if isinstance(quien, int) else None,
        )


def mezclar(
    actual: dict[str, Any],
    cambios: dict[str, str],
    *,
    usuario_id: int,
    ahora: datetime,
) -> tuple[dict[str, Any], list[str]]:
    """JSON nuevo (solo claves conocidas) y los nombres de los campos que de verdad cambiaron.

    Si nada cambia devuelve el JSON actual normalizado sin tocar los metadatos de actualización.
    """
    previo = MetaGuardada.de_json(actual)
    cambiados = [k for k, v in cambios.items() if getattr(previo, k) != v]
    nuevo: dict[str, Any] = {
        k: getattr(previo, k) for k in CLAVES_SECRETO if getattr(previo, k) is not None
    }
    if previo.actualizado_en is not None:
        nuevo["actualizado_en"] = previo.actualizado_en.isoformat()
    if previo.actualizado_por_usuario_id is not None:
        nuevo["actualizado_por_usuario_id"] = previo.actualizado_por_usuario_id
    if not cambiados:
        return nuevo, []
    for k in cambiados:
        nuevo[k] = cambios[k]
    nuevo["actualizado_en"] = ahora.isoformat()
    nuevo["actualizado_por_usuario_id"] = usuario_id
    return nuevo, cambiados


class AlmacenSecretsManager:
    """El secreto ``cc/{env}/meta`` en Secrets Manager (``GetSecretValue``/``PutSecretValue``)."""

    def __init__(
        self,
        secreto_id: str,
        region: str,
        *,
        endpoint: str | None = None,
        cliente: Any | None = None,
    ) -> None:
        self._id = secreto_id
        self._region = region
        self._endpoint = endpoint
        self._cliente = cliente

    def _cli(self) -> Any:
        if self._cliente is None:  # pragma: no cover - requiere AWS
            import boto3

            self._cliente = boto3.client(
                "secretsmanager", region_name=self._region, endpoint_url=self._endpoint or None
            )
        return self._cliente

    def leer(self) -> dict[str, Any]:
        try:
            r = self._cli().get_secret_value(SecretId=self._id)
        except Exception as exc:
            # Solo el tipo de error: el mensaje del SDK podría traer el identificador del secreto.
            log.error("no se pudo leer el secreto de Meta (%s)", type(exc).__name__)
            raise ErrorProveedor(
                "ALMACEN_CREDENCIALES_NO_DISPONIBLE",
                "No se pudo acceder al almacén de credenciales.",
            ) from None
        return interpretar(r.get("SecretString"))

    def escribir(self, datos: dict[str, Any]) -> None:
        try:
            self._cli().put_secret_value(
                SecretId=self._id,
                SecretString=json.dumps(datos, sort_keys=True, ensure_ascii=True),
            )
        except Exception as exc:
            log.error("no se pudo escribir el secreto de Meta (%s)", type(exc).__name__)
            raise ErrorProveedor(
                "ALMACEN_CREDENCIALES_NO_DISPONIBLE",
                "No se pudo acceder al almacén de credenciales.",
            ) from None


class AlmacenMemoria:
    """Sustituto sin red (solo local o pruebas): el JSON vive en el proceso."""

    def __init__(self, inicial: dict[str, Any] | None = None) -> None:
        self.datos: dict[str, Any] = dict(inicial or {})
        self.escrituras = 0

    def leer(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.datos))

    def escribir(self, datos: dict[str, Any]) -> None:
        self.datos = json.loads(json.dumps(datos))
        self.escrituras += 1
