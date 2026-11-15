"""Validación de las filas de la carga masiva (design.md §10.3; CC-REQ-036, 042).

La fila se valida entera y devuelve todos sus errores. Los mensajes no incluyen valores ni datos
personales (CC-REQ-040, 162): solo el nombre de la columna. Reglas que Excel no revisa y esta sí:
apellido materno y tipo de empleado obligatorios, fila con datos pero sin número de empleado,
formatos, estatus y repetidos dentro del archivo.

Una celda vacía de un campo dinámico opcional no se envía al validador, de modo que no borra el
valor existente (DS-18).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from cc_colaboradores.campos_cliente import DefinicionCampo
from cc_colaboradores.excel.lector import FilaCruda
from cc_colaboradores.excel.modelo import (
    CLAVES_FIJAS,
    ESTATUS,
    POR_CLAVE_FIJA,
    TIPOS_EMPLEADO,
    normalizar,
)
from cc_colaboradores.repos.colaborador import DatosFijos
from cc_colaboradores.validador_campos import ValidadorCampos, ValorValidado

_CELULAR = re.compile(r"^\d{10}$")
MAX_NUMERO_EMPLEADO = 30
MAX_NOMBRE = 100
MAX_PUESTO = 150
FECHA_MINIMA = date(1900, 1, 1)

# Códigos de fila (§10.3) y su mensaje; ``{c}`` es el nombre de la columna.
MENSAJES = {
    "FALTA_OBLIGATORIO": "Falta: {c}.",
    "NUMERO_EMPLEADO_VACIO": "La fila no tiene número de empleado.",
    "NUMERO_REPETIDO_EN_ARCHIVO": "Número de empleado repetido en el archivo (fila {c}).",
    "CELULAR_INVALIDO": "El celular debe tener 10 dígitos.",
    "CELULAR_REPETIDO": "El celular ya está asignado a otro colaborador.",
    "ORGANIZACION_NO_EXISTE": "La organización no existe.",
    "PLANTA_NO_EXISTE": "La planta no existe.",
    "ESTATUS_INVALIDO": "Valor no permitido en {c}.",
    "TIPO_EMPLEADO_INVALIDO": "Valor no permitido en {c}.",
    "FECHA_INVALIDA": "Fecha inválida en {c}.",
    "FORMATO_INVALIDO": "Formato inválido en {c}.",
    "SUELDO_SIN_PERIODICIDAD": "Sueldo y periodicidad deben ir juntos.",
    "VALOR_LISTA_INVALIDO": "Opción no válida en {c}.",
}


@dataclass(frozen=True)
class ErrorFila:
    codigo: str
    mensaje: str


def error(codigo: str, columna: str = "") -> ErrorFila:
    return ErrorFila(codigo, MENSAJES[codigo].format(c=columna))


@dataclass(frozen=True)
class FilaValida:
    numero_fila: int
    datos: DatosFijos
    estatus: str  # ACTIVO o BAJA
    valores: list[ValorValidado]


@dataclass(frozen=True)
class Referencias:
    """Organizaciones y plantas activas de la empresa, por clave o nombre normalizados."""

    organizaciones: dict[str, int]
    plantas: dict[str, int]


def _texto(v: Any) -> str | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, str | int):
        return str(v).strip()
    return None


def _fecha(v: Any) -> date | None:
    f: date | None = None
    if isinstance(v, datetime):
        f = v.date()
    elif isinstance(v, date):
        f = v
    elif isinstance(v, str):
        for formato in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                f = datetime.strptime(v.strip(), formato).date()  # noqa: DTZ007
                break
            except ValueError:
                continue
    return f if f is not None and f >= FECHA_MINIMA else None


class ValidadorCarga:
    """Valida filas en orden: recuerda los números y celulares ya vistos en el archivo."""

    def __init__(
        self,
        definiciones: list[DefinicionCampo],
        referencias: Referencias,
        columnas: list[str],
    ) -> None:
        self._ref = referencias
        por_codigo = {d.codigo_interno.upper(): d for d in definiciones if d.activo}
        por_clave = {d.clave.lower(): d for d in definiciones if d.activo}
        self._dinamicas: dict[str, DefinicionCampo] = {}
        for columna in columnas:
            if columna in CLAVES_FIJAS:
                continue
            d = por_codigo.get(columna.upper()) or por_clave.get(columna.lower())
            if d is not None:
                self._dinamicas[columna] = d
        self._validador = ValidadorCampos(list(self._dinamicas.values()))
        self._por_codigo = {d.codigo_interno: d for d in self._dinamicas.values()}
        self._numeros: dict[str, int] = {}
        self._celulares: dict[str, int] = {}

    def validar(self, fila: FilaCruda) -> FilaValida | list[ErrorFila]:
        v = fila.valores
        errores: list[ErrorFila] = []
        faltan: list[str] = []

        # número de empleado
        numero = _texto(v.get("numero_empleado"))
        if not numero:
            errores.append(error("NUMERO_EMPLEADO_VACIO"))
            numero = None
        else:
            numero = numero.upper()
            if len(numero) > MAX_NUMERO_EMPLEADO:
                errores.append(
                    error("FORMATO_INVALIDO", POR_CLAVE_FIJA["numero_empleado"].etiqueta)
                )
            anterior = self._numeros.setdefault(numero, fila.numero_fila)
            if anterior != fila.numero_fila:
                errores.append(error("NUMERO_REPETIDO_EN_ARCHIVO", str(anterior)))

        # textos fijos
        textos: dict[str, str] = {}
        for clave, maximo in (
            ("nombres", MAX_NOMBRE),
            ("apellido_paterno", MAX_NOMBRE),
            ("apellido_materno", MAX_NOMBRE),
            ("puesto", MAX_PUESTO),
        ):
            t = _texto(v.get(clave))
            if not t:
                faltan.append(POR_CLAVE_FIJA[clave].etiqueta)
            elif len(t) > maximo:
                errores.append(error("FORMATO_INVALIDO", POR_CLAVE_FIJA[clave].etiqueta))
            else:
                textos[clave] = t

        # celular
        celular: str | None = None
        crudo = v.get("celular_whatsapp")
        if crudo is None:
            faltan.append(POR_CLAVE_FIJA["celular_whatsapp"].etiqueta)
        else:
            limpio = re.sub(r"[\s-]", "", _texto(crudo) or "")
            if _CELULAR.match(limpio):
                celular = limpio
                anterior = self._celulares.setdefault(celular, fila.numero_fila)
                if anterior != fila.numero_fila and numero is not None:
                    errores.append(error("CELULAR_REPETIDO"))
            else:
                errores.append(error("CELULAR_INVALIDO"))

        # organización y planta
        org_id = planta_id = None
        crudo = _texto(v.get("organizacion"))
        if not crudo:
            faltan.append(POR_CLAVE_FIJA["organizacion"].etiqueta)
        else:
            org_id = self._ref.organizaciones.get(normalizar(crudo))
            if org_id is None:
                errores.append(error("ORGANIZACION_NO_EXISTE"))
        crudo = _texto(v.get("planta"))
        if not crudo:
            faltan.append(POR_CLAVE_FIJA["planta"].etiqueta)
        else:
            planta_id = self._ref.plantas.get(normalizar(crudo))
            if planta_id is None:
                errores.append(error("PLANTA_NO_EXISTE"))

        # fecha de ingreso
        ingreso = None
        if v.get("fecha_ingreso") is None:
            faltan.append(POR_CLAVE_FIJA["fecha_ingreso"].etiqueta)
        else:
            ingreso = _fecha(v["fecha_ingreso"])
            if ingreso is None:
                errores.append(error("FECHA_INVALIDA", POR_CLAVE_FIJA["fecha_ingreso"].etiqueta))

        # tipo de empleado y estatus
        tipo = estatus = None
        crudo = _texto(v.get("tipo_empleado"))
        if not crudo:
            faltan.append(POR_CLAVE_FIJA["tipo_empleado"].etiqueta)
        else:
            tipo = TIPOS_EMPLEADO.get(normalizar(crudo))
            if tipo is None:
                errores.append(
                    error("TIPO_EMPLEADO_INVALIDO", POR_CLAVE_FIJA["tipo_empleado"].etiqueta)
                )
        crudo = _texto(v.get("estatus"))
        if not crudo:
            faltan.append(POR_CLAVE_FIJA["estatus"].etiqueta)
        else:
            estatus = ESTATUS.get(normalizar(crudo))
            if estatus is None:
                errores.append(error("ESTATUS_INVALIDO", POR_CLAVE_FIJA["estatus"].etiqueta))

        # campos dinámicos
        valores, errores_dinamicos = self._dinamicos(v)
        for e in errores_dinamicos:
            if e.codigo == "FALTA_OBLIGATORIO":
                faltan.append(e.mensaje)
            elif e not in errores:
                errores.append(e)

        if faltan:
            errores.insert(0, error("FALTA_OBLIGATORIO", ", ".join(faltan)))
        if errores:
            return errores
        assert numero and celular and org_id and planta_id and ingreso and tipo and estatus
        datos = DatosFijos(
            numero_empleado=numero,
            nombres=textos["nombres"],
            apellido_paterno=textos["apellido_paterno"],
            apellido_materno=textos["apellido_materno"],
            celular=celular,
            organizacion_id=org_id,
            planta_id=planta_id,
            fecha_ingreso=ingreso,
            puesto=textos["puesto"],
            tipo_empleado=tipo,
        )
        return FilaValida(fila.numero_fila, datos, estatus, valores)

    def _dinamicos(self, v: dict[str, Any]) -> tuple[list[ValorValidado], list[ErrorFila]]:
        enviados: dict[str, Any] = {}
        for columna, d in self._dinamicas.items():
            if columna not in v:
                continue
            valor = v[columna]
            if d.tipo_dato == "LISTA":
                valor = self._opcion(d, valor)
            enviados[d.codigo_interno] = valor
        valores, errs = self._validador.validar(enviados)
        salida: list[ErrorFila] = []
        for e in errs:
            codigo = e.campo.removeprefix("campos.")
            d = self._por_codigo.get(codigo)
            nombre = d.nombre_campo if d else "campo"
            if e.codigo == "REQUERIDO":
                salida.append(ErrorFila("FALTA_OBLIGATORIO", nombre))
            elif e.codigo in ("FECHA_INVALIDA", "VALOR_LISTA_INVALIDO", "SUELDO_SIN_PERIODICIDAD"):
                salida.append(error(e.codigo, nombre))
            else:
                salida.append(error("FORMATO_INVALIDO", nombre))
        return valores, salida

    @staticmethod
    def _opcion(d: DefinicionCampo, valor: Any) -> Any:
        """Acepta la etiqueta o el valor de la opción, sin distinguir mayúsculas ni acentos."""
        buscado = normalizar(valor)
        for o in d.opciones:
            if o.activo and buscado in (normalizar(o.etiqueta), normalizar(o.valor)):
                return o.valor
        return valor
