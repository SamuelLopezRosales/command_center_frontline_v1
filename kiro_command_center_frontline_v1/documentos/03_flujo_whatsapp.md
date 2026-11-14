# command-center-v1 — Flujo del proceso de WhatsApp

El diagrama está en `flujos/flujo_whatsapp.png`, con su fuente en `flujos/flujo_whatsapp.dot`. Describe el recorrido desde que el colaborador escribe la palabra clave hasta que recibe su constancia.

## 1. Recorrido normal

El colaborador escribe "constancia" al número de la empresa. El bot busca el número en la base de datos mediante su hash. Si no está registrado, responde que el número no tiene acceso y termina. Si está registrado pero su estatus es BAJA o no tiene consentimiento vigente, responde que el servicio no está disponible y avisa a RH.

Si el estatus es ACTIVO y el consentimiento es válido, el bot envía un código de un solo uso al WhatsApp registrado y pide el dato adicional de verificación (propongo los últimos cuatro dígitos del NSS, duda 6). Si la verificación falla, el bot pide de nuevo ambos datos. Después del tercer intento fallido, bloquea la conversación y avisa a RH. Solo después de verificar, el bot muestra datos o acepta solicitudes.

Una vez verificado, si la empresa tiene más de una plantilla activa, el bot muestra la lista y el colaborador elige una. Si solo hay una, la usa directamente. Antes de generar el documento, el sistema revisa que todos los campos obligatorios de la plantilla tengan valor. Si alguno falta, el bot le responde al colaborador que falta información y avisa a RH con la lista de campos faltantes. La constancia no se genera en ese caso.

Si los datos están completos, el sistema genera el PDF con la versión de plantilla elegida y los datos vigentes del colaborador. Asigna el folio, guarda el snapshot de datos y el hash del archivo, y envía el PDF por WhatsApp. Si el envío se confirma, la solicitud queda como ENTREGADA y se registra en el historial y en la bitácora. Si el envío falla, el sistema reintenta una vez. Si vuelve a fallar, la solicitud queda como FALLIDA y RH recibe el aviso.

## 2. Estados de la solicitud

Una solicitud pasa por RECIBIDA, luego EN_PROCESO mientras se genera, después GENERADA cuando existe el PDF y finalmente ENTREGADA o FALLIDA. Puede quedar en CANCELADA si el colaborador abandona el flujo antes de confirmar la plantilla. Los estados de la conversación son VERIFICANDO, ACTIVA, BLOQUEADA y CERRADA.

## 3. Casos de error

| Situación | Respuesta al colaborador | Acción del sistema |
|---|---|---|
| Número no registrado | Número sin acceso. | Ninguna. Se registra el intento. |
| Estatus BAJA o consentimiento vencido | Servicio no disponible por ahora. | Aviso a RH. |
| Verificación fallida tres veces | Sin acceso temporal; contacta a RH. | Bloqueo de la conversación y aviso a RH. |
| Campo obligatorio vacío | Falta información; RH fue notificado. | Aviso a RH con los campos faltantes. |
| Error al generar el PDF | Estamos preparando tu constancia; te avisamos. | Reintento automático y aviso a RH si falla de nuevo. |
| Entrega fallida dos veces | Aviso de error en el envío. | Solicitud FALLIDA y aviso a RH. RH puede reenviar desde el historial. |

## 4. Restricciones de la plataforma de WhatsApp

La respuesta a una palabra clave del colaborador ocurre dentro de la ventana de atención de 24 horas que abre su mensaje, así que el PDF y los mensajes de verificación se pueden enviar sin plantilla aprobada por Meta. Si una entrega se retrasa más allá de esa ventana, hace falta una plantilla aprobada para reenviar. Los menús interactivos tienen límites de botones y de filas por lista, así que si hay muchas plantillas activas conviene limitar cuántas se ofrecen por mensaje. Cada conversación tiene un costo, y conviene revisarlo con el área de finanzas (ver duda 5 para la forma de entrega del documento).

## 5. Mensaje de aviso de privacidad

Antes de pedir cualquier dato, el primer mensaje del bot debe informar para qué se usan los datos y quién los trata. El texto final lo debe validar el área jurídica (RNF-08).
