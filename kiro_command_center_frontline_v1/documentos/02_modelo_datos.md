# command-center-v1 — Modelo de datos

El modelo se lee en cuatro vistas, en la carpeta `modelo/vistas`:

- `vision_general.png`: todas las entidades y sus relaciones, sin atributos. Es la vista para explicar el sistema.
- `colaboradores.png`, `constancias.png` y `notificaciones.png`: cada módulo con sus campos clave, cinco como máximo por entidad. Las entidades de otro módulo aparecen punteadas.
- `modelo_completo.png`: el diagrama con todos los atributos, como referencia técnica.

Las vistas no muestran EMPRESA, USUARIO ni BITÁCORA, porque todas las tablas dependen de ellas. Esta sección describe el detalle de cada entidad.

## 1. Decisiones de diseño

Los datos del colaborador se dividen en dos grupos. El primero son los once campos fijos que la plantilla de carga marca como obligatorios para todos los casos de uso: número de empleado, nombres, apellidos, celular, organización, planta, fecha de ingreso, puesto, tipo de empleado y estatus. Viven como columnas tipadas en `COLABORADOR`, porque el sistema depende de ellos para verificar, generar y enrutar. El segundo grupo son los campos condicionales (área, departamento, turno, ruta de transporte, sueldo, periodicidad, registro patronal, NSS, RFC, CURP, correo y los que RH agregue). Estos se configuran en `CAMPO_COLABORADOR` y sus valores se guardan en `VALOR_CAMPO`.

En `VALOR_CAMPO` se usan columnas tipadas (`valor_texto`, `valor_numero`, `valor_fecha` y `valor_opcion_id`) en lugar de una sola columna de texto, para que las búsquedas, los filtros y las validaciones funcionen con el tipo real. La restricción de unicidad sobre colaborador y campo evita valores duplicados. Este patrón (atributos en tabla) tiene un costo: consultar varios campos a la vez requiere más uniones. Para el volumen de referencia (10,000 colaboradores por empresa y hasta 100 campos) es manejable. Si el rendimiento se vuelve un problema, la alternativa es una columna JSON validada por la aplicación.

Los campos de tipo lista apuntan a `OPCION_CAMPO`, en lugar de guardar el catálogo como texto dentro del campo. Así cambiar la etiqueta de una opción no rompe los colaboradores que la tienen, y desactivarla no borra valores históricos. Las plantas tienen su propia tabla `PLANTA` porque son campo fijo.

`ORGANIZACION` representa cada razón social de la empresa (ORG01, ORG02…). Define el RFC, el registro patronal y el firmante de las constancias de sus colaboradores. Cuando un colaborador no trae registro patronal propio, se toma el de su organización.

La llave de actualización es `numero_empleado`, único por empresa. La carga masiva hace una actualización por ese número. Un colaborador que no aparece en el archivo no se modifica ni se da de baja.

El estatus ACTIVO o BAJA controla el acceso del colaborador al bot. Un colaborador en BAJA no recibe constancias, aunque conserve su historial.

Las plantillas tienen versiones. `PLANTILLA_CONSTANCIA` es la identidad de la plantilla, y `VERSION_PLANTILLA` guarda cada publicación con su contenido en JSON. Cada constancia emitida apunta a la versión exacta que usó, así que el historial siempre dice con qué plantilla se generó aunque después se edite.

Cada constancia guarda un `datos_snapshot_json` con los valores que tenía el colaborador al emitirse. Si RH corrige el puesto de alguien en marzo, la constancia emitida en febrero conserva el puesto de febrero.

El folio es único por empresa, y la unicidad se impone en la base de datos, no solo en la aplicación.

Los datos sensibles (sueldo, NSS, CURP y RFC) se marcan con `es_sensible` en `CAMPO_COLABORADOR` y se guardan cifrados. Solo los usuarios con permiso los ven. El número de WhatsApp se guarda cifrado, con un hash para la búsqueda.

La carga masiva queda registrada en `CARGA_COLABORADORES`, con el archivo, la versión de plantilla, el hash y los conteos. Cada fila procesada queda en `FILA_CARGA` con su resultado. El mensaje de error no incluye datos personales, para que el registro de cargas no se convierta en una copia de los datos.

La eliminación de colaboradores, campos, organizaciones, plantas y plantillas es lógica. Los registros se marcan como inactivos o eliminados para conservar el historial.

