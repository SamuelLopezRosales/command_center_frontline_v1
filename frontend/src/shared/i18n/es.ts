// Todas las cadenas de la SPA están en español (CC-NFR-012).
export const es = {
  marca: "Command Center",
  nav: { dashboard: "Dashboard", colaboradores: "Colaboradores", constancias: "Constancias", notificaciones: "Notificaciones" },
  comun: {
    cargando: "Cargando…",
    guardar: "Guardar",
    cancelar: "Cancelar",
    reintentar: "Reintentar",
    cerrarSesion: "Cerrar sesión",
    errorGeneral: "No se pudo completar la operación. Intenta de nuevo.",
    sinDatos: "Aún no hay datos para mostrar.",
    pendienteDeDiseno: "Pantalla pendiente de validación visual (PQ-09).",
  },
  auth: {
    subtitulo: "Inicia sesión para continuar",
    correo: "Usuario o correo",
    correoEjemplo: "ejemplo@empresa.com",
    contrasena: "Contraseña", // pragma: allowlist secret
    iniciar: "Iniciar sesión",
    olvido: "¿Olvidaste tu contraseña?",
    credencialesInvalidas: "Correo o contraseña incorrectos.",
    codigoTotp: "Código de verificación",
    codigoTotpAyuda: "Ingresa el código de 6 dígitos de tu aplicación autenticadora.",
    verificar: "Verificar",
    enrolarTitulo: "Configura tu aplicación autenticadora",
    enrolarAyuda: "Escanea el código QR o ingresa la clave y luego escribe el código que muestra la aplicación.",
    claveManual: "Clave manual",
    registro: "Crear cuenta con invitación",
    registroTitulo: "Crea tu cuenta",
    nombre: "Nombre completo",
    codigoInvitacion: "Código de invitación",
    crearCuenta: "Crear cuenta",
    yaTienesCuenta: "¿Ya tienes cuenta? Inicia sesión",
    confirmarTitulo: "Confirma tu correo",
    confirmarAyuda: "Enviamos un código a tu correo.",
    codigoCorreo: "Código del correo",
    confirmar: "Confirmar",
    recuperarTitulo: "Recupera tu contraseña",
    enviarCodigo: "Enviar código",
    nuevaContrasena: "Nueva contraseña", // pragma: allowlist secret
    restablecer: "Restablecer contraseña",
    volver: "Volver a iniciar sesión",
    politica: "Mínimo 12 caracteres con mayúscula, minúscula, número y símbolo.",
    sesionExpirada: "Tu sesión se cerró por inactividad.",
    requerido: "Este campo es obligatorio.",
    correoInvalido: "Escribe un correo válido.",
    contrasenaCorta: "La contraseña debe tener al menos 12 caracteres.", // pragma: allowlist secret
    codigoSeis: "El código tiene 6 dígitos.",
    registroNoPermitido: "No se pudo crear la cuenta. Revisa el código de invitación y tus datos.",
  },
} as const;

export type Textos = typeof es;
