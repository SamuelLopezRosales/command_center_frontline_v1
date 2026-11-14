# command-center-v1 — Análisis de requerimientos

Versión reducida de Command Center con cuatro módulos: Dashboard, Colaboradores, Constancias y Notificaciones. Esta versión reemplaza el alcance de la versión anterior (expedientes, actas, horarios, ausencias, trámites, NOM-035 y notificaciones masivas), que queda documentado en la carpeta de trabajo previa como referencia para versiones futuras.

## 1. Módulos de la versión

El módulo **Dashboard** muestra el resumen de la operación de RH: colaboradores activos, constancias generadas en el mes, solicitudes en proceso y plantillas activas, además de la actividad reciente. Es la pantalla de inicio después del login.

El módulo **Colaboradores** reemplaza a "Empleados" en toda la interfaz. Sus campos no están fijos: el administrador de RH define qué datos se capturan, con qué tipo, si son obligatorios y en qué orden aparecen. A partir de esa configuración se generan el listado, el formulario de alta y edición, y los filtros. Esta parte sigue el boceto de referencia, que muestra una tabla de configuración de campos (con nombre, obligatorio, activo, fechas y valores de catálogo) que alimenta la tabla de colaboradores.

El módulo **Constancias** tiene tres partes. Un editor visual de plantillas donde se arma el texto con formato y variables tomadas de los campos de Colaboradores (por ejemplo `{{nombre_completo}}`, `{{puesto}}`, `{{fecha_ingreso}}`). Un listado de plantillas con crear, editar, duplicar, activar o desactivar y eliminar. Y un historial de constancias generadas, con quién la solicitó, cuándo y con qué plantilla. La solicitud en sí ocurre por WhatsApp, descrita en el documento 03.

Login de RH: se mantiene como pantalla de acceso, pero no cuenta como módulo.

El módulo **Notificaciones** se agregó después de la primera versión del alcance. Permite a RH enviar mensajes por WhatsApp desde el sistema, a un colaborador, a un grupo definido por criterios (organización, planta, departamento, área, turno, tipo de empleado, estatus o antigüedad) o a un grupo guardado. Antes de enviar, el sistema descarta a quien no tiene consentimiento, tiene estatus BAJA o no tiene un celular válido, y muestra cuántos quedaron fuera y por qué. Los mensajes que inicia la empresa solo pueden usar plantillas aprobadas por Meta, así que el sistema administra esas plantillas y su aprobación. Cuando el colaborador responde, la conversación se abre en el chat de RH dentro de la ventana de 24 horas.

## 2. Requisitos funcionales