Al crear una empresa, el sistema carga un catálogo de campos sugeridos en `CAMPO_COLABORADOR`, marcados con `es_sugerido`. Son área, departamento, turno, ruta de transporte, sueldo, periodicidad del sueldo, registro patronal, NSS, RFC, CURP y correo. RH puede activarlos, desactivarlos, renombrarlos o agregar otros, pero no borrarlos. Esto evita que RH defina desde cero lo que las constancias y la carga ya necesitan, y conserva el control de cada empresa sobre sus campos. El catálogo no se guarda como columnas de `COLABORADOR`, porque cada columna nueva obligaría a cambiar la base de datos.

## 2. Diccionario de datos

### Configuración

| Entidad | Atributos clave | Notas |
|---|---|---|
| EMPRESA | id, razon_social, rfc, activa | Raíz de todas las tablas. Ver duda 1 del análisis. |
| USUARIO | id, empresa_id, nombre, correo (UK), cognito_sub (UK), activo | Perfil de usuario de RH. La contraseña y el MFA los administra Cognito; aquí solo se guarda su identificador. |
| ORGANIZACION | id, empresa_id, clave (UK por empresa), razon_social, rfc, registro_patronal, domicilio_fiscal, ciudad, logotipo_s3_key, nombre_firmante, cargo_firmante, correo_firmante, activa | Razón social del colaborador. Ciudad es el lugar de emisión de las constancias. |
| PLANTA | id, empresa_id, nombre, activa | Campo fijo con catálogo administrado por RH. |
| COLABORADOR | id, empresa_id, organizacion_id, planta_id, numero_empleado (UK por empresa), nombres, apellido_paterno, apellido_materno, celular_cifrado, celular_hash, fecha_ingreso, puesto, tipo_empleado, estatus, consentimiento_whatsapp | Campos fijos. Tipo_empleado es ADMINISTRATIVO u OPERATIVO. Estatus es ACTIVO o BAJA. |

### Campos dinámicos

| Entidad | Atributos clave | Notas |
|---|---|---|
| CAMPO_COLABORADOR | id, empresa_id, nombre_campo, clave, codigo_interno, tipo_dato, formato_validacion, obligatorio, orden, activo, es_sensible, es_sugerido, fecha_creacion, fecha_modificacion | Clave es única por empresa y se usa como variable `{{clave}}`; RH puede cambiarla. Codigo_interno es único y no cambia; las plantillas y la carga lo usan como referencia. Tipo_dato es TEXTO, NUMERO, FECHA, LISTA o SI_NO. Formato_validacion es una expresión que el sistema aplica a cada valor (por ejemplo, 13 caracteres alfanuméricos para RFC). Es_sugerido marca los campos del catálogo inicial. |
| OPCION_CAMPO | id, campo_id, etiqueta, valor, descripcion, orden, activo | Solo para campos LISTA (área, departamento, turno, ruta, periodicidad). Descripción guarda, por ejemplo, el horario de un turno. |
| VALOR_CAMPO | id, colaborador_id, campo_id, valor_texto, valor_numero, valor_fecha, valor_opcion_id | Única por colaborador y campo. Solo se llena la columna del tipo del campo. Los valores sensibles van cifrados. |

### Carga masiva

| Entidad | Atributos clave | Notas |
|---|---|---|
| CARGA_COLABORADORES | id, empresa_id, usuario_id, nombre_archivo, version_plantilla, hash_archivo, total_filas, filas_ok, filas_error, estado, fecha_carga | Estado: EN_PROCESO, TERMINADA o CANCELADA. |
| FILA_CARGA | id, carga_id, colaborador_id, numero_fila, numero_empleado, resultado, mensaje | Resultado: NUEVO, ACTUALIZADO, ERROR u OMITIDO. El mensaje no incluye datos personales. |

### Constancias

