# Command Center v1: Documento de requisitos

| Dato | Valor |
|---|---|
| Fase | 1 de spec-driven development (requisitos). No incluye diseño técnico ni tareas. |
| Versión | 0.1, borrador para aprobación |
| Fecha | 13 de noviembre de 2026 |
| Fuentes | Carpeta `kiro_command_center_frontline_v1/`: `documentos/01` a `05`, `casos_de_uso/casos_de_uso_command_center_v1.docx`, `modelo_entidad_relacion/`, `disenos/`, `arquitectura_aws/`, `flujos/`, `plantillas_constancias/`, `plantilla_carga/`. No se usaron `mockups/`, `prototipo_admin/` ni `prototipo_empresa_rh/`. |
| Convenciones | `CC-REQ-nnn` requisito funcional, `CC-NFR-nnn` no funcional, `CC-ASM-nnn` supuesto, `PQ-nn` pregunta abierta. [POR CONFIRMAR] remite a la pregunta indicada en la sección 8. La numeración tiene huecos por bloques a propósito; ningún ID se reutiliza. |

Decisiones tomadas en la ronda de preguntas previa a la redacción (se citan como "Ronda P1" a "Ronda P7"):

- P1: la pantalla de inicio de sesión incluye un formulario de registro de usuarios RH que da de alta la cuenta en Cognito.
- P2: en v1 existe un solo rol, RH.
- P3: tipo de empleado es obligatorio.
- P4: los colaboradores cargados por Excel quedan sin consentimiento.
- P5: RH no genera constancias directamente en v1.
- P6: los borradores de plantilla entran en v1 y "Restaurar" crea una versión nueva.
- P7: ya existe una cuenta de WhatsApp Business. El procedimiento de vinculación se definirá después.

---

## 0. Contexto y glosario

Command Center v1 es un sistema web para que Recursos Humanos (RH) administre la información de los colaboradores de la empresa que atiende. Tiene cuatro módulos: Acceso y dashboard, Colaboradores, Constancias y Notificaciones. El colaborador no entra al sistema web: solo interactúa por WhatsApp.

| Término | Significado |
|---|---|
| Empresa | Cliente que opera el sistema. Todas las tablas llevan `empresa_id`. |
| Organización | Razón social de la empresa (ORG01, ORG02…), con RFC, registro patronal, domicilio fiscal, ciudad y firmante de constancias. Tabla `ORGANIZACION`. |
| Planta | Centro de trabajo del colaborador. Tabla `PLANTA`. |
| Campos fijos | Los once campos obligatorios del colaborador: número de empleado, nombres, apellido paterno, apellido materno, celular de WhatsApp, organización, planta, fecha de ingreso, puesto, tipo de empleado y estatus. Son columnas de `COLABORADOR`. |
| Campos dinámicos | Campos que RH configura en `CAMPO_COLABORADOR`. Sus valores van en `VALOR_CAMPO`. Incluyen los sugeridos: área, departamento, turno, ruta de transporte, sueldo, periodicidad del sueldo, registro patronal, NSS, RFC, CURP y correo. |
| Dato sensible | Sueldo, NSS, CURP y RFC, además de cualquier campo con `es_sensible`. Se cifran y se muestran solo a quien tiene permiso. |
| Código interno | Identificador inmutable de un campo dinámico (`codigo_interno`). Los criterios de audiencia y las plantillas lo usan como referencia. |
| Clave | Nombre de variable del campo, por ejemplo `{{turno}}`. RH puede cambiarla. |
| Plantilla de constancia | Documento con texto, formato y variables. Cada publicación genera una `VERSION_PLANTILLA` inmutable. |
| Constancia generada | PDF emitido con folio, hash y snapshot de datos (`CONSTANCIA_GENERADA`). |
| Plantilla de mensaje | Plantilla de WhatsApp aprobada por Meta (`PLANTILLA_MENSAJE`). Se usa en mensajes que inicia la empresa. |
| Ventana de 24 horas | Periodo posterior al último mensaje del colaborador en el que se permite texto libre. |
| Audiencia | Grupo guardado de criterios (`AUDIENCIA`). |
| Embudo de exclusiones | Resumen previo al envío: seleccionados, con consentimiento, ACTIVOS y con celular válido. |
| Consentimiento vigente | Consentimiento de WhatsApp registrado para el colaborador (`consentimiento_whatsapp`). Su vigencia y caducidad están en PQ-04. |
| Folio | Identificador único de constancia por empresa. En los diseños aparece como `CG-2026-0142` (PQ-16). |
| MFA | Segundo factor de autenticación administrado por Cognito. |
| RTO / RPO | Tiempo y punto objetivo de recuperación. |

---

## 1. Alcance

### 1.1 Dentro de alcance

- **Acceso y dashboard:** inicio de sesión con Cognito y MFA, registro de usuarios RH desde la pantalla de acceso, dashboard con indicadores, solicitudes recientes y alertas, y consulta de la bitácora de auditoría.
- **Colaboradores:** alta, edición, baja lógica y reactivación. Listado con búsqueda y filtros. Campos fijos y dinámicos. Carga masiva desde Excel. Catálogos de organizaciones y plantas.
- **Constancias:** editor visual de plantillas con variables, borradores, versiones inmutables, solicitud por WhatsApp con verificación de identidad, generación de PDF con folio y QR, entrega, historial, descarga, reenvío y verificación pública por QR.
- **Notificaciones:** audiencias por criterios, individuales o guardadas. Plantillas de mensaje. Embudo de exclusiones. Envío inmediato o programado. Respaldo por correo. Seguimiento de entrega. Reintento de fallidos. Respuestas de colaboradores atendidas desde el sistema.
- **Transversal:** seguridad, datos sensibles, bitácora, consentimiento y cumplimiento con la LFPDPPP.

### 1.2 Fuera de alcance de v1

- Expedientes con nóminas, actas y horarios.
- Ausencias, vacaciones y trámites.
- Políticas y preguntas frecuentes.
- NOM-035 y sus reportes.
- Certificados (versión anterior).
- Administración de múltiples empresas: pantalla de empresas y operación de varias empresas por instancia (propuesta del análisis, PQ-08). El modelo conserva `empresa_id`.
- Firma electrónica avanzada de las constancias.
- Acceso web para colaboradores.
- Roles y permisos diferenciados (Ronda P2). Solo existe el rol RH. Los roles se agregarán en versiones futuras.
- Generación de constancias por RH a nombre de un colaborador desde el panel (Ronda P5). El canal "RH" que aparece en `cv1_07` queda fuera.
- Cualquier función que no aparezca en los insumos.

La sección 5 del análisis (`01_analisis_requerimientos.md`) lista "Notificaciones masivas" como fuera de alcance. Es un resto de la versión anterior y contradice a los RF-35 a RF-42. Este documento trata Notificaciones como dentro de alcance (PQ-18).

### 1.3 Supuestos

| ID | Supuesto | Origen |
|---|---|---|
| CC-ASM-001 | Cada empresa tiene su propia configuración de campos, plantillas y colaboradores. | Análisis §4 |
| CC-ASM-002 | El colaborador no tiene acceso web. Toda su interacción es por WhatsApp. | Análisis §4, casos de uso §2 |
| CC-ASM-003 | Se usa la API oficial de WhatsApp Business (Meta WhatsApp Cloud API). | Análisis §4 |
| CC-ASM-004 | Un número de WhatsApp pertenece a un solo colaborador. | Análisis §4, `02_modelo_datos.md` §3 |
| CC-ASM-005 | Las constancias son de tamaño carta y en español. | Análisis §4 |
| CC-ASM-006 | v1 opera para una sola empresa por instancia. [POR CONFIRMAR] (PQ-08) | Análisis §7.1 |
| CC-ASM-007 | La empresa ya cuenta con una cuenta de WhatsApp Business. El procedimiento para vincularla o sincronizarla con el sistema se entregará después. [POR CONFIRMAR] (PQ-07) | Ronda P7 |
| CC-ASM-008 | En v1 todos los usuarios RH tienen el mismo rol y los mismos permisos, incluida la visualización de datos sensibles. | Ronda P2 |
| CC-ASM-009 | La entrega de la constancia por WhatsApp es un enlace de descarga de un solo uso que caduca a las 24 horas. [POR CONFIRMAR] (PQ-03) | Análisis §7.3, UC-14 |
| CC-ASM-010 | Los envíos de notificaciones solo se programan o ejecutan de 08:00 a 20:00 en la zona horaria de la empresa. [POR CONFIRMAR] (PQ-06) | Decisión 12, UC-23 |
| CC-ASM-011 | Los colaboradores cargados por Excel quedan sin consentimiento hasta que RH lo registre. | Ronda P4 |
| CC-ASM-012 | Las plantillas de mensaje de WhatsApp las aprueba Meta. El tiempo de aprobación es externo al sistema. [POR CONFIRMAR] (PQ-11) | UC-28 |
| CC-ASM-013 | La zona horaria de la empresa es America/Mexico_City. | RNF-07, `cv1_09` |

---

## 2. Actores

| Actor | Descripción | Casos de uso |
|---|---|---|
| Usuario RH | Personal de RH de la empresa. Opera el panel web con Cognito y MFA. Único rol en v1. | UC-01 a UC-13, UC-17, UC-18, UC-20 a UC-23, UC-27 a UC-29 |
| Colaborador | Persona registrada. Interactúa solo por WhatsApp. | UC-14, UC-15, respuestas de UC-27 |
| Tercero | Quien verifica una constancia con su QR. No requiere cuenta. | UC-19 |
| Sistema | Procesos automáticos: workers de PDF y de carga, enviador, programador de envíos y servicio de estados. | UC-08, UC-16, UC-24, UC-25 |
| Meta WhatsApp Cloud API | Plataforma externa: entrega mensajes, reporta estados y aprueba plantillas. | UC-14, UC-15, UC-24, UC-26, UC-27, UC-28 |

---

## 3. Requisitos funcionales por módulo

Convención de criterios: `CUANDO [disparador] EL SISTEMA DEBERÁ [respuesta]`. Cada requisito indica su origen.

### 3.1 Módulo Acceso y dashboard

**Historias de usuario**

- Como Usuario RH, quiero iniciar sesión con contraseña y MFA, para que solo personal autorizado acceda a datos de colaboradores.
- Como persona de RH sin cuenta, quiero registrarme desde la pantalla de acceso, para obtener mi usuario sin depender de un desarrollador.
- Como Usuario RH, quiero ver un resumen de la operación al entrar, para atender primero lo urgente.
- Como Usuario RH, quiero consultar la bitácora, para saber quién hizo qué y cuándo.

**CC-REQ-001. Inicio de sesión con credenciales.** Origen: UC-01, RF-01.
- CUANDO RH captura correo y contraseña válidos EL SISTEMA DEBERÁ validarlos con Cognito y solicitar el código MFA.
- CUANDO las credenciales son incorrectas EL SISTEMA DEBERÁ mostrar un error sin indicar cuál dato falló.

**CC-REQ-002. MFA obligatorio.** Origen: UC-01 (regla de negocio), RF-01, Ronda P1.
- CUANDO RH completa correo y contraseña EL SISTEMA DEBERÁ pedir el código MFA antes de crear la sesión.
- CUANDO el código MFA es válido EL SISTEMA DEBERÁ crear la sesión y mostrar el Dashboard.
- EL SISTEMA NO DEBERÁ permitir una sesión de RH sin MFA.
- La pantalla `01_login.png` no incluye el paso del código MFA. El diseño debe ampliarse. [POR CONFIRMAR] (PQ-09)

**CC-REQ-003. Bloqueo por intentos fallidos.** Origen: UC-01 A1.
- CUANDO se acumulan intentos de acceso fallidos EL SISTEMA DEBERÁ bloquear la cuenta temporalmente. El número de intentos y la duración del bloqueo son [POR CONFIRMAR] (PQ-10).

**CC-REQ-004. Cierre de sesión por inactividad.** Origen: UC-01 A2.
- CUANDO la sesión permanece inactiva más de 30 minutos EL SISTEMA DEBERÁ cerrarla y pedir un nuevo acceso.

**CC-REQ-005. Registro del inicio de sesión.** Origen: UC-01 paso 5, RNF-03.
- CUANDO se crea una sesión EL SISTEMA DEBERÁ registrar el inicio de sesión en la bitácora.

**CC-REQ-006. Recuperación de contraseña.** Origen: `01_login.png` (enlace de recuperación).
- CUANDO RH usa el enlace de recuperación EL SISTEMA DEBERÁ iniciar el flujo de restablecimiento de contraseña de Cognito. El flujo detallado es [POR CONFIRMAR] (PQ-10).

