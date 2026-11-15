"""Contenidos de las tres plantillas de referencia del cliente (``plantillas_constancias/*.docx``),
ya con las variables corregidas de ``05_plantillas_constancias.md`` §3, y datos de prueba válidos.

Texto fiel al documento original. Una diferencia deliberada: en la de consulado el importe va como
``{{sueldo_mensual}} ({{sueldo_letra}})`` sin repetir ``00/100 MN``, porque ``sueldo_letra`` ya
trae ese sufijo (design.md §5.2, PQ-17).

Mini-marcado de ``p``: ``{{variable}}`` es una variable y ``**texto**`` va en negrita.
"""

import re

_TOKEN = re.compile(r"(\*\*|\{\{[a-z_.]+\}\})")
_VARIABLE = re.compile(r"\{\{([a-z_.]+)\}\}")


def nodos(texto: str) -> list[dict]:
    negrita = False
    salida: list[dict] = []
    for parte in _TOKEN.split(texto):
        if not parte:
            continue
        if parte == "**":
            negrita = not negrita
            continue
        m = _VARIABLE.fullmatch(parte)
        nodo = {"var": m.group(1)} if m else {"texto": parte}
        if negrita:
            nodo["negrita"] = True
        salida.append(nodo)
    return salida


def p(texto: str = "", alin: str = "izquierda") -> dict:
    return {"tipo": "parrafo", "alineacion": alin, "contenido": nodos(texto)}


def _firma() -> list[dict]:
    return [
        p("**ATENTAMENTE**"),
        p(),
        p(),
        p("**{{organizacion.nombre_firmante}}**"),
        p("**{{organizacion.cargo_firmante}}**"),
        p("**{{organizacion.correo_firmante}}**"),
        p(),
        p("c.c.p. Expediente del Colaborador."),
    ]


def _documento(bloques: list[dict], tamano: str = "CARTA") -> dict:
    return {"esquema": 1, "pagina": {"tamano": tamano}, "bloques": bloques}


LABORAL = _documento(
    [
        {"tipo": "logotipo", "alineacion": "izquierda"},
        p("{{lugar}}, {{fecha_emision}}.", "derecha"),
        p(),
        p("A quien corresponda:"),
        p(),
        p(
            "Por medio de la presente, {{organizacion.razon_social}} hace constar que "
            "**{{nombre_completo}}**, con RFC {{rfc}} y Número de Seguridad Social {{nss}}, "
            "forma parte de nuestra Organización desde el **{{fecha_ingreso}}**, desempeñando el "
            "puesto de **{{puesto}}**, adscrito al área de {{area}} con un Sueldo mensual bruto "
            "(antes de impuestos) de {{sueldo_mensual}} ({{sueldo_letra}}).",
            "justificado",
        ),
        p(),
        p("• Registro Patronal: {{registro_patronal}}"),
        p("• RFC Empresa: {{organizacion.rfc}}"),
        p(),
        p("Se extiende la presente constancia, para los fines que estime convenientes."),
        p(),
        *_firma(),
    ]
)

GUARDERIA = _documento(
    [
        {"tipo": "logotipo", "alineacion": "izquierda"},
        p("{{lugar}}, {{fecha_emision}}.", "derecha"),
        p(),
        p("A quien corresponda:"),
        p(),
        p(
            "Por medio de la presente, informo que {{nombre_completo}} presta sus servicios para "
            "{{organizacion.razon_social}} con Registro Patronal {{registro_patronal}} en el que "
            "está inscrito el Colaborador y domicilio en {{organizacion.domicilio_fiscal}}, en un "
            "horario de {{horario}} de lunes a viernes, contando con días de descanso y festivos "
            "marcados por la ley federal de trabajo y disfrutando el periodo vacacional que indica "
            "la misma ley.",
            "justificado",
        ),
        p(),
        p(
            "Sin más por el momento se extiende la presente para los fines que el interesado "
            "considere.",
            "justificado",
        ),
        p(),
        *_firma(),
    ]
)

CONSULADO = _documento(
    [
        {"tipo": "logotipo", "alineacion": "izquierda"},
        p("{{lugar}}, {{fecha_emision}}.", "derecha"),
        p(),
        p("A quien corresponda:"),
        p(),
        p(
            "Por medio de la presente, informo que **{{nombre_completo}}** con CURP {{curp}} y "
            "RFC {{rfc}} labora actualmente en {{organizacion.razon_social}} con Registro "
            "Patronal {{registro_patronal}} y domicilio en {{organizacion.domicilio_fiscal}}, "
            "desde el {{fecha_ingreso}} desempeñando el puesto de {{puesto}}, dentro del área de "
            "{{area}}.",
            "justificado",
        ),
        p(),
        p(
            "Percibiendo un **Ingreso mensual bruto** (antes de impuestos) de {{sueldo_mensual}} "
            "({{sueldo_letra}}).",
        ),
        p(),
        p(
            "Sin más por el momento se extiende la presente para los fines que el interesado "
            "considere conveniente.",
            "justificado",
        ),
        p(),
        *_firma(),
    ]
)

REFERENCIAS = {"laboral": LABORAL, "guarderia": GUARDERIA, "consulado": CONSULADO}

# Valores con formatos válidos (CC-REQ-063): RFC de 13, CURP de 18, registro patronal de 11, NSS de 11.
COLABORADOR = {
    "nombre_completo": "María Fernanda Ramírez Ortiz",
    "puesto": "Operadora de producción",
    "fecha_ingreso": "2021-03-15",
    "area": "Producción",
    "horario": "9:00 am a 07:00 pm",
    "rfc": "RAOM900101AB1",
    "curp": "RAOM900101MNLMRR05",
    "nss": "12345678901",
    "sueldo": "9500",
    "periodicidad_sueldo": "QUINCENAL",
    "registro_patronal": "A0000000000",
    "lugar": "Monterrey",
    "organizacion.razon_social": "Empresa Ejemplo, S.A. de C.V.",
    "organizacion.rfc": "EEJ010101AAA",
    "organizacion.domicilio_fiscal": "Av. Ejemplo 100, Col. Centro, Monterrey, N.L., C.P. 64000",
    "organizacion.nombre_firmante": "Lic. Nombre Apellido",
    "organizacion.cargo_firmante": "Gerente de Recursos Humanos",
    "organizacion.correo_firmante": "rh@ejemplo.com",
}
