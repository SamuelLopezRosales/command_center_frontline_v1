# Conexión con Meta (WhatsApp Cloud API): guía paso a paso

Esta guía explica cómo conseguir en el panel de Meta cada dato que pide el módulo **Integraciones →
Conexión con Meta** de Command Center, cómo registrar el webhook y qué hacer si algo falla.

> **La interfaz de Meta cambia con frecuencia.** Si un menú no está donde dice esta guía, busque el
> **nombre del campo** (está en negritas y entre comillas): casi siempre sigue existiendo aunque cambie de
> lugar. Meta llama a la plataforma "Meta for Developers" (`developers.facebook.com`, para la app) y "Meta
> Business Suite / Business Settings" (`business.facebook.com`, para la empresa y los usuarios del sistema).

> **No comparta tokens por chat, correo ni capturas, y nunca los suba a git.** El token de acceso y el App
> Secret dan control sobre su cuenta de WhatsApp. Se pegan **solo** en la pantalla de Command Center. Si un
> valor se filtró, genere uno nuevo en Meta (sección 6) y bórrelo de donde quedó.

## 1. Qué datos hacen falta

Es **una sola cuenta de Meta para toda la instalación** (una sola empresa). La pantalla guarda cinco datos
más la versión de la API:

| Dato en la pantalla | Qué es | Dónde se toma en Meta |
|---|---|---|
| **WABA ID** | Identificador de la cuenta de WhatsApp Business | Sección 2.1 |
| **Phone Number ID** | Identificador del número de WhatsApp (**no** es el teléfono) | Sección 2.2 |
| **Token de acceso** | Credencial con la que Command Center envía mensajes y administra plantillas | Sección 2.3 |
| **App Secret** | Con él se valida la firma de los avisos (webhook) que manda Meta | Sección 2.4 |
| **Token de verificación** | Una clave que usted y Meta comparten al registrar el webhook | Sección 2.5 (lo inventa el sistema) |
| **Versión de la API** | Por defecto `v21.0`; solo cámbiela si Meta retira esa versión | Formato `v21.0` |

Qué guarda y qué muestra el sistema: los valores se guardan **cifrados** en el secreto de Secrets Manager
`cc/{ambiente}/meta` (no en la base de datos). La pantalla nunca vuelve a mostrar un valor completo: solo los
últimos 4 caracteres del token de acceso y del App Secret, y si ya hay un token de verificación.

## 2. De dónde tomar cada dato

### 2.1 WABA ID (ID de la cuenta de WhatsApp Business)

Dos caminos, el que le resulte más a la mano:

- **Meta Business Suite → Configuración (Business Settings) → Cuentas → Cuentas de WhatsApp.** Seleccione
  la cuenta: el **ID de la cuenta de WhatsApp Business** aparece arriba, junto al nombre.
- **Panel de la app (`developers.facebook.com` → su app) → WhatsApp → API Setup (Configuración de la API).**
  En el paso "Send and receive messages" figura **"WhatsApp Business Account ID"**.

Son solo dígitos (entre 8 y 25).

### 2.2 Phone Number ID

**Panel de la app → WhatsApp → API Setup.** En el paso donde elige el número de origen ("From") aparece
**"Phone number ID"** debajo del teléfono.

**Importante:** el *Phone number ID* **no es el número de teléfono**. Es un identificador largo de solo
dígitos (por ejemplo 15 o 16 dígitos). Si pega el teléfono (`+52 1 55 …`), la prueba de conexión dirá que no
encontró el número.

### 2.3 Token de acceso permanente

El token que muestra **API Setup** ("Temporary access token") **dura 24 horas**: sirve **solo para una primera
prueba**. Para producción necesita un token **sin vencimiento** de un *usuario del sistema*:

1. **Business Settings (Configuración del negocio) → Usuarios → Usuarios del sistema → Agregar.**
2. Cree un usuario del sistema (nombre libre, por ejemplo `command-center`) con el rol **Admin**.
3. Con el usuario seleccionado, **Asignar activos** (Add assets):
   - **Apps**: elija su app y active **control total / administrar la app**.
   - **Cuentas de WhatsApp**: elija su cuenta de WhatsApp Business y active **control total**.
4. **Generar token** (Generate new token): elija su app y marque los permisos
   **`whatsapp_business_messaging`** y **`whatsapp_business_management`**. En el vencimiento elija
   **Nunca** (sin vencimiento).