**CC-REQ-007. Registro de usuarios RH desde la pantalla de acceso.** Origen: Ronda P1. No existe un UC; se propone UC-30 en la matriz de trazabilidad.
- CUANDO una persona abre la pantalla de inicio de sesión EL SISTEMA DEBERÁ ofrecer el acceso a un formulario de registro. Los campos del formulario son [POR CONFIRMAR] (PQ-10). Como mínimo se esperan nombre y correo, porque `USUARIO` guarda nombre y correo.
- CUANDO la persona envía el formulario con datos válidos EL SISTEMA DEBERÁ crear el usuario en Cognito y registrar su perfil en `USUARIO` con el `cognito_sub`.
- CUANDO el correo ya está registrado EL SISTEMA DEBERÁ rechazar el registro e indicar que el correo ya existe (`correo` y `cognito_sub` son únicos).
- CUANDO el usuario se registra EL SISTEMA DEBERÁ exigir la confirmación del correo y la configuración de MFA antes del primer acceso.
- EL SISTEMA NO DEBERÁ guardar contraseñas en la base de datos. Cognito las administra.
- El diseño de la pantalla de registro no existe. [POR CONFIRMAR] (PQ-09)

**CC-REQ-008. Autorización de cuentas nuevas.** Origen: Ronda P1, Ronda P2 y regla de datos sensibles (decisión 5).
- EL SISTEMA NO DEBERÁ conceder acceso a datos de colaboradores, constancias ni notificaciones a una cuenta recién registrada hasta que se cumpla el mecanismo de autorización que se defina.
- CUANDO el usuario completa el registro EL SISTEMA DEBERÁ asociarlo a la empresa que le corresponde (`USUARIO.empresa_id`).
- El mecanismo que impide que cualquier persona se registre y vea datos sensibles (código de invitación, dominio de correo, aprobación por un usuario existente u otro) es [POR CONFIRMAR] y es el riesgo de seguridad de mayor prioridad de v1 (PQ-10).

**CC-REQ-009. Rol único RH.** Origen: Ronda P2, decisión 5.
- CUANDO un usuario autorizado inicia sesión EL SISTEMA DEBERÁ concederle el rol RH, con acceso a todas las funciones de v1, incluida la visualización de datos sensibles.
- El diseño no debe impedir agregar roles después.

**CC-REQ-010. Desactivación de usuarios RH.** Origen: `USUARIO.activo`, `02_modelo_datos.md`.
- CUANDO se desactiva un usuario RH EL SISTEMA DEBERÁ impedirle iniciar sesión y conservar su historial de acciones. Quién desactiva y cómo es [POR CONFIRMAR] (PQ-10).

**CC-REQ-011. Indicadores del dashboard.** Origen: UC-02, RF-02, `cv1_01`.
- CUANDO RH abre el Dashboard EL SISTEMA DEBERÁ mostrar colaboradores activos, constancias generadas en el mes, solicitudes en proceso y plantillas activas.
- CUANDO RH selecciona una tarjeta EL SISTEMA DEBERÁ llevarla al detalle correspondiente.

**CC-REQ-012. Solicitudes y constancias recientes.** Origen: UC-02, RF-03, `cv1_01`.
- CUANDO RH abre el Dashboard EL SISTEMA DEBERÁ listar las solicitudes recientes (colaborador, plantilla con versión, estado) y las constancias recientes (folio, colaborador, plantilla, fecha, estado).

**CC-REQ-013. Alertas de RH.** Origen: UC-02 paso 2, `cv1_01`, RF-27.
- CUANDO existen colaboradores sin consentimiento de WhatsApp, constancias con entrega fallida o campos obligatorios vacíos que afectan una plantilla EL SISTEMA DEBERÁ mostrarlos como alertas con acceso al detalle.

**CC-REQ-014. Dashboard sin datos.** Origen: UC-02 A1.
- CUANDO no hay datos en el periodo EL SISTEMA DEBERÁ mostrar un mensaje en lugar de tablas vacías.

**CC-REQ-015. Consulta de la bitácora.** Origen: UC-03, RNF-03.
- CUANDO RH abre la bitácora EL SISTEMA DEBERÁ permitir filtrar por fecha, usuario, colaborador y tipo de acción, y mostrar los registros en orden cronológico.
- Las reglas de inmutabilidad y de contenido de la bitácora están en CC-REQ-154 a CC-REQ-156.

### 3.2 Módulo Colaboradores

**Historias de usuario**

- Como Usuario RH, quiero registrar y mantener los datos de cada colaborador, para que las constancias y los mensajes salgan con información correcta.
- Como Usuario RH, quiero configurar qué datos se capturan, para adaptar el sistema sin depender de un desarrollador.
- Como Usuario RH, quiero cargar colaboradores desde Excel, para no capturarlos uno por uno.
- Como Usuario RH, quiero administrar organizaciones y plantas, para que cada colaborador tenga la razón social y el centro de trabajo correctos.

**CC-REQ-020. Alta de colaborador con campos fijos.** Origen: UC-04, RF-04, RF-05, RF-13, decisión 1, Ronda P3.
- CUANDO RH guarda un colaborador EL SISTEMA DEBERÁ exigir los once campos fijos: número de empleado, nombres, apellido paterno, apellido materno, celular de WhatsApp, organización, planta, fecha de ingreso, puesto, tipo de empleado y estatus.
- EL SISTEMA DEBERÁ aceptar solo ADMINISTRATIVO u OPERATIVO como tipo de empleado y solo ACTIVO o BAJA como estatus.
- CUANDO se crea el colaborador EL SISTEMA DEBERÁ registrar ALTA en la bitácora.

**CC-REQ-021. Campos dinámicos en el alta.** Origen: UC-04, RF-10.
- CUANDO RH abre el formulario EL SISTEMA DEBERÁ mostrar los campos dinámicos activos, generados desde la configuración, e indicar los sensibles.
- CUANDO RH guarda EL SISTEMA DEBERÁ validar cada valor según su tipo, formato de validación y si es obligatorio.
- CUANDO el valor pertenece a un campo sensible EL SISTEMA DEBERÁ guardarlo cifrado (CC-REQ-151).

**CC-REQ-022. Consentimiento en el alta.** Origen: UC-04 paso 4 y A3, decisión 11, `cv1_03`.
- CUANDO RH marca que el colaborador dio su consentimiento EL SISTEMA DEBERÁ registrarlo en `consentimiento_whatsapp`.
- CUANDO RH guarda sin consentimiento EL SISTEMA DEBERÁ crear el colaborador sin consentimiento y no enviarle constancias ni notificaciones.
- El texto de la casilla en `cv1_03` dice "para recibir constancias por WhatsApp" y no menciona notificaciones. [POR CONFIRMAR] (PQ-12)

**CC-REQ-023. Unicidad del número de empleado.** Origen: UC-04 A1, `02_modelo_datos.md` §3.
- CUANDO el número de empleado ya existe en la empresa EL SISTEMA DEBERÁ marcar el campo y no guardar.

**CC-REQ-024. Unicidad del celular.** Origen: UC-04 A2, `02_modelo_datos.md` §3, CC-ASM-004.
- CUANDO el celular ya existe en la empresa (comparado por `celular_hash`) EL SISTEMA DEBERÁ marcar el campo y no guardar.

**CC-REQ-025. Validación de formatos.** Origen: `02_modelo_datos.md` §4, `04_plantilla_carga_colaboradores.md` §4, plantilla v1.3 (hoja Diccionario).
- CUANDO se captura o carga un colaborador EL SISTEMA DEBERÁ validar: celular de 10 dígitos; RFC del colaborador de 13 caracteres; CURP de 18 caracteres; NSS de 11 dígitos; registro patronal de 11 caracteres; fecha válida; sueldo y periodicidad capturados juntos.
- Los formatos de RFC son [POR CONFIRMAR]: `02_modelo_datos.md` §4 dice 12 o 13 caracteres, mientras que el Diccionario de la plantilla y `cv1_03` dicen 13 para el colaborador y 12 o 13 para la organización (PQ-13).

**CC-REQ-026. Edición de colaborador.** Origen: UC-05, RF-04, RF-10.
- CUANDO RH guarda cambios válidos EL SISTEMA DEBERÁ actualizar el registro y registrar MODIFICACION en la bitácora con los campos cambiados, sin valores personales.
- Las constancias ya emitidas no cambian (CC-REQ-082).

**CC-REQ-027. Retiro del consentimiento.** Origen: UC-05 A2.
- CUANDO RH retira el consentimiento EL SISTEMA DEBERÁ dejar de enviar constancias y notificaciones al colaborador (CC-REQ-157).

**CC-REQ-028. Cambio de organización o planta.** Origen: UC-05 A1.
- CUANDO cambia la organización o la planta de un colaborador EL SISTEMA DEBERÁ recalcular las audiencias guardadas la siguiente vez que se usen.

**CC-REQ-029. Baja de colaborador.** Origen: UC-06, RF-04, decisión 10.
- CUANDO RH da de baja a un colaborador y captura la fecha EL SISTEMA DEBERÁ cambiar su estatus a BAJA, conservar el expediente y el historial, y registrar BAJA en la bitácora.
- EL SISTEMA NO DEBERÁ borrar físicamente al colaborador.
- El modelo no tiene un campo para la fecha de baja. [POR CONFIRMAR] (PQ-14)

**CC-REQ-030. Reactivación.** Origen: UC-06 A2.
- CUANDO RH reactiva a un colaborador EL SISTEMA DEBERÁ cambiar su estatus a ACTIVO y registrar REACTIVACION en la bitácora.
- CUANDO el colaborador no tiene consentimiento vigente EL SISTEMA DEBERÁ pedirlo antes de reactivar.

**CC-REQ-031. Listado de colaboradores.** Origen: UC-07, RF-09, `cv1_02`.
- CUANDO RH abre el listado EL SISTEMA DEBERÁ mostrar las columnas de los campos activos en el orden configurado, con paginación, y permitir elegir qué columnas ver.

**CC-REQ-032. Búsqueda y filtros.** Origen: UC-07, RF-11.
- CUANDO RH escribe en el buscador EL SISTEMA DEBERÁ buscar por nombre o número de empleado.
- CUANDO RH elige filtros EL SISTEMA DEBERÁ filtrar por organización, planta, estatus o cualquier campo activo.

**CC-REQ-033. Listado sin resultados.** Origen: UC-07 A1.
- CUANDO no hay resultados EL SISTEMA DEBERÁ indicarlo y sugerir quitar filtros.

**CC-REQ-034. Plantilla de carga generada desde la configuración.** Origen: UC-08, RF-32, UC-09 postcondición.
- CUANDO RH descarga la plantilla de carga EL SISTEMA DEBERÁ generarla con los campos activos, de modo que encabezados y reglas coincidan con la configuración.
- CUANDO RH activa, desactiva o agrega un campo EL SISTEMA DEBERÁ reflejarlo en la siguiente plantilla descargada.

**CC-REQ-035. Subida y registro de la carga.** Origen: UC-08 pasos 2 y 3, RF-30.
- CUANDO RH sube un archivo EL SISTEMA DEBERÁ aceptarlo mediante una URL firmada de S3 y registrar la carga en estado EN_PROCESO con nombre de archivo, hash y usuario.
- CUANDO termina el procesamiento EL SISTEMA DEBERÁ cambiar la carga a TERMINADA. CANCELADA existe como estado del modelo, pero ningún caso de uso define cómo se cancela una carga (PQ-14).

**CC-REQ-036. Validación por fila en el servidor.** Origen: UC-08 pasos 4 a 6, RF-31, `02_modelo_datos.md` §4.
- CUANDO se procesa una fila EL SISTEMA DEBERÁ validarla completa en el servidor, aunque Excel ya la haya validado: obligatorios completos, número de empleado no repetido en el archivo, celular válido y no repetido, organización y planta existentes, estatus ACTIVO o BAJA, formatos (CC-REQ-025) y fecha válida.
- CUANDO una fila tiene error EL SISTEMA DEBERÁ omitirla, cargar el resto del archivo y registrar el resultado de cada fila en `FILA_CARGA` (NUEVO, ACTUALIZADO, ERROR u OMITIDO).
- CUANDO una fila trae datos pero no número de empleado EL SISTEMA DEBERÁ marcarla como ERROR.

