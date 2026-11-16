# Runbook: errores en `cognito-pre-token`

**Alarma (propuesta T-225):** `cc-{env}-cognito-pre-token-errores` (errores mayores a 0 durante
5 min). **Severidad:** Crítica. Diseño: §4.6, §14.6. Convenciones: [README](README.md).

## Síntoma
Nadie puede iniciar sesión: Cognito no emite tokens si la Lambda falla (es la que agrega
`empresa_id`, `rol` y `usuario_id` al token).

## Impacto
Toda la SPA queda inaccesible. Los servicios siguen funcionando con sesiones ya emitidas hasta que
expiran.

## Diagnóstico (solo lectura)
1. Logs y errores de la función:
   ```
   aws logs tail /aws/lambda/cc-$ENV-cognito-pre-token --since 30m --profile $PERFIL
   aws lambda get-alias --function-name cc-$ENV-cognito-pre-token --name live --profile $PERFIL
   aws lambda list-versions-by-function --function-name cc-$ENV-cognito-pre-token --profile $PERFIL
   ```
2. ¿Hubo un despliegue reciente (la alarma empieza justo después)? Compare la versión a la que apunta
   `live`. Si no hubo despliegue, revise la conexión a la base (la Lambda se conecta como
   `svc_dashboard`, ver [rds.md](rds.md)) y el secreto `db/svc_dashboard`.

## Mitigación
1. Regresar el alias `live` a la versión anterior (cambia el sistema; la guardia lo hace):
   ```
   aws lambda update-alias --function-name cc-$ENV-cognito-pre-token --name live --function-version <versión-anterior> --profile $PERFIL
   ```
2. Si persiste y el problema no es de código: **solo con aprobación escrita**, desasociar
   temporalmente el trigger del grupo de usuarios con la CLI. Sin el trigger los tokens no llevan
   `empresa_id`, así que los servicios los rechazarían: es el último recurso y no restablece el
   servicio por sí solo.

## Escalamiento
Inmediato al responsable del sistema si el rollback del alias no corrige.

## Verificación de resolución
Un inicio de sesión de prueba con MFA completa; el token trae `empresa_id`; la alarma vuelve a `OK`.

## Qué NO hacer
- No desasocie el trigger sin aprobación.
- No reduzca la validación de `client_id`/`token_use` ni acepte tokens sin `empresa_id` en los servicios.
- No cree usuarios en Cognito saltándose la invitación para "evitar" el trigger.