5. Copie el token **en ese momento**: Meta no vuelve a mostrarlo. Pegue directamente en Command Center.

Los tokens de Meta suelen empezar con `EA…`, pero el sistema solo exige que tenga entre 20 y 1000
caracteres sin espacios.

### 2.4 App Secret

**Panel de la app → App settings (Configuración de la app) → Basic (Básica) → "App secret" → botón "Show"
(Mostrar).** Meta puede pedirle su contraseña. Son **32 caracteres hexadecimales** (0-9 y a-f); el sistema
exige ese formato, que es el que usa Meta.

### 2.5 Token de verificación

**No se toma de Meta: lo inventa el sistema.** En la pantalla pulse **"Generar"** junto al token de
verificación. El valor se muestra **una sola vez** (cópielo en ese momento) y queda guardado. Después se
pega en Meta al registrar el webhook (sección 4). Si lo pierde, genere otro y repita el registro del webhook.

## 3. Orden recomendado de uso

1. En **Integraciones → Conexión con Meta**, guarde **WABA ID, Phone Number ID, token de acceso y App Secret**
   (puede ser en varios guardados: cada guardado solo cambia lo que usted escribió).
2. Pulse **"Generar"** para el token de verificación y cópielo.
3. Pulse **"Probar conexión"**. Debe salir en verde **token**, **número** y **WABA**. El renglón **webhook**
   saldrá en rojo ("ninguna app está suscrita") hasta el paso 5: es lo esperado.
4. **Espere 5 minutos** desde que guardó o generó el token de verificación (el webhook guarda las credenciales
   en memoria 5 minutos) y **registre el webhook en Meta** (sección 4).
5. Vuelva a pulsar **"Probar conexión"**: ahora también debe salir en verde el **webhook**.

"Probar conexión" no envía mensajes: solo consulta la API de Meta con lo guardado.

## 4. Registrar el webhook en Meta

La URL del webhook es la de **su ambiente en CloudFront**:

```
https://<dominio de CloudFront del ambiente>/webhook/meta
```

(Ambiente `samuel`: el dominio está en `docs/arquitectura-desplegada-samuel.md`. En general es el `…cloudfront.net` de la distribución del ambiente; está en la salida del despliegue
`CcEdge` o en la consola de CloudFront. Meta exige HTTPS válido: no use la URL de API Gateway con encabezados.)

1. **Panel de la app → WhatsApp → Configuration (Configuración) → Webhook → Edit (Editar).**
2. **Callback URL**: la URL de arriba.
3. **Verify token**: el token de verificación que generó en Command Center.
4. **Espere 5 minutos** desde que guardó o generó el token de verificación y pulse **Verify and save
   (Verificar y guardar)**. Meta hace una petición `GET`; si el token coincide, se
   guarda. (Si falla, vea la sección 7.)
5. En **Webhook fields**, pulse **Manage** y **suscríbase (Subscribe)** a **`messages`** (mensajes y estados
   de entrega) y **`message_template_status_update`** (aprobación o rechazo de plantillas).
6. **Suscriba la app a la cuenta de WhatsApp Business.** En muchas cuentas se hace sola al completar el
   paso anterior; la prueba de conexión lo confirma (renglón **webhook**). Si no, en el panel de la app →
   WhatsApp → API Setup (o en la consola de la cuenta) busque **"Subscribed apps"/"Webhooks"** de la cuenta, o
   pídale a quien administre la cuenta que suscriba la app. Sin esta suscripción Meta no manda avisos.

Los avisos llegan firmados con el **App Secret**: si ese valor es incorrecto, el webhook responde 403 y
**no se procesa ningún mensaje entrante ni estado de entrega**.

## 5. Número de prueba de Meta: limitaciones

Mientras la empresa no esté verificada, Meta da un **número de prueba**:

- Solo puede **enviar** a los destinatarios que usted agregue manualmente en **API Setup → "To" (Manage phone
  number list)**, y cada uno debe confirmar con un código que le llega por WhatsApp.
- Solo permite la plantilla de ejemplo **`hello_world`** y las que usted cree y Meta apruebe; los mensajes de
  texto libre solo funcionan dentro de la ventana de 24 horas tras una respuesta del destinatario.
