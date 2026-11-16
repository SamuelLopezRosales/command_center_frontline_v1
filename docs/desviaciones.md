# Desviaciones respecto al diseño

Registro de lo que la infraestructura hace distinto de `design.md` y por qué. T-225 y T-226 amplían este
archivo con las del borde (CloudFront, WAF, API Gateway) y las económicas de `test`.

## T-224: cómputo (`CcCompute` y `CcWorkersLambdas`)

| # | Diseño | Lo que se construyó | Motivo |
|---|---|---|---|
| 1 | ALB interno con HTTPS 443 y certificado de ACM (§13.6) | En `test`: listener **HTTP 80** dentro de la VPC. Con `-c certificado_alb_arn=... -c dominio_interno=...` el listener es HTTPS 443 con TLS 1.2 y 1.3 (`ELBSecurityPolicy-TLS13-1-2-2021-06`) y las URL entre servicios usan `dominio_interno`. `prod` **exige** el certificado (la síntesis falla sin él) | PQ-22: sin dominio, ACM no emite un certificado para el nombre del ALB y un certificado autofirmado importado exige un paso manual que el prototipo no justifica. El tráfico no sale de la VPC: el ALB es interno, `sg-alb` solo admite `sg-vpclink`, `sg-ecs` y `sg-lambda` (las reglas del puerto 80 se crean en `CcNetwork` solo si el ambiente no tiene dominio) y cada llamada interna va firmada con el token de servicio (§11.1) |
| 2 | Tráfico interno "directo al ALB" (§13.7) | Un solo ALB para las rutas públicas (`/api/v1/*`, `/d/*`) y las internas (`/internal/*`), separadas por reglas y prioridades (las internas desde 110). Todas las `CC_*_URL` apuntan al ALB, que enruta por ruta | Evita un segundo mecanismo de descubrimiento (Cloud Map). API Gateway (T-225) no define rutas `/internal/*`, así que el VPC Link nunca las alcanza; la separación se prueba en `test_compute.py` |
| 3 | `/internal/*` "al servicio dueño" | Reglas por prefijo: `/internal/campos/*/uso` va a `colaboradores` (INT-COL-10) **antes** que `/internal/campos*` (`campos`); `/internal/plantillas-mensaje*` va a `notificaciones` **antes** que `/internal/plantillas*` (`constancias`) | Los prefijos se parecen entre servicios; la prioridad lo resuelve |
| 4 | Imágenes publicadas por el pipeline con etiquetas (§14.2) | Activos de CDK (`ContainerImage.from_asset`, `linux/arm64`, contexto = raíz del repositorio): `cdk deploy` construye y publica sin etiquetas manuales. El contexto es una lista de permitidos (solo `services/<x>/` y `services/shared/cc_common`), así que la imagen solo cambia si cambia su código | Decisión D-11 (14 de noviembre de 2026) |
| 5 | Registro de ECS Exec (§13.6) | Sin ECS Exec en los servicios y sin registro de sesión en el clúster | Grabaría el código de invitación que T-049 muestra una vez. Ver `compute_base.py` |
| 6 | Lambdas con DLQ propia (§4.5) | Las funciones con cola como origen usan la **DLQ de la propia cola** (`CcMessaging`, `maxReceiveCount` de §4.1). `conciliador` no lleva DLQ (§4.5: el siguiente ciclo repite) y `webhook-meta` responde síncrono a Meta, que reintenta (§4.2) | Una DLQ de invocación asíncrona no recibe nada de una fuente SQS; duplicarla confundiría los runbooks |
| 7 | Ventana de lote de 2 s en `enviador` (§4.3) | Sin ventana (`wa-salida.fifo` es FIFO) y sin `maximum concurrency` en esa fuente; lote de 10 | La documentación de Lambda no garantiza la ventana de lote ni `maximum concurrency` en colas FIFO y no se puede probar sin desplegar (regla de no tocar AWS); se evita el riesgo de un rechazo en el despliegue. La concurrencia la acotan los grupos de mensajes y la reservada (10). Si Meta limita la tasa, el reintento con espera creciente del `enviador` lo absorbe |
| 8 | Concurrencia en las fuentes SQS | `maximum concurrency` = concurrencia reservada de la función en las colas estándar (5, 5 y 3) | Con un tope inferior al de los *pollers* de SQS, Lambda rechaza lotes por límite de concurrencia y cada rechazo cuenta como recepción hacia la DLQ |
| 9 | `enviador`/`estados-entrega` con `events:PutEvents` y `kms` de la llave de datos (§12) | No se conceden: el código escribe los eventos en el `outbox` de la base (los publica el `relay-outbox` del servicio) y no cifra con la llave de datos. `estados-entrega` tampoco publica en SNS (el código no lo hace todavía) | Mínimo privilegio según lo que el código usa hoy; si T-2xx agrega esas llamadas, se agrega el permiso |
| 10 | Rol de tarea con `sqs:SendMessage` y `sns:Publish` para `dashboard` (§12) | `dashboard` solo tiene Cognito, sus secretos y su rol de base de datos; `campos` solo publica en el bus | El código de esos servicios no usa SQS ni SNS |
| 11 | `consumidor-eventos` en el rol del worker | Los workers no leen las colas `ev-*`; solo las lee la API del servicio (`CC_EVENTOS_ACTIVOS=true`) | Un worker no corre el consumidor de eventos |
| 12 | Tema `alertas-rh` recibe los eventos de SES | `CcMessaging` agrega el tema `cc-{env}-ses-eventos`; el conjunto de configuración de SES publica ahí y `notif-respaldo` se suscribe (sobre de SNS, sin entrega cruda). `alertas-rh` queda para las alertas dirigidas a personas | RH no debe recibir el JSON crudo de SES en su correo. La llave de infraestructura admite a `sns.amazonaws.com` (condicionado a la cuenta) para entregar a la cola cifrada |
| 13 | Buckets con nombre generado | Nombre fijo `cc-{env}-{cuenta}-{bucket}` | `CcCompute` y `CcEdge` los importan por nombre (§13.7) sin referencias entre stacks |
| 14 | Endpoints de VPC de interfaz (§13.3) | No se crearon (ECR, Logs, Secrets Manager, KMS, SQS, STS, EventBridge, SNS) | Cuestan por hora y por zona; en `test` todo sale por la instancia NAT. Sin crear tampoco en `prod` (T-226): se evalúan con el tráfico real (T-230) |
| 15 | `CC_DOMINIO`, `CC_CLOUDFRONT_DOMINIO` y `CC_CLOUDFRONT_KEY_PAIR_ID` del servicio `constancias` | Sin definir en `test`: el dominio de CloudFront no existe cuando se crea `CcCompute` y `CcEdge` depende de `CcApi`, que depende de `CcCompute` | Un valor de `CcEdge` no puede entrar a `CcCompute` sin un ciclo. Ver "Pendiente para T-225" |
| 16 | `CC_EMPRESA_ID` del worker de WhatsApp | Opcional: `-c empresa_id_whatsapp=<id>` (queda sin definir hasta que exista la empresa, PQ-07) | La empresa nace con `bootstrap_admin.py`, después del despliegue |

