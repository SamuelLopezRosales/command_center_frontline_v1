# Runbook: pérdida de la región principal

**Sin alarma automática** (procedimiento manual de §14.6 y §15.5). **Severidad:** Crítica.
Valores de recuperación propuestos y **[POR CONFIRMAR]**: región de recuperación `us-east-2`,
RPO hasta 1 hora, RTO hasta 4 horas. Convenciones: [README](README.md).

## Síntoma
`us-east-1` no responde (estado de AWS) o los recursos (RDS, ECS, API) no están disponibles de
forma sostenida; no es una falla de una sola zona (esa la cubre Multi-AZ).

## Impacto
Servicio caído. Cognito es regional y **no replica contraseñas ni dispositivos de MFA**: tras
recuperar, los usuarios RH deben registrarse de nuevo con invitaciones nuevas.

## Diagnóstico (solo lectura)
1. Confirme que es la región y no la propia cuenta o el perfil: estado de AWS (página de estado) y
   `aws sts get-caller-identity --profile $PERFIL --region us-east-2`.
2. Confirme que existen los respaldos replicados en `us-east-2` (AWS Backup, copias de RDS) y la
   réplica del bucket `constancias`:
   ```
   aws backup list-recovery-points-by-backup-vault --backup-vault-name <vault-us-east-2> --region us-east-2 --profile $PERFIL
   ```

## Mitigación (la decide el responsable del sistema; es una acción mayor)
Procedimiento de §15.5:
1. Restaurar RDS desde el respaldo replicado en `us-east-2`.
2. Desplegar los stacks de CDK en la región de recuperación (infraestructura como código lista, sin
   servicios en espera; el bootstrap de CDK en `us-east-2` es un requisito previo: no está
   desplegado en `test`).
3. Usar la réplica de `constancias` (lectura directa); recrear los secretos y las llaves de datos
   (la llave de KMS de datos debe existir en la región de destino; sin ella los valores cifrados no
   se pueden leer: **verificar antes de depender de este procedimiento**, ver la brecha de §15.5).
4. Cambiar el DNS y **reconfigurar el webhook de Meta** a la nueva URL.
5. Recrear usuarios RH con `bootstrap_admin.py` (invitaciones nuevas).

## Escalamiento
Inmediato: responsable del sistema, cliente (comunicación del incidente) y área jurídica si hay
datos personales fuera de su región de residencia.

## Verificación de resolución
Humo verde en la región de recuperación; conteos comparados con el último punto conocido; RH
puede iniciar sesión con MFA; el webhook de Meta responde 200 a la verificación; un mensaje de
prueba completa el flujo.

## Qué NO hacer
- No abra puertos ni desactive controles para "acelerar".
- No restaure `constancias` copiando objetos por encima del Object Lock de la región principal.
- No reutilice una llave de KMS o secretos de otra cuenta.
- No vuelva a la región principal sin una ventana acordada y sin reconciliar datos.

## Nota de validación
Este procedimiento nunca se ha ejecutado de punta a punta; la prueba de restauración trimestral de §14.5 es lo que lo valida.
