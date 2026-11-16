# Runbook: mensajes antiguos en una cola

**Alarmas (propuesta T-225):** `cc-{env}-cola-antigua-wa-salida` (más de 5 min) y
`cc-{env}-cola-antigua-cola-pdf` (más de 10 min). **Severidad:** Alta. Diseño: §15.2.
Convenciones y variables: [README](README.md).

## Síntoma
`ApproximateAgeOfOldestMessage` supera el umbral: los mensajes se acumulan sin consumirse. La DLQ
todavía puede estar vacía.

## Impacto
`wa-salida`: constancias y notificaciones tardan en llegar al colaborador. `cola-pdf`: solicitudes
de constancia siguen en `EN_PROCESO` más tiempo del esperado.

## Diagnóstico (solo lectura)
1. Profundidad y edad:
   ```
   aws sqs get-queue-attributes --queue-url <url> --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible ApproximateAgeOfOldestMessage --profile $PERFIL
   ```
   Muchos mensajes "no visibles" = se están procesando pero lento o fallando y volviendo a la cola.
2. Consumidor:
   - `wa-salida`: Lambda `enviador` (reservada 10): errores, throttles y duración:
     ```
     aws lambda get-function-concurrency --function-name cc-$ENV-enviador --profile $PERFIL
     aws logs tail /aws/lambda/cc-$ENV-enviador --since 30m --profile $PERFIL
     ```
     Una cola FIFO procesa en orden **por grupo** (`colaborador_id`): un solo mensaje que falla
     bloquea los siguientes del mismo colaborador hasta agotar recepciones.
   - `cola-pdf`: tareas del `worker-pdf` en ECS:
     ```
     aws ecs describe-services --cluster <cluster> --services cc-$ENV-worker-pdf --profile $PERFIL
     aws logs tail /cc/$ENV/worker-pdf --since 30m --profile $PERFIL
     ```
3. Causa frecuente: límite de tasa o caída de Meta (ver [meta-autenticacion-y-errores.md](meta-autenticacion-y-errores.md)),
   `worker-pdf` sin tareas o saturado (ver [worker-pdf.md](worker-pdf.md)), o un envío masivo de 10,000
   destinatarios (acumulación esperada, el despachador tarda varias invocaciones, §15.4).

## Mitigación
- Envío masivo legítimo: espere; vigile que la edad deje de crecer. No hay nada que corregir.
- `worker-pdf` sin tareas: escale la cantidad deseada del servicio (cambia el sistema).
- `enviador` con throttling: revise la concurrencia reservada con la guardia antes de subirla (acota
  la velocidad hacia Meta y las conexiones a la base).

## Escalamiento
Si la edad sigue creciendo 30 minutos después de la mitigación, o aparece la DLQ, escale a
[dlq-con-mensajes.md](dlq-con-mensajes.md) y al responsable del sistema.

## Verificación de resolución
La edad del mensaje más antiguo baja del umbral y la alarma vuelve a `OK`; el panel de Colas muestra
profundidad decreciente.

## Qué NO hacer
- No purgue la cola: se perderían envíos o constancias pendientes.
- No ponga `ReservedConcurrentExecutions` en 0 en el `enviador` "para detener" sin avisar a RH.
- No reenvíe manualmente mensajes que siguen en la cola: duplicaría envíos (la idempotencia por
  `mensaje_uuid` cubre el consumo, no un envío manual por otro canal).
