# Runbook: errores de Meta y token de acceso inválido o vencido

**Alarma (propuesta T-225):** `cc-{env}-meta-errores` (métricas `meta_error_*` con tasa mayor a 10 %
durante 10 min). **Severidad:** Crítica si todos los envíos fallan; Alta si es parcial.
Diseño: §4.3, §14.6. Convenciones y variables: [README](README.md).

## Síntoma
Casi todos los envíos de WhatsApp fallan (token inválido o vencido, código de error de
autenticación de Meta) o falla una fracción (límite de tasa, 5xx de Meta, plantilla rechazada).

## Impacto
Constancias y notificaciones no llegan; los destinatarios quedan `FALLIDO` tras agotar intentos y
la DLQ `wa-salida` empieza a recibir mensajes.

## Diagnóstico (solo lectura)
1. Qué código predomina (métricas `meta_error_{codigo}` en el panel de WhatsApp o en los logs):
   ```
   aws logs tail /aws/lambda/cc-$ENV-enviador --since 30m --filter-pattern '"meta_error"' --profile $PERFIL
   ```
   - Autenticación (token inválido o vencido): todos los envíos, desde un instante dado.
   - Límite de tasa o 5xx de Meta: intermitente; reintento con espera creciente.
   - Número o plantilla: errores permanentes en mensajes concretos (negocio, no de plataforma).
   Los códigos concretos de Meta se confirman al vincular la cuenta (PQ-07).
2. Fecha de la última modificación del secreto (sin ver su valor):
   ```
   aws secretsmanager describe-secret --secret-id cc/$ENV/meta --profile $PERFIL
   ```
3. Estado de la plataforma de Meta (página de estado de WhatsApp Business) y calidad/límites de la
   cuenta (la Lambda `estados-entrega` puede alertar por SNS, §4.4).

## Mitigación
1. Token vencido o revocado: genere un token nuevo en Meta y **rótelo** en el secreto
   `cc/$ENV/meta` (una persona autorizada; cambia el sistema).
2. Espere 5 minutos (caché del secreto) o fuerce con un nuevo despliegue/versión de las Lambdas.
3. Haga el **re-drive** de `wa-salida` desde su DLQ (ver [dlq-con-mensajes.md](dlq-con-mensajes.md)); las notificaciones
   `FALLIDO` por esta causa también pueden **Reintentarse** desde RH.
4. Límite de tasa de Meta: no hay acción; el reintento lo absorbe. Si es por volumen de una
   notificación masiva, reduzca el tope diario del despachador.

## Escalamiento
Si el token es válido en Meta y sigue fallando, o la cuenta quedó restringida por calidad,
escale al responsable del sistema y a quien administra la cuenta de WhatsApp Business.

## Verificación de resolución
La tasa de `meta_error_*` baja de 10 %, un envío de prueba llega y queda `ENVIADO`, la DLQ de
`wa-salida` se vacía tras el re-drive y la alarma vuelve a `OK`.

## Qué NO hacer
- No pegue el token en chats, tickets ni en variables de entorno de las Lambdas: solo en Secrets Manager.
- No haga re-drive antes de rotar el token (volvería a fallar y agotaría intentos).
- No cambie de plantilla ni de número para "esquivar" un error de autenticación.
- No reenvíe manualmente por WhatsApp personal: se rompe la bitácora y el consentimiento.
