# Runbook: usuario RH sin dispositivo de MFA

**Sin alarma** (solicitud de una persona; §14.6). **Severidad:** Media. Convenciones: [README](README.md).

## Síntoma
Una persona de RH no puede iniciar sesión porque perdió o cambió el dispositivo del código TOTP.

## Impacto
Una sola persona sin acceso. El riesgo está en el reinicio: quien lo pida podría no ser quien dice.

## Diagnóstico (solo lectura)
1. **Verifique la identidad por un canal acordado** distinto al correo que se está usando para
   entrar (llamada a un teléfono ya registrado con el responsable de RH de la empresa, por ejemplo).
   El canal exacto es **[POR CONFIRMAR]** con el cliente.
2. Consulte el estado del usuario (sin datos innecesarios):
   ```
   aws cognito-idp admin-get-user --user-pool-id <pool> --username <correo-o-sub> --profile $PERFIL
   ```
   Confirme que está `CONFIRMED` y activo, y que corresponde a la empresa correcta.

## Mitigación
1. Reiniciar el MFA con la CLI de Cognito (cambia el sistema): quitar el dispositivo TOTP registrado
   (`admin-set-user-mfa-preference` / reinicio del registro de software token) para que la persona
   vuelva a asociar uno en su siguiente inicio de sesión. Como el MFA es obligatorio en el grupo de
   usuarios, **la secuencia exacta de comandos se valida en T-229 contra el pool real** y se anota
   aquí; no se ha probado contra Cognito real todavía.
2. Cierre las sesiones activas: `aws cognito-idp admin-user-global-sign-out --user-pool-id <pool> --username <u>`.
3. **Registre en la bitácora de operación** quién lo pidió, quién lo verificó, cuándo y cómo.

## Escalamiento
Si no se puede verificar la identidad, o hay varias solicitudes de reinicio a la vez: responsable del
sistema. Posible suplantación: también área jurídica.

## Verificación de resolución
La persona inicia sesión y registra un nuevo dispositivo; el usuario aparece en la bitácora de
accesos con su inicio de sesión.

## Qué NO hacer
- No reinicie el MFA solo por un correo o mensaje de quien lo solicita.
- No deshabilite el MFA del grupo de usuarios ni cree una excepción permanente.
- No pegue códigos de invitación, contraseñas temporales o códigos TOTP en tickets o chats.
