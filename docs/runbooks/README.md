# Runbooks de operación

Un runbook por cada alarma de `design.md` §14.6 y §15.2 (T-144). Cada alarma de CloudWatch debe
enlazar su runbook en la descripción (`alarm_description`), con la ruta de esta tabla.

**Estado:** las alarmas las crea `CcObservability` (T-225) con exactamente los identificadores de la
columna "Alarma"; una prueba de `infra/tests/test_observability.py` exige que esta tabla y el stack
coincidan. Además `CcEdge` crea la alarma de 5xx de CloudFront (`edge-5xx`, fuera de esta tabla porque vive en otro stack; su runbook es [api-5xx-y-latencia.md](api-5xx-y-latencia.md)) y hay tres temas SNS: `alertas-rh`
(avisos de negocio), `alertas-ops` (operación) y `alertas-edge` (borde). Los umbrales siguen siendo
valores propuestos **[POR CONFIRMAR]** (PQ-20) y están en una sola tabla, `UMBRALES`, en
`infra/stacks/observability.py`.

## Índice: alarma, runbook y severidad

Severidad: **Crítica** = SNS de guardia inmediato, atender de inmediato. **Alta** = SNS, atender el
mismo día hábil. **Media** = revisar en el mismo día o en la siguiente revisión de operación.

| Alarma (propuesta) | Umbral propuesto (§15.2) | Runbook | Severidad |
|---|---|---|---|
| `cc-{env}-dlq-{cola}` (una por cada DLQ: `cola-pdf`, `cola-cargas`, `wa-entrada`, `wa-salida`, `wa-estados`, `notif-despacho`, `notif-respaldo`, `ev-colaboradores`, `ev-constancias`, `ev-notificaciones`) | `ApproximateNumberOfMessagesVisible` mayor a 0 | [dlq-con-mensajes.md](dlq-con-mensajes.md) | Crítica |
| `cc-{env}-cola-antigua-wa-salida`, `cc-{env}-cola-antigua-cola-pdf` | Edad del mensaje más antiguo mayor a 5 min (`wa-salida`) y 10 min (`cola-pdf`) | [mensajes-antiguos.md](mensajes-antiguos.md) | Alta |
| `cc-{env}-webhook-firma-invalida` | `webhook_firma_invalida` mayor a 10 en 5 min | [webhook-firma-invalida.md](webhook-firma-invalida.md) | Alta |
| `cc-{env}-webhook-5xx` | 5xx de `webhook-meta` (§4.2) | [webhook-firma-invalida.md](webhook-firma-invalida.md) | Crítica |
| `cc-{env}-meta-errores` (incluye token inválido o vencido) | `meta_error_*` con tasa mayor a 10 % durante 10 min | [meta-autenticacion-y-errores.md](meta-autenticacion-y-errores.md) | Crítica |
| `cc-{env}-pdf-lento` | Duración de generación p95 mayor a 5 s (CC-NFR-001) | [worker-pdf.md](worker-pdf.md) | Alta |
| `cc-{env}-worker-pdf-fallos` | Solicitudes `FALLIDA` con `ERROR_RENDER` (el diseño lo menciona en §14.6; sin umbral en §15.2) | [worker-pdf.md](worker-pdf.md) | Alta |
| `cc-{env}-rds-cpu`, `cc-{env}-rds-conexiones`, `cc-{env}-rds-almacenamiento`, `cc-{env}-rds-conmutacion` | CPU mayor a 80 %, conexiones mayores a 80 %, almacenamiento libre menor a 20 %, evento de conmutación | [rds.md](rds.md) | Crítica (conmutación y almacenamiento), Alta (CPU y conexiones) |
| `cc-{env}-programadas-atrasadas` | `programadas_atrasadas` mayor a 0 durante 15 min | [notificaciones-atrasadas.md](notificaciones-atrasadas.md) | Alta |
| `cc-{env}-cognito-pre-token-errores` | Errores de `cognito-pre-token` mayores a 0 durante 5 min | [cognito-pre-token.md](cognito-pre-token.md) | Crítica |
| `cc-{env}-ses-rebotes` | Tasa de rebote mayor a 5 % | [ses-rebotes-y-quejas.md](ses-rebotes-y-quejas.md) | Media |
| `cc-{env}-error-descifrado` | `error_descifrado` mayor a 0 | [error-descifrado.md](error-descifrado.md) | Crítica |
| `cc-{env}-5xx-{servicio}` | 5xx mayor a 5 % durante 5 min | [api-5xx-y-latencia.md](api-5xx-y-latencia.md) | Alta |
| `cc-{env}-latencia-{servicio}` | p95 mayor a 2 s durante 10 min | [api-5xx-y-latencia.md](api-5xx-y-latencia.md) | Media |
| Sin alarma (procedimiento manual de §14.6): pérdida de datos o corrupción | Lo detecta una persona | [perdida-o-corrupcion-de-datos.md](perdida-o-corrupcion-de-datos.md) | Crítica |
| Sin alarma (procedimiento manual de §14.6): pérdida de la región principal | Lo detecta una persona o el estado de AWS | [perdida-de-region.md](perdida-de-region.md) | Crítica |
| Sin alarma (procedimiento manual de §14.6): usuario RH sin dispositivo de MFA | Solicitud de la persona | [mfa-perdido.md](mfa-perdido.md) | Media |