- Sin **verificación del negocio** (Business Verification) no hay números reales ni envío a públicos
  abiertos. Los colaboradores reales no recibirán mensajes hasta tener un número real aprobado.

El token temporal de 24 horas también aplica a este número de prueba.

## 6. Rotar el token o el App Secret

1. Genere el nuevo valor en Meta (sección 2.3 o 2.4). Para el token de acceso, genere el nuevo **antes** de
   revocar el anterior.
2. Pegue **solo ese valor** en la pantalla y guarde (los demás datos se conservan).
3. **Tarda hasta 5 minutos en surtir efecto en todo el sistema**: el webhook, el envío de mensajes y la
   gestión de plantillas guardan las credenciales en memoria 5 minutos (la tarea que atendió su guardado las
   renueva al instante). Espere ese tiempo antes de revocar el valor viejo.
4. Pulse **Probar conexión**.

Si cambió el **App Secret** en Meta y todavía no lo actualiza aquí, los avisos de Meta se rechazan (403) y
Meta reintenta por un tiempo: actualícelo cuanto antes.

Cambiar el **token de verificación** exige repetir el paso 4.3 del registro del webhook (Meta debe conocer el
nuevo valor).

## 7. Si "Probar conexión" falla

| Mensaje (resumen) | Qué significa | Qué hacer |
|---|---|---|
| "Meta rechazó el token de acceso: no es válido o ya venció" | Código 190 / HTTP 401 | Es el caso típico del token temporal de 24 h. Genere un token permanente (2.3) y guárdelo. Revise que no tenga espacios ni esté cortado al pegarlo |
| "El token no tiene permisos suficientes…" | Códigos 10 y 200-299 / HTTP 403 | Genere el token con `whatsapp_business_messaging` **y** `whatsapp_business_management`, y confirme que el usuario del sistema tenga **asignada la cuenta de WhatsApp** con control total |
| "No se encontró el Phone Number ID…" | Código 100/803 al consultar el número | Revise que sea el **Phone number ID** (sección 2.2) y no el teléfono, y que el token tenga acceso a ese número |
| "No se encontró el WABA ID…" | Código 100/803 al consultar la cuenta | Revise el **WABA ID** (2.1) y que la cuenta esté asignada al usuario del sistema |
| "Ninguna app está suscrita a la cuenta todavía" (renglón webhook en rojo, lo demás en verde) | Falta registrar el webhook o suscribir la app | Siga la sección 4 y vuelva a probar |
| "Meta limitó temporalmente las consultas" | Límite de tasa | Espere unos minutos |
| "Meta no respondió a tiempo" / "no pudo responder en este momento" / "No se pudo contactar a Meta" | Tiempo agotado, error de Meta o red | Reintente en unos minutos; si persiste, revise `status.fb.com` / el estado de Meta y la salida a internet del ambiente |
| "Meta devolvió una respuesta inesperada (HTTP …)" | Otro error | Reintente; si persiste, avise al equipo técnico con la hora exacta |
| Error 422 `META_NO_CONFIGURADA` | Faltan WABA ID, Phone Number ID o token de acceso | Guárdelos primero |

**"Verify and save" falla al registrar el webhook** ("The callback URL or verify token couldn't be
validated"): el token de verificación pegado en Meta no coincide con el guardado (genere uno nuevo, guarde y
pegue ese), la URL no es la `…/webhook/meta` del ambiente, o se pulsó antes de que pasaran 5 minutos tras
generarlo (espere ese tiempo). Si el token es correcto y aun así falla, pruebe de nuevo pasados 5 minutos.

## 8. Referencia técnica (para el equipo)

- Pantalla y API: `GET|PUT /api/v1/integraciones/meta`, `POST /api/v1/integraciones/meta/verify-token:generar`
  y `POST /api/v1/integraciones/meta/probar`, servicio `notificaciones`, permiso `integraciones:administrar`.
  Contrato en `contracts/openapi/notificaciones.json`.
- El **servidor de la Graph API** (`CC_META_API_BASE`, por defecto `https://graph.facebook.com`) es
  configuración del despliegue y **no se puede cambiar desde la pantalla**: permitirlo mandaría el token a
  cualquier servidor.
- Precedencia: lo guardado en el secreto (`phone_number_id`, `api_version`) manda; las variables
  `CC_META_PHONE_NUMBER_ID` y `CC_META_API_VERSION` solo son respaldo si el secreto no trae el valor.
