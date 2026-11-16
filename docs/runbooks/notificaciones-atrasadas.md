# Runbook: notificaciones `PROGRAMADA` atrasadas

**Alarma (propuesta T-225):** `cc-{env}-programadas-atrasadas` (`programadas_atrasadas` mayor a 0
durante 15 min). **Severidad:** Alta. Diseño: §4.5, §6.3, §14.6. Convenciones: [README](README.md).

## Síntoma
Notificaciones programadas no salen a su hora; siguen `PROGRAMADA` pasada su `fecha_envio`.

## Impacto
Avisos a colaboradores fuera de tiempo. Cuidado: el horario permitido (08:00 a 20:00 de la empresa)
puede ser la razón legítima: una notificación fuera de horario sin confirmación se reprograma a las
08:00 y no es una falla.

## Diagnóstico (solo lectura)
1. ¿Está dentro del horario de la empresa y confirmada? Revise el estado en la SPA (detalle del envío).
2. EventBridge Scheduler: el schedule `cc-{id}-{n}` existe en el grupo `cc-$ENV-envios`:
   ```
   aws scheduler list-schedules --group-name cc-$ENV-envios --profile $PERFIL
   ```
3. Cola `notif-despacho` y su DLQ:
   ```
   aws sqs get-queue-attributes --queue-url <notif-despacho> --attribute-names All --profile $PERFIL
   ```
4. Logs del `despachador` y del `conciliador` (el conciliador reencola programadas con más de 10 min y
   libera encolados con más de 30 min):
   ```
   aws logs tail /aws/lambda/cc-$ENV-despachador --since 1h --profile $PERFIL
   aws logs tail /aws/lambda/cc-$ENV-conciliador --since 1h --profile $PERFIL
   ```
   El `conciliador` corre por un schedule recurrente: confirme que sigue activo.

## Mitigación
- El `conciliador` ya reencola solo en su siguiente ciclo; espere un ciclo antes de intervenir.
- Si el schedule no existe o está deshabilitado: recréelo desde la aplicación (RH reprograma la
  notificación) en lugar de editar tablas.
- Si el `despachador` falla (DLQ o errores): corrija la causa y haga el re-drive de `notif-despacho`
  ([dlq-con-mensajes.md](dlq-con-mensajes.md)). Reencolar manualmente un mensaje de despacho es seguro porque el
  `despachador` es idempotente por destinatario (uuid determinista), pero hágalo con la guardia.

## Escalamiento
Más de una hora de atraso o notificaciones de varias empresas: responsable del sistema.

## Verificación de resolución
La notificación pasa a `ENVIANDO` y luego `COMPLETADA`/`CON_FALLAS`; `programadas_atrasadas` baja a 0.

## Qué NO hacer
- No cambie `estado` de la notificación en la base a mano.
- No dispare el envío por otro medio (duplica mensajes a colaboradores).
- No omita la confirmación de fuera de horario: es una decisión de RH registrada en bitácora.