**CC-REQ-037. Alta y actualización por número de empleado.** Origen: UC-08 paso 5 y A3, RF-30, decisión 4.
- CUANDO el número de empleado de una fila no existe EL SISTEMA DEBERÁ crear el colaborador. CUANDO existe EL SISTEMA DEBERÁ actualizarlo.
- CUANDO un colaborador no aparece en el archivo EL SISTEMA NO DEBERÁ modificarlo ni darlo de baja.
- CUANDO la fila trae estatus BAJA EL SISTEMA DEBERÁ cambiar el estatus del colaborador a BAJA sin borrar el registro.

**CC-REQ-038. Límite de filas y lotes.** Origen: UC-08 A2, análisis §7.2, RNF-09.
- CUANDO un archivo trae más de 2,000 filas EL SISTEMA DEBERÁ pedir dividirlo.
- EL SISTEMA DEBERÁ permitir varias cargas, de modo que con varios archivos se cubran los 10,000 colaboradores de capacidad de la empresa. [POR CONFIRMAR] (PQ-02)

**CC-REQ-039. Archivo que no corresponde.** Origen: UC-08 A1.
- CUANDO el archivo no corresponde a la plantilla (hojas o encabezados distintos) EL SISTEMA DEBERÁ rechazarlo sin procesar filas.

**CC-REQ-040. Resumen y reporte de errores.** Origen: UC-08 paso 7, `02_modelo_datos.md` §1.
- CUANDO termina la carga EL SISTEMA DEBERÁ mostrar el total de filas, las cargadas y las que tuvieron error, y permitir descargar el reporte de errores.
- EL SISTEMA NO DEBERÁ incluir datos personales en el mensaje de error de cada fila.

**CC-REQ-041. Consentimiento en la carga masiva.** Origen: Ronda P4, UC-04 A3.
- CUANDO la carga crea un colaborador EL SISTEMA DEBERÁ dejarlo sin consentimiento de WhatsApp.
- CUANDO la carga actualiza un colaborador existente EL SISTEMA NO DEBERÁ cambiar su consentimiento.
- La plantilla de Excel v1.3 no tiene columna de consentimiento y en v1 no se agrega. RH lo registra desde la ficha (CC-REQ-022). La fecha y caducidad del consentimiento son [POR CONFIRMAR] (PQ-04).

**CC-REQ-042. Tipo de empleado obligatorio en la carga.** Origen: Ronda P3, decisión 1.
- CUANDO una fila viene sin tipo de empleado EL SISTEMA DEBERÁ marcarla como ERROR, aunque la plantilla de Excel lo marque como opcional.
- La plantilla v1.3 debe ajustar el encabezado de tipo de empleado a obligatorio (PQ-01).

**CC-REQ-043. Administración de organizaciones.** Origen: UC-10, RF-29, decisión 3.
- CUANDO RH crea o edita una organización EL SISTEMA DEBERÁ capturar clave, razón social, RFC, registro patronal, domicilio fiscal, ciudad, nombre, cargo y correo del firmante, y logotipo opcional.
- CUANDO la clave ya existe en la empresa EL SISTEMA DEBERÁ rechazar el registro.
- CUANDO una organización tiene colaboradores EL SISTEMA NO DEBERÁ eliminarla, solo desactivarla.
- La hoja Organizaciones de la plantilla de Excel no incluye `ciudad` ni `correo_firmante`, y los insumos no dicen si la carga masiva crea organizaciones (PQ-15).

**CC-REQ-044. Administración de plantas.** Origen: UC-10, RF-05.
- CUANDO RH crea o edita una planta EL SISTEMA DEBERÁ validar que el nombre sea único.
- CUANDO una planta tiene colaboradores EL SISTEMA NO DEBERÁ eliminarla, solo desactivarla.

**CC-REQ-045. Configuración de campos dinámicos.** Origen: UC-09, RF-06, RF-34, `cv1_04`.
- CUANDO RH crea un campo EL SISTEMA DEBERÁ capturar nombre visible, clave de variable, tipo, formato de validación, obligatorio, sensible y orden.
- CUANDO RH ordena, activa, desactiva o renombra un campo EL SISTEMA DEBERÁ aplicar el cambio sin intervención de un desarrollador.
- EL SISTEMA DEBERÁ permitir marcar como sensible un campo personalizado (por ejemplo "Bono de productividad" en `cv1_04`).

**CC-REQ-046. Código interno inmutable.** Origen: UC-09 paso 4, RF-34, `02_modelo_datos.md` §2.
- CUANDO se guarda un campo nuevo EL SISTEMA DEBERÁ asignarle un código interno único que no cambia.
- CUANDO RH renombra el campo o cambia su clave EL SISTEMA DEBERÁ conservar el código interno.

**CC-REQ-047. Tipos de dato y opciones de lista.** Origen: RF-07, RF-08, UC-09 paso 3.
- EL SISTEMA DEBERÁ ofrecer los tipos TEXTO, NUMERO, FECHA, LISTA y SI_NO.
- CUANDO el campo es LISTA EL SISTEMA DEBERÁ permitir administrar sus opciones (etiqueta, valor, descripción, orden y activo). La descripción puede guardar, por ejemplo, el horario de un turno.

**CC-REQ-048. Tipo de dato protegido.** Origen: UC-09 A1, RF-12.
- CUANDO RH intenta cambiar el tipo de un campo con valores registrados EL SISTEMA DEBERÁ impedirlo.

**CC-REQ-049. Campos sugeridos.** Origen: RF-33, UC-09 A2, decisión 2.
- CUANDO se da de alta la empresa EL SISTEMA DEBERÁ cargar los campos sugeridos: área, departamento, turno, ruta de transporte, sueldo, periodicidad del sueldo, registro patronal, NSS, RFC, CURP y correo.
- CUANDO RH intenta eliminar un campo sugerido EL SISTEMA DEBERÁ permitir solo desactivarlo.
- En `cv1_04` el campo "Ruta de transporte" aparece INACTIVO. El estado inicial de cada sugerido es [POR CONFIRMAR] (PQ-14).

**CC-REQ-050. Conservación de valores.** Origen: RF-12, UC-09 reglas.
- CUANDO se desactiva un campo con valores EL SISTEMA DEBERÁ conservar sus valores.
- EL SISTEMA NO DEBERÁ eliminar un campo con valores registrados.

**CC-REQ-051. Campos fijos protegidos.** Origen: RF-05, `cv1_04`.
- EL SISTEMA NO DEBERÁ permitir eliminar, desactivar ni editar los once campos fijos en la pantalla de configuración de campos.

**CC-REQ-052. Cambio de clave usada en una plantilla.** Origen: UC-09 A3, análisis §7.6.
- CUANDO RH cambia la clave de un campo usado en plantillas publicadas EL SISTEMA DEBERÁ advertir cuántas plantillas se afectan y pedir confirmación, sin bloquear el cambio. [POR CONFIRMAR] (PQ-17: el UC dice "pide confirmación" y el análisis dice "advertir sin bloquear".)
- Las constancias ya emitidas no cambian, porque conservan su snapshot.

### 3.3 Módulo Constancias

**Historias de usuario**

- Como Usuario RH, quiero armar plantillas con texto, formato y variables, para emitir constancias con el formato de cada trámite.
- Como Usuario RH, quiero que cada versión publicada no cambie, para poder demostrar con qué documento se emitió cada constancia.
- Como Colaborador, quiero pedir mi constancia por WhatsApp, para recibirla sin ir con RH.
- Como Usuario RH, quiero consultar el historial y reenviar entregas fallidas, para atender a los colaboradores.
- Como Tercero, quiero verificar una constancia con su código QR, para confirmar que es auténtica.

**CC-REQ-060. Editor visual de plantillas.** Origen: UC-11, RF-14, `cv1_06`.
- CUANDO RH crea o abre una plantilla EL SISTEMA DEBERÁ ofrecer texto con negrita, cursiva, subrayado, tamaño, alineación, color y saltos de línea.

**CC-REQ-061. Variables.** Origen: UC-11 paso 3, RF-15, `05_plantillas_constancias.md` §1.
- CUANDO RH inserta variables EL SISTEMA DEBERÁ listar los campos activos (`{{clave}}`), las variables de organización (`{{organizacion.razon_social}}`, `{{organizacion.rfc}}`, `{{organizacion.domicilio_fiscal}}`, `{{organizacion.nombre_firmante}}`, `{{organizacion.cargo_firmante}}`, `{{organizacion.correo_firmante}}`, `{{lugar}}`) y las del sistema (`{{folio}}`, `{{fecha_emision}}`, `{{qr_verificacion}}`).
- EL SISTEMA DEBERÁ ofrecer `{{nombre_completo}}`, `{{horario}}` (descripción de la opción del turno), `{{sueldo_mensual}}` y `{{sueldo_letra}}` como variables derivadas.
- `{{empresa}}` aparece en el análisis (RF-15) pero no en el editor `cv1_06` ni en las plantillas de referencia. [POR CONFIRMAR] (PQ-17)

**CC-REQ-062. Logotipo.** Origen: UC-11 paso 4, RF-14, `05_plantillas_constancias.md` §4.
- CUANDO RH inserta el logotipo EL SISTEMA DEBERÁ usar el logotipo de la organización (`logotipo_s3_key`).
- Las plantillas de referencia no traen logotipo. El archivo oficial lo debe entregar la empresa (PQ-11).

**CC-REQ-063. Vista previa.** Origen: UC-11 paso 5, RF-16.
- CUANDO RH elige un colaborador de prueba EL SISTEMA DEBERÁ rellenar la plantilla con sus datos.
- Los datos de prueba deben respetar los formatos válidos (RFC, CURP, registro patronal) para que la vista previa sea representativa.

**CC-REQ-064. Borradores.** Origen: UC-11 paso 6, Ronda P6, `cv1_05`.
- CUANDO RH guarda como borrador EL SISTEMA DEBERÁ conservar el contenido en S3 y no ponerlo disponible para WhatsApp.
- EL SISTEMA DEBERÁ mostrar la plantilla con estado BORRADOR en el listado.
- El modelo de datos no tiene dónde registrar el borrador (PQ-14).

**CC-REQ-065. Validación previa a la publicación.** Origen: UC-11 A1, UC-12 paso 2 y A1, RF-19.
- CUANDO RH pulsa Publicar EL SISTEMA DEBERÁ verificar que todas las variables existan y estén activas.
- CUANDO hay errores EL SISTEMA DEBERÁ mostrarlos y no publicar.

**CC-REQ-066. Publicación de versiones inmutables.** Origen: UC-12, RF-17, decisión 6.
- CUANDO la validación pasa EL SISTEMA DEBERÁ crear la versión siguiente con su número y hash SHA-256, guardar el contenido como JSON en S3 (la base guarda ruta y hash) y dejarla disponible para solicitudes nuevas.
- EL SISTEMA NO DEBERÁ modificar una versión publicada. Cualquier cambio crea otra versión.
- Las constancias emitidas con versiones anteriores permanecen intactas.

**CC-REQ-067. Advertencias de publicación.** Origen: UC-12 A2, RF-19, `cv1_06`.
- CUANDO la plantilla usa campos sensibles EL SISTEMA DEBERÁ advertirlo y pedir confirmación de RH antes de publicar.
- CUANDO la plantilla usa campos obligatorios que podrían quedar vacíos EL SISTEMA DEBERÁ avisar cuántos colaboradores están afectados (por ejemplo, "2 colaboradores sin NSS").

**CC-REQ-068. Restaurar una versión.** Origen: Ronda P6, `cv1_06`.
- CUANDO RH elige Restaurar en una versión anterior EL SISTEMA DEBERÁ crear una versión nueva con el contenido de la anterior, sin modificar la versión original.

**CC-REQ-069. Listado y ciclo de vida de plantillas.** Origen: UC-13, RF-18, `cv1_05`.
- CUANDO RH abre el listado EL SISTEMA DEBERÁ mostrar nombre, descripción, versión, fecha de actualización, constancias emitidas y estado, con las acciones editar, duplicar, activar o desactivar y eliminar.
- CUANDO RH elimina una plantilla con constancias emitidas EL SISTEMA DEBERÁ ocultarla de forma lógica y conservar el historial.
- EL SISTEMA NO DEBERÁ borrar ninguna constancia emitida.

**CC-REQ-070. Disponibilidad de plantillas en WhatsApp.** Origen: UC-13 A2, UC-14 precondición.
- CUANDO una plantilla está desactivada, eliminada o sin versión publicada EL SISTEMA DEBERÁ excluirla de la lista que ve el colaborador.

