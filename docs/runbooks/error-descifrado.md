# Runbook: errores de descifrado

**Alarma (propuesta T-225):** `cc-{env}-error-descifrado` (métrica `error_descifrado` mayor a 0).
**Severidad:** Crítica. Diseño: §8.3, §9.2, §15.2. Convenciones: [README](README.md).

## Síntoma
Una respuesta 500 `ERROR_INTERNO` por fallo de descifrado de un dato sensible (celular, NSS, sueldo,
snapshot de constancia, contenido de chat).

## Impacto
No se pueden mostrar o usar datos cifrados de uno o más colaboradores. Puede indicar un problema de
KMS, una DEK dañada o de otra empresa, un valor copiado entre filas (el AAD lo detecta) o corrupción.

## Diagnóstico (solo lectura)
1. Logs del servicio (identifica `empresa_id`, `colaborador_id` y tabla; nunca el valor):
   ```
   aws logs tail /cc/$ENV/<servicio> --since 1h --filter-pattern '"error_descifrado"' --profile $PERFIL
   ```
2. ¿Es KMS? Estado de la llave y de permisos, y errores de CloudTrail (`Decrypt`, `GenerateDataKey`):
   ```
   aws kms describe-key --key-id alias/cc-$ENV-datos --profile $PERFIL
   aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=Decrypt --max-results 20 --profile $PERFIL
   ```
   Una política que ya no exige el contexto `{servicio, empresa_id}` o que lo niega causa este fallo.
3. ¿Una sola fila o todas? Una fila: dato corrupto o restaurado de otra fuente. Todas de una empresa:
   su DEK (`clave_datos`) cambió o falta. Todas de todas las empresas: KMS o permisos.

## Mitigación
- KMS o permisos: restaurar la política o el permiso previo (la guardia; cambia el sistema).
- Una fila corrupta: no se puede reconstruir el valor sin el original; RH debe volver a capturarlo.
  Si hay duda de corrupción en la base, siga [perdida-o-corrupcion-de-datos.md](perdida-o-corrupcion-de-datos.md).
- Si la DEK de una empresa se perdió: restaurar `clave_datos` desde respaldo (PITR) a una instancia
  paralela y comparar; no genere una DEK nueva sobre datos existentes (los volvería ilegibles).

## Escalamiento
Inmediato al responsable del sistema. Un descifrado que falla por AAD puede indicar manipulación:
avise al área jurídica si se sospecha acceso indebido.

## Verificación de resolución
El detalle de un colaborador afectado se abre sin error, `error_descifrado` en 0 durante 1 hora.

## Qué NO hacer
- No quite el contexto de cifrado de la política de KMS ni abra `kms:*`.
- No programe la eliminación de la llave `cc-$ENV-datos` (período mínimo de 7 días, pérdida total de datos).
- No ejecute `UPDATE` a mano sobre columnas `*_cifrado`.