- Auditoría: cada guardado queda en la bitácora como `META_CONFIGURADA` (solo los **nombres** de los campos
  cambiados) y cada prueba como `META_PROBADA`.
- La prueba de conexión no confirma que la app suscrita sea *esta* app (Meta no lo informa sin el id de la
  app): solo que hay alguna suscrita a la cuenta.
- Dos guardados simultáneos se serializan con un candado de PostgreSQL; el secreto se reescribe solo con las
  claves conocidas.
- La **importación de plantillas ya aprobadas** (sección 9) reutiliza estas mismas credenciales y el `WABA ID`
  guardado (`cargador_credenciales`).

## 9. Importar plantillas aprobadas

Sirve para **asociar a Command Center las plantillas que ya están aprobadas en su cuenta de Meta**, sin volver
a mandarlas a revisión. Está en **Notificaciones → Plantillas de mensaje → «Importar desde Meta»** (permiso
`notificaciones:editar`) y necesita la conexión con Meta guardada y probada (secciones 1 a 3).

### 9.1 Cómo se usa

1. Pulse **«Importar desde Meta»**. El diálogo consulta a Meta (solo lectura) y lista todas las plantillas de la
   cuenta con su texto (las variables se ven como `{{1}}`, `{{2}}` o `{{guest_name}}`), idioma, categoría y estado,
   y, si las tiene, sus variables con nombre, **botones** y **encabezado**.
2. Cada plantilla muestra una insignia: **Compatible**, **No compatible: motivo** (una por cada problema), **Variables
   con nombre** o **Ya importada**. Solo las
   compatibles y no importadas tienen casilla; **«Seleccionar todas las compatibles»** marca las que se puedan.
3. Pulse **«Importar seleccionadas»**. El resumen dice, por plantilla, si quedó **importada**, **ya existía** o fue
   **omitida** (con el motivo). La lista de plantillas locales se actualiza sola.

Las plantillas importadas quedan en estado **Aprobada** y se pueden usar de inmediato al crear una notificación.
**No se editan** (como cualquier plantilla aprobada): para cambiar el texto hay que crear otra en Meta.

### 9.2 Qué se importa y qué no

Command Center maneja **un cuerpo de texto** con variables **numeradas** (`{{1}}`, `{{2}}`…, consecutivas desde 1)
**o con nombre** (`{{guest_name}}`), más un encabezado de texto fijo, un pie fijo y botones estáticos. Una
plantilla es **compatible** si cumple todo lo siguiente; la pantalla y la API informan **todos** los motivos de
incompatibilidad (`motivos_incompatibles`), no solo el primero:

| Condición | Si no se cumple (código del motivo) |
|---|---|
| Aprobada en Meta (`APPROVED`) | Las que están en revisión, rechazadas, **pausadas** o **deshabilitadas** se listan pero no se importan (`ESTADO_NO_APROBADO`, con su estado) |
| Nombre solo con minúsculas, números y guion bajo | `NOMBRE_INVALIDO` |
| Categoría Utilidad, Marketing o Autenticación | `CATEGORIA_NO_SOPORTADA` |
| Idioma con el formato de Meta (`es_MX`, `en`, `en_US`, `pt_BR`…): **cualquier idioma sirve** | `IDIOMA_INVALIDO` |
| **Encabezado:** ninguno, o de **texto fijo** (sin variables) | `ENCABEZADO_IMAGEN`, `ENCABEZADO_VIDEO`, `ENCABEZADO_DOCUMENTO`, `ENCABEZADO_UBICACION`, `ENCABEZADO_TEXTO_CON_VARIABLE`, `ENCABEZADO_NO_SOPORTADO` |
| **Botones:** ninguno, o todos **estáticos**: respuesta rápida (`QUICK_REPLY`), teléfono (`PHONE_NUMBER`) y URL **sin** variable | `BOTON_URL_CON_VARIABLE`, `BOTON_COPIAR_CODIGO`, `BOTON_OTP`, `BOTON_FLOW`, `BOTON_CATALOGO`, `BOTON_MPM`, `BOTON_SPM`, `BOTON_NO_SOPORTADO` |
| Que no sea carrusel ni lleve otro componente especial | `TIENE_CARRUSEL`, `COMPONENTE_NO_SOPORTADO` |
| Un cuerpo de texto de hasta 1024 caracteres | `SIN_CUERPO_TEXTO`, `TEXTO_DEMASIADO_LARGO` |
| Variables **todas numeradas** (consecutivas desde 1) o **todas con nombre** (`^[a-z][a-z0-9_]*$`), hasta 20 | `VARIABLES_MEZCLADAS`, `NOMBRE_VARIABLE_INVALIDO`, `VARIABLES_NO_CONSECUTIVAS`, `VARIABLES_INVALIDAS`, `DEMASIADAS_VARIABLES`, `VARIABLES_FORMATO_INCONSISTENTE` |