**CC-REQ-071. Solicitud por palabra clave.** Origen: UC-14, RF-22, `03_flujo_whatsapp.md` §1.
- CUANDO el colaborador escribe la palabra clave (por ejemplo "constancia") EL SISTEMA DEBERÁ buscar su número por hash e iniciar el flujo.
- La lista de palabras clave aceptadas es [POR CONFIRMAR] (PQ-17).

**CC-REQ-072. Número no registrado y servicio no disponible.** Origen: UC-14 A1 y A2, decisión 10, RNF-02.
- CUANDO el número no está registrado EL SISTEMA DEBERÁ responder que no tiene acceso, registrar el intento y no continuar.
- CUANDO el colaborador está en BAJA o sin consentimiento vigente EL SISTEMA DEBERÁ responder que el servicio no está disponible, no generar la constancia y avisar a RH (CC-REQ-164).

**CC-REQ-073. Verificación de identidad.** Origen: UC-15, RF-23, `03_flujo_whatsapp.md` §1.
- CUANDO el colaborador está ACTIVO con consentimiento vigente EL SISTEMA DEBERÁ enviar un código de seis dígitos al WhatsApp registrado y pedir un dato adicional: los últimos cuatro dígitos del NSS, o la fecha de ingreso en formato dd/mm si la empresa no captura NSS. [POR CONFIRMAR] (PQ-05)
- CUANDO el código y el dato son correctos EL SISTEMA DEBERÁ dejar la conversación ACTIVA.
- EL SISTEMA NO DEBERÁ mostrar datos ni aceptar solicitudes antes de la verificación.

**CC-REQ-074. Caducidad del código y bloqueo.** Origen: UC-15 A1 a A3, RF-23.
- CUANDO el código tiene más de 10 minutos EL SISTEMA DEBERÁ enviar uno nuevo.
- CUANDO el dato es incorrecto EL SISTEMA DEBERÁ contar un intento y pedir de nuevo ambos datos.
- CUANDO se acumulan tres intentos fallidos EL SISTEMA DEBERÁ dejar la conversación BLOQUEADA, informar al colaborador que contacte a RH y avisar a RH.

**CC-REQ-075. Selección de plantilla.** Origen: UC-14 paso 3, RF-24.
- CUANDO hay más de una plantilla activa EL SISTEMA DEBERÁ mostrar la lista para que el colaborador elija. La lista se limita a lo que permiten los menús interactivos de WhatsApp (`03_flujo_whatsapp.md` §4).
- CUANDO hay una sola EL SISTEMA DEBERÁ usarla sin preguntar.

**CC-REQ-076. Campos obligatorios de la plantilla.** Origen: UC-14 paso 4 y A3, RF-27, `03_flujo_whatsapp.md` §3.
- CUANDO algún campo obligatorio de la plantilla elegida está vacío EL SISTEMA DEBERÁ informar al colaborador que falta información, avisar a RH con la lista de campos faltantes y no generar la constancia.

**CC-REQ-077. Generación del PDF.** Origen: UC-16, RF-25.
- CUANDO la solicitud está validada EL SISTEMA DEBERÁ tomarla de la cola de PDF, recuperar la versión de plantilla elegida y los datos vigentes del colaborador y generar el PDF con el logotipo.
- La solicitud pasa por los estados de CC-REQ-086.

**CC-REQ-078. Variables derivadas.** Origen: UC-16 paso 3, `05_plantillas_constancias.md` §1 y §4.
- CUANDO se genera el PDF EL SISTEMA DEBERÁ calcular `{{sueldo_mensual}}` a partir de sueldo y periodicidad, `{{sueldo_letra}}` y las fechas en texto, y no guardar estos valores como campos.
- Factores propuestos: semanal × 52/12, catorcenal × 26/12, quincenal × 2, mensual × 1. [POR CONFIRMAR] con contabilidad o RH (PQ-18). Alternativa: mostrar el sueldo con su periodicidad.
- El formato de `{{sueldo_letra}}` incluye "00/100 MN" según el análisis, pero la corrección de la plantilla de consulado vuelve a escribirlo después de la variable (PQ-17).

**CC-REQ-079. Folio único.** Origen: UC-16 paso 4, RF-28, `02_modelo_datos.md` §3.
- CUANDO se genera una constancia EL SISTEMA DEBERÁ asignarle un folio único por empresa, con la unicidad garantizada en la base de datos.
- El formato (`CG-AAAA-NNNN` en los diseños) y si la numeración reinicia cada año son [POR CONFIRMAR] (PQ-16).

**CC-REQ-080. QR y folio en el documento.** Origen: UC-16 paso 5, `05_plantillas_constancias.md` §4, análisis §7.5.
- CUANDO se genera el PDF EL SISTEMA DEBERÁ incluir el folio y un código QR de verificación en el pie, sin que RH tenga que ponerlos en la plantilla. [POR CONFIRMAR] (PQ-19)

**CC-REQ-081. Almacenamiento inmutable del PDF.** Origen: UC-16 paso 6, decisión 7.
- CUANDO se genera el PDF EL SISTEMA DEBERÁ guardarlo en S3 con Object Lock y registrar su hash SHA-256.
- EL SISTEMA NO DEBERÁ modificar el PDF después de generado.

**CC-REQ-082. Snapshot de datos.** Origen: UC-16 paso 7, RF-25, RNF-04, decisión 6.
- CUANDO se emite una constancia EL SISTEMA DEBERÁ guardar el snapshot de los datos usados (incluidas las variables calculadas) en `datos_snapshot_json`.
- CUANDO cambian después los datos del colaborador o la plantilla EL SISTEMA NO DEBERÁ alterar la constancia emitida.

**CC-REQ-083. Reintento y falla de generación.** Origen: UC-16 A1 y A2, RNF-06, `03_flujo_whatsapp.md` §3.
- CUANDO falla la generación EL SISTEMA DEBERÁ reintentar de forma automática sin perder la solicitud y avisar al colaborador que su constancia se está preparando.
- CUANDO el error persiste EL SISTEMA DEBERÁ marcar la solicitud FALLIDA y avisar a RH. El número de reintentos de generación es [POR CONFIRMAR] (PQ-20).

**CC-REQ-084. Entrega por enlace de un solo uso.** Origen: UC-14 paso 5, RF-26, análisis §7.3.
- CUANDO el PDF está generado EL SISTEMA DEBERÁ enviar al colaborador por WhatsApp un enlace de descarga de un solo uso que caduca a las 24 horas, sin adjuntar el archivo. [POR CONFIRMAR] (PQ-03)
- CUANDO el envío se confirma EL SISTEMA DEBERÁ marcar la solicitud ENTREGADA y registrar la entrega en el historial y en la bitácora.
- `flujos/flujo_whatsapp.dot` dice "Enviar PDF por WhatsApp" sin precisar enlace o adjunto (PQ-03).

**CC-REQ-085. Reintento de entrega.** Origen: UC-14 A4, `03_flujo_whatsapp.md` §1.
- CUANDO falla el envío EL SISTEMA DEBERÁ reintentar una vez.
- CUANDO vuelve a fallar EL SISTEMA DEBERÁ marcar la solicitud FALLIDA y avisar a RH.
- CUANDO el reenvío cae fuera de la ventana de 24 horas EL SISTEMA DEBERÁ usar una plantilla aprobada por Meta (`03_flujo_whatsapp.md` §4). El catálogo de plantillas necesarias es [POR CONFIRMAR] (PQ-11).

**CC-REQ-086. Estados de solicitud y conversación.** Origen: `03_flujo_whatsapp.md` §2, `02_modelo_datos.md` §2.
- EL SISTEMA DEBERÁ manejar los estados de solicitud RECIBIDA, EN_PROCESO, GENERADA, ENTREGADA, FALLIDA y CANCELADA, y los estados de conversación VERIFICANDO, ACTIVA, BLOQUEADA y CERRADA.
- EL SISTEMA DEBERÁ mantener a lo más una conversación de verificación activa por colaborador.

**CC-REQ-087. Historial de constancias.** Origen: UC-17, RF-20, RF-21, `cv1_07`.
- CUANDO RH abre el historial EL SISTEMA DEBERÁ mostrar folio, colaborador, plantilla con versión, fecha, canal, estado de entrega y acción.
- CUANDO RH aplica filtros EL SISTEMA DEBERÁ filtrar por rango de fechas, plantilla, colaborador, folio y estado.
- Con la decisión de la Ronda P5, el canal de las constancias de v1 es WhatsApp. El valor "RH" de `cv1_07` queda fuera de v1.

**CC-REQ-088. Descarga del PDF por RH.** Origen: UC-17 paso 4 y A1, RNF-03.
- CUANDO RH pulsa Descargar EL SISTEMA DEBERÁ entregar el PDF mediante un enlace firmado de S3 válido 24 horas y registrar la descarga en la bitácora.
- CUANDO la constancia está PENDIENTE EL SISTEMA DEBERÁ indicarlo y no ofrecer descarga. En `cv1_07` esa fila muestra el botón Descargar, lo que contradice el UC (PQ-17).

**CC-REQ-089. Reenvío de constancia fallida.** Origen: UC-18, RF-26, RF-27.
- CUANDO RH pulsa Reenviar en una constancia FALLIDA EL SISTEMA DEBERÁ generar un nuevo enlace de un solo uso, enviarlo por WhatsApp, actualizar el estado de entrega y registrar quién reenvió en la bitácora.
- CUANDO falla de nuevo EL SISTEMA DEBERÁ dejar la constancia FALLIDA y sugerir revisar el número del colaborador.

**CC-REQ-090. Verificación pública de autenticidad.** Origen: UC-19, análisis §7.5.
- CUANDO un tercero abre el enlace del QR EL SISTEMA DEBERÁ mostrar una página pública con nombre, folio, fecha de emisión y estado (vigente o cancelada).
- EL SISTEMA NO DEBERÁ mostrar sueldo ni ningún dato sensible en esa página.
- CUANDO el folio no existe o está cancelado EL SISTEMA DEBERÁ indicarlo.
- [POR CONFIRMAR] (PQ-19). Además, el modelo no tiene un estado "cancelada" para `CONSTANCIA_GENERADA` ni un caso de uso para cancelar una constancia (PQ-14).

**CC-REQ-091. Cancelación por abandono.** Origen: `03_flujo_whatsapp.md` §2.
- CUANDO el colaborador abandona el flujo antes de confirmar la plantilla EL SISTEMA DEBERÁ dejar la solicitud en CANCELADA. El tiempo de espera para considerar abandono es [POR CONFIRMAR] (PQ-20).

### 3.4 Módulo Notificaciones

**Historias de usuario**

- Como Usuario RH, quiero enviar mensajes por WhatsApp a un colaborador, a un grupo por criterios o a un grupo guardado, para comunicar avisos sin contactar uno por uno.
- Como Usuario RH, quiero ver cuántos colaboradores quedan fuera y por qué antes de enviar, para evitar envíos sin consentimiento.
- Como Usuario RH, quiero programar envíos dentro de un horario permitido, para no molestar a los colaboradores.
- Como Usuario RH, quiero dar seguimiento al estado de cada destinatario y atender sus respuestas, para saber que el aviso llegó.

**CC-REQ-100. Audiencia por criterios.** Origen: UC-20, UC-21 paso 1, RF-35, `cv1_09`.
- CUANDO RH define criterios EL SISTEMA DEBERÁ permitir filtrar por organización, planta, departamento, área, turno, tipo de empleado, estatus y antigüedad, combinados con Y u O, y mostrar el tamaño de la audiencia.
- CUANDO RH elige modo individual EL SISTEMA DEBERÁ permitir seleccionar un colaborador.

**CC-REQ-101. Grupos guardados.** Origen: UC-20, `02_modelo_datos.md` §2.
- CUANDO RH guarda un grupo EL SISTEMA DEBERÁ guardar el nombre y los criterios por código interno de campo.
- CUANDO no hay colaboradores que cumplan los criterios EL SISTEMA DEBERÁ pedir ajustar los criterios.

**CC-REQ-102. Creación de la notificación.** Origen: UC-21, RF-35.
- CUANDO RH elige modo (por criterios, individual o grupo guardado) y define la audiencia EL SISTEMA DEBERÁ mostrar cuántos colaboradores hay y permitir guardar la notificación como BORRADOR.

**CC-REQ-103. Plantilla aprobada, variables y vista previa.** Origen: UC-21 pasos 3 y 4 y A1, RF-37.
- CUANDO RH elige la plantilla EL SISTEMA DEBERÁ listar solo plantillas con estado APROBADA.
- EL SISTEMA DEBERÁ permitir asignar las variables por destinatario y mostrar una vista previa del mensaje.