| ID | Requisito | Módulo |
|---|---|---|
| RF-01 | El personal de RH inicia sesión con Cognito, con contraseña y MFA. | Acceso |
| RF-02 | El dashboard muestra colaboradores activos, constancias generadas en el mes, solicitudes en proceso y plantillas activas. | Dashboard |
| RF-03 | El dashboard lista las solicitudes y constancias más recientes, con colaborador y plantilla. | Dashboard |
| RF-04 | Alta, edición, baja lógica y reactivación de colaboradores. La baja conserva sus constancias. | Colaboradores |
| RF-05 | Los once campos fijos para todos los casos son fijos: número de empleado, nombres, apellidos, celular, organización, planta, fecha de ingreso, puesto, tipo de empleado y estatus. No se pueden eliminar ni desactivar. | Colaboradores |
| RF-06 | RH crea, edita, ordena, marca como obligatorio y activa o desactiva campos adicionales sin depender de un desarrollador. | Colaboradores |
| RF-07 | Los tipos de dato disponibles son texto, número, fecha, lista y sí/no. | Colaboradores |
| RF-08 | Para campos tipo lista, RH administra las opciones (etiqueta y valor). | Colaboradores |
| RF-09 | El listado de colaboradores muestra las columnas que corresponden a los campos activos, en el orden configurado. | Colaboradores |
| RF-10 | El formulario de alta y edición se genera desde la configuración y valida cada valor según su tipo y si es obligatorio. | Colaboradores |
| RF-11 | El listado permite buscar y filtrar por cualquier campo activo. | Colaboradores |
| RF-12 | Un campo que ya tiene valores registrados no puede cambiar de tipo de dato. Si se desactiva, sus valores se conservan. | Colaboradores |
| RF-13 | Tipo de empleado (administrativo u operativo) es un campo fijo de lista cerrada. | Colaboradores |
| RF-29 | Cada colaborador pertenece a una organización (razón social) con su RFC, registro patronal y firmante. | Colaboradores |
| RF-30 | Carga masiva desde la plantilla de Excel. La carga actualiza por número de empleado y no modifica ni da de baja a quien no aparece en el archivo. | Carga |
| RF-31 | El sistema vuelve a validar cada fila al cargar. Las filas con error no se cargan y el resto sí, con el resultado por fila. | Carga |
| RF-32 | La plantilla de carga se genera desde la configuración de campos, para que encabezados y reglas coincidan con el sistema. | Carga |
| RF-33 | Al crear una empresa, el sistema carga un catálogo de campos sugeridos (área, departamento, turno, ruta, sueldo, periodicidad, registro patronal, NSS, RFC, CURP y correo). RH puede activarlos, desactivarlos o renombrarlos, pero no borrarlos. | Colaboradores |
| RF-34 | Cada campo tiene un código interno que no cambia al renombrarlo, y un formato de validación (por ejemplo, 13 caracteres para RFC) que el sistema aplica a cada valor. | Colaboradores |
| RF-35 | RH crea una notificación dirigida a un colaborador, a un grupo por criterios (combinados con Y u O) o a un grupo guardado, y el sistema muestra el tamaño de la audiencia. | Notificaciones |
| RF-36 | Antes de enviar, el sistema muestra un embudo de exclusiones (sin consentimiento, estatus BAJA, celular no válido) y registra el motivo de cada exclusión. | Notificaciones |
| RF-37 | Los mensajes iniciados por la empresa usan solo plantillas aprobadas por Meta, con variables por destinatario. El sistema no permite enviar texto libre fuera de la ventana de 24 horas. | Notificaciones |
| RF-38 | RH puede enviar ahora o programar, y el sistema solo envía dentro de un horario permitido en la zona horaria de la empresa. | Notificaciones |
| RF-39 | Cada destinatario tiene su propio estado de envío (enviado, entregado, leído, respondió o fallido), y RH puede reintentar solo a los fallidos. | Notificaciones |
| RF-40 | Si el WhatsApp no se entrega en 24 horas y el colaborador tiene correo registrado, el sistema puede enviar el mismo aviso por correo, si RH lo activó al crear la notificación. | Notificaciones |
| RF-41 | Las respuestas de los colaboradores se vinculan a la notificación que las originó y se asignan a una persona de RH. | Notificaciones |
| RF-42 | RH administra un catálogo de plantillas de mensaje, con su estado de aprobación en Meta, y puede duplicar y reenviar a revisión. | Notificaciones |
| RF-14 | El editor de plantillas permite texto con formato (negrita, cursiva, subrayado, tamaño, alineación y color), saltos de línea e inserción de logotipo de la empresa. | Constancias |
| RF-15 | RH inserta variables desde un selector que lista los campos activos (`{{clave}}`) y variables del sistema (`{{folio}}`, `{{fecha_emision}}`, `{{empresa}}`). | Constancias |
| RF-16 | La vista previa rellena la plantilla con los datos de un colaborador elegido. | Constancias |
| RF-17 | Cada vez que se publica una plantilla se crea una versión nueva. Las versiones anteriores se conservan. | Constancias |
| RF-18 | El listado de plantillas permite crear, editar, duplicar, activar o desactivar y eliminar. Una plantilla con constancias emitidas se elimina solo de forma lógica. | Constancias |
| RF-19 | Al guardar, el sistema revisa que las variables existan y estén activas, y avisa si la plantilla usa campos obligatorios que podrían quedar vacíos. | Constancias |
| RF-20 | El historial muestra folio, colaborador, fecha, plantilla con su versión, estado de entrega y permite descargar el PDF. | Constancias |
| RF-21 | El historial se filtra por rango de fechas, plantilla y colaborador. | Constancias |
| RF-22 | El colaborador solicita su constancia escribiendo una palabra clave por WhatsApp. | WhatsApp |
| RF-23 | Antes de mostrar cualquier dato, el sistema verifica la identidad del colaborador. Tras tres intentos fallidos bloquea la verificación y avisa a RH. | WhatsApp |
| RF-24 | Si hay más de una plantilla activa, el colaborador elige una desde una lista. | WhatsApp |
| RF-25 | El PDF se genera con los datos vigentes del colaborador y se guarda un snapshot de los valores usados. | WhatsApp |
| RF-26 | El PDF se envía por WhatsApp y el sistema registra si fue entregado. | WhatsApp |
| RF-27 | RH recibe aviso cuando una solicitud falla: campos obligatorios vacíos, entrega fallida o verificación bloqueada. | WhatsApp |
| RF-28 | Cada constancia tiene un folio único por empresa. | Constancias |

## 3. Requisitos no funcionales

