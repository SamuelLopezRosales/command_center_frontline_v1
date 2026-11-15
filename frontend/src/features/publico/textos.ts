// Cadenas de las páginas públicas (CC-NFR-012).
export const t = {
  marca: "Command Center",
  cargando: "Cargando…",
  verificacion: {
    titulo: "Verificación de constancia",
    nombre: "Nombre",
    folio: "Folio",
    fecha: "Fecha de emisión",
    estado: "Estado",
    vigente: "Vigente",
    cancelada: "Cancelada",
    noEncontrada: "No encontramos una constancia con este código.",
    noEncontradaAyuda: "Revisa que hayas escaneado el código completo.",
    error: "No pudimos verificar la constancia en este momento. Intenta de nuevo más tarde.",
  },
  descarga: {
    titulo: "Tu constancia está lista",
    ayuda: "Este enlace sirve una sola vez. Toca el botón para descargarla.",
    boton: "Descargar constancia",
    invalidoTitulo: "Enlace no válido",
    invalido: "El enlace ya se usó o venció. Solicita la constancia de nuevo.",
    error: "No pudimos revisar el enlace en este momento. Intenta de nuevo más tarde.",
  },
} as const;