**CC-REQ-104. Texto libre fuera de la ventana de 24 horas.** Origen: UC-21 A2, RF-37, decisión 11.
- CUANDO el mensaje lo inicia la empresa EL SISTEMA DEBERÁ permitir únicamente plantillas aprobadas por Meta.
- CUANDO RH intenta texto libre fuera de la ventana de 24 horas EL SISTEMA NO DEBERÁ permitirlo.
- En `cv1_09` el campo Canal ofrece "Plantilla aprobada por Meta" y "Respuesta dentro de 24 h". El valor "Respuesta dentro de 24 h" (`RESPUESTA_24H` en `NOTIFICACION.canal`) no aplica a una notificación nueva a una audiencia, solo a respuestas de un chat (PQ-17).

**CC-REQ-105. Embudo de exclusiones.** Origen: UC-22, RF-36, `cv1_09`.
- CUANDO RH pulsa Revisar y enviar EL SISTEMA DEBERÁ calcular el embudo en este orden: seleccionados, con consentimiento, con estatus ACTIVO y con celular válido.
- EL SISTEMA DEBERÁ mostrar cuántos quedan excluidos y el motivo de cada grupo: SIN_CONSENTIMIENTO, ESTATUS_BAJA o SIN_CELULAR_VALIDO.
- CUANDO RH confirma EL SISTEMA DEBERÁ fijar la audiencia final.

**CC-REQ-106. Un renglón por colaborador.** Origen: UC-22 postcondición, `02_modelo_datos.md` §2.
- CUANDO se confirma la audiencia EL SISTEMA DEBERÁ crear un renglón por colaborador seleccionado, incluidos los excluidos con su motivo, y guardar el snapshot de criterios (`criterios_snapshot_json`) y los totales.
- CUANDO cambia después el grupo guardado EL SISTEMA NO DEBERÁ cambiar un envío ya confirmado.

**CC-REQ-107. Sin destinatarios válidos.** Origen: UC-22 A1.
- CUANDO ningún destinatario es válido EL SISTEMA NO DEBERÁ permitir confirmar el envío.

**CC-REQ-108. Enviar o programar.** Origen: UC-23, RF-38, `cv1_09`.
- CUANDO RH elige Enviar ahora o Programar EL SISTEMA DEBERÁ cambiar el estado a ENVIANDO o PROGRAMADA al confirmar.
- CUANDO el envío está programado EL SISTEMA DEBERÁ dispararlo a la fecha y hora indicadas mediante el programador de envíos.

**CC-REQ-109. Horario permitido.** Origen: UC-23 pasos 2, A1 y A2, decisión 12, RNF-11.
- CUANDO la hora programada cae fuera del horario permitido (08:00 a 20:00, hora de la empresa) EL SISTEMA DEBERÁ pedir ajustarla. [POR CONFIRMAR] (PQ-06)
- CUANDO RH pide un envío inmediato fuera de horario EL SISTEMA DEBERÁ pedir confirmación explícita antes de enviar.
- CUANDO se confirma EL SISTEMA DEBERÁ registrar en la bitácora el envío con su audiencia exacta.

**CC-REQ-110. Respaldo por correo (opción).** Origen: UC-23 paso 3, RF-40, `cv1_09`.
- CUANDO RH activa el respaldo por correo EL SISTEMA DEBERÁ mostrar cuántos destinatarios tienen correo registrado.
- EL SISTEMA DEBERÁ guardar la opción en `respaldo_correo`.
- La obligatoriedad del correo para usar el respaldo es [POR CONFIRMAR] (PQ-12).

**CC-REQ-111. Entrega a destinatarios.** Origen: UC-24, RF-39.
- CUANDO la notificación está ENVIANDO EL SISTEMA DEBERÁ enviar la plantilla aprobada con sus variables a cada destinatario válido, guardar el identificador del mensaje y marcar el destinatario ENVIADO.
- CUANDO falla un envío EL SISTEMA DEBERÁ reintentar hasta dos veces antes de marcar FALLIDO.
- CUANDO todos los destinatarios válidos están enviados EL SISTEMA DEBERÁ pasar la notificación a COMPLETADA. CUANDO alguno falló EL SISTEMA DEBERÁ pasarla a CON_FALLAS.
- EL SISTEMA NO DEBERÁ enviar a un colaborador sin consentimiento vigente (CC-REQ-157).

**CC-REQ-112. Estados de la notificación.** Origen: `02_modelo_datos.md` §2, `cv1_08`.
- EL SISTEMA DEBERÁ manejar los estados BORRADOR, PROGRAMADA, ENVIANDO, COMPLETADA, CON_FALLAS y CANCELADA.
- `cv1_08` usa "COMPLETADO" y "PROGRAMADO". Prevalece el modelo y los diseños deben alinearse (PQ-14).
- Ningún caso de uso define cómo se cancela una notificación (PQ-14).

**CC-REQ-113. Respaldo por correo (ejecución).** Origen: UC-25, RF-40.
- CUANDO pasan 24 horas sin estado ENTREGADO y el respaldo está activo y el colaborador tiene correo EL SISTEMA DEBERÁ enviar el mismo aviso por correo y registrar el canal CORREO.
- CUANDO no hay correo registrado EL SISTEMA DEBERÁ marcar el destinatario FALLIDO y avisar a RH.

**CC-REQ-114. Estados de entrega y lectura.** Origen: UC-26, RF-39.
- CUANDO Meta envía un estado EL SISTEMA DEBERÁ validar la firma del mensaje, actualizar el destinatario (ENTREGADO, LEIDO o RESPONDIO) y actualizar los contadores de la notificación.
- EL SISTEMA DEBERÁ hacer que los estados solo avancen: ENVIADO, ENTREGADO, LEIDO.
- CUANDO el estado es desconocido EL SISTEMA DEBERÁ registrarlo en la bitácora técnica sin cambiar el estado del destinatario.
- CUANDO la firma no es válida EL SISTEMA DEBERÁ rechazar el mensaje (CC-REQ-158).

**CC-REQ-115. Respuestas vinculadas.** Origen: UC-27, RF-41.
- CUANDO un colaborador responde una notificación EL SISTEMA DEBERÁ vincular la respuesta a la notificación original y marcar al destinatario como RESPONDIO.
- EL SISTEMA DEBERÁ permitir a RH asignar la conversación a una persona de RH.

**CC-REQ-116. Responder desde el sistema.** Origen: UC-27 pasos 3 y A1, RF-37.
- CUANDO RH escribe una respuesta dentro de la ventana de 24 horas EL SISTEMA DEBERÁ enviarla y registrarla en el chat.
- CUANDO han pasado más de 24 horas desde el último mensaje del colaborador EL SISTEMA DEBERÁ permitir únicamente una plantilla aprobada.
- El modelo no tiene tablas para los mensajes del chat ni para la asignación a RH (PQ-14).

**CC-REQ-117. Plantillas de mensaje.** Origen: UC-28, RF-42, `02_modelo_datos.md` §2.
- CUANDO RH crea una plantilla con nombre, categoría y texto con variables EL SISTEMA DEBERÁ guardarla en BORRADOR y permitir enviarla a revisión de Meta (EN_REVISION).
- CUANDO Meta responde EL SISTEMA DEBERÁ actualizar el estado a APROBADA o RECHAZADA.
- CUANDO la plantilla es RECHAZADA EL SISTEMA DEBERÁ mostrar el motivo y permitir editarla y reenviarla a revisión.
- EL SISTEMA DEBERÁ permitir duplicar una plantilla.
- El motivo del rechazo no tiene campo en el modelo (PQ-14).
- Quién crea las plantillas y el catálogo inicial son [POR CONFIRMAR] (PQ-11).

**CC-REQ-118. Reintento de fallidos.** Origen: UC-29, RF-39, `cv1_10`.
- CUANDO RH pulsa Reintentar fallidos en una notificación CON_FALLAS EL SISTEMA DEBERÁ enviar solo a los destinatarios en FALLIDO.
- EL SISTEMA NO DEBERÁ reenviar a quien ya recibió el mensaje.
- CUANDO el celular no es válido EL SISTEMA NO DEBERÁ reintentar y deberá marcar al colaborador para corrección.

**CC-REQ-119. Detalle del envío.** Origen: RF-39, `cv1_10`.
- CUANDO RH abre el detalle EL SISTEMA DEBERÁ mostrar los totales (seleccionados, enviados, entregados, leídos, fallidos), los excluidos con su motivo, la tabla de destinatarios con su estado y hora, el mensaje enviado, la plantilla con su estado de Meta, la audiencia y una línea de tiempo.
- CUANDO el destinatario respondió EL SISTEMA DEBERÁ ofrecer el acceso a la conversación.

**CC-REQ-120. Listado de notificaciones.** Origen: RF-39, `cv1_08`.
- CUANDO RH abre Notificaciones EL SISTEMA DEBERÁ listar los envíos con audiencia, plantilla, destinatarios, estado y fecha, en las pestañas Envíos, Programadas y Borradores.
- EL SISTEMA DEBERÁ mostrar los indicadores del mes (enviadas, entregadas, leídas y fallidas). Estos indicadores no aparecen en los RF (PQ-17).

**CC-REQ-121. Celular enmascarado.** Origen: `cv1_10`, RNF-01.
- CUANDO el detalle del envío muestra el celular EL SISTEMA DEBERÁ mostrarlo enmascarado, con solo los últimos cuatro dígitos visibles.

**CC-REQ-122. Duplicar envío.** Origen: `cv1_10` (botón "Duplicar envío").
- CUANDO RH pulsa Duplicar envío EL SISTEMA DEBERÁ crear un borrador con la misma plantilla y criterios. [POR CONFIRMAR] (PQ-17: no aparece en ningún UC ni RF.)

---

## 4. Requisitos transversales

Un requisito que afecta a varios módulos vive aquí y se referencia desde cada módulo.

**CC-REQ-150. Aislamiento por empresa.** Origen: UC-02 y UC-07 (reglas), CC-ASM-006.
- CUANDO un usuario consulta o modifica datos EL SISTEMA DEBERÁ limitar el acceso a los datos de su empresa (`empresa_id`).
- Aplica a CC-REQ-011, 012, 031, 032 y 087.

**CC-REQ-151. Cifrado de datos sensibles.** Origen: decisión 5, RNF-10, `02_modelo_datos.md` §1.
- CUANDO se guarda sueldo, NSS, CURP, RFC o un campo marcado `es_sensible` EL SISTEMA DEBERÁ cifrarlo con una clave administrada por KMS.
- EL SISTEMA DEBERÁ tratar estos datos como sensibles desde v1.

**CC-REQ-152. Celular cifrado y hash.** Origen: RNF-01, `02_modelo_datos.md` §1.
- CUANDO se guarda un celular EL SISTEMA DEBERÁ guardarlo cifrado (`celular_cifrado`) y calcular `celular_hash` para búsquedas y unicidad.

**CC-REQ-153. Visibilidad de datos sensibles.** Origen: decisión 5, Ronda P2.
- CUANDO un usuario del rol RH consulta un dato sensible EL SISTEMA DEBERÁ mostrarlo.
- EL SISTEMA NO DEBERÁ mostrar datos sensibles a personas sin sesión, ni a terceros (CC-REQ-090), ni al colaborador por WhatsApp salvo en su propia constancia.
- Cuando existan más roles, la visibilidad se restringirá por permiso. En v1 no hay permiso separado.

**CC-REQ-154. Eventos de bitácora.** Origen: decisión 9, RNF-03, UC-03.
- EL SISTEMA DEBERÁ registrar en la bitácora: inicio de sesión, altas, cambios, bajas y reactivaciones de colaboradores, cambios de campos, cargas, cambios de plantillas, generación y entrega de constancias, descargas y reenvíos, consultas de datos sensibles y envíos de notificaciones con su audiencia exacta.
- Cada registro debe guardar usuario (o sistema), acción, entidad, identificador, fecha y hora e IP.

**CC-REQ-155. Inmutabilidad de la bitácora.** Origen: UC-03 reglas.
- EL SISTEMA NO DEBERÁ permitir editar ni borrar registros de la bitácora.

**CC-REQ-156. Bitácora sin datos personales y consulta de detalle.** Origen: UC-03 A1, `02_modelo_datos.md` §1.
- EL SISTEMA NO DEBERÁ guardar datos personales en el texto de los registros.
- CUANDO RH consulta el detalle de un colaborador o un dato sensible EL SISTEMA DEBERÁ registrar esa consulta.
- El modelo de `BITACORA` no tiene campo para el detalle de la acción ni para la audiencia (PQ-14).

