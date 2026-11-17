"""Conexión con Meta (WhatsApp Cloud API): ``/api/v1/integraciones/meta``.

Es **una sola cuenta de Meta para toda la instalación**. Las credenciales viven en el secreto
``cc/{env}/meta`` de Secrets Manager (no en la base de datos). Todas las rutas exigen
``integraciones:administrar``.

Seguridad:
- Ninguna respuesta devuelve un valor secreto. El ``GET`` solo trae los últimos 4 caracteres del
  token de acceso y del App Secret (y ni eso si el valor mide menos de 12 caracteres) y si hay
  un token de verificación. El token de verificación recién generado se devuelve **una sola vez**,
  en la respuesta de ``verify-token:generar``.
- El servidor de la Graph API (``meta_api_base``, ``CC_META_API_BASE``) **no es editable** desde
  esta API ni desde la pantalla: es configuración del despliegue. Permitir cambiarlo enviaría el
  token de acceso a cualquier servidor. La versión de la API (``api_version``) sí es editable.
- Los errores de validación indican el campo y el formato esperado, nunca el valor recibido.
- Los cambios se reflejan en los demás componentes (webhook, enviador, plantillas) en 5 minutos como
  máximo, lo que dura su caché de credenciales.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from cc_common.auth import UsuarioActual, requiere_permiso
from cc_common.permisos import Permiso
from fastapi import APIRouter, Depends, Request, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from cc_notificaciones import integracion_meta as im
from cc_notificaciones.dependencias import almacen_meta, motor, usuario_actual
from cc_notificaciones.servicios import integraciones as servicio

router = APIRouter(prefix="/integraciones/meta", tags=["integraciones"])

Administrar = Permiso.INTEGRACIONES_ADMINISTRAR

_FORMATOS = {
    "waba_id": (im.RE_ID_META, "Debe tener solo dígitos (de 8 a 25)."),
    "phone_number_id": (im.RE_ID_META, "Debe tener solo dígitos (de 8 a 25)."),
    "api_version": (
        im.RE_VERSION,
        "Use el formato v21.0 (la letra v, un número, un punto y otro).",
    ),
    "access_token": (
        im.RE_ACCESS_TOKEN,
        "Debe tener de 20 a 1000 caracteres, sin espacios ni saltos de línea.",
    ),
    "app_secret": (im.RE_APP_SECRET, "Debe tener 32 caracteres hexadecimales."),
    "verify_token": (
        im.RE_VERIFY_TOKEN,
        "Debe tener de 16 a 128 caracteres: letras, números, guion y guion bajo.",
    ),
}


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ActualizarMeta(_Base):
    """Solo cambia lo enviado: un campo omitido no se toca. Cadena vacía o ``null`` es 422."""

    waba_id: str | None = Field(default=None, description="ID de la cuenta de WhatsApp Business.")
    phone_number_id: str | None = Field(
        default=None, description="Phone number ID (no es el número de teléfono)."
    )
    api_version: str | None = Field(default=None, description="Versión de la Graph API, v21.0.")
    access_token: str | None = Field(default=None, description="Token de acceso permanente.")
    app_secret: str | None = Field(default=None, description="App Secret de la app de Meta.")
    verify_token: str | None = Field(
        default=None, description="Token de verificación del webhook (lo puede generar el sistema)."
    )

    @field_validator(
        "waba_id", "phone_number_id", "api_version", "access_token", "app_secret", "verify_token"
    )
    @classmethod
    def _formato(cls, v: str | None, info: ValidationInfo) -> str:
        # Los mensajes son fijos: nunca incluyen el valor recibido (CC-REQ-162).
        if not v:
            raise ValueError("No puede ir vacío.")
        patron, mensaje = _FORMATOS[str(info.field_name)]
        if not patron.match(v):
            raise ValueError(mensaje)
        return v

    @model_validator(mode="after")
    def _al_menos_uno(self) -> ActualizarMeta:
        if not self.model_fields_set:
            raise ValueError("Envíe al menos un campo para cambiar.")
        return self

    def cambios(self) -> dict[str, str]:
        return {c: getattr(self, c) for c in self.model_fields_set}


class SecretoDto(BaseModel):
    configurado: bool
    ultimos4: str | None = Field(
        description="Últimos 4 caracteres; nulo si no hay valor o mide menos de 12 caracteres."
    )


class VerifyTokenDto(BaseModel):
    configurado: bool


class EstadoMetaDto(BaseModel):
    configurada: bool = Field(description="Verdadero si están guardados los cinco datos.")
    waba_id: str | None
    phone_number_id: str | None
    api_version: str
    access_token: SecretoDto
    app_secret: SecretoDto
    verify_token: VerifyTokenDto
    actualizado_en: datetime | None
    actualizado_por_usuario_id: int | None


class TokenGeneradoDto(BaseModel):
    verify_token: str = Field(description="Se devuelve solo en esta respuesta; el GET no lo trae.")


class ResultadoPruebaDto(BaseModel):
    clave: Literal["token", "numero", "waba", "webhook"]
    ok: bool
    detalle: str


class NumeroDto(BaseModel):
    nombre_verificado: str | None
    numero_mostrado: str | None
    calidad: str | None


class PruebaMetaDto(BaseModel):
    ok: bool = Field(description="Token, número y WABA válidos. El webhook se informa aparte.")
    resultados: list[ResultadoPruebaDto]
    numero: NumeroDto | None
    webhook_suscrito: bool | None


def _sin_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _invalidar(request: Request):
    def invalidar() -> None:
        cliente = getattr(request.app.state, "meta", None)
        invalidar_cache = getattr(cliente, "invalidar_cache", None)
        if callable(invalidar_cache):
            invalidar_cache()

    return invalidar


def _version(request: Request) -> str:
    return request.app.state.config.meta_api_version


@router.get(
    "",
    response_model=EstadoMetaDto,
    summary="Estado de la conexión con Meta (sin valores secretos)",
)
async def estado(
    request: Request,
    response: Response,
    _u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    almacen=Depends(almacen_meta),
) -> dict[str, Any]:
    _sin_cache(response)
    return await servicio.obtener(almacen, _version(request))


@router.put(
    "",
    response_model=EstadoMetaDto,
    summary="Guardar credenciales de Meta (solo cambia lo enviado)",
)
async def guardar(
    entrada: ActualizarMeta,
    request: Request,
    response: Response,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
    almacen=Depends(almacen_meta),
) -> dict[str, Any]:
    _sin_cache(response)
    return await servicio.guardar(
        m,
        almacen,
        u,
        entrada.cambios(),
        version_defecto=_version(request),
        ahora=request.app.state.reloj(),
        al_guardar=_invalidar(request),
    )


@router.post(
    "/verify-token:generar",
    response_model=TokenGeneradoDto,
    summary="Generar y guardar un token de verificación nuevo (se devuelve una sola vez)",
)
async def generar_token(
    request: Request,
    response: Response,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
    almacen=Depends(almacen_meta),
) -> TokenGeneradoDto:
    _sin_cache(response)
    token = await servicio.generar_token_verificacion(
        m,
        almacen,
        u,
        version_defecto=_version(request),
        ahora=request.app.state.reloj(),
        al_guardar=_invalidar(request),
    )
    return TokenGeneradoDto(verify_token=token)


@router.post(
    "/probar",
    response_model=PruebaMetaDto,
    summary="Probar la conexión con la Graph API usando lo guardado",
    responses={422: {"description": "META_NO_CONFIGURADA: faltan credenciales guardadas."}},
)
async def probar(
    request: Request,
    response: Response,
    u: UsuarioActual = requiere_permiso(Administrar, usuario_actual),
    m=Depends(motor),
    almacen=Depends(almacen_meta),
) -> PruebaMetaDto:
    _sin_cache(response)
    cfg = request.app.state.config
    r = await servicio.probar(
        m,
        almacen,
        u,
        base=cfg.meta_api_base,
        version_defecto=cfg.meta_api_version,
        timeout_s=cfg.meta_sonda_timeout_s,
        transporte=getattr(request.app.state, "transporte_sonda_meta", None),
    )
    return PruebaMetaDto(
        ok=r.ok,
        resultados=[
            ResultadoPruebaDto(clave=x.clave, ok=x.ok, detalle=x.detalle) for x in r.resultados
        ],
        numero=NumeroDto(**r.numero) if r.numero else None,
        webhook_suscrito=r.webhook_suscrito,
    )
