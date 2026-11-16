# Runbook: rebotes o quejas altos en SES

**Alarma (propuesta T-225):** `cc-{env}-ses-rebotes` (tasa de rebote mayor a 5 %).
**Severidad:** Media. Diseño: §6.4, §14.6, §15.2. Convenciones: [README](README.md).

## Síntoma
La tasa de rebote o de quejas del correo de respaldo sube; AWS puede poner la cuenta en revisión o
pausa el envío.

## Impacto
Riesgo de reputación del dominio de envío y, a futuro, de perder la capacidad de enviar correo.
El correo es solo respaldo de la notificación de WhatsApp (24 h después).

## Diagnóstico (solo lectura)
1. Métricas de reputación y eventos de rebote/queja (tema `cc-$ENV-ses-eventos` y la cola
   `notif-respaldo`):
   ```
   aws sesv2 get-account --profile $PERFIL
   aws cloudwatch get-metric-statistics --namespace AWS/SES --metric-name Reputation.BounceRate --start-time <ISO> --end-time <ISO> --period 3600 --statistics Maximum --profile $PERFIL
   ```
2. Logs de `respaldo-correo`: `aws logs tail /aws/lambda/cc-$ENV-respaldo-correo --since 24h --profile $PERFIL`
   (el rebote se registra por `notificacion_id` y `colaborador_id`, sin direcciones de correo).
3. Causa típica: correos de colaboradores mal capturados en la carga o desactualizados. El sistema
   marca el destinatario como correo inválido (sin alertar con datos personales).

## Mitigación
1. Pausar el respaldo por correo con el parámetro de SSM del diseño (cambia el sistema). El nombre
   exacto del parámetro lo define `CcObservability`/`CcMessaging` (T-225/T-224): **[POR CONFIRMAR]**.
2. Pida a RH depurar los correos con rebote (campo `correo` de los colaboradores).
3. Reanude el respaldo cuando la tasa regrese a lo normal.

## Escalamiento
Aviso de AWS de revisión o suspensión de SES: responsable del sistema de inmediato.

## Verificación de resolución
Tasa de rebote por debajo de 5 % en las siguientes 24 h; la alarma vuelve a `OK`.

## Qué NO hacer
- No envíe pruebas masivas ni reintente a direcciones que rebotaron.
- No imprima ni pegue correos de colaboradores en tickets.
- No elimine el conjunto de configuración de SES ni la suscripción de eventos.
