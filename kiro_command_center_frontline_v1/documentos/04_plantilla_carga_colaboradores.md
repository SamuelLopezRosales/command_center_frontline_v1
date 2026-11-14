# command-center-v1 — Análisis de la plantilla de carga de colaboradores

Fuente: `Duual Frontline Plantilla Carga Colaboradores v1.3.xlsx`. La hoja Instrucciones dice "Versión 1.2", así que hay que confirmar cuál es la vigente.

## 1. Contenido del archivo

La hoja **Colaboradores** tiene 22 columnas de captura, una de validación y capacidad para 2,000 filas. La **Organizaciones** lista razones sociales, cada una con clave (ORG01, ORG02…), RFC, registro patronal, domicilio fiscal y firmante de la constancia. La hoja **Diccionario** describe cada columna, y la oculta **Catálogos** guarda las listas de planta, sucursal, área, departamento, turno, tipo de empleado, periodicidad del sueldo y estatus.

La fila 2 de cada hoja trae las claves técnicas (`numero_empleado`, `nombres`, `celular_whatsapp`…). Estas claves son el puente natural hacia la tabla `CAMPO_COLABORADOR`.

## 2. Impacto en el modelo

El archivo cambia cuatro puntos del modelo que teníamos.

La llave de actualización es `numero_empleado`. El Instructivo dice que con él se actualiza el expediente, pero el modelo actual no tiene ese campo. Hay que agregarlo a `COLABORADOR`, único por empresa, y la carga debe hacer una actualización por ese número.

Cada colaborador pertenece a una organización (razón social). Esa organización define el RFC, el registro patronal y el firmante de la constancia. Falta la entidad `ORGANIZACION` bajo `EMPRESA`, y `COLABORADOR` debe apuntar a ella.

La plantilla separa los campos en obligatorios para todos los casos de uso (marcados con asterisco) y condicionales ("solo si el caso de uso lo requiere"). Ese criterio sirve para separar lo fijo de lo dinámico: lo obligatorio para todos va fijo en el sistema, y lo condicional se configura como campo dinámico.

La duda 3 del análisis queda resuelta. "Tipo de empleado" tiene dos valores fijos (Administrativo y Operativo), así que es un campo de lista fijo, no una categoría abierta. Los catálogos de planta, área, departamento y turno son listas que el cliente administra, y se modelan como campos de tipo lista con sus opciones.

## 3. Datos sensibles

Sueldo, NSS, CURP y RFC son datos sensibles. El Instructivo ya pide no capturarlos si la constancia no los lleva. El sistema debe marcar esos campos como sensibles, cifrarlos y mostrarlos solo a quien tenga permiso. Planta, área, departamento y tipo de empleado también los usa la segmentación de comunicación y el reporte NOM-035, que todavía no están en v1. Conviene capturarlos desde ahora para no tener que pedirlos de nuevo después.

## 4. Problemas detectados en la plantilla

La fórmula de validación de la columna W no revisa el apellido materno, aunque el encabezado y el diccionario lo marcan como obligatorio.

Si una fila tiene datos pero no tiene número de empleado, la fórmula devuelve vacío y la fila no aparece como error. Eso permite cargar colaboradores sin llave de actualización.

La validación no revisa el formato de RFC (13 caracteres), CURP (18), NSS (11) ni fechas, y tampoco verifica que el estatus sea ACTIVO o BAJA. Si las listas desplegables no lo impiden, esos valores entran sin error.

La capacidad de la plantilla (2,000 filas) es menor que el requisito de 10,000 colaboradores por empresa (RNF-09). Se puede cargar por lotes o subir ese límite.

La validación de Excel es una ayuda para RH, pero la validación definitiva tiene que vivir en el sistema, del lado del servidor, porque cualquier archivo puede modificarse.

## 5. Recomendación de diseño

La plantilla debe generarse desde la configuración de campos. Los encabezados y la fila 2 salen de `CAMPO_COLABORADOR`, así que la plantilla y el sistema nunca se desfasan cuando RH agrega o desactiva un campo.

## 6. Propuesta de campos fijos

Los campos fijos del sistema serían numero_empleado, nombres, apellido_paterno, apellido_materno, celular_whatsapp, organizacion, fecha_ingreso, puesto, planta, tipo_empleado y estatus. Todo lo demás sería dinámico. Esta propuesta reemplaza a los tres campos fijos de la versión anterior (nombre, WhatsApp y consentimiento).

## 7. Dudas nuevas

1. ¿Aprobamos el conjunto de campos fijos de la sección 6?
2. ¿Las organizaciones (razones sociales) entran en v1? Recomiendo que sí, porque la constancia depende de ellas.
3. ¿Sueldo, NSS, CURP y RFC se capturan en v1 o después?
4. ¿La carga actualiza por número de empleado y deja sin cambios a los colaboradores que no aparecen en el archivo? Recomiendo que sí, para no dar de baja por accidente a quien se omitió.
5. ¿El límite de 2,000 filas por archivo se mantiene o se sube?

## 8. Decisiones confirmadas

Se aprobaron las cuatro propuestas de esta sección. Los once campos fijos son los que marca la plantilla. Las organizaciones entran en v1 como entidad propia. Sueldo, NSS, CURP y RFC se capturan desde v1 y se cifran. La carga actualiza por número de empleado y no modifica a quien no aparece en el archivo.

El modelo de datos y el diagrama ya reflejan estas decisiones. Los requisitos nuevos son RF-29 a RF-32 y RNF-10 en el documento de análisis. La validación de la plantilla que se describe en la sección 4 se implementa en el sistema, no solo en Excel.