## Convenciones de todos los runbooks

- **Variables:** `$ENV` es el ambiente (`test` o `prod`), `$PERFIL` el perfil de AWS del ambiente y
  la región es `us-east-1`. Antes de cualquier comando, confirme la cuenta con
  `aws sts get-caller-identity --profile $PERFIL` o con `scripts/aws_guard.ps1`. Si la cuenta no es
  la del ambiente, **no continúe**.
- **Nombres de recursos** (los de CDK): colas `cc-$ENV-<cola>` y su DLQ `cc-$ENV-<cola>-dlq`
  (las FIFO terminan en `.fifo`, por ejemplo `cc-$ENV-wa-salida-dlq.fifo`); bus
  `cc-$ENV-eventos`; grupos de logs de los servicios `/cc/$ENV/<servicio>` y de las Lambdas
  `/aws/lambda/cc-$ENV-<función>`; secretos `cc/$ENV/<nombre>`.
- **Diagnóstico = solo lectura.** Los comandos de las secciones "Diagnóstico" no cambian nada.
  `aws sqs receive-message` **no** se usa para leer mensajes: oculta el mensaje durante el tiempo de
  visibilidad y su cuerpo puede traer el texto del mensaje, el token de un enlace o un código
  (ver la brecha de `docs/cumplimiento-lfpdppp.md` §4).
- **Nunca pegue datos personales** en tickets, chats ni capturas: celulares, nombres, RFC, CURP,
  NSS, texto de mensajes, tokens, códigos de verificación o URL firmadas. Use `correlacion_id`,
  `empresa_id`, `colaborador_id`, `solicitud_id`, `notificacion_id` o el folio (design.md §11.5).
- **Mitigación** puede cambiar el sistema. En `prod` toda acción que cambie algo en AWS la ejecuta
  una persona con autorización de la guardia; en `test` se aplica la regla del proyecto de
  aprobación por escrito de Samuel (T-229 y T-230).
- **Escalamiento:** 1) guardia técnica; 2) responsable del sistema (Samuel); 3) si hay posible
  exposición de datos personales, además el área jurídica (PQ-12) de inmediato. Los datos de
  contacto de la guardia son **[POR CONFIRMAR]** (canal de SNS de guardia, PQ-17/PQ-20).
- **Pendiente de la operación real:** varios runbooks hablan de "re-drive", "reencolar" o "script de
  operación". Hoy la tarea `ops` solo tiene `contrasenas` y `bootstrap` (`infra/docker/ops/ops.sh`):
  **no existe aún un script para reencolar solicitudes `FALLIDA` ni para reenviar el despacho**.
  Cada runbook indica la alternativa disponible (re-drive de SQS, `reintentar` de la API) y marca
  lo que falta como brecha operativa.