| ID | Requisito |
|---|---|
| RNF-01 | El número de WhatsApp se guarda cifrado y se busca por un hash, para no descifrar todos los registros en cada mensaje. |
| RNF-02 | El colaborador solo recibe constancias propias. El bot no responde datos de otro colaborador aunque se le pida. |
| RNF-03 | La bitácora registra altas y cambios de colaboradores, cambios de campos, cambios de plantillas, generación y entrega de constancias. |
| RNF-04 | Una constancia emitida no cambia aunque después cambien la plantilla o los datos del colaborador. Se logra con el snapshot y la versión de plantilla. |
| RNF-05 | Generar un PDF tarda menos de 5 segundos en el percentil 95. |
| RNF-06 | Si falla la generación o el envío, se reintenta de forma automática y no se pierde la solicitud. |
| RNF-07 | Interfaz en español y zona horaria de México. |
| RNF-08 | Tratamiento de datos personales conforme a la LFPDPPP. El área jurídica debe validar el aviso de privacidad que se muestra en el primer mensaje del bot. |
| RNF-09 | Capacidad de referencia: hasta 100 campos por empresa, 10,000 colaboradores por empresa y 500 constancias al mes. |
| RNF-10 | Sueldo, NSS, CURP y RFC son datos sensibles: se cifran, se marcan como tales y solo los ven usuarios con permiso. |
| RNF-11 | Las notificaciones se envían fuera de horarios restringidos solo cuando RH lo confirma explícitamente, y cada envío queda en la bitácora con su audiencia exacta. | Notificaciones |

## 4. Supuestos

Cada empresa tiene su propia configuración de campos, plantillas y colaboradores. El colaborador no tiene acceso web: toda su interacción es por WhatsApp. Se usa la API oficial de WhatsApp Business. Un número de WhatsApp pertenece a un solo colaborador. Las constancias son de tamaño carta y en español. Los campos del boceto (tipo de dato, obligatorio, activo, orden y valores de catálogo) cubren la configuración que pide el requerimiento.

## 5. Fuera de alcance en v1

Expedientes con nóminas, actas y horarios. Ausencias, vacaciones y trámites. Políticas y preguntas frecuentes. NOM-035. Notificaciones masivas. Pantallas de administración de empresas (ver dudas). Firma electrónica avanzada del documento.

## 6. Dudas abiertas

Las dudas 2 y 3 quedaron resueltas: los once campos fijos son los de la plantilla de carga, y tipo de empleado es una lista cerrada. Quedan abiertas las demás.

1. ¿v1 es para una sola empresa o el Administrador seguirá registrando varias empresas? El modelo ya incluye `empresa_id` en todas las tablas, así que no bloquea ninguna de las dos opciones, pero define si se diseña la pantalla de empresas.
2. ¿Los campos fijos (nombre, WhatsApp y consentimiento) son correctos, o también quieres que sean dinámicos? Propongo que sean fijos porque el bot necesita siempre el nombre y el número para verificar y generar la constancia.
3. En el boceto aparece "tipoEmpleado". ¿Es una categoría del colaborador (por ejemplo planta u honorarios) o un catálogo de tipos de dato? Lo modelé como categoría opcional.
4. ¿Cómo se elige la plantilla por WhatsApp? Propongo un menú cuando hay más de una activa, y una plantilla fija por tipo de colaborador como opción futura.
5. ¿El PDF se envía como archivo adjunto de WhatsApp o como enlace de descarga con caducidad? El adjunto es más directo, pero el documento queda almacenado en servidores de Meta mientras se entrega. El enlace caduca y reduce ese riesgo.
6. ¿Qué dato adicional pedimos para verificar al colaborador además del código enviado a su WhatsApp? Propongo los últimos cuatro dígitos del NSS.
7. ¿La constancia debe llevar folio y código QR de verificación para que un tercero confirme su autenticidad?
8. ¿Qué pasa si RH cambia un campo que ya usa una plantilla publicada? Propongo advertir antes de guardar, sin bloquear el cambio.

## 7. Propuestas para las dudas abiertas

1. **Una o varias empresas.** Propuesta: v1 opera para una sola empresa cliente por instancia. El modelo conserva `empresa_id`, así que pasar a varias empresas después no requiere rehacer la base. La pantalla de administración de empresas queda fuera de v1, porque no forma parte de los tres módulos.

2. **Límite de 2,000 filas por archivo.** Propuesta: mantener la plantilla en 2,000 filas y permitir subir varios archivos en una misma carga, procesados por lotes. Con cinco archivos se cubren los 10,000 colaboradores por empresa, y cada lote deja su resultado en `FILA_CARGA`.

3. **Entrega del PDF por WhatsApp.** Propuesta: enviar un enlace de descarga de un solo uso que caduca a las 24 horas, en lugar de adjuntar el PDF. Así el documento no queda almacenado en los servidores de Meta, y el enlace solo sirve una vez.

4. **Dato adicional de verificación.** Propuesta: código de seis dígitos enviado al WhatsApp registrado, más los últimos cuatro dígitos del NSS. Si la empresa no captura NSS, el dato alterno es la fecha de ingreso en formato dd/mm. Así la verificación no depende de un campo condicional.

5. **Código QR en la constancia.** Propuesta: sí. Cada constancia lleva folio y un QR que abre una página de verificación pública con nombre, folio, fecha y estatus (vigente o cancelada). La página no muestra sueldo ni otros datos sensibles.

6. **Cambio de un campo usado por una plantilla publicada.** Propuesta: advertir antes de guardar, indicando cuántas plantillas usan ese campo, sin bloquear el cambio. Las constancias ya emitidas no cambian, porque conservan su snapshot.
