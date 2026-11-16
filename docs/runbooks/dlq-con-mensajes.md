# Runbook: DLQ con mensajes

**Alarmas (propuesta T-225):** `cc-{env}-dlq-{cola}`, una por DLQ. **Severidad:** Crítica.
Diseño: §4.1, §14.6. Convenciones y variables: [README](README.md).

## Síntoma
`ApproximateNumberOfMessagesVisible` de una DLQ es mayor a 0. Hay entregas, generaciones, cargas,
estados o eventos que agotaron sus recepciones y no se completaron.

| DLQ | Qué se quedó sin hacer | Consumidor |
|---|---|---|
| `cc-$ENV-cola-pdf-dlq` | Constancias sin generar | `worker-pdf` |
| `cc-$ENV-cola-cargas-dlq` | Cargas masivas sin procesar | `worker-cargas` |
| `cc-$ENV-wa-entrada-dlq.fifo` | Mensajes de colaboradores sin atender | `worker-whatsapp-entrada` |
| `cc-$ENV-wa-salida-dlq.fifo` | Mensajes de WhatsApp sin enviar | `enviador` |
| `cc-$ENV-wa-estados-dlq` | Estados de entrega sin aplicar | `estados-entrega` |
| `cc-$ENV-notif-despacho-dlq` | Notificaciones sin despachar | `despachador` |
| `cc-$ENV-notif-respaldo-dlq` | Correos de respaldo sin enviar | `respaldo-correo` |
| `cc-$ENV-ev-colaboradores-dlq`, `ev-constancias-dlq`, `ev-notificaciones-dlq` | Eventos entre servicios sin consumir | API de cada servicio |

## Impacto
Retención de las DLQ: 14 días (§4.1). Pasado ese plazo los mensajes se pierden. Un colaborador o RH
puede estar esperando una constancia o una notificación.

## Diagnóstico (solo lectura)
1. Identifique la cola y cuántos mensajes hay:
   ```
   aws sqs get-queue-url --queue-name cc-$ENV-<cola>-dlq --profile $PERFIL
   aws sqs get-queue-attributes --queue-url <url> --attribute-names ApproximateNumberOfMessages ApproximateAgeOfOldestMessage --profile $PERFIL
   ```
2. Busque la causa en los logs del consumidor por `correlacion_id` y código de error, **nunca** por
   el contenido del mensaje:
   ```
   aws logs tail /cc/$ENV/<servicio> --since 1h --filter-pattern '"ERROR"' --profile $PERFIL
   aws logs tail /aws/lambda/cc-$ENV-<función> --since 1h --filter-pattern '"ERROR"' --profile $PERFIL
   ```
3. Clasifique:
   - **Técnico** (Meta, SES, S3, KMS o base de datos caídos; despliegue defectuoso): el mensaje es
     válido y puede reintentarse tras corregir.
   - **De negocio** (colaborador sin elegibilidad, plantilla sin datos, ventana de 24 h cerrada):
     la solicitud o el destinatario ya quedó `FALLIDA`/`FALLIDO` en la base. No se reintenta el
     mensaje; se atiende por la pantalla de RH.
4. Confirme que el aviso a RH salió: evento `constancia.fallida` en el panel de Constancias o la
   alerta del dashboard (T-213), según el caso.

## Mitigación
- Técnico, tras corregir la causa: **re-drive de SQS** de la DLQ a su cola de origen:
  ```
  aws sqs start-message-move-task --source-arn <arn-de-la-DLQ> --profile $PERFIL
  ```
  (cambia el sistema: requiere autorización de la guardia). Observe que la DLQ se vacía.
- Notificaciones fallidas por Meta: RH puede usar **Reintentar** en el detalle del envío
  (`notificaciones:enviar`); no hace falta el re-drive.
- Constancias `FALLIDA` por `ERROR_RENDER`: ver [worker-pdf.md](worker-pdf.md).
- De negocio: no se mueve nada; se deja registrado y se avisa a RH.

## Escalamiento
Si una DLQ de `wa-salida`, `cola-pdf` o `ev-*` sigue recibiendo mensajes tras corregir, o la causa
no está en los logs, escale al responsable del sistema. Si la causa podría exponer datos
personales (por ejemplo, un cuerpo de mensaje en un log), escale además al área jurídica.

## Verificación de resolución
`ApproximateNumberOfMessagesVisible = 0` en la DLQ, la alarma vuelve a `OK`, y las solicitudes o
destinatarios afectados terminan en `ENTREGADA`/`ENTREGADO` o en un estado `FALLIDA` explicado.

## Qué NO hacer
- No haga `receive-message` para "ver qué trae": puede exponer un código, token o texto.
- No haga `purge-queue` ni borre mensajes de una DLQ sin clasificarlos.
- No reintente en bloque mensajes de `wa-salida` si la causa es el token de Meta (reenviaría todo
  y volvería a fallar): primero [meta-autenticacion-y-errores.md](meta-autenticacion-y-errores.md).
- No suba `maxReceiveCount` para "hacer pasar" mensajes que fallan.