**CC-REQ-157. Consentimiento y estatus BAJA.** Origen: decisiones 10 y 11, UC-06 A1, UC-24.
- CUANDO un colaborador está en BAJA o no tiene consentimiento vigente EL SISTEMA NO DEBERÁ generarle constancias ni enviarle notificaciones, aunque RH lo pida.
- Aplica a CC-REQ-072, 105 y 111.

**CC-REQ-158. Seguridad de la integración con Meta.** Origen: UC-26 paso 2, arquitectura de referencia.
- CUANDO llega un mensaje al webhook de Meta EL SISTEMA DEBERÁ validar su firma antes de procesarlo.
- EL SISTEMA DEBERÁ guardar las credenciales de Meta fuera del código y de la base de datos (Secrets Manager).

**CC-REQ-159. Aviso de privacidad y LFPDPPP.** Origen: RNF-08, `03_flujo_whatsapp.md` §5.
- CUANDO el colaborador inicia una conversación EL SISTEMA DEBERÁ mostrar primero el aviso de privacidad, con la finalidad del tratamiento y quién trata los datos, antes de pedir cualquier dato.
- El texto lo debe validar el área jurídica. [POR CONFIRMAR] (PQ-12)

**CC-REQ-160. Retención y borrado a solicitud del titular.** Origen: RNF-08, LFPDPPP.
- Los insumos no definen plazo de retención ni procedimiento de atención a solicitudes del titular. [POR CONFIRMAR] (PQ-12)

**CC-REQ-161. Eliminación lógica.** Origen: `02_modelo_datos.md` §1 y §3.
- CUANDO se elimina un colaborador, campo, organización, planta o plantilla EL SISTEMA DEBERÁ marcarlo como inactivo o eliminado y conservar el historial.

**CC-REQ-162. Datos personales en errores y registros técnicos.** Origen: UC-03 reglas, `02_modelo_datos.md` §1.
- EL SISTEMA NO DEBERÁ incluir datos personales en mensajes de error, reportes de errores ni registros técnicos.

**CC-REQ-164. Avisos a RH por fallas operativas.** Origen: RF-27, UC-14, UC-16, UC-25.
- CUANDO una solicitud falla por campos obligatorios vacíos, verificación bloqueada, entrega fallida, colaborador en BAJA o sin consentimiento, o error persistente de generación EL SISTEMA DEBERÁ avisar a RH.
- El canal del aviso (alerta en el dashboard, correo, otro) es [POR CONFIRMAR] (PQ-17).

---

## 5. Requisitos no funcionales

| ID | Categoría | Requisito | Origen |
|---|---|---|---|
| CC-NFR-001 | Rendimiento | La generación de un PDF debe tardar menos de 5 segundos en el percentil 95. | RNF-05 |
| CC-NFR-002 | Rendimiento | El tiempo de respuesta de listados, búsquedas, carga de 2,000 filas y respuesta al webhook de Meta es [POR CONFIRMAR]. | PQ-20 |
| CC-NFR-003 | Capacidad | El sistema debe soportar hasta 100 campos y 10,000 colaboradores por empresa, y 500 constancias al mes. | RNF-09 |
| CC-NFR-004 | Capacidad | La carga masiva acepta hasta 2,000 filas por archivo. | UC-08 A2, plantilla v1.3 |
| CC-NFR-005 | Disponibilidad | Disponibilidad objetivo: [POR CONFIRMAR]. La base de datos opera en RDS Multi-AZ. | Arquitectura, PQ-15 |
| CC-NFR-006 | Recuperación | Región principal, región de recuperación, RTO y RPO: [POR CONFIRMAR]. Hay respaldo con restauración a un punto en el tiempo (PITR). | Arquitectura, PQ-15 |
| CC-NFR-007 | Fiabilidad | Si falla la generación o el envío, el sistema reintenta de forma automática y no pierde la solicitud. | RNF-06 |
| CC-NFR-008 | Seguridad | Acceso por CloudFront con WAF. Credenciales de Meta en Secrets Manager. Datos sensibles con KMS. Roles de IAM de mínimo privilegio. | Arquitectura |
| CC-NFR-009 | Seguridad | Los PDF de constancia se guardan con Object Lock. Las cargas de Excel son temporales en S3 y su plazo de conservación es [POR CONFIRMAR]. | Decisión 7, arquitectura, PQ-12 |
| CC-NFR-010 | Observabilidad | Registro y métricas en CloudWatch, auditoría de la cuenta AWS en CloudTrail y alertas a RH por SNS. Los umbrales de alarma son [POR CONFIRMAR]. | Arquitectura |
| CC-NFR-011 | Costo | El presupuesto de costo es [POR CONFIRMAR]. El costo por conversación de WhatsApp debe revisarse con finanzas. | PQ-15, `03_flujo_whatsapp.md` §4 |
| CC-NFR-012 | Mantenibilidad | Cada servicio de backend es dueño de sus tablas. Los campos se configuran sin intervención de un desarrollador. | Arquitectura, RF-06 |
| CC-NFR-013 | Mantenibilidad | La infraestructura se define como código con AWS CDK (decisión del cliente en la fase de diseño). El lenguaje del CDK (propuesta: Python) está por confirmar en `design.md`. | PQ-15, `design.md` §17 |
| CC-NFR-014 | Localización | La interfaz está en español y la zona horaria es de México (America/Mexico_City). | RNF-07 |
| CC-NFR-015 | Cumplimiento | El tratamiento de datos personales cumple la LFPDPPP. | RNF-08 |
| CC-NFR-016 | Procesos asíncronos | La generación de PDF, las cargas masivas y los mensajes de WhatsApp se procesan en segundo plano mediante colas. | Arquitectura |
| CC-NFR-017 | Extensibilidad | El modelo de usuarios no debe impedir agregar roles después. | Ronda P2 |

---

## 6. Interfaces de usuario

Las pantallas están en `disenos/svg/cv1_01` a `cv1_10` y `disenos/png/01_login.png`. Los criterios describen el comportamiento esperado.

### 6.1 `01_login`: Inicio de sesión (CC-REQ-001 a 008)

- El diseño muestra correo, contraseña, botón de iniciar sesión y enlace de recuperación. **No tiene el paso del código MFA que exige UC-01.** El requisito CC-REQ-002 incluye ese paso. La diferencia con el diseño es [POR CONFIRMAR] (PQ-09).
- CUANDO el usuario completa correo y contraseña la pantalla DEBERÁ pasar a un paso de captura del código MFA.
- La pantalla DEBERÁ dar acceso al formulario de registro de usuarios RH (CC-REQ-007). El diseño de ese formulario no existe (PQ-09).
- Este diseño no se pudo abrir durante la redacción; se usa la descripción del contexto del producto.

### 6.2 `cv1_01`: Dashboard (CC-REQ-011 a 014)

- Tarjetas: activos, constancias este mes, en proceso, plantillas activas.
- Tablas: solicitudes recientes (con estado) y constancias recientes (con acción Descargar).
- Panel de alertas con acción Revisar.
- Botón "Ver historial".

### 6.3 `cv1_02`: Listado de colaboradores (CC-REQ-031 a 033)

- Buscador, filtros de organización, planta y estatus, selector de columnas y paginación.
- Botones "Configurar campos" y "Nuevo colaborador".
- CUANDO el usuario cambia columnas el contador "Columnas (8 de 19)" DEBERÁ reflejar los campos activos. Con los 23 campos de `cv1_04` y uno inactivo el total no coincide con 19 (PQ-17).

### 6.4 `cv1_03`: Formulario de colaborador (CC-REQ-020 a 025)

- Sección "Datos fijos del sistema" con los once campos marcados con asterisco.
- Sección "Campos adicionales" generada desde la configuración, con los sensibles marcados "Sensible".
- Casilla de consentimiento.
- CUANDO falta un campo obligatorio, repetido o con formato inválido la pantalla DEBERÁ marcarlo y no guardar.

### 6.5 `cv1_04`: Configuración de campos (CC-REQ-045 a 053)

- Pestañas Todos, Sugeridos y Personalizados. Fila resumen de los once campos fijos, no editables.
- Panel "Editar campo" con nombre visible, clave, código interno, tipo, opciones con descripción, obligatorio, sensible y activo.
- CUANDO el campo está usado en plantillas la pantalla DEBERÁ mostrar en cuáles ("Usada en 1 plantilla").

### 6.6 `cv1_05`: Plantillas de constancia (CC-REQ-064, 069, 070)

- Pestañas Plantillas e Historial. Tabla con versión, fecha, constancias emitidas y estado (ACTIVA o BORRADOR).
- Acciones Editar, Duplicar y Eliminar. Las acciones Activar y Desactivar de UC-13 no aparecen en este diseño (PQ-17).

### 6.7 `cv1_06`: Editor de plantilla (CC-REQ-060 a 068)

- Panel de variables agrupadas (colaborador, organización, sensibles, sistema) con búsqueda.
- Barra de formato, inserción de logotipo y área del documento.
- Vista previa con colaborador de prueba y panel de validación con avisos (por ejemplo, "rfc, nss y curp son sensibles").
- Lista de versiones con la activa y la acción Restaurar.
- Botones "Guardar borrador" y "Publicar vN".

### 6.8 `cv1_07`: Historial de constancias (CC-REQ-087 a 089)

- Filtros de búsqueda, fechas, plantilla y estado.
- Columna Acción: Descargar o, para FALLIDA, Reenviar.
- CUANDO la constancia está PENDIENTE la pantalla NO DEBERÁ ofrecer descarga (CC-REQ-088).

### 6.9 `cv1_08`: Listado de notificaciones (CC-REQ-120)

- Indicadores del mes, pestañas Envíos, Programadas y Borradores, y tabla de envíos.
- Botones "Plantillas de mensaje" y "Nueva notificación".

### 6.10 `cv1_09`: Nueva notificación (CC-REQ-100 a 110)

- Selector de modo: Por criterios, Individual, Grupo guardado. Criterios con lógica Y u O y antigüedad en años.
- Selector de plantilla aprobada, variables y vista previa.
- **Embudo de exclusiones.** CUANDO RH define la audiencia la pantalla DEBERÁ mostrar seleccionados, con consentimiento, estatus ACTIVO y celular válido, y un resumen de excluidos por motivo (por ejemplo, "5 sin consentimiento y 2 con estatus BAJA").
- Selector Enviar ahora o Programar, con fecha, hora y leyenda del horario permitido.
- Casilla de respaldo por correo con el conteo de colaboradores con correo.
- El botón final DEBERÁ indicar el número de destinatarios válidos ("Enviar a 54 colaboradores") y estar deshabilitado si no hay ninguno.

### 6.11 `cv1_10`: Detalle del envío (CC-REQ-118 a 122)

- Totales del resultado, nota de excluidos, tabla de destinatarios con celular enmascarado, estado y acción (Ver chat o Reintentar).
- Mensaje enviado con su plantilla, conteo de respuestas, audiencia y línea de tiempo.
- Botones "Duplicar envío" y "Reintentar fallidos (n)".
- La línea de tiempo del diseño muestra un evento de las 16:12 antes de uno de las 16:03. DEBE ordenarse cronológicamente (PQ-17).

---

## 7. Reglas de negocio consolidadas

