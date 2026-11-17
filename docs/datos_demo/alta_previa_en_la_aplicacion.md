# Datos de demostración: qué dar de alta antes de cargar el Excel

Todo es **ficticio**. El Excel `Plantilla_Carga_Colaboradores_DEMO.xlsx` trae 10 colaboradores y 3 organizaciones, pero la
carga masiva **no crea** organizaciones, plantas ni opciones de listas: las busca entre las que ya
existen. Si faltan, la fila se rechaza con `ORGANIZACION_NO_EXISTE`, `PLANTA_NO_EXISTE` o un error
de opción. Dé de alta primero esto, en la aplicación, en este orden:

## 1. Organizaciones (menú Colaboradores → Organizaciones)

| Clave | Razón social | RFC | Registro patronal |
|---|---|---|---|
| `ORG01` | Industrias Norte Demo, S.A. de C.V. | INO190101AB1 | B5612345678 |
| `ORG02` | Servicios Logísticos Demo, S.A. de C.V. | SLD200315QR4 | C7823456789 |
| `ORG03` | Comercializadora Demo del Golfo, S.A. de C.V. | CDG180720MN8 | D9034567890 |

El domicilio fiscal y la persona que firma están en la hoja «Organizaciones» del Excel.

## 2. Plantas

- Planta Apodaca
- Planta Saltillo
- Oficinas Centrales

## 3. Opciones de las listas (menú Colaboradores → Campos)

Las listas vienen **sin opciones**. En cada campo, agregue exactamente estas (con esa ortografía):

- **Área**: Producción, Calidad, Logística, Administración, Ventas
- **Departamento**: Línea 1, Línea 2, Laboratorio, Recursos Humanos, Almacén, Transporte, Finanzas, Comercial, Atención a clientes
- **Turno**: Matutino, Vespertino, Nocturno

*Periodicidad del sueldo* ya trae sus opciones (Semanal, Catorcenal, Quincenal, Mensual).
*Ruta de transporte* viene desactivada y el Excel la deja vacía.

## 4. Cargar el archivo

Menú Colaboradores → Carga masiva → suba `Plantilla_Carga_Colaboradores_DEMO.xlsx`, revise el resumen y confirme. Debe dar
**10 filas válidas**: 9 `ACTIVO` y 1 `BAJA` (el colaborador E-2005, para ver cómo se
trata una baja).

## Para probar WhatsApp

- Los celulares del archivo son ficticios (`81555xxxxx`): **no les envíe mensajes reales**.
- Los colaboradores cargados por Excel quedan **sin consentimiento de WhatsApp**. Para probar el
  bot o una notificación, edite uno y marque el consentimiento, y cambie su celular por uno suyo.
- Una notificación solo llega a quien está `ACTIVO`, con consentimiento vigente y celular válido.