Un **pie de página** (footer) de texto sin variables **sí se tolera**, igual que un **encabezado de texto fijo** y los
**botones estáticos**: Meta los agrega al enviar el mensaje, pero Command Center no los muestra en la vista previa ni
los manda como parámetros; la pantalla lo avisa. La API devuelve además `botones` (`{tipo, texto}`) y `encabezado`
(`{tipo, formato, texto}`) para que el mensaje sea exacto, por ejemplo «Encabezado de imagen: requiere adjuntar la
imagen al enviar; aún no soportado».

**Plantillas con encabezado de medios** (imagen, video, documento) **o de ubicación** no se importan hoy: Meta exige
mandar un enlace público o el id de un medio subido **en cada mensaje**, y Command Center no lo tiene. Diseño futuro
(**no implementado**): guardar por plantilla una URL pública fija o un `media id` subido a Meta con
`POST /{phone_number_id}/media` y agregar el componente `header` al enviar. Mientras tanto, cree en Meta una versión sin
encabezado de medios o con encabezado de texto, o cree la plantilla desde Command Center (**«+ Nueva plantilla»**).

### 9.2.1 Variables con nombre (`{{guest_name}}`)

Las plantillas de Meta con `parameter_format` `NAMED` (por ejemplo `Hola {{guest_name}}, tu salida es a las
{{checkout_time}}`) se importan y se envían de punta a punta:

- **El formato se infiere del texto**, sin cambios en la base de datos: si todos los marcadores son números
  consecutivos desde 1, es *posicional*; si todos son nombres, es *con nombre*. **Mezclarlos es inválido**
  (`VARIABLES_MEZCLADAS`), igual que un nombre fuera de `^[a-z][a-z0-9_]*$` (hasta 50 caracteres) o que el
  `parameter_format` que declara Meta no coincida con el texto. Un mismo nombre puede aparecer varias veces en el
  texto y cuenta **una** variable. El código común es `cc_common/plantillas_meta.py`.
- **La fila local guarda el texto tal cual** (`{{guest_name}}`) y los ejemplos salen de
  `example.body_text_named_params` (en el orden de aparición).
- **Notificaciones:** `variables_json` va **por nombre** y debe cubrir **exactamente** las variables de la plantilla
  (faltantes y sobrantes dan 422 por campo, `variables.<nombre>`):

  ```json
  {"guest_name": {"origen": "COLABORADOR", "campo": "nombre_completo"},
   "checkout_time": {"origen": "FIJO", "valor": "12:00"}}
  ```

  En las posicionales sigue siendo `{"1": ..., "2": ...}`. La pantalla «Nueva notificación» muestra una fila por
  nombre (en letra monoespaciada) y la vista previa sustituye por nombre.
- **El envío usa `parameter_name`:** el despachador arma `variables` en el orden de aparición de los nombres en el
  texto y agrega `variables_nombres` (lista paralela); el enviador manda
  `{"type":"body","parameters":[{"type":"text","parameter_name":"guest_name","text":"Juan"}, ...]}`. Meta exige enviar
  **todos** los nombres y rechaza (códigos `132000` o `132012`, que el enviador guarda como `PLANTILLA_PARAMETROS`, sin
  reintento) los parámetros posicionales en una plantilla con nombre y al revés. Si falta el dato de un colaborador
  para una variable con nombre, el enviador no llama a Meta: el destinatario queda **FALLIDO** con
  `VARIABLE_SIN_VALOR`.
- **Chat de RH:** una plantilla con nombre se envía con `variables_nombradas` (`{"guest_name": "Juan"}`); la
  posicional, con `variables` (lista). El servidor valida contra el texto de la plantilla (INT-NOT-01) y guarda cifrado
  el texto ya renderizado.
