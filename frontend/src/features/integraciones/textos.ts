// Textos de «Conexión con Meta». Las ayudas siguen docs/meta-configuracion.md (la interfaz de Meta
// cambia con frecuencia: se cita el nombre del campo, que casi siempre sigue existiendo).
export const t = {
  titulo: "Conexión con Meta",
  subtitulo: "Credenciales de WhatsApp Cloud API. Es una sola cuenta de Meta para toda la instalación.",
  pendienteDeDiseno: "Pantalla pendiente de validación visual con Samuel.",
  cargando: "Cargando…",
  errorCarga: "No se pudo cargar la conexión con Meta.",
  reintentar: "Reintentar",
  sinPermiso: "No tienes permiso para administrar la conexión con Meta.",
  guia: "La guía paso a paso está en docs/meta-configuracion.md.",

  estado: {
    titulo: "Estado",
    configurada: "Conexión configurada",
    faltan: "Faltan datos",
    faltanLista: (campos: string[]) => `Falta capturar: ${campos.join(", ")}.`,
    todoCapturado: "Están guardados los cinco datos. Pulsa «Probar conexión» para comprobarlos con Meta.",
    actualizado: (fecha: string) => `Última actualización: ${fecha} (hora de la Ciudad de México).`,
    sinActualizacion: "Todavía no se ha guardado ningún dato.",
  },

  campos: {
    waba_id: "WABA ID",
    phone_number_id: "Phone Number ID",
    access_token: "Token de acceso permanente",
    app_secret: "App Secret",  // pragma: allowlist secret
    verify_token: "Token de verificación",
    api_version: "Versión de la API",
  },

  ayudas: {
    waba_id: {
      resumen: "Identificador de la cuenta de WhatsApp Business. Son solo dígitos (de 8 a 25).",
      pasos: [
        "Opción 1: Meta Business Suite, Configuración del negocio, Cuentas, Cuentas de WhatsApp. Elige la cuenta: el ID aparece arriba, junto al nombre.",
        "Opción 2: panel de la app en developers.facebook.com, WhatsApp, API Setup. En el paso «Enviar y recibir mensajes» figura «WhatsApp Business Account ID».",
      ],
    },
    phone_number_id: {
      resumen: "Identificador del número de WhatsApp. No es el número de teléfono: es un código largo de solo dígitos.",
      pasos: [
        "Panel de la app, WhatsApp, API Setup. Donde eliges el número de origen aparece «Phone number ID» debajo del teléfono.",
        "Si pegas el teléfono (+52 1 55…), la prueba de conexión dirá que no encontró el número.",
      ],
    },
    access_token: {
      resumen: "Credencial con la que Command Center envía mensajes y administra plantillas. Usa un token permanente de usuario del sistema.",
      pasos: [
        "El «Temporary access token» de API Setup dura 24 horas: sirve solo para una primera prueba.",
        "Para producción: Configuración del negocio, Usuarios, Usuarios del sistema, Agregar. Crea un usuario con rol Admin.",
        "Asígnale como activos tu app y tu cuenta de WhatsApp Business, con control total.",
        "Genera el token con los permisos whatsapp_business_messaging y whatsapp_business_management, y vencimiento «Nunca».",
        "Cópialo en ese momento (Meta no vuelve a mostrarlo) y pégalo aquí. Suele empezar con EA…; se aceptan de 20 a 1000 caracteres sin espacios.",
      ],
    },
    app_secret: {
      resumen: "Con él se valida la firma de los avisos (webhook) que manda Meta. Son 32 caracteres hexadecimales (dígitos del 0 al 9 y letras de la a a la f).",
      pasos: [
        "Panel de la app, Configuración de la app, Básica, «App secret», botón «Mostrar». Meta puede pedir tu contraseña.",
        "Si este valor es incorrecto, el webhook responde 403 y no se procesa ningún mensaje entrante ni estado de entrega.",
      ],
    },
    verify_token: {
      resumen: "No se toma de Meta: lo inventa el sistema. Pulsa «Generar», cópialo y pégalo en Meta al registrar el webhook.",
      pasos: [
        "El valor se muestra una sola vez y queda guardado en el servidor; después ya no se puede ver.",
        "Espera unos 5 minutos antes de pulsar «Verificar y guardar» en Meta: el webhook guarda las credenciales en memoria ese tiempo.",
        "Si lo pierdes, genera otro y repite el registro del webhook en Meta.",
      ],
    },
    api_version: {
      resumen: "Por defecto v21.0. Cámbiala solo si Meta retira esa versión. Formato: la letra v, un número, un punto y otro número.",
      pasos: [],
    },
    verPasos: "Dónde encontrarlo en Meta",
  },

  secreto: {
    configurado: "Configurado",
    termina: (u4: string) => `Configurado · termina en ••••${u4}`,
    reemplazar: "Reemplazar",
    cancelarReemplazo: "Cancelar reemplazo",
    noConfigurado: "Sin configurar",
    soloEscritura: "Solo se escribe: nunca se vuelve a mostrar el valor completo.",
  },

  verify: {
    estadoConfigurado: "Configurado",
    estadoNo: "Sin configurar",
    generar: "Generar",
    usarPropio: "Usar uno propio",
    noUsarPropio: "Mejor generar uno",
    propioAyuda: "De 16 a 128 caracteres: letras, números, guion y guion bajo. Se guarda al pulsar «Guardar cambios».",
  },

  endpoint: {
    texto:
      "El servidor de la API de Meta (graph.facebook.com) lo fija el despliegue y no se edita aquí: si se pudiera cambiar, el token de acceso se enviaría a ese servidor.",
  },

  formulario: {
    titulo: "Credenciales",
    guardar: "Guardar cambios",
    guardando: "Guardando…",
    guardado: "Cambios guardados. Pueden tardar hasta 5 minutos en surtir efecto en todo el sistema.",
    sinCambios: "No hay cambios que guardar: escribe al menos un dato nuevo.",
    error: "No se pudo guardar. Intenta de nuevo.",
    soloLoEscrito: "Solo se guarda lo que escribas: lo que dejes vacío no cambia.",
    versionAyuda: "Versión de la API",
  },

  errores: {
    id: "Debe tener solo dígitos (de 8 a 25).",
    version: "Usa el formato v21.0 (la letra v, un número, un punto y otro).",
    tokenAcceso: "Debe tener de 20 a 1000 caracteres, sin espacios ni saltos de línea.",
    appSecret: "Debe tener 32 caracteres hexadecimales.",  // pragma: allowlist secret
    verifyToken: "Debe tener de 16 a 128 caracteres: letras, números, guion y guion bajo.",
  },

  generar: {
    titulo: "Generar token de verificación",
    explicacion: "El sistema inventará un token y lo guardará. Se mostrará una sola vez.",
    reemplaza: "Ya hay un token de verificación. Al generar uno nuevo, el actual deja de funcionar: tendrás que registrar el webhook otra vez en Meta con el valor nuevo.",
    generar: "Generar token",
    generando: "Generando…",
    cancelar: "Cancelar",
    error: "No se pudo generar el token. Intenta de nuevo.",
    resultadoTitulo: "Token de verificación generado",
    advertencia:
      "Cópialo ahora: no se podrá volver a ver. Pégalo en Meta al registrar el webhook y espera unos 5 minutos antes de pulsar «Verificar y guardar».",
    etiqueta: "Token de verificación",
    copiar: "Copiar",
    copiado: "Copiado al portapapeles.",
    noCopiado: "No se pudo copiar. Selecciona el texto y cópialo manualmente.",
    cerrar: "Cerrar",
  },

  webhook: {
    titulo: "URL del webhook",
    ayuda: "Pégala en Meta: panel de la app, WhatsApp, Configuración, Webhook, Editar. Meta exige HTTPS válido.",
    etiqueta: "URL de devolución de llamada",
    copiar: "Copiar URL",
    copiada: "URL copiada.",
    noCopiada: "No se pudo copiar. Selecciona el texto y cópialo manualmente.",
    camposTitulo: "Campos a suscribir en Meta",
    campos: [
      ["messages", "mensajes entrantes y estados de entrega"],
      ["message_template_status_update", "aprobación o rechazo de plantillas"],
    ] as [string, string][],
    suscribirCuenta:
      "Después suscribe la app a la cuenta de WhatsApp Business; la prueba de conexión lo confirma en el renglón del webhook.",
  },

  prueba: {
    titulo: "Probar conexión",
    ayuda: "Consulta la API de Meta con lo guardado. No envía mensajes.",
    boton: "Probar conexión",
    probando: "Probando…",
    sinConfigurar:
      "Aún no hay datos suficientes para probar. Guarda primero el WABA ID, el Phone Number ID y el token de acceso, y vuelve a intentar.",
    error: "No se pudo probar la conexión. Intenta de nuevo.",
    resumenOk: "Token, número y cuenta son válidos.",
    resumenFalla: "Hay datos por corregir (revisa los renglones marcados).",
    renglones: {
      token: "Token de acceso",
      numero: "Número de WhatsApp",
      waba: "Cuenta de WhatsApp Business",
      webhook: "Webhook",
    },
    correcto: "Correcto",
    fallo: "Falló",
    noProbado: "No probado",
    pendienteWebhook: "Pendiente",
    webhookNota:
      "Antes de registrar el webhook en Meta es normal que salga «sin suscribir»: no es un error y no afecta el resultado de arriba.",
    webhookSuscrito: "Hay una app suscrita a la cuenta.",
    datosNumero: "Datos del número",
    nombreVerificado: "Nombre verificado",
    numeroMostrado: "Número mostrado",
    calidad: "Calidad",
    sinDato: "Sin dato",
  },
};