### Tamaños, escalado y concurrencias elegidos

- Servicios de API: 0.5 vCPU y 1 GB (`campos` 0.25 vCPU y 0.5 GB), según §13.6. Una tarea en `test`
  y dos en `prod`; en `prod` autoescalado de 2 a 6 por CPU al 60 %.
- Workers: `worker-pdf` 1 vCPU y 2 GB (1 a 4 en `prod`, 5 mensajes por tarea); `worker-cargas`
  0.5 vCPU y 1 GB (1 a 2); `worker-whatsapp-entrada` 0.5 vCPU y 1 GB (2 a 4, alta disponibilidad).
  En `test` el mínimo es 0 (cambio D) y el máximo 1. Escalan por el trabajo pendiente de la cola
  (`ApproximateNumberOfMessagesVisible` más los mensajes en proceso, para no apagar una tarea que
  todavía procesa el último mensaje).
- Lambdas: ver la tabla de `infra/stacks/workers_lambdas.py` (memoria, tiempo y reservada de §4).
  La concurrencia aprovisionada de `webhook-meta` es 0 en `test` (no se configura) y 2 en `prod`.

### Pendiente para T-225

- API Gateway: el VPC Link y la integración usan `CcCompute.listener` (ARN en la salida
  `AlbListenerArn`) y `UrlInterna`. No debe haber ninguna ruta `/internal/*`.
- `webhook-meta`: la integración usa el alias `live` (salida `SalidaAlias-webhook-meta`) y el
  permiso de invocación para API Gateway se agrega en `CcApi`.
- El dominio público de las constancias (`CC_DOMINIO`, `CC_CLOUDFRONT_*`): proponer leerlo de un
  parámetro de SSM al arrancar el servicio, o fijarlo con `-c` en un segundo `cdk deploy` cuando
  se conozca el dominio de CloudFront.
- Certificado y nombre interno del ALB para `prod`.

Estado de los pendientes de T-224: el VPC Link, la integración con el ALB, el alias `live` del
webhook y la ausencia de rutas `/internal/*` quedaron resueltos en `CcApi` (T-225). Siguen
abiertos `CC_DOMINIO` y `CC_CLOUDFRONT_*` de `constancias` (desviación 15; ver la 24) y el
certificado interno de `prod`.

