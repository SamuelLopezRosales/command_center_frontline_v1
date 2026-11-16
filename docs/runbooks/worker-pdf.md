# Runbook: `worker-pdf` lento o con fallos

**Alarmas (propuesta T-225):** `cc-{env}-pdf-lento` (duración de generación p95 mayor a 5 s,
CC-NFR-001) y `cc-{env}-worker-pdf-fallos` (solicitudes `FALLIDA` con motivo `ERROR_RENDER`).
**Severidad:** Alta. Diseño: §5.4, §14.6, §15.3. Convenciones y variables: [README](README.md).

## Síntoma
Las constancias tardan más de lo esperado o quedan `FALLIDA`. Línea base medida (T-210, contenedor de
1 vCPU y 2 GB): p95 = 0.069 s; un p95 mayor a 5 s indica un problema real, no ruido.

## Impacto
Colaboradores sin su constancia; RH ve solicitudes `FALLIDA` y el aviso `constancia.fallida`.

## Diagnóstico (solo lectura)
1. CPU y memoria de las tareas y número de tareas en ejecución:
   ```
   aws ecs describe-services --cluster <cluster> --services cc-$ENV-worker-pdf --profile $PERFIL
   aws cloudwatch get-metric-statistics --namespace AWS/ECS --metric-name CPUUtilization --dimensions Name=ClusterName,Value=<cluster> Name=ServiceName,Value=cc-$ENV-worker-pdf --start-time <ISO> --end-time <ISO> --period 60 --statistics Maximum --profile $PERFIL
   ```
2. Logs del worker (códigos de error, sin contenido de la constancia):
   ```
   aws logs tail /cc/$ENV/worker-pdf --since 1h --filter-pattern '"ERROR_RENDER"' --profile $PERFIL
   ```
3. Dependencias: S3 `constancias` (Object Lock), KMS, la base de datos ([rds.md](rds.md)) y `colaboradores`
   (INT-COL-04). Un fallo técnico se reintenta hasta `max_intentos_pdf` (3 recepciones) y luego queda
   `FALLIDA`. Un fallo de negocio (`CAMPOS_FALTANTES`) no es del worker: RH completa los datos.
4. Profundidad de `cola-pdf` y su DLQ ([mensajes-antiguos.md](mensajes-antiguos.md), [dlq-con-mensajes.md](dlq-con-mensajes.md)).

## Mitigación
1. Escalar la cantidad de tareas del servicio `worker-pdf` (cambia el sistema; autorización de la guardia).
2. Si hay un despliegue reciente defectuoso, revertir a la versión anterior de la tarea.
3. **Reencolar las `FALLIDA` por `ERROR_RENDER`:** el diseño pide un "script de operación"; **hoy no
   existe** (la tarea `ops` solo tiene `contrasenas` y `bootstrap`). Mientras tanto, RH puede volver
   a solicitar la constancia desde la SPA o el colaborador por WhatsApp; el folio no se reutiliza de
   forma insegura: el worker revalida y reutiliza `folio_reservado`. Registrar esta brecha para T-229.

## Escalamiento
Si tras escalar tareas el p95 sigue mayor a 5 s o los fallos continúan, escale al responsable del
sistema. Una constancia emitida con datos incorrectos es un incidente de datos: ver
[perdida-o-corrupcion-de-datos.md](perdida-o-corrupcion-de-datos.md).

## Verificación de resolución
`pdf-lento` vuelve a `OK`, una solicitud nueva termina en `ENTREGADA` en segundos, `cola-pdf` y su
DLQ en cero.

## Qué NO hacer
- No borre ni sobrescriba PDF en el bucket `constancias` (Object Lock; la inmutabilidad es parte del control).
- No reutilice un folio a mano ni edite `constancias.constancia` en la base.
- No abra el renderizador a contenido externo para "arreglar" una imagen (seguridad del PDF, T-210).