| ID | Regla | Requisitos |
|---|---|---|
| RN-01 | El número de empleado es único por empresa y es la llave de la carga masiva. | CC-REQ-023, 037 |
| RN-02 | El celular tiene 10 dígitos y es único por empresa (por hash). | CC-REQ-024, 025 |
| RN-03 | Los once campos fijos son obligatorios, incluido tipo de empleado. | CC-REQ-020, 042 |
| RN-04 | La carga actualiza por número de empleado y no modifica ni da de baja a quien no aparece. | CC-REQ-037 |
| RN-05 | Los colaboradores cargados por Excel quedan sin consentimiento. | CC-REQ-041 |
| RN-06 | Sueldo, NSS, CURP y RFC (y cualquier campo marcado) se cifran y se muestran solo a quien tiene permiso (en v1, el rol RH). | CC-REQ-151, 153 |
| RN-07 | Un campo con valores no cambia de tipo ni se elimina. Un campo sugerido solo se desactiva. Los campos fijos no se editan. | CC-REQ-048 a 051 |
| RN-08 | El código interno de un campo no cambia. | CC-REQ-046 |
| RN-09 | Una organización o planta con colaboradores solo se desactiva. | CC-REQ-043, 044 |
| RN-10 | Las versiones de plantilla publicadas son inmutables. Restaurar crea una versión nueva. | CC-REQ-066, 068 |
| RN-11 | Una constancia emitida no cambia: conserva versión, snapshot, hash y PDF con Object Lock. | CC-REQ-081, 082 |
| RN-12 | El folio es único por empresa. | CC-REQ-079 |
| RN-13 | Una plantilla con constancias emitidas se elimina solo de forma lógica. | CC-REQ-069 |
| RN-14 | El bot no muestra datos antes de verificar. Máximo tres intentos fallidos. El código caduca a los 10 minutos. | CC-REQ-073, 074 |
| RN-15 | El colaborador solo recibe sus propias constancias. | CC-REQ-073, 153 |
| RN-16 | BAJA o sin consentimiento vigente: no hay constancias ni notificaciones. | CC-REQ-157 |
| RN-17 | La entrega de la constancia es un enlace de un solo uso válido 24 horas [POR CONFIRMAR]. Falla de entrega: un reintento y después FALLIDA. | CC-REQ-084, 085 |
| RN-18 | Los mensajes iniciados por la empresa solo usan plantillas aprobadas por Meta. Texto libre solo dentro de la ventana de 24 horas. | CC-REQ-104, 116 |
| RN-19 | Los envíos de notificaciones solo se programan o ejecutan de 08:00 a 20:00 (hora de la empresa) [POR CONFIRMAR]. El envío inmediato fuera de horario exige confirmación explícita. | CC-REQ-109 |
| RN-20 | Los excluidos de un envío quedan registrados con su motivo. | CC-REQ-105, 106 |
| RN-21 | Los estados de entrega solo avanzan: ENVIADO, ENTREGADO, LEIDO. | CC-REQ-114 |
| RN-22 | No se reenvía a quien ya recibió el mensaje. | CC-REQ-118 |
| RN-23 | El respaldo por correo solo aplica a quien tiene correo y si RH lo activó. | CC-REQ-110, 113 |
| RN-24 | La bitácora no se edita ni se borra y no guarda datos personales en su texto. | CC-REQ-155, 156 |
| RN-25 | El MFA es obligatorio para todos los usuarios RH. La sesión inactiva más de 30 minutos se cierra. | CC-REQ-002, 004 |
| RN-26 | Una cuenta registrada no accede a datos hasta cumplir el mecanismo de autorización [POR CONFIRMAR]. | CC-REQ-008 |
| RN-27 | La eliminación es lógica en colaboradores, campos, organizaciones, plantas y plantillas. | CC-REQ-161 |

---

## 8. Preguntas abiertas

Las propuestas ya están reflejadas en el texto como [POR CONFIRMAR]. Las que pudieron resolverse en la ronda previa se marcan como resueltas.

| ID | Pregunta | Propuesta o estado | Afecta |
|---|---|---|---|
| PQ-01 | Tipo de empleado: ¿obligatorio u opcional? | **Resuelta (Ronda P3): obligatorio.** Falta ajustar el encabezado de la plantilla de Excel v1.3 y registrar que la hoja Instrucciones dice "Versión 1.2" mientras el archivo es v1.3. | CC-REQ-020, 042 |
| PQ-02 | Volumen de carga: 2,000 filas por archivo contra 10,000 colaboradores. | Propuesta: mantener 2,000 y permitir varios archivos (análisis §7.2). | CC-REQ-038 |
| PQ-03 | Entrega del PDF: enlace de un solo uso (24 h) o archivo adjunto. | Propuesta: enlace (análisis §7.3). `flujo_whatsapp.dot` no lo precisa. | CC-REQ-084 |
| PQ-04 | Consentimiento: ¿tiene fecha de registro y caducidad ("vencido" en UC-14)? El modelo solo guarda un booleano. | Propuesta: registrar fecha de consentimiento. Caducidad sin definir. Quedó resuelto que los cargados por Excel entran sin consentimiento (Ronda P4). | CC-REQ-022, 041 |
| PQ-05 | Verificación del colaborador. | Propuesta: código de seis dígitos y últimos cuatro del NSS, o fecha de ingreso dd/mm si no hay NSS (análisis §7.4). El diagrama del flujo solo menciona el NSS. | CC-REQ-073 |
| PQ-06 | Horario de envíos. | Propuesta: 08:00 a 20:00 en la zona horaria de la empresa. | CC-REQ-109 |
| PQ-07 | Cuenta de WhatsApp Business. | **Parcial (Ronda P7):** la cuenta ya existe. Falta el procedimiento de vinculación y sincronización, que se entregará después, y si el número está verificado por Meta. | CC-ASM-007 |
| PQ-08 | Una empresa o varias. | Propuesta: una empresa por instancia, con `empresa_id` en todas las tablas (análisis §7.1). | CC-ASM-006, 1.2 |
| PQ-09 | Diseños pendientes de login: paso MFA y formulario de registro. | `01_login.png` no tiene MFA ni registro. Hay que actualizar el diseño. | CC-REQ-002, 007 |
| PQ-10 | Registro y cuentas de usuarios RH. | **Parcial (Ronda P1):** habrá formulario de registro junto al login, que crea el usuario en Cognito. Faltan: campos del formulario; mecanismo que autoriza a quién se le concede acceso (código de invitación, dominio de correo, aprobación u otro); cómo se asocia la cuenta a la empresa; quién desactiva cuentas; flujo de recuperación de contraseña; número de intentos y duración del bloqueo. **Riesgo alto:** con rol único RH que ve datos sensibles, un registro abierto expondría datos personales. | CC-REQ-003, 006 a 010 |
| PQ-11 | Plantillas de mensaje de Meta: ¿quién las crea, cuánto tarda la aprobación y hay catálogo inicial? Incluye las plantillas para reenvíos fuera de la ventana de 24 horas y el logotipo oficial de la razón social. | Sin propuesta en los insumos. | CC-REQ-062, 085, 117 |
| PQ-12 | Aviso de privacidad (texto y validación jurídica), alcance del consentimiento (constancias y notificaciones), obligatoriedad del correo para el respaldo y plazo de conservación de datos y de cargas de Excel. | Sin propuesta en los insumos. | CC-REQ-022, 110, 159, 160, CC-NFR-009 |
| PQ-13 | RFC: `02_modelo_datos.md` §4 dice 12 o 13 caracteres. Plantilla y diseño dicen 13 para el colaborador y 12 o 13 para la organización. | Propuesta: 13 para el colaborador y 12 o 13 para la organización. | CC-REQ-025 |
| PQ-14 | Brechas del modelo `.dot` para la fase de diseño: fecha de baja; estado cancelada de constancia y cómo se cancela; cómo se cancela una carga o una notificación; estado inicial de campos sugeridos; almacenamiento de borradores de plantilla; mensajes del chat y asignación a RH; motivo de rechazo de plantilla de mensaje; detalle y audiencia en la bitácora; fecha de consentimiento; códigos de verificación y enlaces de un solo uso; `ORGANIZACION` repite "registro_patronal" en dos filas del diagrama; Excel menciona "Sucursal" en catálogos y el modelo solo tiene `PLANTA`. | Se resuelven en `design.md`. | CC-REQ-029, 035, 049, 064, 090, 112, 116, 117, 156 |
| PQ-15 | Organizaciones y carga: ¿la carga masiva crea o actualiza organizaciones (hoja Organizaciones)? Faltan `ciudad` y `correo_firmante` en esa hoja. Pendientes de arquitectura: región principal, región de recuperación, RTO, RPO, disponibilidad, herramienta de IaC y presupuesto. | Sin propuesta. | CC-REQ-043, CC-NFR-005, 006, 011, 013 |
| PQ-16 | Formato de folio y si reinicia por año. | Los diseños muestran `CG-AAAA-NNNN`. | CC-REQ-079 |
| PQ-17 | Discrepancias de diseños y documentos: cambio de clave de campo (pide confirmación o solo advierte); `{{empresa}}`; palabras clave del bot; formato "00/100 MN" duplicado en plantilla de consulado; botón Descargar en constancia PENDIENTE; canal "Respuesta dentro de 24 h" en notificación nueva; indicadores del listado de notificaciones; "Duplicar envío"; contador de columnas; botones Activar y Desactivar de plantillas; orden de la línea de tiempo; canal de avisos a RH. | Se corrigen en diseños o en `design.md` tras aprobar este documento. | CC-REQ-052, 061, 071, 078, 088, 104, 120, 122, 164 |
| PQ-18 | Factores de conversión del sueldo mensual y contradicción del análisis sobre "Notificaciones masivas" fuera de alcance. | Propuesta de factores: semanal × 52/12, catorcenal × 26/12, quincenal × 2, mensual × 1 (debe validarlo contabilidad o RH). Notificaciones se trata como dentro de alcance. | CC-REQ-078, 1.2 |
| PQ-19 | Código QR y verificación pública. | Propuesta: sí, con nombre, folio, fecha y estatus, sin datos sensibles (análisis §7.5). | CC-REQ-080, 090 |
| PQ-20 | Valores sin definir: tiempo de respuesta de listados y carga, reintentos de generación de PDF, tiempo para considerar abandono y umbrales de alarma. | Sin propuesta. | CC-REQ-083, 091, CC-NFR-002, 010 |
| PQ-21 | Diferencia de reintentos: la constancia reintenta la entrega una vez (dos intentos en total) y las notificaciones hasta dos veces. | Se tratan como flujos distintos. Confirmar que es intencional. | CC-REQ-085, 111 |

---

## 9. Matriz de trazabilidad

El campo "UC" es "N/D" donde el requisito no tiene caso de uso. UC-30 es una propuesta para el registro de usuarios (Ronda P1).