## T-225: API, borde, SPA y observabilidad (`CcApi`, `CcEdge`, `CcFrontend`, `CcObservability`)

| # | Diseño | Lo que se construyó | Motivo |
|---|---|---|---|
| 17 | Encabezado secreto de origen que "exige el ALB" (§11.4) | CloudFront agrega `X-Origin-Verify` en `/api/*`, `/webhook/*` y `/d/*`. Lo exigen las reglas **públicas** del ALB (prioridad menor de 100) en `CcCompute`; las `/internal/*` no lo llevan (no pasan por CloudFront). El valor es el secreto `cc/{env}/origin-verify` (nuevo en `CcSecurity`) y viaja como referencia dinámica de CloudFormation (`{{resolve:secretsmanager:...}}`): la plantilla nunca lleva el valor. **La Lambda `webhook-meta` no lo verifica**: la protege la firma HMAC (CC-REQ-158) | Una HTTP API no admite WAF ni condiciones por encabezado, y un autorizador Lambda no puede convivir con el JWT en la misma ruta; el ALB sí puede comparar un encabezado. Una petición sin el valor no coincide con ninguna regla pública y recibe el 404 del listener. Rotar el secreto exige redesplegar `CcCompute` y `CcEdge` (la referencia se resuelve al desplegar) |
| 18 | Dominio propio, certificado de ACM y registros de Route 53 (§13.7); punto de acceso `execute-api` deshabilitado | **Sin dominio propio en `test` (PQ-22)**: la API usa el punto de acceso predeterminado de `execute-api` (protegido por el JWT en `/api/*` y por el encabezado de origen en el ALB), CloudFront usa su dominio `*.cloudfront.net` y su certificado predeterminado (no permite fijar TLS 1.2 como mínimo para el visitante; la conexión al origen sí es TLS 1.2). El CORS de la API y el de `cargas` admiten `https://*.cloudfront.net`. Con `ambiente.dominio` el código ya crea: certificado de ACM validado por DNS, alias A y AAAA, `TLSv1.2_2021`, dominio regional de origen (`-c dominio_origen_api=... -c certificado_origen_api_arn=... -c zona_hospedada_id=...`) y deshabilita `execute-api`. **Esa rama de `prod` solo se probó con un `prod` sintético** | No hay dominio ni zona alojada. `prod` rechaza la síntesis sin esos valores |
| 19 | `/descargas/*` hacia el bucket `constancias` con grupo de claves (§13.7) | El patrón es **`/constancias/*.pdf`** | `firma_cloudfront.py` firma `https://{dominio}/{clave_s3}` con la clave `constancias/{empresa}/{año}/{folio}.pdf` y la firma cubre la URL pedida: con `/descargas` habría que quitar el prefijo antes de la validación. `*.pdf` evita chocar con las rutas `/constancias/...` de la SPA. Si el servicio pasa a firmar `descargas/{clave}` hay que cambiar `PATRON_DESCARGAS` y el prefijo de la política del bucket |
| 20 | La política OAC de los buckets se define desde `CcEdge` (§13.7) | Se define en **`CcStorage`**: el bucket `frontend` admite `s3:GetObject` a `cloudfront.amazonaws.com` y `constancias` solo sobre `constancias/*`, con la condición `aws:SourceArn` = `arn:aws:cloudfront::{cuenta}:distribution/*` (cualquier distribución de la cuenta, no una en particular). La llave `cc-{env}-infra` admite `kms:Decrypt` a CloudFront con la misma condición, y a CloudTrail las sentencias que documenta su guía | Un bucket tiene una sola política y la de `enforce_ssl` ya vive en `CcStorage`: dos stacks no pueden escribir la misma política. El ARN exacto de la distribución crearía un ciclo `CcStorage`-`CcEdge`. Los warnings de CDK por buckets importados sin política se reconocen en `CcEdge` |
| 21 | Registro de CloudFront y de WAF (implícito en §15.1) | **Ninguno**. Ni registros estándar, ni en tiempo real, ni de WAF | Guardarían `/d/{token}` y las URL firmadas (CC-REQ-162). Cierra el pendiente de T-210: API Gateway tampoco guarda la ruta, su registro de acceso lleva `routeKey` (la plantilla `/d/{proxy+}`) y no `$context.path`. Quedan las métricas estándar. Si se necesitara el registro de WAF, hay que censurar `UriPath` y la consulta |
| 22 | CSP "la SPA llama solo a su origen" (T-225); `connect-src` solo "el dominio y el punto de acceso de Cognito" (§11.4) | `default-src 'self'`; `script-src 'self'`; **`style-src 'self' 'unsafe-inline'`**; `connect-src 'self'` + `https://cognito-idp.{región}.amazonaws.com` + los dos puntos de acceso de S3 (regional y global) de los buckets `cargas` y `plantillas` (subidas prefirmadas); `img-src 'self' data: blob:`; `object-src 'none'`; `frame-ancestors 'none'`. La página `/d/{token}` y las respuestas de la API tienen su propia CSP más cerrada | La SPA inicia sesión con Amplify directo contra Cognito, así que no llama solo a su origen. `'unsafe-inline'` en estilos lo piden TipTap y los estilos de React (igual que la CSP de desarrollo de `frontend/cabeceras.ts`); los scripts no lo admiten |
| 23 | Política de origen que reenvía `Authorization` (§13.7) | CloudFront no permite `Authorization` en una política de origen: va en una política de **caché** propia (TTL 0 a 1 s, `Authorization` en la llave, sin cookies). Solo `/api/*` la usa; `/webhook/*` y `/d/*` usan `CachingDisabled` y no reciben `Authorization` | Restricción de CloudFront (la comprueba el SDK al sintetizar). Una respuesta cacheable quedaría guardada por token, nunca compartida |
| 24 | Llave de firma de CloudFront cargada en T-138 | `CcEdge` crea la llave pública y el grupo de claves con la llave de `-c cloudfront_public_key_pem=...` o de `infra/config/cloudfront-{env}.pub.pem`. **Sin ninguna, `test` usa una llave pública inerte** (se generó el par y se descartó la privada): se despliega, pero ninguna URL firmada valida. `prod` la exige. **Procedimiento (lo ejecuta una persona, no el CDK):** 1) `openssl genrsa -out cf.pem 2048` y `openssl rsa -pubout -in cf.pem -out infra/config/cloudfront-test.pub.pem`; 2) desplegar `CcEdge` y leer la salida `LlavePublicaId`; 3) cargar en el secreto `cc/test/cf-signing-key` el JSON `{"key_pair_id": "<LlavePublicaId>", "private_key_pem": "<cf.pem>"}`; 4) definir `CC_CLOUDFRONT_DOMINIO` (salida `DominioPublico`), `CC_CLOUDFRONT_KEY_PAIR_ID` y `CC_CLOUDFRONT_CLAVE_SECRETO_ID` en `constancias` (desviación 15) y borrar `cf.pem` | La llave privada nunca pasa por el CDK ni por una plantilla. El identificador de la llave y el grupo llevan la huella de la llave pública: rotarla crea una nueva y no reemplaza en sitio |
| 25 | Conjuntos administrados de WAF en bloqueo (§11.4) | Solo con `waf_habilitado` (en `prod`): reputación de IP, reglas comunes y entradas maliciosas conocidas, y tres reglas de tasa por IP en 5 minutos (`/api/v1/publico/` y `/d/` 100; `/api/` 1,000; `/webhook/` 5,000). **`CrossSiteScripting_BODY` y `SizeRestrictions_BODY` van en conteo** y la regla del webhook cuenta, no bloquea | El editor de plantillas envía HTML en el cuerpo JSON y esas reglas lo bloquearían; Meta envía desde pocas IP y la firma HMAC ya protege (§11.4). Los límites son **[POR CONFIRMAR]** (PQ-20) |
| 26 | Limitación de tasa en API Gateway (§11.4) | Por etapa y por ruta (`LIMITES` en `api.py`: JWT 50 por segundo y ráfaga de 100; públicas y descargas 5 y 10; webhook POST 50 y 100, GET 2 y 5; predeterminado de la etapa 100 y 200). **[POR CONFIRMAR]** (PQ-20) | API Gateway limita por ruta y no por IP (eso lo hace WAF en `prod`). Los valores son una propuesta conservadora para un solo cliente |
| 27 | Alarmas "SNS de guardia" (§15.2) | Todas notifican al tema nuevo `cc-{env}-alertas-ops` de `CcObservability` (cifrado con la llave de infraestructura), no a `alertas-rh`; el borde tiene su propio `cc-{env}-alertas-edge` en `CcEdge` (§13.2). Ninguno tiene suscripciones: dependen del canal (PQ-17) | `alertas-rh` es para personas de RH (desviación 12), no para alarmas de infraestructura |
| 28 | Alarma de conmutación de RDS | Es una **regla de EventBridge** (`cc-{env}-rds-conmutacion`, categoría `failover`) hacia el tema de operación, no una alarma de CloudWatch: la conmutación es un evento, no una métrica | Es la forma de detectarla |
| 29 | Métricas de §15.2 | Existen hoy en el código (EMF): `webhook_firma_invalida` y `programadas_atrasadas`. `meta_error_*` lleva el código en el nombre, así que un filtro de métricas del registro de `enviador` las suma (`CommandCenter/Observabilidad:meta_errores`) y la alarma divide entre las invocaciones de `enviador` (aproximación: la unidad real es el envío, no el lote). **Ningún servicio emite todavía** `duracion_generacion_ms` y `solicitudes_render_fallidas` (`CommandCenter/Constancias`) ni `error_descifrado` (`CommandCenter/Seguridad`): sus alarmas existen, quedan sin datos (`notBreaching`) y los paneles muestran vacío hasta que el servicio las emita. La alarma `5xx` de un servicio exige al menos 10 solicitudes en la ventana; `webhook-5xx` mide errores de la Lambda (una respuesta 500 explícita del handler no cuenta como error de Lambda) | Evitar falsas alarmas con poco tráfico y no inventar métricas que el código no tiene. Seguimiento: T-229 o una tarea de los servicios |
| 30 | Cinco paneles (§15.2) | `prod` crea los cinco (Operación, Colas, WhatsApp, Constancias y Base de datos). **`test` crea tres**: Operación con Base de datos, Colas con WhatsApp y Constancias | Los tres primeros paneles de la cuenta no cuestan y cada adicional cuesta unos 3 USD al mes. Cada panel de `test` queda por debajo de 50 métricas |
| 31 | CloudTrail con 1 año en S3 (§15.1) | Un trail de gestión multirregión con validación de integridad de archivos, bucket propio cifrado con `cc-{env}-infra`, 365 días de retención y **sin entrega a CloudWatch Logs ni registro de datos de S3** (`DESTROY` en `test`, `RETAIN` en `prod`) | El primer trail de gestión es gratis; la entrega a Logs y los eventos de datos cuestan |
| 32 | Referencias entre regiones (§13.2) | `CcEdge` se fija en `us-east-1` y se crea con `cross_region_references`; hoy el proyecto completo está en `us-east-1`, así que no hay recursos entre regiones. La referencia dinámica del secreto de origen solo resuelve en la región del stack: si la región principal cambiara, el secreto debe replicarse o leerse de otra forma | Cambiar la región principal no debe obligar a rehacer el borde |
| 33 | La SPA lee su configuración de Cognito al compilar (`VITE_COGNITO_*`) | `CcFrontend` publica `config.json` junto a la SPA (`userPoolId`, `userPoolClientId`, `region`, `apiBaseUrl`, sin secretos) y `frontend/src/shared/config.ts` lo lee antes de montar; sin archivo cae en `VITE_COGNITO_*` y el acceso de desarrollo (`VITE_AUTH_LOCAL`) no cambia. La síntesis exige `frontend/dist` (`npm run build` en `frontend/`) | El mismo paquete sirve a cualquier ambiente sin recompilar |

