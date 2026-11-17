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
- Preparado para la **importación de plantillas ya aprobadas** (tarea posterior): reutilizará estas mismas
  credenciales y el `WABA ID` guardado (`cargador_credenciales` ya los entrega al cliente de plantillas).
