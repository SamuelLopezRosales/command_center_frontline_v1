"""Variables derivadas: sueldo mensual, importe en letra y fechas en texto (design.md §5.2;
CC-REQ-078).

No se guardan como campos: se calculan al generar el PDF y su valor queda en el snapshot. Los
factores de conversión son una propuesta por confirmar con contabilidad o RH (PQ-18); si cambian,
solo cambia ``FACTORES`` y se sube ``FACTORES_VERSION``, que se guarda en el snapshot.

Toda la aritmética es exacta (``Fraction`` y enteros): sin flotantes y con redondeo "mitad hacia
arriba" a dos decimales.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction

FACTORES_VERSION = "1"
FACTORES: dict[str, Fraction] = {
    "SEMANAL": Fraction(52, 12),
    "CATORCENAL": Fraction(26, 12),
    "QUINCENAL": Fraction(2),
    "MENSUAL": Fraction(1),
}
ZONA_MX = timezone(timedelta(hours=-6))  # America/Mexico_City (México no usa horario de verano)
MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
SUELDO_MAXIMO = Decimal("999999999999.99")


class SueldoInvalido(ValueError):
    """El sueldo o la periodicidad no permiten calcular el importe."""


def a_decimal(texto: str) -> Decimal:
    """Convierte el texto del sueldo (``9500``, ``9,500.50``) a ``Decimal`` positivo."""
    try:
        valor = Decimal(str(texto).strip().replace(",", "").replace("$", ""))
    except InvalidOperation:
        raise SueldoInvalido("sueldo no numérico") from None
    if not valor.is_finite() or valor <= 0 or valor > SUELDO_MAXIMO:
        raise SueldoInvalido("sueldo fuera de rango")
    return valor


def sueldo_mensual(sueldo: Decimal, periodicidad: str) -> Decimal:
    """``sueldo × factor`` con dos decimales, redondeo mitad hacia arriba."""
    factor = FACTORES.get(periodicidad.strip().upper())
    if factor is None:
        raise SueldoInvalido("periodicidad desconocida")
    exacto = Fraction(sueldo) * factor * 100  # en centavos
    centavos = (2 * exacto.numerator + exacto.denominator) // (2 * exacto.denominator)
    return Decimal(centavos).scaleb(-2).quantize(Decimal("0.01"))


def formato_moneda(importe: Decimal) -> str:
    """``$9,500.00``."""
    return f"${importe:,.2f}"


# ------------------------------------------------------------------ importe en letra

_UNIDADES = (
    "CERO",
    "UNO",
    "DOS",
    "TRES",
    "CUATRO",
    "CINCO",
    "SEIS",
    "SIETE",
    "OCHO",
    "NUEVE",
    "DIEZ",
    "ONCE",
    "DOCE",
    "TRECE",
    "CATORCE",
    "QUINCE",
    "DIECISÉIS",
    "DIECISIETE",
    "DIECIOCHO",
    "DIECINUEVE",
    "VEINTE",
    "VEINTIUNO",
    "VEINTIDÓS",
    "VEINTITRÉS",
    "VEINTICUATRO",
    "VEINTICINCO",
    "VEINTISÉIS",
    "VEINTISIETE",
    "VEINTIOCHO",
    "VEINTINUEVE",
)
_DECENAS = (
    "",
    "",
    "",
    "TREINTA",
    "CUARENTA",
    "CINCUENTA",
    "SESENTA",
    "SETENTA",
    "OCHENTA",
    "NOVENTA",
)
_CENTENAS = (
    "",
    "CIENTO",
    "DOSCIENTOS",
    "TRESCIENTOS",
    "CUATROCIENTOS",
    "QUINIENTOS",
    "SEISCIENTOS",
    "SETECIENTOS",
    "OCHOCIENTOS",
    "NOVECIENTOS",
)


def _menor_de_mil(n: int, apocopado: bool) -> str:
    """Texto de 1 a 999. ``apocopado``: ``UN`` en lugar de ``UNO`` (delante de MIL y MILLONES)."""
    if n == 100:
        return "CIEN"
    centenas, resto = divmod(n, 100)
    partes = [_CENTENAS[centenas]] if centenas else []
    if resto:
        if resto < 30:
            palabra = _UNIDADES[resto]
            if apocopado and resto == 1:
                palabra = "UN"
            elif apocopado and resto == 21:
                palabra = "VEINTIÚN"
            partes.append(palabra)
        else:
            decenas, unidad = divmod(resto, 10)
            if unidad:
                palabra = _UNIDADES[unidad]
                if apocopado and unidad == 1:
                    palabra = "UN"
                partes.append(f"{_DECENAS[decenas]} Y {palabra}")
            else:
                partes.append(_DECENAS[decenas])
    return " ".join(partes)


def _sub_millon(n: int, apocopado: bool) -> str:
    """Texto de 1 a 999,999. ``apocopado`` solo afecta al último grupo (los miles siempre
    llevan ``UN``: ``VEINTIÚN MIL``)."""
    miles, unidades = divmod(n, 1000)
    partes: list[str] = []
    if miles:
        partes.append("MIL" if miles == 1 else f"{_menor_de_mil(miles, True)} MIL")
    if unidades:
        partes.append(_menor_de_mil(unidades, apocopado))
    return " ".join(partes)


def entero_en_letra(n: int, *, apocopar_final: bool = False) -> str:
    """Entero de 0 a 999,999,999,999 en palabras mayúsculas.

    El último grupo termina en ``UNO`` (``VEINTIUNO``); con ``apocopar_final`` termina en ``UN``
    (``VEINTIÚN``), que es lo que lleva delante de un sustantivo como ``PESOS``.
    """
    if n < 0 or n > 999_999_999_999:
        raise ValueError("fuera de rango")
    if n == 0:
        return "CERO"
    millones, resto = divmod(n, 1_000_000)
    partes: list[str] = []
    if millones:
        partes.append("UN MILLÓN" if millones == 1 else f"{_sub_millon(millones, True)} MILLONES")
    if resto:
        partes.append(_sub_millon(resto, apocopar_final))
    return " ".join(partes)


def importe_en_letra(importe: Decimal) -> str:
    """``NUEVE MIL QUINIENTOS PESOS 00/100 MN``.

    El sufijo de centavos y ``MN`` forman parte del valor: la plantilla no debe repetirlos
    (PQ-17 registra que las correcciones propuestas de la plantilla de consulado sí lo repiten).
    """
    if importe < 0:
        raise ValueError("importe negativo")
    total = int((importe * 100).to_integral_value(rounding="ROUND_HALF_UP"))
    pesos, centavos = divmod(total, 100)
    if pesos == 1:
        texto = "UN PESO"
    elif pesos and pesos % 1_000_000 == 0:
        texto = f"{entero_en_letra(pesos)} DE PESOS"  # UN MILLÓN DE PESOS
    else:
        texto = f"{entero_en_letra(pesos, apocopar_final=True)} PESOS"
    return f"{texto} {centavos:02d}/100 MN"


# ------------------------------------------------------------------ fechas


def fecha_en_texto(fecha: date) -> str:
    """``15 de marzo de 2021``, con los meses en español sin depender del locale del sistema."""
    return f"{fecha.day} de {MESES[fecha.month - 1]} de {fecha.year}"


def fecha_iso_en_texto(texto: str) -> str | None:
    """De ``AAAA-MM-DD`` a texto largo; ``None`` si no es una fecha."""
    try:
        return fecha_en_texto(date.fromisoformat(texto.strip()))
    except ValueError:
        return None


def hoy_en_mexico(ahora: datetime | None = None) -> date:
    """La fecha de emisión se calcula en la zona de México, no en UTC."""
    ahora = ahora or datetime.now(UTC)
    return ahora.astimezone(ZONA_MX).date()