### Desviaciones económicas de `test` (presupuesto de 50 USD)

Ninguna se aplica a `prod`. Ver también `docs/ambientes.md` §2.

| Elemento | `test` | `prod` | Dónde |
|---|---|---|---|
| Salida a internet | Una instancia NAT `t4g.micro` | Una NAT Gateway por zona | `CcNetwork` |
| RDS | `db.t4g.micro`, una zona, sin protección contra borrado, respaldos de 1 día | `db.t4g.medium`, Multi-AZ, protegida, 14 días | `CcData` |
| RDS Proxy | No se despliega; las Lambdas se conectan directo | Sí | `CcData`, `CcWorkersLambdas` |
| WAF | No se crea (`waf_habilitado=false`) | Conjuntos administrados y reglas de tasa en bloqueo | `CcEdge` |
| Workers de ECS | Mínimo 0 tareas y máximo 1; sin concurrencia aprovisionada | Mínimo 1 (2 en WhatsApp) | `CcWorkersLambdas` |
| Servicios de API | 1 tarea y sin autoescalado | 2 tareas y autoescalado de 2 a 6 | `CcCompute` |
| Buckets | Nombre fijo `cc-{env}-{cuenta}-{bucket}`; se vacían y borran con `cdk destroy` | Conservados | `CcStorage` |
| ALB interno | HTTP en el puerto 80 (sin certificado) y sin registro de acceso | HTTPS y registro de acceso | `CcCompute` |
| Dominio | Sin dominio propio: `*.cloudfront.net` y `execute-api` predeterminado | Dominio, ACM y Route 53 | `CcEdge`, `CcApi` |
| Paneles de CloudWatch | Tres (gratuitos) | Cinco | `CcObservability` |
| CloudTrail | Mismo trail de gestión, bucket borrable | Bucket conservado | `CcObservability` |
| Container Insights y endpoints de VPC | No | Container Insights; endpoints de interfaz sin crear (T-226, desviación 14) | `CcComputeBase` |
| Respaldo (T-226) | Bóveda y plan de 1 día, sin copia, sin región de recuperación | Plan de 35 días con copia y réplica a `us-east-2`, bóveda con bloqueo | `CcBackup`, `CcBackupRecuperacion` |
| Pipeline (T-226) | No se crea (solo con `-c pipeline=true`) | Se crea, con aprobación manual | `CcPipeline` |

