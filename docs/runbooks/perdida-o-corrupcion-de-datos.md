# Runbook: pérdida de datos o corrupción

**Sin alarma automática** (procedimiento manual de §14.6). **Severidad:** Crítica.
Diseño: §14.5, §15.5. Convenciones: [README](README.md).

## Síntoma
Datos incorrectos o ausentes que RH o una persona reporta; errores de descifrado
([error-descifrado.md](error-descifrado.md)); conteos que no cuadran; constancias con datos equivocados.

## Impacto
Riesgo para la integridad de datos de personal y de constancias emitidas (inmutables). Si hay
acceso o modificación indebida, es además un posible incidente de seguridad con implicaciones de la
LFPDPPP: **avise al área jurídica** (ver `docs/retencion-y-derechos-arco.md` §6 sobre notificación
de vulneraciones, plazos pendientes de decisión jurídica).

## Diagnóstico (solo lectura)
1. Delimite: ¿qué tablas, empresa, desde cuándo? Use la bitácora (inmutable) por `entidad`,
   `usuario_id` y fecha desde la SPA (pantalla de bitácora) o consultas de solo lectura con una
   cuenta autorizada: quién cambió qué y cuándo.
2. CloudTrail para accesos de infraestructura (`rds`, `s3`, `kms`) en la ventana:
   ```
   aws cloudtrail lookup-events --start-time <ISO> --end-time <ISO> --max-results 50 --profile $PERFIL
   ```
3. Confirme el punto en el tiempo anterior al daño y la ventana de PITR (14 días):
   ```
   aws rds describe-db-instances --db-instance-identifier <instancia> --query 'DBInstances[0].LatestRestorableTime' --profile $PERFIL
   ```

## Mitigación
1. **Detener escrituras** si el daño continúa (pausar las tareas de los servicios afectados; cambia el sistema).
2. **Restaurar con PITR a una instancia paralela** (nunca sobre la existente):
   ```
   aws rds restore-db-instance-to-point-in-time --source-db-instance-identifier <instancia> --target-db-instance-identifier <instancia>-restaurada --restore-time <ISO> --profile $PERFIL
   ```
3. Comparar y **reconciliar** los datos entre la restaurada y la original (conteos por empresa;
   humo; revisión de RH). Las constancias PDF viven en S3 con Object Lock y no se ven afectadas.
4. Si es necesario, cambiar el RDS Proxy y los secretos a la instancia restaurada (§14.5).
5. Registre el incidente, la causa y el tiempo de recuperación (contrasta con RTO y RPO propuestos de §15.5, [POR CONFIRMAR]).

## Escalamiento
Inmediato: responsable del sistema y área jurídica si hay datos personales involucrados.

## Verificación de resolución
Conteos y muestras de RH coinciden con la restaurada; humo verde; sin errores de descifrado; las
nuevas escrituras funcionan; reporte del incidente guardado.

## Qué NO hacer
- No restaure sobre la instancia productiva ni borre la original antes de reconciliar.
- No edite ni borre filas de `bitacora` (inmutable, CC-REQ-155) ni sobrescriba PDF (Object Lock).
- No "corrija" a mano columnas cifradas.
- No comunique el incidente a colaboradores por su cuenta: lo decide el área jurídica.