| Entidad | Atributos clave | Notas |
|---|---|---|
| PLANTILLA_CONSTANCIA | id, empresa_id, nombre, descripcion, activa, eliminada, fecha_creacion, fecha_modificacion | Identidad de la plantilla. |
| VERSION_PLANTILLA | id, plantilla_id, numero, contenido_s3_key, hash_sha256, creada_por_usuario_id, fecha_creacion | Número es único por plantilla. El contenido (bloques de texto, formato, variables) vive como archivo JSON en S3; aquí se guarda su ruta y su hash. |
| CONVERSACION_WHATSAPP | id, colaborador_id, estado, intentos_verificacion, fecha_inicio, fecha_ultimo_mensaje | Estado: VERIFICANDO, ACTIVA, BLOQUEADA o CERRADA. Colaborador_id queda vacío hasta verificar. |
| SOLICITUD_CONSTANCIA | id, colaborador_id, conversacion_id, version_plantilla_id, estado, motivo_fallo, fecha_solicitud, fecha_atencion | Estado: RECIBIDA, EN_PROCESO, GENERADA, ENTREGADA, FALLIDA o CANCELADA. |
| CONSTANCIA_GENERADA | id, solicitud_id (UK), colaborador_id, version_plantilla_id, generada_por_usuario_id, folio, pdf_s3_key, pdf_hash_sha256, datos_snapshot_json, estado_entrega, fecha_generacion, fecha_entrega | Generada_por_usuario_id queda vacío cuando la emite el bot. |

### Notificaciones

| Entidad | Atributos clave | Notas |
|---|---|---|
| AUDIENCIA | id, empresa_id, nombre, activa, criterios_json, creada_por_usuario_id, fecha_creacion | Grupo guardado. Los criterios usan el código interno de cada campo, así que sobreviven a cambios de nombre. |
| PLANTILLA_MENSAJE | id, empresa_id, creada_por_usuario_id, nombre, categoria, texto_con_variables, estado_meta, id_plantilla_meta, fecha_creacion | Estado_meta es BORRADOR, EN_REVISION, APROBADA o RECHAZADA. Solo las APROBADAS se pueden usar para iniciar conversaciones. |
| NOTIFICACION | id, empresa_id, usuario_id, audiencia_id, plantilla_mensaje_id, canal, mensaje, variables_json, criterios_snapshot_json, respaldo_correo, programada_para, zona_horaria, estado, total_seleccionados, total_excluidos, fecha_creacion, fecha_envio | El criterios_snapshot_json guarda la audiencia exacta al enviarse. Si después cambia el grupo guardado, el envío no cambia. |
| NOTIFICACION_DESTINATARIO | id, notificacion_id, colaborador_id, conversacion_id, estado_envio, motivo_exclusion, canal_usado, id_mensaje_proveedor, intentos, fecha_estado | Un renglón por colaborador seleccionado, incluidos los excluidos, para que el motivo quede registrado. Conversacion_id se llena cuando el colaborador responde. |

### Transversal

| Entidad | Atributos clave | Notas |
|---|---|---|
| BITACORA | id, usuario_id, colaborador_id, accion, entidad, entidad_id, fecha_hora, ip | Registra acciones de RH y del sistema sobre colaboradores, campos, cargas, plantillas y constancias. |

## 3. Reglas de integridad

El número de empleado es único por empresa, y una carga que lo repite se rechaza como error. El celular es único por empresa (`celular_hash`). Una organización o planta usada por colaboradores no se elimina, solo se desactiva. Un campo con valores registrados no puede cambiar su `tipo_dato`. Un campo con valores registrados no se elimina, solo se desactiva. Una `VERSION_PLANTILLA` publicada es inmutable: los cambios crean una versión nueva. Una `CONSTANCIA_GENERADA` es inmutable: no se edita, solo cambia su estado de entrega. Un colaborador no puede tener dos conversaciones de verificación activas al mismo tiempo. Un colaborador en BAJA no puede iniciar una conversación que genere constancias. Una notificación no puede enviarse a un colaborador sin consentimiento vigente: el sistema lo marca como EXCLUIDO con su motivo. Una PLANTILLA_MENSAJE solo puede usarse en envíos iniciados por la empresa si su estado_meta es APROBADA.

## 4. Validación de la carga

La plantilla de Excel ayuda a RH a detectar errores, pero el sistema vuelve a validar todo del lado del servidor. Esta validación revisa que los obligatorios estén completos, que el número de empleado no se repita, que el celular tenga 10 dígitos y no se repita, que la organización y la planta existan, que el estatus sea ACTIVO o BAJA, que el RFC tenga 12 o 13 caracteres, que la CURP tenga 18, que el NSS tenga 11 dígitos, que la fecha sea válida y que el sueldo y la periodicidad vayan juntos. Una fila con error no se carga, y el resto del archivo sí, con el resultado de cada fila en `FILA_CARGA`.