### Pendiente después de T-225

- ~~**T-226**: aserciones globales de IAM, respaldo y pipeline~~. Hecho: ver la sección siguiente.
  El pipeline corre `npm run build` en `frontend/` antes de sintetizar (`CcFrontend` falla sin
  `frontend/dist`).
- **T-229**: probar de extremo a extremo, ya desplegado, lo que no se puede verificar sin AWS:
  `Authorization` en la política de caché, referencia dinámica del secreto en el ALB y en CloudFront,
  `AllowOrigins` con comodín en la HTTP API, filtro de métricas `meta_error_*`, firma de URL con la
  llave real y el 404 de `/internal/*` por el borde.
- **Servicios**: emitir `duracion_generacion_ms`, `solicitudes_render_fallidas` y `error_descifrado`
  (desviación 29), y fijar `CC_CLOUDFRONT_*` (desviaciones 15 y 24).

## T-226: respaldo, pipeline y revisión global (`CcBackup`, `CcBackupRecuperacion`, `CcPipeline`)

| # | Diseño | Lo que se construyó | Motivo |
|---|---|---|---|
| 34 | `CcBackup` es un stack "principal y recuperación (`us-east-2`)" (§13.1) | **Dos stacks**: `CcBackup-{env}` (región principal: bóveda `cc-{env}-respaldos`, plan y rol) y `CcBackupRecuperacion-{env}` (`us-east-2`: llave `alias/cc-{env}-recuperacion`, bóveda `cc-{env}-recuperacion` y el bucket `constancias-replica`). El segundo **solo existe en `prod`** | Un stack de CloudFormation vive en una sola región. En `test` la región de recuperación no está inicializada con `cdk bootstrap` y no se despliega nada allí: queda definido y se prueba con un `prod` sintético (`infra/tests/test_backup.py`). Ni un `-c` lo crea en `test` |
| 35 | Plan diario de AWS Backup con copia a `us-east-2`, retención de 35 días (§14.5) | `prod`: regla diaria a las 07:00 UTC, retención de **35 días** en la bóveda principal y en la de recuperación, bloqueo de la bóveda en modo de gobierno (7 días mínimos, se puede quitar con un permiso explícito) y política de acceso que niega `DeleteRecoveryPoint` y `UpdateRecoveryPointLifecycle`; la bóveda se conserva al destruir. `test`: la misma regla con **1 día** (`retencion_respaldos_dias`), sin copia, sin bloqueo y con la bóveda borrable | Sin borrado accidental en `prod` (CC-NFR-006) y limpieza posible en `test`. El PITR de RDS (14 días) sigue activo en `prod` además de AWS Backup |
| 36 | La réplica de `constancias` la define `CcBackup` | La define **`CcStorage`** (propiedad `ReplicationConfiguration` del bucket, solo `prod`) con un rol propio `cc-{env}-s3-replicacion-constancias`; el destino es el bucket de `CcBackupRecuperacion`. Por eso **`CcStorage` depende de `CcBackupRecuperacion`** (S3 exige que el bucket de destino exista al configurar la réplica) y el orden de despliegue de `prod` empieza por la región de recuperación. Las marcas de borrado no se replican; sin S3 RTC (el RPO de la réplica es de minutos, sin garantía de 15 minutos) | Un bucket tiene una sola configuración y CDK no permite modificar un bucket importado. Ningún valor cruza regiones por una referencia de CloudFormation: los nombres se arman en `infra/constructs/recuperacion.py` |
| 37 | La llave de la región de recuperación en la réplica y en la copia | Se identifica por su **alias** (`ReplicaKmsKeyID` con el ARN del alias) y los permisos de uso llevan `kms:ResourceAliases = alias/cc-{env}-recuperacion` sobre `arn:aws:kms:us-east-2:{cuenta}:key/*` | El identificador de una llave no se conoce antes de crearla. **No se pudo verificar sin AWS** que S3 y AWS Backup acepten el alias y la condición; si no, T-230 lo detecta en la prueba de recuperación (el síntoma sería una réplica en `FAILED`) |
| 38 | Réplica opcional de `plantillas` (§14.5) | **No se activa**. El versionado conserva cada versión de plantilla y `prod` niega borrar versiones | Más costo y más superficie sin un requisito que la exija; se activa agregando otra regla de réplica |
| 39 | Rol de AWS Backup (§12 no lo lista) | Rol propio `cc-{env}-backup` con política mínima (instantáneas de RDS con el prefijo `awsbackup:`, instancias con la etiqueta `ambiente` del ambiente, la llave de infraestructura y, en `prod`, la bóveda y la llave de recuperación), sin la política administrada `AWSBackupServiceRolePolicyForBackup`. La selección es `CfnBackupSelection` (L1) porque la clase L2 le agrega esa política administrada. La restauración la hace una persona con su propio rol | Mínimo privilegio y que ningún rol tenga políticas administradas amplias |
| 40 | `CcPipeline` en una "cuenta de herramientas" (§13.1) | **Un pipeline por ambiente en la misma cuenta del ambiente** (`CcPipeline-{env}`), sin referencias a otros stacks. **No se crea en `test`** salvo con `-c pipeline=true -c repositorio_pipeline=propietario/repo`; en `prod` sí (`-c pipeline=false` lo omite) | Una sola cuenta por ambiente (PA-1 a PA-3) y el pipeline completo cuesta y crea una conexión que se autoriza a mano. Si el cliente da una cuenta de herramientas hay que agregar roles entre cuentas (fuera del alcance) |
| 41 | Aprobación manual antes de `test` y antes de `prod` (§14.2) | La etapa **Aprobacion** va **en ambos ambientes**, después de la compilación y antes de cualquier despliegue. En `test` no hay instantánea de RDS (solo `prod`, §14.2) | Más conservador: un pipeline de `test` nunca despliega solo, que es lo que pasaría con el presupuesto de 50 USD |
| 42 | `ecs run-task` por servicio con "misma imagen de cada servicio" (§2.8) | Una sola tarea `migrar` (la de T-043: imagen `cc-{env}/migrar`, `scripts/migrar_todo.py`) que aplica el orden de §2.8 y luego `roles.sql`, `rls.sql` y `grants.sql`. El pipeline la lanza y **se detiene si el código de salida no es 0**. Las imágenes `migrar` y `ops` se publican en la etapa Base si su etiqueta no existe (los repositorios son inmutables) | Es lo que ya construyó y probó T-043 a T-047 en `cc-test` |
| 43 | Permiso del pipeline "`cloudformation:*` y `sts:AssumeRole`" (§12) | Sin `cloudformation:*` y sin `iam:*`: los proyectos de despliegue solo **asumen los cuatro roles de bootstrap de CDK** de la cuenta (`cdk-hnb659fds-*`, en la región principal y, en `prod`, en `us-east-2`), leen las salidas de los stacks `Cc*-{env}` (`DescribeStacks`) y la versión del bootstrap. La instantánea, la tarea `migrar` y la publicación de imágenes tienen cada una su rol acotado al ambiente y la cuenta. **El poder real de despliegue lo da el rol de ejecución de CloudFormation del bootstrap** (por defecto `AdministratorAccess`, fuera de este repositorio) | Mínimo privilegio en lo que controla este código; endurecer el rol del bootstrap es una decisión de cuenta (`cdk bootstrap --cloudformation-execution-policies`) |
| 44 | Conexión de origen "[POR CONFIRMAR]" (§14.2) | `CfnConnection` de CodeConnections (GitHub) en estado **PENDIENTE**: una persona la autoriza en la consola. Se puede reutilizar una existente con `-c conexion_codigo_arn=...`. La llave pública de CloudFront de `prod` (`*.pem` no se versiona) llega por el parámetro de SSM `/cc/prod/pipeline/clave-publica-cloudfront` (se crea a mano una vez) | Ningún token pasa por la plantilla |
| 45 | Buildspec de T-016 (`infra/pipeline/buildspec-ci.yml`) | Se **eliminó** y lo reemplazan los buildspecs de `infra/pipeline/buildspecs.py`: CI (`npm run build` antes del synth, empaquetado de las tres variantes de Lambdas, ruff, pytest, vitest y `cdk synth` con cdk-nag), instantánea (`prod`), base, migrar y servicios | Un solo origen de verdad, probado por `infra/tests/test_pipeline.py` |
| 46 | Alarmas y notificaciones de AWS Backup | No se crean (sin tema SNS suscrito: PQ-17) | Igual que las alarmas de `CcObservability` (desviación 27) |

