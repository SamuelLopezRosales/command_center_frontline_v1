# Runbook: firma inválida o errores 5xx en el webhook de Meta

**Alarmas (propuesta T-225):** `cc-{env}-webhook-firma-invalida` (más de 10 `webhook_firma_invalida`
en 5 min, **Alta**) y `cc-{env}-webhook-5xx` (errores de la Lambda `webhook-meta`, **Crítica**).
Diseño: §4.2, §11.3, §14.6. Convenciones y variables: [README](README.md).

## Síntoma
Meta rechaza o reintenta entregas del webhook, o no llegan mensajes de colaboradores. La Lambda
responde 403 (firma inválida) o 500 (falló el envío a SQS).

## Impacto
Los colaboradores no reciben respuesta del bot y los estados de entrega no se actualizan. Meta
reintenta durante días: no se pierde lo ya enviado por Meta, se atrasa.

## Diagnóstico (solo lectura)
1. ¿Firma o SQS? La métrica y los logs de la Lambda (no registran cuerpo ni números):
   ```
   aws logs tail /aws/lambda/cc-$ENV-webhook-meta --since 30m --profile $PERFIL
   ```
   Busque `webhook_firma_invalida` frente a `webhook_error_sqs`.
2. **Firma inválida repetida.** Causas: (a) el secreto de la aplicación en Secrets Manager no
   coincide con el de Meta (tras una rotación o un cambio de app); (b) alguien envía solicitudes
   falsas al endpoint (ataque o sondeo). Si son pocas y de orígenes variados y no hay quejas de
   mensajes perdidos, es (b) y el WAF ya limita por IP.
   Compare **sin imprimir el valor**: confirme que la versión del secreto cambió y cuándo:
   ```
   aws secretsmanager describe-secret --secret-id cc/$ENV/meta --profile $PERFIL
   ```
   (muestra fechas y versiones, no el valor; el valor lo compara una persona autorizada contra el
   panel de Meta sin copiarlo a ningún ticket).
3. **5xx.** Profundidad de `wa-entrada.fifo` y estado de SQS/KMS:
   ```
   aws sqs get-queue-attributes --queue-url <wa-entrada.fifo> --attribute-names All --profile $PERFIL
   ```
   Revise también permisos recientes (`sqs:SendMessage`, descifrado de la llave de infraestructura).

## Mitigación
- (a) Corregir el secreto `cc/$ENV/meta` con el valor vigente de Meta (cambia el sistema; caché de
  5 minutos en la Lambda, o publique una nueva versión para forzar). Después Meta reintenta solo;
  reprocese lo que quede en `wa-entrada` revisando [dlq-con-mensajes.md](dlq-con-mensajes.md).
- (b) Sin acción en la Lambda: es el comportamiento correcto (403 y no encola). Si el volumen es
  alto, pida a la guardia endurecer la regla de WAF de `/webhook/meta`.
- 5xx por SQS: restablecer el permiso o la clave; Meta reintenta.

## Escalamiento
Si tras alinear el secreto sigue la firma inválida, o hay evidencia de que se aceptó una solicitud
sin firma válida (no debe ocurrir: la prueba de T-143 lo cubre), escale de inmediato al responsable
del sistema y al área jurídica.

## Verificación de resolución
`webhook_firma_invalida` vuelve a cerca de 0; un mensaje de prueba al número de WhatsApp llega a
`wa-entrada` y el bot contesta; la alarma vuelve a `OK`.

## Qué NO hacer
- No desactive la verificación de firma "temporalmente" ni la bypassee para probar.
- No pegue el secreto de la aplicación en chats ni tickets.
- No abra el límite del WAF de `/webhook/meta` a todo internet sin firma: la firma es la barrera.
- No registre el cuerpo del webhook para diagnosticar (contiene números y mensajes).
