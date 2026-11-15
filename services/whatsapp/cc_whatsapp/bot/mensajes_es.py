"""Textos del bot (español de México). Son propuesta de redacción: los validan RH y el área jurídica
(PQ-12). Ninguno lleva datos personales (design.md §7.4)."""

from __future__ import annotations

SIN_ACCESO = "Este número no tiene acceso al servicio."
NO_DISPONIBLE = "El servicio no está disponible por ahora."
DATOS_NO_COINCIDEN = "Los datos no coinciden. Envía de nuevo el código y tu dato de verificación."
BLOQUEADO = "Por seguridad, el acceso se bloqueó temporalmente. Contacta a RH."
CODIGO_VENCIDO = "El código venció. Te enviamos uno nuevo."
FORMATO_VERIFICACION = (
    "Envía en un solo mensaje el código de 6 dígitos y tu dato de verificación, "
    "separados por un espacio."
)
FALTA_INFORMACION = "Falta información en tu expediente. RH ya fue notificado."
PREPARANDO = "Estamos preparando tu constancia; te la enviaremos en un momento."
AYUDA = "Escribe *constancia* para solicitar tu constancia."
SIN_PLANTILLAS = "Por ahora no hay constancias disponibles. Contacta a RH."
SOLICITUD_EN_PROCESO = "Ya tienes una constancia en proceso. Te la enviaremos en un momento."
LIMITE_DIA = "Alcanzaste el límite de solicitudes de hoy. Intenta de nuevo mañana."
DEMASIADOS_MENSAJES = "Estás enviando demasiados mensajes. Espera un minuto e intenta de nuevo."
PLANTILLA_NO_DISPONIBLE = (
    "Esa constancia ya no está disponible. Escribe *constancia* para ver las opciones."
)
MENU_CUERPO = "Elige la constancia que necesitas."
MENU_BOTON = "Ver constancias"
VER_MAS = "Ver más"


def aviso_privacidad(url: str | None) -> str:
    base = "Antes de continuar, consulta el aviso de privacidad"
    return f"{base}: {url}" if url else f"{base} que te compartió tu empresa."


DESAFIOS = {
    "NSS_ULTIMOS4": "los últimos 4 dígitos de tu NSS",
    "FECHA_INGRESO_DDMM": "tu fecha de ingreso en formato día/mes (por ejemplo, 15/03)",
}


def codigo_y_desafio(codigo: str, tipo_desafio: str) -> str:
    dato = DESAFIOS.get(tipo_desafio, "tu dato de verificación")
    return (
        f"Tu código de verificación es {codigo} (vence en 10 minutos). "
        f"Respóndeme en un solo mensaje el código y {dato}."
    )
