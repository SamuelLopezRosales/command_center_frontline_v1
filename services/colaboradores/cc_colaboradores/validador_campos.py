"""Validación de los campos dinámicos contra sus definiciones (design.md §10.1, §10.2).

Reglas por tipo: ``TEXTO`` hasta 500 caracteres, ``NUMERO`` decimal, ``FECHA``, ``LISTA`` con una
opción activa y ``SI_NO``. ``obligatorio`` y ``formato_validacion`` (coincidencia completa con
``re2``, de tiempo lineal, para evitar ReDoS). Sueldo y periodicidad van juntos (§10.3).

Los mensajes de error nunca incluyen el valor recibido (CC-REQ-162).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import re2
from cc_common.errores import ErrorCampo

from cc_colaboradores.campos_cliente import DefinicionCampo

TEXTO_MAXIMO = 500
NUMERO_MAXIMO = Decimal("99999999999999.9999")  # numeric(18, 4)
VERDADEROS = {"si", "sí", "s", "true", "1", "verdadero"}
FALSOS = {"no", "n", "false", "0", "falso"}


@dataclass(frozen=True)
class ValorValidado:
    """Un valor listo para guardarse en ``valor_campo``; ``None`` en ``valor`` lo borra."""

    campo_id: int
    codigo_interno: str
    tipo_dato: str
    es_sensible: bool
    valor: str | Decimal | date | int | bool | None  # opción: id de ``opcion_campo``


class ValidadorCampos:
    def __init__(self, definiciones: list[DefinicionCampo]) -> None:
        self._por_codigo = {d.codigo_interno: d for d in definiciones}
        self._por_clave = {d.clave: d for d in definiciones}

    @property
    def definiciones(self) -> list[DefinicionCampo]:
        return list(self._por_codigo.values())

    def validar(
        self, valores: dict[str, Any], *, parcial: bool = False
    ) -> tuple[list[ValorValidado], list[ErrorCampo]]:
        """Valida ``{codigo_interno: valor}``. Con ``parcial`` no exige los obligatorios
        ausentes (edición). Devuelve los valores normalizados y la lista de errores."""
        resultado: list[ValorValidado] = []
        errores: list[ErrorCampo] = []
        for codigo, crudo in valores.items():
            d = self._por_codigo.get(codigo)
            ruta = f"campos.{codigo}"
            if d is None:
                errores.append(ErrorCampo(ruta, "CAMPO_DESCONOCIDO", "El campo no existe."))
                continue
            if not d.activo:
                errores.append(ErrorCampo(ruta, "CAMPO_INACTIVO", "El campo está inactivo."))
                continue
            if _vacio(crudo):
                if d.obligatorio:
                    errores.append(ErrorCampo(ruta, "REQUERIDO", "El campo es obligatorio."))
                else:
                    resultado.append(_valor(d, None))
                continue
            normalizado, error = _normalizar(d, crudo)
            if error:
                errores.append(ErrorCampo(ruta, *error))
                continue
            resultado.append(_valor(d, normalizado))
        if not parcial:
            for d in self._por_codigo.values():
                if d.activo and d.obligatorio and d.codigo_interno not in valores:
                    errores.append(
                        ErrorCampo(
                            f"campos.{d.codigo_interno}", "REQUERIDO", "El campo es obligatorio."
                        )
                    )
        errores += self._reglas_cruzadas(resultado, valores, parcial)
        return resultado, errores

    def _reglas_cruzadas(
        self, resultado: list[ValorValidado], valores: dict[str, Any], parcial: bool
    ) -> list[ErrorCampo]:
        sueldo, periodo = self._por_clave.get("sueldo"), self._por_clave.get("periodicidad_sueldo")
        if not (sueldo and periodo and sueldo.activo and periodo.activo):
            return []
        # Se juzga por lo enviado: un sueldo mal escrito ya tiene su propio error de formato.
        enviados = {c for c, v in valores.items() if not _vacio(v)}
        tocados = {sueldo.codigo_interno, periodo.codigo_interno} & set(valores)
        if parcial and not tocados:
            return []
        if (sueldo.codigo_interno in enviados) != (periodo.codigo_interno in enviados):
            return [
                ErrorCampo(
                    f"campos.{sueldo.codigo_interno}",
                    "SUELDO_SIN_PERIODICIDAD",
                    "Sueldo y periodicidad deben ir juntos.",
                )
            ]
        return []


def _valor(d: DefinicionCampo, v: Any) -> ValorValidado:
    return ValorValidado(d.id, d.codigo_interno, d.tipo_dato, d.es_sensible, v)


def _vacio(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _normalizar(d: DefinicionCampo, crudo: Any) -> tuple[Any, tuple[str, str] | None]:
    tipo = d.tipo_dato
    if tipo == "TEXTO":
        if not isinstance(crudo, str | int):
            return None, ("FORMATO_INVALIDO", "Debe ser texto.")
        texto = str(crudo).strip()
        if len(texto) > TEXTO_MAXIMO:
            return None, ("DEMASIADO_LARGO", "El valor es demasiado largo.")
        if d.formato_validacion and not _coincide(d.formato_validacion, texto):
            return None, ("FORMATO_INVALIDO", "Formato inválido.")
        return texto, None
    if tipo == "NUMERO":
        if isinstance(crudo, bool):
            return None, ("FORMATO_INVALIDO", "Debe ser un número.")
        try:
            numero = Decimal(str(crudo).strip().replace(",", ""))
        except InvalidOperation:
            return None, ("FORMATO_INVALIDO", "Debe ser un número.")
        if not numero.is_finite() or abs(numero) > NUMERO_MAXIMO:
            return None, ("FORMATO_INVALIDO", "Debe ser un número.")
        if d.formato_validacion and not _coincide(d.formato_validacion, str(numero)):
            return None, ("FORMATO_INVALIDO", "Formato inválido.")
        return numero.quantize(Decimal("0.0001")), None
    if tipo == "FECHA":
        fecha = _fecha(crudo)
        if fecha is None:
            return None, ("FECHA_INVALIDA", "Fecha inválida.")
        return fecha, None
    if tipo == "LISTA":
        valor = str(crudo).strip()
        for o in d.opciones:
            if o.activo and o.valor == valor:
                return o.id, None
        return None, ("VALOR_LISTA_INVALIDO", "Opción no válida.")
    if tipo == "SI_NO":
        if isinstance(crudo, bool):
            return crudo, None
        texto = str(crudo).strip().lower()
        if texto in VERDADEROS:
            return True, None
        if texto in FALSOS:
            return False, None
        return None, ("VALOR_NO_PERMITIDO", "Debe ser sí o no.")
    return None, ("TIPO_NO_SOPORTADO", "Tipo de campo no soportado.")


def _coincide(patron: str, texto: str) -> bool:
    try:
        return re2.compile(patron).fullmatch(texto) is not None
    except Exception:  # noqa: BLE001 - un patrón inválido se trata como no coincidente
        return False


def _fecha(crudo: Any) -> date | None:
    if isinstance(crudo, datetime):
        return crudo.date()
    if isinstance(crudo, date):
        return crudo
    texto = str(crudo).strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).date()  # noqa: DTZ007 - solo fecha
        except ValueError:
            continue
    return None