### Hallazgos de la revisión global de IAM y de infraestructura (T-141)

`infra/tests/test_global.py` revisa `test` y un `prod` sintético con todos los stacks. Resultado:

- **Sin `Resource: "*"`** salvo la lista cerrada `ACCIONES_CON_COMODIN_PERMITIDO`
  (`ecr:GetAuthorizationToken`, los cuatro `ssmmessages:*` de ECS Exec y
  `cloudfront:CreateInvalidation`/`GetInvalidation` del `BucketDeployment` de CDK), cada una con su
  motivo. Ningún `iam:*` ni `servicio:*`, ningún `AdministratorAccess` ni `PowerUserAccess`, ninguna
  política de recurso con principal comodín.
- **`kms:Decrypt`** presente en cada rol que lee un secreto en todos los stacks de `test` y `prod`
  (la prueba cubre `CcAuth`, `CcCompute`, `CcComputeBase`, `CcWorkersLambdas`, el RDS Proxy de
  `CcData` y `CcPipeline`).
- **Corregido, `prod`: sin registro de flujo de la VPC** (`AwsSolutions-VPC7`). `CcNetwork` solo lo
  reconocía fuera de `prod` ("se agregan en producción") pero nunca lo creó. Ahora `prod` registra
  el tráfico **rechazado** en `/cc/prod/vpc-flujos` (30 días, se conserva). `test` sigue sin registro.