- **Plantillas nuevas** creadas en Command Center con variables con nombre se envían a revisión con
  `parameter_format: "NAMED"` y `body_text_named_params` (no verificado contra Meta real, ver 9.4).

### 9.2.2 Idioma por plantilla y botones estáticos

- **Idioma:** el despachador lee el `idioma` de la fila de la plantilla y lo agrega a `MensajeSalida` (`idioma`); el
  enviador manda `language.code` con ese idioma (si el mensaje no lo trae, constancias y bot, usa
  `plantilla_idioma`, `es_MX`); el chat de RH usa el de la plantilla. Una plantilla importada en `en_US` o `en` se
  envía en ese idioma. Si Meta no tiene la plantilla en el idioma enviado responde `132001` y el destinatario queda
  **FALLIDO** con `PLANTILLA_INEXISTENTE`.
- **Botones estáticos:** para enviar una plantilla con botones **no se agrega ningún componente `button`** al mensaje:
  solo el cuerpo con sus parámetros (y nada si no tiene variables). **Supuesto no verificado con Meta real:** Meta
  acepta el envío de plantillas con botones sin parámetros (respuesta rápida, URL fija, teléfono) sin ese
  componente. Si Meta respondiera `132000` o `132012`, el error queda en el destinatario como
  `PLANTILLA_PARAMETROS` (la pantalla de detalle lo explica), es **permanente** y **no se reintenta**.
- **Respuestas a botones de respuesta rápida:** llegan al **webhook configurado en Meta** para la cuenta, que puede
  ser el de otro proyecto, **no a Command Center**, mientras no registre el nuestro (ver sección 4). La pantalla de
  importación y el catálogo lo advierten.

### 9.3 Cómo funciona por dentro (y cómo reimportar)

- El servidor identifica cada plantilla por **nombre e idioma** y **vuelve a consultar a Meta**: la fila local se
  crea con los datos de Meta (nombre, categoría, texto, idioma, `id_plantilla_meta`, ejemplos del cuerpo si
  vienen), nunca con lo que mande el navegador.
- Cada plantilla se procesa **por separado** (no es "todo o nada"): una omitida no impide importar las demás.
- **Es seguro repetir la importación:** si ya hay una fila con el mismo `id_plantilla_meta` el resultado es
  **Ya existía** y no se cambia nada. Para **reimportar** una plantilla (por ejemplo después de borrarla de
  Command Center) basta con volver a abrir el diálogo y elegirla. Importar de nuevo **no actualiza** el texto de
  una plantilla ya importada: si Meta la modificó, bórrela localmente (o renómbrela) y reimporte.
- La consulta trae **hasta 500 plantillas** (cinco páginas de 100). Si la cuenta tiene más, el diálogo avisa que
  la lista está truncada; el servidor consulta por separado las que se pidan por nombre e idioma y no hayan
  entrado en esas 500.
- Cada alta queda en la bitácora como `PLANTILLA_MENSAJE_IMPORTADA` (solo el id de la plantilla local y el
  estado; sin texto ni credenciales).
- Errores: sin credenciales guardadas responde **422 `META_NO_CONFIGURADA`** (el diálogo remite a «Conexión con
  Meta»); un fallo de Meta (token vencido, permisos, tasa, caída, tiempo agotado) responde **502
  `ERROR_PROVEEDOR_META`** con un mensaje en español, nunca un 500 y nunca con el token ni el texto de Meta.

### 9.4 Limitaciones conocidas

- **Nombre repetido en varios idiomas.** Meta permite el mismo nombre en varios idiomas (`aviso` en `es_MX` y en
  `en_US`), pero la tabla local es única por **(empresa, nombre)**. Se importa **el primero que se pida**; el
  resto se **omite** (`NOMBRE_EN_USO`, y la lista lo marca) y **no se puede enviar el mismo nombre en otro
  idioma**. No se cambió la restricción ni se hizo migración. Renombre o elimine la local, o use nombres distintos
  por idioma en Meta.
- **Encabezado de medios y botones con parámetros.** Imagen, video, documento, ubicación, encabezado de texto con
  variable, botones URL con variable, copiar código, OTP, Flow, catálogo y multiproducto **no se soportan** (se
  listan con su motivo exacto). Ver el diseño futuro en 9.2.
