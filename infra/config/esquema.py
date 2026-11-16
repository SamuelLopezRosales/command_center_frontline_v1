"""Carga y validación de la configuración de ambientes.

La lista de cuentas permitidas vive en ``ambientes.json`` y no en el código de los stacks
(tasks.md, sección 0.2, regla 4). Este módulo solo usa la biblioteca estándar.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RUTA_POR_DEFECTO = Path(__file__).with_name("ambientes.json")
PERFIL_TEST = "cc-test"
ETIQUETAS_OBLIGATORIAS = ("proyecto", "ambiente", "responsable")
_CUENTA = re.compile(r"^\d{12}$")
_REGION = re.compile(r"^[a-z]{2}-[a-z]+-\d$")
_DOMINIO = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Patrones de llaves de acceso de AWS: el archivo de configuración nunca debe contenerlos.
_LLAVE_AWS = re.compile(r"(?:AKIA|ASIA|AIDA|AROA)[0-9A-Z]{16}")
_CLAVES_PROHIBIDAS = ("aws_access_key_id", "aws_secret_access_key", "access_key", "secret_key")


class ConfiguracionInvalida(ValueError):
    """La configuración de ambientes no cumple el esquema."""


@dataclass(frozen=True)
class Alerta:
    tipo: str
    umbral_pct: int


@dataclass(frozen=True)
class Presupuesto:
    monto_usd: float
    correo: str
    alertas: tuple[Alerta, ...]


@dataclass(frozen=True)
class Economia:
    nat: str
    rds_clase: str
    rds_multi_az: bool
    rds_proxy: bool
    waf_habilitado: bool
    workers_min_tareas: int
    tareas_por_servicio: int
    concurrencia_aprovisionada_webhook: int
    retencion_respaldos_dias: int
    permite_borrado: bool
    # Falso en cuentas nuevas con cuota de Lambda de 10: sin reservas no se exige dejar 100 libres.
    reservar_concurrencia: bool = True
    # MFA de Cognito: ON (obligatorio, CC-REQ-002), OPTIONAL u OFF. Solo ON es válido en prod.
    mfa: str = "ON"
    # Registro de usuarios: INVITACION (código de invitación, CC-REQ-008) o ABIERTO (sin código;
    # solo correos de ``registro_dominios``, todos con el rol RH de la única empresa).
    registro: str = "INVITACION"
    registro_dominios: tuple[str, ...] = ()


@dataclass(frozen=True)
class Ambiente:
    nombre: str
    cuentas_permitidas: tuple[str, ...]
    region: str
    perfil: str
    etiquetas: dict[str, str]
    presupuesto: Presupuesto
    economia: Economia
    dominio: str | None


def _requerir(datos: dict[str, Any], campo: str, ctx: str) -> Any:
    if campo not in datos or datos[campo] in (None, "", [], {}):
        if campo == "dominio":
            return None
        raise ConfiguracionInvalida(f"{ctx}: falta '{campo}'")
    return datos[campo]


def _validar_sin_llaves(texto: str) -> None:
    if _LLAVE_AWS.search(texto):
        raise ConfiguracionInvalida("el archivo contiene una llave de acceso de AWS")
    bajo = texto.lower()
    for clave in _CLAVES_PROHIBIDAS:
        if clave in bajo:
            raise ConfiguracionInvalida(f"el archivo contiene la clave prohibida '{clave}'")


def _construir_ambiente(nombre: str, datos: dict[str, Any], proyecto: str) -> Ambiente:
    ctx = f"ambiente '{nombre}'"
    cuentas = _requerir(datos, "cuentas_permitidas", ctx)
    if not isinstance(cuentas, list) or not all(
        isinstance(c, str) and _CUENTA.match(c) for c in cuentas
    ):
        raise ConfiguracionInvalida(f"{ctx}: las cuentas deben ser cadenas de 12 dígitos")
    region = _requerir(datos, "region", ctx)
    if not _REGION.match(region):
        raise ConfiguracionInvalida(f"{ctx}: región inválida '{region}'")
    perfil = _requerir(datos, "perfil", ctx)
    if nombre == "test" and perfil != PERFIL_TEST:
        raise ConfiguracionInvalida(f"{ctx}: el perfil debe ser '{PERFIL_TEST}', no '{perfil}'")
    etiquetas = _requerir(datos, "etiquetas", ctx)
    for et in ETIQUETAS_OBLIGATORIAS:
        if not etiquetas.get(et):
            raise ConfiguracionInvalida(f"{ctx}: falta la etiqueta '{et}'")
    if etiquetas["proyecto"] != proyecto:
        raise ConfiguracionInvalida(f"{ctx}: la etiqueta 'proyecto' debe ser '{proyecto}'")
    if etiquetas["ambiente"] != nombre:
        raise ConfiguracionInvalida(f"{ctx}: la etiqueta 'ambiente' debe ser '{nombre}'")

    pre = _requerir(datos, "presupuesto", ctx)
    if not isinstance(pre.get("monto_usd"), int | float) or pre["monto_usd"] <= 0:
        raise ConfiguracionInvalida(f"{ctx}: el presupuesto debe ser mayor que cero")
    if not _CORREO.match(str(pre.get("correo", ""))):
        raise ConfiguracionInvalida(f"{ctx}: correo de presupuesto inválido")
    alertas = tuple(Alerta(a["tipo"], int(a["umbral_pct"])) for a in pre.get("alertas", []))
    if not alertas:
        raise ConfiguracionInvalida(f"{ctx}: el presupuesto necesita alertas")
    for a in alertas:
        if a.tipo not in ("ACTUAL", "PRONOSTICADO") or not 0 < a.umbral_pct <= 200:
            raise ConfiguracionInvalida(f"{ctx}: alerta inválida {a}")

    eco = _requerir(datos, "economia", ctx)
    economia = Economia(
        nat=eco["nat"],
        rds_clase=eco["rds_clase"],
        rds_multi_az=bool(eco["rds_multi_az"]),
        rds_proxy=bool(eco["rds_proxy"]),
        waf_habilitado=bool(eco["waf_habilitado"]),
        workers_min_tareas=int(eco["workers_min_tareas"]),
        tareas_por_servicio=int(eco["tareas_por_servicio"]),
        concurrencia_aprovisionada_webhook=int(eco["concurrencia_aprovisionada_webhook"]),
        retencion_respaldos_dias=int(eco["retencion_respaldos_dias"]),
        permite_borrado=bool(eco["permite_borrado"]),
        reservar_concurrencia=bool(eco.get("reservar_concurrencia", True)),
        mfa=str(eco.get("mfa", "ON")),
        registro=str(eco.get("registro", "INVITACION")),
        registro_dominios=tuple(str(d).strip().lower() for d in eco.get("registro_dominios", [])),
    )
    if economia.mfa not in ("ON", "OPTIONAL", "OFF"):
        raise ConfiguracionInvalida(f"{ctx}: 'mfa' debe ser ON, OPTIONAL u OFF")
    if not economia.permite_borrado and economia.mfa != "ON":
        raise ConfiguracionInvalida(
            f"{ctx}: un ambiente tipo prod exige MFA obligatorio (CC-REQ-002)"
        )
    if economia.registro not in ("INVITACION", "ABIERTO"):
        raise ConfiguracionInvalida(f"{ctx}: 'registro' debe ser INVITACION o ABIERTO")
    if economia.registro == "ABIERTO":
        if not economia.permite_borrado:
            raise ConfiguracionInvalida(
                f"{ctx}: un ambiente tipo prod exige registro por invitación (CC-REQ-008)"
            )
        if not economia.registro_dominios or not all(
            _DOMINIO.match(d) for d in economia.registro_dominios
        ):
            raise ConfiguracionInvalida(
                f"{ctx}: el registro abierto exige registro_dominios con dominios válidos"
            )
    if economia.nat not in ("instancia", "gateway"):
        raise ConfiguracionInvalida(f"{ctx}: 'nat' debe ser 'instancia' o 'gateway'")
    return Ambiente(
        nombre=nombre,
        cuentas_permitidas=tuple(cuentas),
        region=region,
        perfil=perfil,
        etiquetas=dict(etiquetas),
        presupuesto=Presupuesto(float(pre["monto_usd"]), pre["correo"], alertas),
        economia=economia,
        dominio=datos.get("dominio"),
    )


def parsear(texto: str) -> dict[str, Ambiente]:
    """Valida el texto JSON y devuelve los ambientes por nombre."""
    _validar_sin_llaves(texto)
    try:
        crudo = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise ConfiguracionInvalida(f"JSON inválido: {exc.msg}") from exc
    proyecto = crudo.get("proyecto")
    ambientes = crudo.get("ambientes")
    if not proyecto or not isinstance(ambientes, dict) or not ambientes:
        raise ConfiguracionInvalida("faltan 'proyecto' o 'ambientes'")
    return {nombre: _construir_ambiente(nombre, d, proyecto) for nombre, d in ambientes.items()}


def cargar(ruta: Path | None = None) -> dict[str, Ambiente]:
    ruta = ruta or RUTA_POR_DEFECTO
    return parsear(ruta.read_text(encoding="utf-8"))


def obtener_ambiente(nombre: str, ruta: Path | None = None) -> Ambiente:
    ambientes = cargar(ruta)
    if nombre not in ambientes:
        raise ConfiguracionInvalida(f"ambiente desconocido '{nombre}'")
    return ambientes[nombre]
