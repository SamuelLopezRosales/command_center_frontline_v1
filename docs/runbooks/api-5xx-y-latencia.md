# Runbook: errores 5xx y latencia alta de un servicio de API

**Alarmas (propuesta T-225):** `cc-{env}-5xx-{servicio}` (más de 5 % durante 5 min, **Alta**) y
`cc-{env}-latencia-{servicio}` (p95 mayor a 2 s durante 10 min, **Media**), por cada servicio:
`dashboard`, `colaboradores`, `campos`, `constancias`, `notificaciones`, `whatsapp`.
Diseño: §15.2. Convenciones: [README](README.md). Objetivo candidato de listados y búsquedas:
p95 menor a 1 s (§15.3, `docs/resultados-carga-local.md`).

## Síntoma
Errores 500/502/503 o respuestas lentas en un servicio.

## Impacto
La parte de la SPA que usa ese servicio falla o va lenta. Si varios servicios fallan a la vez, la
causa común suele ser la base de datos ([rds.md](rds.md)) o la red.

## Diagnóstico (solo lectura)
1. Logs del servicio por `correlacion_id` (cada línea es JSON con `ruta`, `estado_http`, `duracion_ms`):
   ```
   aws logs tail /cc/$ENV/<servicio> --since 30m --filter-pattern '{ $.estado_http >= 500 }' --profile $PERFIL
   ```
2. Estado de las tareas (reinicios, salud del ALB):
   ```
   aws ecs describe-services --cluster <cluster> --services cc-$ENV-<servicio> --profile $PERFIL
   aws elbv2 describe-target-health --target-group-arn <arn> --profile $PERFIL
   ```
3. ¿Despliegue reciente? ¿Un proveedor (Meta, SES, KMS, S3) con errores? (tabla de errores §9.2:
   `ERROR_PROVEEDOR` 502 es transitorio). ¿Base de datos saturada ([rds.md](rds.md))?
4. Para latencia: ruta concreta con más `duracion_ms`; compare con las mediciones locales.

## Mitigación
- Despliegue defectuoso: revertir a la versión anterior de la tarea.
- Saturación: escalar tareas del servicio (autoescalado por CPU 60 %); revisar la base.
- Proveedor caído: esperar y confirmar que los reintentos funcionan; informar a RH.

## Escalamiento
5xx sostenidos más de 15 minutos o en `whatsapp`/`constancias` durante un envío masivo: responsable del sistema.

## Verificación de resolución
5xx por debajo de 5 % y p95 por debajo de 2 s durante 30 minutos; alarma en `OK`; humo verde.

## Qué NO hacer
- No active modo de depuración ni registre cuerpos de solicitud o respuesta (datos personales, CC-REQ-162).
- No reinicie todas las tareas a la vez en horario de uso.
- No desactive RLS o permisos de roles para "ver si funciona".