- **No verificado contra Meta real:** (1) que Meta acepte enviar una plantilla con botones estáticos o encabezado de
  texto fijo sin los componentes `button` / `header`; (2) el formato exacto de `parameter_format` y
  `body_text_named_params` al **crear** una plantilla con nombre desde Command Center; (3) el límite real de la
  longitud de un nombre de variable (se usa 50); (4) los textos de error `132000`, `132012` y `132001` (el simulador
  los imita). La importación y el envío de plantillas ya aprobadas con nombre solo dependen de lo que Meta documenta
  para el envío.
- **Plantillas que Meta pausa o deshabilita después.** El estado local solo cambia desde "En revisión" (eventos
  `wa.plantilla_estado` y «Sincronizar estado»). Una plantilla **ya aprobada** (importada o no) que Meta pasa a
  `PAUSED` o `DISABLED` por baja calidad **sigue "Aprobada" en Command Center**, y sus envíos fallarán en Meta
  (`PLANTILLA_PAUSADA` / `PLANTILLA_DESHABILITADA`, códigos `132015` y `132016`). El evento ignorado queda en el log
  del servicio (`evento de plantilla sin efecto (estado de Meta PAUSED)`, sin nombre ni texto). Reflejar esos
  estados en la pantalla es un cambio de diseño pendiente.
- **Ejemplos.** Si Meta no devuelve los ejemplos del cuerpo, la fila se guarda sin ejemplos (no afecta el envío,
  solo la edición de un borrador duplicado a partir de ella).
- **Mezclas.** Una plantilla que mezcla `{{1}}` con `{{nombre}}` no se puede importar ni crear
  (`VARIABLES_MEZCLADAS`): Meta no la admite y el envío fallaría.

### 9.5 Referencia técnica

- `GET /api/v1/plantillas-mensaje/meta` y `POST /api/v1/plantillas-mensaje/importar` (máximo 50 plantillas por
  solicitud), servicio `notificaciones`, permiso `notificaciones:editar`; contrato en
  `contracts/openapi/notificaciones.json`. Ambas llevan `Cache-Control: no-store`.
- Meta: `GET /{version}/{waba_id}/message_templates?fields=id,name,language,category,status,components,parameter_format&limit=100`,
  paginando con `paging.cursors.after`. **No se sigue** la URL `paging.next` (Meta la arma con su servidor y a
  veces con el token): solo se usa `CC_META_API_BASE`.
- Código: `cc_notificaciones/meta.py` (`listar`, `obtener`), `servicios/plantillas_meta.py` (compatibilidad e
  importación), `api/plantillas_meta.py`. En local, con `CC_META_PLANTILLAS_STUB`, el listado devuelve datos de
  ejemplo (una de bienvenida compatible; otras con botón con variable, encabezado de imagen, variables mezcladas,
  rechazada y pausada; y las siete plantillas reales de la cuenta compartida: `hello_world` en `en_US`, `vida_*` con
  variables con nombre y botones, y tres en inglés) para ver la pantalla sin Meta.
- No hay cambios de permisos de IAM, ALB ni migraciones: se usa la lectura que ya tenía el servicio sobre
  `cc/{env}/meta` y las reglas de `/api/v1/plantillas-mensaje*`.
- **Contrato de `MensajeSalida`** (cola `wa-salida.fifo`): dos campos **aditivos y opcionales** para plantillas:
  `idioma` (código de idioma de la plantilla; ausente en constancias y bot, que usan `plantilla_idioma`) y
  `variables_nombres` (lista de `parameter_name`, paralela a `variables`; solo en plantillas con nombre). Los mensajes
  de plantillas posicionales conservan su forma (más `idioma`) y el mismo `mensaje_uuid`. Un enviador anterior ignora
  los campos nuevos; un despachador anterior no los manda y el enviador nuevo se comporta como antes.
- **Respuesta de `GET /plantillas-mensaje/meta`** (campos nuevos, aditivos): `formato_variables`
  (`POSICIONAL` | `NOMBRADO`), `variables` (`["1","2"]` o los nombres), `motivos_incompatibles`
  (`[{codigo, motivo}]`), `botones` (`[{tipo, texto}]`) y `encabezado` (`{tipo, formato, texto}` o `null`). Las
  plantillas locales (`PlantillaDto`) también traen `formato_variables` y `variables`.