- **Corregido, `prod`: monitoreo ampliado de RDS** usa la política administrada
  `AmazonRDSEnhancedMonitoringRole` (`AwsSolutions-IAM4`) y no tenía el reconocimiento. Se agregó con
  su motivo (es la única forma documentada de dar ese permiso a RDS).
- El `cdk synth` con cdk-nag de **`prod` con todos los stacks no se probaba**: ahora lo hace
  `test_cdk_nag_no_deja_hallazgos_en_prod_con_todos_los_stacks` (y la variante con pipeline en `test`).
- **Sin hallazgo, por decisión**: no hay ingreso `0.0.0.0/0` en ningún grupo de seguridad, ni en
  `test` ni en `prod`; no hay excepciones que documentar.
- **Sigue abierto** (desviación 14): los endpoints de VPC de interfaz de `prod` no se crearon. La
  decisión es no agregarlos todavía: `prod` sale por una NAT Gateway por zona y los endpoints cuestan
  por hora y por zona; se evalúan con el tráfico real (T-230) antes de pagar.

### Qué no se pudo verificar sin AWS (T-229 y T-230)

- Que S3 acepte el **alias** de la llave como `ReplicaKmsKeyID` y que `kms:ResourceAliases` autorice
  al rol de replicación y al de AWS Backup (desviación 37).
