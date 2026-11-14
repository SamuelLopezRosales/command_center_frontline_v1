# command-center-v1 — Análisis de plantillas de constancias

Fuentes: `Constancia laboral.docx`, `Constancia guarderia.docx` y `Constancia Consulado.docx`, en la carpeta del proyecto. Las tres son texto libre con datos de ejemplo en lugar de variables. No tienen encabezado ni logotipo, así que el logotipo se agregaría desde el editor de plantillas.

## 1. Variables que usan las plantillas

Cada dato de ejemplo se sustituye por una variable del sistema. Las variables se dividen en tres grupos según de dónde salen.

| Variable | Dónde vive | Usada en |
|---|---|---|
| `{{lugar}}` | Nuevo campo `ciudad` en ORGANIZACION | Laboral, Guardería, Consulado |
| `{{fecha_emision}}` | Sistema, fecha de hoy en texto largo | Las tres |
| `{{organizacion.razon_social}}` | ORGANIZACION | Las tres |
| `{{organizacion.rfc}}` | ORGANIZACION | Laboral |
| `{{organizacion.domicilio_fiscal}}` | ORGANIZACION | Guardería, Consulado |
| `{{organizacion.nombre_firmante}}`, `{{organizacion.cargo_firmante}}` | ORGANIZACION | Las tres |
| `{{organizacion.correo_firmante}}` | Nuevo campo en ORGANIZACION | Las tres |
| `{{nombre_completo}}` | COLABORADOR (nombres y apellidos) | Las tres |
| `{{puesto}}`, `{{fecha_ingreso}}` | COLABORADOR (fijos) | Las tres |
| `{{area}}` | Campo dinámico de lista | Laboral, Consulado |
| `{{horario}}` | Descripción de la opción del turno | Guardería |
| `{{rfc}}`, `{{curp}}`, `{{nss}}` | Campos dinámicos sensibles | Laboral (RFC, NSS), Consulado (CURP, RFC) |
| `{{registro_patronal}}` | COLABORADOR o, si no tiene, ORGANIZACION | Laboral, Guardería, Consulado |
| `{{sueldo_mensual}}`, `{{sueldo_letra}}` | Calculadas por el sistema a partir de sueldo y periodicidad | Laboral, Consulado |
| `{{folio}}`, `{{qr_verificacion}}` | Sistema | Las tres (ver duda 5) |

Las variables de sueldo no se guardan, se calculan al generar el PDF. `sueldo_letra` convierte el importe a texto con el formato "00/100 MN".

## 2. Cambios al modelo que surgen de las plantillas

ORGANIZACION necesita dos campos más: `ciudad`, que es el lugar de emisión que aparece al inicio de cada constancia, y `correo_firmante`, que las tres plantillas piden. OPCION_CAMPO necesita una columna `descripcion`, para que el turno (Matutino, Vespertino, Nocturno) lleve su horario y la guardería lo tome de ahí, en lugar de tenerlo escrito fijo en el texto.

Las variables calculadas no se guardan en la base. Se generan en `generador-pdf` y su valor queda en `datos_snapshot_json`, para que la constancia emitida conserve el valor exacto con el que se produjo.

## 3. Correcciones a las plantillas

### Constancia laboral

El texto "Lugar a fecha (hoy)" debe ser `{{lugar}}, {{fecha_emision}}`. La frase "adscrito al área de área" repite la palabra y debe quedar `adscrito al área de {{area}}`. La frase "desde el día fecha de ingreso" debe quedar `desde el {{fecha_ingreso}}`, porque la fecha ya incluye el día. El número de seguridad social de ejemplo, "111111111", tiene 9 dígitos y debe tener 11, así que la variable es `{{nss}}`. El registro patronal de ejemplo tiene 9 dígitos y debe ser `{{registro_patronal}}`, de 11 caracteres. El sueldo "$0,000.00" y su letra deben ser `{{sueldo_mensual}}` y `{{sueldo_letra}}`. La línea "Correo electrònico" tiene un acento incorrecto en la "è", y debe ser `{{organizacion.correo_firmante}}`.

### Constancia guardería

La línea de horario "de 9:00 am a 07:00 pm" está escrita fija para todos los colaboradores, y no todos trabajan ese horario. Debe ser `{{horario}}`. Si se quiere mantener el formato de hora, conviene definirlo en la descripción de cada turno. La palabra "COMPELTO" está mal escrita y debe ser "COMPLETO". Las demás partes siguen el mismo patrón de variables que la laboral.

### Constancia consulado

La CURP de ejemplo, "AAAA000000BBBB11", tiene 16 caracteres y debe tener 18. El RFC de ejemplo, "AAAA111111BB0", tiene 11 caracteres y debe tener 13, así que debe ser `{{rfc}}`. El registro patronal de ejemplo tiene 8 caracteres y debe ser `{{registro_patronal}}`. La frase "desde el fecha de ingreso" debe quedar `desde el {{fecha_ingreso}}`. La frase "dentro del área área del Colaborador" debe quedar `dentro del área de {{area}}`. El importe "$cantidad (cantidad con letra 00/100 MN)" debe ser `{{sueldo_mensual}} ({{sueldo_letra}} 00/100 MN)`. El correo de la firma debe ser `{{organizacion.correo_firmante}}`.

Los datos de ejemplo de RFC, CURP y registro patronal no cumplen el formato real. Eso no afecta la generación, porque se reemplazan por variables, pero sí afecta la vista previa, así que conviene que las variables usen datos de prueba válidos.

## 4. Preguntas que salen de estas plantillas

1. **Conversión de sueldo a mensual.** Las plantillas laboral y consulado dicen "mensual", pero el sueldo puede ser semanal, catorcenal, quincenal o mensual. Propuesta: calcular el mensual con factores fijos (semanal × 52/12, catorcenal × 26/12, quincenal × 2, mensual × 1). Esta regla debe confirmarla contabilidad o RH antes de usarla en un documento oficial. Otra opción es mostrar el sueldo con su periodicidad, sin convertirlo.

2. **Horarios por turno.** Hay que confirmar el horario de cada turno de Duual (Matutino, Vespertino, Nocturno) para cargarlo en la descripción de cada opción.

3. **Lugar de emisión.** Propuesta: la ciudad se captura por organización, porque cada razón social puede estar en una ciudad distinta.

4. **Código QR.** Las tres plantillas no tienen espacio para QR ni folio. Propuesta: el editor agrega el folio y el QR en el pie de página de forma automática, para que las plantillas de RH no tengan que incluirlos.

5. **Logotipo y encabezado.** Como las plantillas no traen logotipo, hay que pedir el archivo oficial de la razón social para que el editor lo pueda insertar.
