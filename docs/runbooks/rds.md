# Runbook: RDS con CPU alta, conexiones agotadas, poco almacenamiento o conmutación por error

**Alarmas (propuesta T-225):** `cc-{env}-rds-cpu` (mayor a 80 %), `cc-{env}-rds-conexiones`
(mayor a 80 % del máximo), `cc-{env}-rds-almacenamiento` (libre menor a 20 %) y
`cc-{env}-rds-conmutacion` (evento de conmutación). **Severidad:** Crítica (almacenamiento y
conmutación), Alta (CPU y conexiones). Diseño: §14.6, §15.4. Convenciones: [README](README.md).

## Síntoma
Latencia alta o errores 5xx en varios servicios a la vez; errores de conexión; tras una conmutación,
servicios que no reconectan.

## Impacto
Toda la aplicación depende de PostgreSQL. Sin almacenamiento, la base queda de solo lectura o se cae.

## Diagnóstico (solo lectura)
1. Métricas de la instancia:
   ```
   aws cloudwatch get-metric-statistics --namespace AWS/RDS --metric-name CPUUtilization --dimensions Name=DBInstanceIdentifier,Value=<instancia> --start-time <ISO> --end-time <ISO> --period 60 --statistics Maximum --profile $PERFIL
   aws rds describe-db-instances --db-instance-identifier <instancia> --profile $PERFIL
   aws rds describe-events --source-type db-instance --source-identifier <instancia> --duration 120 --profile $PERFIL
   ```
2. Performance Insights (consola): consultas con más carga y esperas. Busque una consulta nueva sin
   índice (revise los índices de §2.4) o una carga masiva / envío de 10,000 destinatarios en curso.
3. Conexiones por rol (consulta de solo lectura con un usuario autorizado, nunca con los de servicio):
   `SELECT usename, count(*) FROM pg_stat_activity GROUP BY 1;` Capacidad esperada: menos de 150
   directas más RDS Proxy (§15.4). Un rol con muchas conexiones apunta a un servicio con fuga o a un
   escalado de tareas.
4. Tras conmutación: confirme que cada servicio reconectó (`describe-services` sin reinicios
   continuos, `aws logs tail /cc/$ENV/<servicio>` sin errores de conexión).

## Mitigación
- CPU: detener o pausar el origen de carga (carga masiva grande, despacho masivo) si es evitable;
  optimizar la consulta; ampliar la clase de instancia (ventana acordada).
- Conexiones: reducir tareas o el tamaño del grupo de conexiones del servicio culpable; revisar el
  RDS Proxy (conexiones ancladas, "pinning"; ver `docs/resultados-carga-local.md`).
- Almacenamiento: ampliar el almacenamiento asignado (no se puede reducir después; decisión de la
  guardia); revisar si crece `bitacora` o `outbox` (nota: las filas de `outbox` publicadas se conservan).
- Conmutación: normalmente automática; si un servicio no reconecta, reinicie sus tareas.

## Escalamiento
Almacenamiento libre menor a 10 % o conmutaciones repetidas: escale de inmediato al responsable del
sistema. Si hay sospecha de corrupción, siga [perdida-o-corrupcion-de-datos.md](perdida-o-corrupcion-de-datos.md).

## Verificación de resolución
Métricas por debajo de umbral durante 30 minutos, 5xx en cero, humo (`scripts/verificar_f1.ps1`) verde.

## Qué NO hacer
- No reinicie ni elimine la instancia de RDS por iniciativa propia; no desactive Multi-AZ.
- No ejecute `VACUUM FULL`, `DELETE` masivo ni cambios de esquema a mano en producción.
- No use las credenciales de los roles de servicio (`svc_*`) para diagnóstico; no desactive RLS.
- No borre filas de `bitacora` para liberar espacio (inmutable por diseño, CC-REQ-155).