- Que la política de acceso de la bóveda de `prod` (`Deny` a todos los principales) no impida el
  vencimiento normal de los puntos de recuperación ni la copia entre regiones.
- Que `aws:ResourceTag/ambiente` esté disponible en `rds:CreateDBSnapshot` y en
  `rds:DescribeDBInstances` para el rol de respaldo y el de la instantánea previa.
- El buildspec completo: `docker info` en CodeBuild con modo privilegiado, que `cdk deploy` de los
  stacks base (RDS) quepa en el límite de 90 minutos y que `aws ecs wait tasks-stopped` (10 minutos
  como máximo) alcance para las migraciones.
- La conexión de CodeConnections debe estar `AVAILABLE` (autorizada a mano) antes de la primera
  ejecución; si no, la etapa Fuente falla.


## Ambiente `samuel`: MFA apagado y sin concurrencia reservada

| # | Diseño | Lo que se construyó | Motivo |
|---|---|---|---|
| 1 | MFA obligatorio con app autenticadora (CC-REQ-002, DS-21) | `economia.mfa` en `infra/config/ambientes.json`: `ON` (por defecto), `OPTIONAL` u `OFF`. El ambiente `samuel` usa `OFF`: Cognito no pide el segundo factor. `prod` (tipo prod, `permite_borrado: false`) **solo admite `ON`**: el cargador de configuración lo rechaza | Decisión de Samuel (15 de noviembre de 2026): el ambiente lo usarán varias personas del equipo y el MFA estorba durante el desarrollo. Con MFA apagado la seguridad de acceso depende de la contraseña de 12 caracteres, el bloqueo por intentos de Cognito y el código de invitación. cdk-nag `AwsSolutions-COG2` se reconoce solo cuando el MFA no es `ON`. La SPA ya maneja el paso `DONE` de Amplify (sin pantalla de TOTP). Para volver a exigirlo basta cambiar el valor a `ON` y redesplegar `CcAuth` |
| 2 | Concurrencia reservada por Lambda (§4.2 a §4.5) | `economia.reservar_concurrencia`: `false` en `samuel`; las Lambdas no reservan y los *pollers* de SQS estándar usan un tope de 2 | Una cuenta nueva de AWS tiene una cuota de 10 ejecuciones concurrentes y AWS exige dejar 100 sin reservar. Las funciones comparten esas 10; si hay estrangulamiento, pedir el aumento `L-B99A9384` y volver a `true` |