| CC-REQ | UC | RF / RNF | Pantalla | Tabla o entidad |
|---|---|---|---|---|
| CC-REQ-001 | UC-01 | RF-01 | 01_login | USUARIO |
| CC-REQ-002 | UC-01 | RF-01 | 01_login | USUARIO |
| CC-REQ-003 | UC-01 | RF-01 | 01_login | N/D (Cognito) |
| CC-REQ-004 | UC-01 | RF-01 | N/D | N/D (sesión) |
| CC-REQ-005 | UC-01 | RNF-03 | N/D | BITACORA |
| CC-REQ-006 | UC-01 (relacionado) | RF-01 | 01_login | N/D (Cognito) |
| CC-REQ-007 | UC-30 (propuesto) | RF-01 | 01_login | USUARIO |
| CC-REQ-008 | UC-30 (propuesto) | RF-01, RNF-10 | N/D | USUARIO, EMPRESA |
| CC-REQ-009 | UC-01 | RF-01, RNF-10 | N/D | USUARIO |
| CC-REQ-010 | UC-30 (propuesto) | N/D | N/D | USUARIO |
| CC-REQ-011 | UC-02 | RF-02 | cv1_01 | COLABORADOR, CONSTANCIA_GENERADA, SOLICITUD_CONSTANCIA, PLANTILLA_CONSTANCIA |
| CC-REQ-012 | UC-02 | RF-03 | cv1_01 | SOLICITUD_CONSTANCIA, CONSTANCIA_GENERADA |
| CC-REQ-013 | UC-02 | RF-27 | cv1_01 | COLABORADOR, CONSTANCIA_GENERADA |
| CC-REQ-014 | UC-02 | RF-02 | cv1_01 | N/D |
| CC-REQ-015 | UC-03 | RNF-03 | N/D | BITACORA |
| CC-REQ-020 | UC-04 | RF-04, RF-05, RF-13 | cv1_03 | COLABORADOR, ORGANIZACION, PLANTA |
| CC-REQ-021 | UC-04 | RF-06, RF-10 | cv1_03 | CAMPO_COLABORADOR, VALOR_CAMPO |
| CC-REQ-022 | UC-04 | RF-04 | cv1_03 | COLABORADOR |
| CC-REQ-023 | UC-04 | RF-04 | cv1_03 | COLABORADOR |
| CC-REQ-024 | UC-04 | RF-04 | cv1_03 | COLABORADOR |
| CC-REQ-025 | UC-04, UC-08 | RF-10, RF-31, RF-34 | cv1_03 | CAMPO_COLABORADOR, VALOR_CAMPO |
| CC-REQ-026 | UC-05 | RF-04, RF-10 | cv1_03 | COLABORADOR, BITACORA |
| CC-REQ-027 | UC-05 | RF-04 | cv1_03 | COLABORADOR |
| CC-REQ-028 | UC-05 | RF-04 | cv1_03 | COLABORADOR, AUDIENCIA |
| CC-REQ-029 | UC-06 | RF-04 | cv1_02 | COLABORADOR, BITACORA |
| CC-REQ-030 | UC-06 | RF-04 | cv1_02 | COLABORADOR, BITACORA |
| CC-REQ-031 | UC-07 | RF-09 | cv1_02 | COLABORADOR, CAMPO_COLABORADOR |
| CC-REQ-032 | UC-07 | RF-11 | cv1_02 | COLABORADOR, VALOR_CAMPO |
| CC-REQ-033 | UC-07 | RF-11 | cv1_02 | N/D |
| CC-REQ-034 | UC-08, UC-09 | RF-32 | cv1_02 | CAMPO_COLABORADOR |
| CC-REQ-035 | UC-08 | RF-30 | cv1_02 | CARGA_COLABORADORES |
| CC-REQ-036 | UC-08 | RF-31 | N/D | FILA_CARGA |
| CC-REQ-037 | UC-08 | RF-30 | N/D | COLABORADOR, FILA_CARGA |
| CC-REQ-038 | UC-08 | RF-30, RNF-09 | N/D | CARGA_COLABORADORES |
| CC-REQ-039 | UC-08 | RF-30 | N/D | CARGA_COLABORADORES |
| CC-REQ-040 | UC-08 | RF-31 | N/D | CARGA_COLABORADORES, FILA_CARGA |
| CC-REQ-041 | UC-04, UC-08 | RF-30 | N/D | COLABORADOR |
| CC-REQ-042 | UC-08 | RF-05, RF-31 | N/D | COLABORADOR, FILA_CARGA |
| CC-REQ-043 | UC-10 | RF-29 | N/D | ORGANIZACION |
| CC-REQ-044 | UC-10 | RF-29 | N/D | PLANTA |
| CC-REQ-045 | UC-09 | RF-06, RF-34 | cv1_04 | CAMPO_COLABORADOR |
| CC-REQ-046 | UC-09 | RF-34 | cv1_04 | CAMPO_COLABORADOR |
| CC-REQ-047 | UC-09 | RF-07, RF-08 | cv1_04 | CAMPO_COLABORADOR, OPCION_CAMPO |
| CC-REQ-048 | UC-09 | RF-12 | cv1_04 | CAMPO_COLABORADOR, VALOR_CAMPO |
| CC-REQ-049 | UC-09 | RF-33 | cv1_04 | CAMPO_COLABORADOR |
| CC-REQ-050 | UC-09 | RF-12 | cv1_04 | CAMPO_COLABORADOR, VALOR_CAMPO |
| CC-REQ-051 | UC-09 | RF-05 | cv1_04 | COLABORADOR |
| CC-REQ-052 | UC-09 | RF-19, RF-34 | cv1_04 | CAMPO_COLABORADOR, VERSION_PLANTILLA |
| CC-REQ-060 | UC-11 | RF-14 | cv1_06 | VERSION_PLANTILLA |
| CC-REQ-061 | UC-11 | RF-15 | cv1_06 | CAMPO_COLABORADOR, ORGANIZACION |
| CC-REQ-062 | UC-11 | RF-14 | cv1_06 | ORGANIZACION |
| CC-REQ-063 | UC-11 | RF-16 | cv1_06 | COLABORADOR, VALOR_CAMPO |
| CC-REQ-064 | UC-11 | RF-14 | cv1_05, cv1_06 | PLANTILLA_CONSTANCIA, VERSION_PLANTILLA |
| CC-REQ-065 | UC-11, UC-12 | RF-19 | cv1_06 | CAMPO_COLABORADOR, VERSION_PLANTILLA |
| CC-REQ-066 | UC-12 | RF-17 | cv1_06 | VERSION_PLANTILLA |
| CC-REQ-067 | UC-12 | RF-19 | cv1_06 | VERSION_PLANTILLA, CAMPO_COLABORADOR |
| CC-REQ-068 | UC-12 (relacionado) | RF-17 | cv1_06 | VERSION_PLANTILLA |
| CC-REQ-069 | UC-13 | RF-18 | cv1_05 | PLANTILLA_CONSTANCIA |
| CC-REQ-070 | UC-13 | RF-18, RF-24 | cv1_05 | PLANTILLA_CONSTANCIA |
| CC-REQ-071 | UC-14 | RF-22 | N/D | CONVERSACION_WHATSAPP, SOLICITUD_CONSTANCIA |
| CC-REQ-072 | UC-14 | RF-22, RF-27, RNF-02 | N/D | COLABORADOR, CONVERSACION_WHATSAPP |
| CC-REQ-073 | UC-15 | RF-23 | N/D | CONVERSACION_WHATSAPP |
| CC-REQ-074 | UC-15 | RF-23 | N/D | CONVERSACION_WHATSAPP |
| CC-REQ-075 | UC-14 | RF-24 | N/D | PLANTILLA_CONSTANCIA, SOLICITUD_CONSTANCIA |
| CC-REQ-076 | UC-14 | RF-27 | N/D | SOLICITUD_CONSTANCIA |
| CC-REQ-077 | UC-16 | RF-25 | N/D | SOLICITUD_CONSTANCIA, CONSTANCIA_GENERADA |
| CC-REQ-078 | UC-16 | RF-25 | cv1_06 | CONSTANCIA_GENERADA |
| CC-REQ-079 | UC-16 | RF-28 | cv1_07 | CONSTANCIA_GENERADA |
| CC-REQ-080 | UC-16 | RF-28 | N/D | CONSTANCIA_GENERADA |
| CC-REQ-081 | UC-16 | RNF-04 | N/D | CONSTANCIA_GENERADA |
| CC-REQ-082 | UC-05, UC-16 | RF-25, RNF-04 | N/D | CONSTANCIA_GENERADA |
| CC-REQ-083 | UC-16 | RNF-06 | N/D | SOLICITUD_CONSTANCIA |
| CC-REQ-084 | UC-14 | RF-26 | N/D | CONSTANCIA_GENERADA, SOLICITUD_CONSTANCIA |
| CC-REQ-085 | UC-14 | RF-26, RF-27 | cv1_07 | CONSTANCIA_GENERADA, SOLICITUD_CONSTANCIA |
| CC-REQ-086 | UC-14, UC-15 | RF-22 | N/D | SOLICITUD_CONSTANCIA, CONVERSACION_WHATSAPP |
| CC-REQ-087 | UC-17 | RF-20, RF-21 | cv1_07 | CONSTANCIA_GENERADA, VERSION_PLANTILLA |
| CC-REQ-088 | UC-17 | RF-20 | cv1_07 | CONSTANCIA_GENERADA, BITACORA |
| CC-REQ-089 | UC-18 | RF-26, RF-27 | cv1_07 | CONSTANCIA_GENERADA, BITACORA |
| CC-REQ-090 | UC-19 | N/D (propuesta) | N/D | CONSTANCIA_GENERADA |
| CC-REQ-091 | UC-14 | RF-22 | N/D | SOLICITUD_CONSTANCIA |
| CC-REQ-100 | UC-20, UC-21 | RF-35 | cv1_09 | AUDIENCIA, COLABORADOR |
| CC-REQ-101 | UC-20 | RF-35 | cv1_09 | AUDIENCIA |
| CC-REQ-102 | UC-21 | RF-35 | cv1_09 | NOTIFICACION |
| CC-REQ-103 | UC-21 | RF-37 | cv1_09 | PLANTILLA_MENSAJE, NOTIFICACION |
| CC-REQ-104 | UC-21, UC-27 | RF-37 | cv1_09 | NOTIFICACION |
| CC-REQ-105 | UC-22 | RF-36 | cv1_09 | NOTIFICACION, NOTIFICACION_DESTINATARIO |
| CC-REQ-106 | UC-22 | RF-36 | cv1_09 | NOTIFICACION, NOTIFICACION_DESTINATARIO |
| CC-REQ-107 | UC-22 | RF-36 | cv1_09 | NOTIFICACION |
| CC-REQ-108 | UC-23 | RF-38 | cv1_09 | NOTIFICACION |
| CC-REQ-109 | UC-23 | RF-38, RNF-11 | cv1_09 | NOTIFICACION, BITACORA |
| CC-REQ-110 | UC-23 | RF-40 | cv1_09 | NOTIFICACION |
| CC-REQ-111 | UC-24 | RF-39 | cv1_10 | NOTIFICACION_DESTINATARIO |
| CC-REQ-112 | UC-23, UC-24 | RF-39 | cv1_08 | NOTIFICACION |
| CC-REQ-113 | UC-25 | RF-40 | cv1_10 | NOTIFICACION_DESTINATARIO |
| CC-REQ-114 | UC-26 | RF-39 | cv1_10 | NOTIFICACION_DESTINATARIO |
| CC-REQ-115 | UC-27 | RF-41 | cv1_10 | NOTIFICACION_DESTINATARIO, CONVERSACION_WHATSAPP |
| CC-REQ-116 | UC-27 | RF-37, RF-41 | cv1_10 | CONVERSACION_WHATSAPP |
| CC-REQ-117 | UC-28 | RF-42 | cv1_08 | PLANTILLA_MENSAJE |
| CC-REQ-118 | UC-29 | RF-39 | cv1_10 | NOTIFICACION_DESTINATARIO |
| CC-REQ-119 | UC-24, UC-29 | RF-39 | cv1_10 | NOTIFICACION, NOTIFICACION_DESTINATARIO |
| CC-REQ-120 | UC-23, UC-24 | RF-39 | cv1_08 | NOTIFICACION |
| CC-REQ-121 | UC-24 | RNF-01 | cv1_10 | COLABORADOR |
| CC-REQ-122 | N/D | N/D | cv1_10 | NOTIFICACION |
| CC-REQ-150 | UC-02, UC-07 | RF-02 | N/D | EMPRESA (empresa_id en todas) |
| CC-REQ-151 | UC-04 | RNF-10 | cv1_03 | CAMPO_COLABORADOR, VALOR_CAMPO |
| CC-REQ-152 | UC-04 | RNF-01 | N/D | COLABORADOR |
| CC-REQ-153 | UC-04, UC-14 | RNF-02, RNF-10 | cv1_03 | CAMPO_COLABORADOR |
| CC-REQ-154 | UC-03 | RNF-03 | N/D | BITACORA |
| CC-REQ-155 | UC-03 | RNF-03 | N/D | BITACORA |
| CC-REQ-156 | UC-03 | RNF-03 | N/D | BITACORA |
| CC-REQ-157 | UC-06, UC-14, UC-24 | RF-36 | N/D | COLABORADOR, NOTIFICACION_DESTINATARIO |
| CC-REQ-158 | UC-26 | RF-39 | N/D | N/D |
| CC-REQ-159 | UC-14 | RNF-08 | N/D | CONVERSACION_WHATSAPP |
| CC-REQ-160 | N/D | RNF-08 | N/D | N/D |
| CC-REQ-161 | UC-06, UC-10, UC-13 | RF-04, RF-12, RF-18 | N/D | COLABORADOR, ORGANIZACION, PLANTA, CAMPO_COLABORADOR, PLANTILLA_CONSTANCIA |
| CC-REQ-162 | UC-03, UC-08 | RNF-03 | N/D | BITACORA, FILA_CARGA |
| CC-REQ-164 | UC-14, UC-16, UC-25 | RF-27 | cv1_01 | SOLICITUD_CONSTANCIA, NOTIFICACION_DESTINATARIO |

Cobertura de casos de uso: UC-01 (CC-REQ-001 a 005, 009), UC-02 (011 a 014), UC-03 (015, 154 a 156), UC-04 (020 a 025), UC-05 (026 a 028), UC-06 (029, 030), UC-07 (031 a 033), UC-08 (034 a 042), UC-09 (045 a 052), UC-10 (043, 044), UC-11 (060 a 065), UC-12 (065 a 067), UC-13 (069, 070), UC-14 (071, 072, 075, 076, 084, 085, 091), UC-15 (073, 074), UC-16 (077 a 083), UC-17 (087, 088), UC-18 (089), UC-19 (090), UC-20 (100, 101), UC-21 (102, 103, 104), UC-22 (105 a 107), UC-23 (108 a 110), UC-24 (111, 112), UC-25 (113), UC-26 (114), UC-27 (115, 116), UC-28 (117), UC-29 (118).

---

## Aprobación

Este documento queda a la espera de aprobación. Después de aprobarlo se crea `design.md` y, en una fase posterior, `tasks.md`.
