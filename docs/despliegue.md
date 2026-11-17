# Despliegue de Command Center en una cuenta de AWS

Guía de la tarea T-227. Sirve para `cc-test` (T-229) y para **otra cuenta de AWS** (otro cliente, otro
ambiente). El procedimiento completo es un solo comando por ambiente:

```powershell
$env:AWS_PROFILE = "cc-test"
.\scripts\desplegar.ps1 -Ambiente test -SoloRevisar   # primero: guardia, verificación previa, diff y costo
.\scripts\desplegar.ps1 -Ambiente test                # después: despliegue completo (pide aprobación)
```

La lógica está en `scripts/desplegar.py` (probada con AWS simulado en `scripts/tests/test_desplegar.py`);
`scripts/desplegar.ps1` es el punto de entrada. Las reglas de seguridad del script:

- Nunca acepta ni imprime credenciales. Rechaza llaves de acceso y tokens de sesión en el entorno
  (`AWS_ACCESS_KEY_ID`, `AWS_SESSION_TOKEN`...): solo se usa el **perfil** del ambiente.
- El perfil, la región y la cuenta salen de `infra/config/ambientes.json`, nunca de argumentos.
- **Nunca borra ni destruye nada** (`cdk destroy`, `delete-*`). Destruir lo hace la persona (regla 8).
- No tiene un modo "sí a todo". La aprobación es una **frase exacta** que la persona teclea en una
  consola interactiva; sin consola interactiva el script termina con error aunque se tenga la frase.
- Cada paso que cambia algo ocurre tras la aprobación y tras volver a pasar la guardia de cuenta.
- No escribe secretos a disco ni a los registros. El código de invitación del primer usuario lo ve
  solo la persona (paso 7); el script imprime el comando, no lo ejecuta.

## 1. Qué hace, paso por paso

| Paso | Qué ocurre | Cambia algo en AWS |
|---|---|---|
| 1. Guardia | PA-1 a PA-3 con `aws_guard`: `AWS_PROFILE` igual al perfil del ambiente, sin llaves en el entorno, región correcta, sesión válida (`sts get-caller-identity`) y cuenta permitida | No |
| 2. Verificación previa | Solo lecturas: bootstrap de CDK (`CDKToolkit`, versión mínima 21) en cada región usada; cuota de concurrencia de Lambda; nombres en conflicto; stacks en estado malo; Docker con `linux/arm64` y carpeta temporal de credenciales; presupuesto; versiones de `cdk`, Node, `uv`, `npm` y `aws`; contextos obligatorios del ambiente | No |
| 3. Empaquetado | `empaquetar_lambdas.py` (normal, `--notificaciones`, `--whatsapp`) y `npm run build` en `frontend/`; comprueba que existan `frontend/dist` y los tres paquetes | No (solo local; descarga de PyPI y npm) |
| 4. Diff y costo | `cdk diff` de todos los stacks y la estimación del costo de la ventana contra el presupuesto | `cdk diff` publica las plantillas en el bucket de assets del `CDKToolkit` (ver sección 5) |
| 5. Aprobación | Pausa: la persona teclea la frase exacta del ambiente (en `test`: `apruebo T-229`) | No |
| 6a. Grupo Base | `cdk deploy` de `CcSecurity`, `CcNetwork`, `CcStorage`, `CcData`, `CcMessaging`, `CcAuth` y `CcComputeBase` (en `prod` antes: `CcBackupRecuperacion`) | Sí |
| 6b. Imágenes | `docker login` en ECR con una carpeta TEMPORAL de credenciales de Docker (el almacén de Windows rechaza el token de ECR, lección de T-046), `buildx --platform linux/arm64` y `docker push` de `migrar` y `ops` si su etiqueta no existe (los repositorios son inmutables) | Sí |
| 6c. Migraciones | `ecs run-task` de `migrar`; espera y **exige código de salida 0** (`scripts/migrar_todo.py`: seis servicios en orden, luego `roles.sql`, `rls.sql`, `grants.sql`) | Sí |
| 6d. Contraseñas | `ecs run-task` de `ops` con `./ops.sh contrasenas`; exige código 0. Va **antes** de los servicios: los roles nacen sin contraseña y los servicios leen sus secretos al arrancar | Sí |
| 6e. Grupo Servicios | `cdk deploy` de `CcCompute`, `CcWorkersLambdas`, `CcApi`, `CcEdge`, `CcFrontend`, `CcObservability` y `CcBackup` | Sí |
| 7. Datos finales | Imprime ids de Cognito, la URL de la SPA y los comandos de ECS Exec de `bootstrap_admin` para que la persona los ejecute | No |

**Por qué grupos y no `--all`:** el diseño exige las migraciones **entre** las bases de datos y los
servicios (design.md §14.2: migrar, luego `cdk deploy`). `CcData` y `CcComputeBase` tienen que existir
(y las imágenes publicadas) antes de la tarea `migrar`; `CcCompute` y los siguientes arrancan servicios
que ya necesitan el esquema y las contraseñas. Los grupos son los mismos que usa el pipeline
(`nombres_de_stacks()` en `infra/stacks/pipeline.py`). `CcPipeline` nunca lo despliega este script.

Si un paso falla, el script se detiene y **no revierte ni borra**: lo ya creado queda como está. Volver
a ejecutar el comando es seguro (`cdk deploy`, las migraciones y las contraseñas son idempotentes; una
imagen ya publicada se omite).

## 2. Herramientas

PowerShell 5.1 (los `.ps1` están en UTF-8 con BOM), `uv`, Node 20 o superior, la CLI de CDK
(`npm install -g aws-cdk`, versión igual o superior a la de `infra/pipeline/buildspecs.py`), la CLI de
AWS v2, Docker Desktop con emulación `linux/arm64` (Fargate es ARM64) y el plugin
`session-manager-plugin` (para ECS Exec). Si falta la emulación arm64, la habilita la persona:
`docker run --privileged --rm tonistiigi/binfmt --install arm64`.

## 3. Pasos para otra cuenta de AWS

### 3.1 Agregar el ambiente en `infra/config/ambientes.json`

Copie el bloque de `test` con otro nombre (minúsculas, de 2 a 20 caracteres) y cambie:

```json
"cliente-a": {
  "cuentas_permitidas": ["123456789012"],
  "region": "us-east-1",
  "perfil": "cc-cliente-a",
  "etiquetas": { "proyecto": "command-center", "ambiente": "cliente-a", "responsable": "Nombre" },
  "presupuesto": { "monto_usd": 50, "correo": "responsable@ejemplo.com", "alertas": [ ... ] },
  "economia": { ... },
  "dominio": null
}
```

- `cuentas_permitidas`: la lista cerrada de cuentas donde puede desplegarse. La guardia de CDK y la del
  script rechazan cualquier otra. Nunca ponga llaves de acceso en este archivo (el cargador lo rechaza).
- `perfil`: el nombre del perfil de la CLI de AWS (sección 3.3). El perfil `cc-test` es solo de `test`.
- `etiquetas.ambiente` debe ser igual al nombre; las tres etiquetas son obligatorias.
- `presupuesto`: monto mensual en USD, correo y alertas; el script compara el costo de la ventana con
  este monto.
- `economia`: copie los valores de `test` para un prototipo corto, o los de producción (ver
  `docs/ambientes.md`, sección 2). **`permite_borrado: false` convierte el ambiente en "tipo prod"**:
  política `RETAIN`, Multi-AZ, WAF, respaldo con copia a `us-east-2`, pipeline por defecto y los
  contextos obligatorios de la sección 3.7.
- Opcional, `infra/config/despliegue.json`: frase de aprobación del ambiente
  (`"ambientes": {"cliente-a": {"frase_aprobacion": "apruebo despliegue cliente-a"}}`). Sin entrada, la
  frase es `apruebo despliegue <ambiente>`.

Después ejecute `uv run pytest infra/tests -q -p no:cacheprovider` para validar la configuración.

### 3.2 Crear el perfil de AWS (sin llaves)

```powershell
aws configure sso --profile cc-cliente-a      # o: aws login --profile cc-cliente-a
aws sso login --profile cc-cliente-a          # cuando la sesión venza
$env:AWS_PROFILE = "cc-cliente-a"
.\scripts\aws_guard.ps1 -Ambiente cliente-a   # debe decir: PA-1 a PA-3 correctos
```

Si no hay IAM Identity Center, se acepta un perfil con llaves de acceso de un **usuario IAM** (nunca
del usuario raíz): `aws configure --profile <perfil>` las guarda en `~/.aws/credentials`, fuera del
repositorio. Nunca guarde llaves en el repositorio ni en variables de entorno (el script rechaza
`AWS_ACCESS_KEY_ID` y `AWS_SESSION_TOKEN`), y desactívelas en IAM al terminar la prueba. Ejemplo
del ambiente `samuel`: perfil `cc-samuel-sdk`. Si hay un perfil
`default` con otra cuenta, no pasa nada: el script solo usa el perfil del ambiente y la guardia
compara la cuenta.

### 3.3 `cdk bootstrap` (lo hace LA PERSONA; el script solo lo verifica)

```powershell
cdk bootstrap aws://123456789012/us-east-1 --profile cc-cliente-a
```

- En una cuenta que ya tiene `CDKToolkit` compartido con otros proyectos **no** se vuelve a ejecutar
  (T-012): el script solo exige que exista y que su versión sea al menos la 21.
- En `prod` también hace falta en `us-east-2` (región de recuperación): `cdk bootstrap
  aws://CUENTA/us-east-2`. `CcEdge` vive en `us-east-1`: si la región principal es otra, también ahí.
- El rol de ejecución de CloudFormation del bootstrap es el que da el poder de despliegue (por defecto
  `AdministratorAccess`); se puede acotar con `--cloudformation-execution-policies`.

### 3.4 Presupuesto

```powershell
.\scripts\crear_presupuesto.ps1 -Ambiente cliente-a -WhatIf   # muestra lo que haría
.\scripts\crear_presupuesto.ps1 -Ambiente cliente-a           # lo crea (requiere aprobación)
```

La verificación previa **exige** que el presupuesto `command-center-{ambiente}-mensual` exista.

### 3.5 Cuota de concurrencia de Lambda

Una cuenta nueva suele tener 10 ejecuciones concurrentes. Los stacks reservan concurrencia por
función (`infra/stacks/workers_lambdas.py` y `auth.py`; el script la suma al leer el código) y AWS exige
dejar **al menos 100 sin reservar**. Solicite en Service Quotas el aumento de "Concurrent executions"
(`L-B99A9384`) a un valor mayor que la reservada más 100 y espere su aprobación. La verificación previa
lo comprueba con `lambda get-account-settings` y detiene el despliegue si no alcanza.

### 3.6 Nombres en conflicto

La verificación previa lista (solo lectura) los nombres que impedirían crear los recursos:

| Recurso | Patrón | Qué hacer si aparece |
|---|---|---|
| Secretos pendientes de borrado | `cc/{ambiente}/…` | El nombre no se reutiliza hasta que termine la recuperación (7 días en `test`, 30 en `prod`). La persona espera o decide un borrado forzado (`aws secretsmanager delete-secret --force-delete-without-recovery`, bajo su responsabilidad) |
| Alias de KMS | `alias/cc-{ambiente}-…` | La persona revisa de quién es y lo borra si es un residuo |
| Grupos de logs | `/cc/{ambiente}/…` y `/aws/lambda/cc-{ambiente}-…` | Residuos de un despliegue anterior: los borra la persona |
| Buckets retenidos | `cc-{ambiente}-{cuenta}-…` | En `prod` se conservan al destruir; vacíelos o cámbieles el nombre a mano |
| Repositorios de ECR, colas SQS | `cc-{ambiente}/…`, `cc-{ambiente}-…` | Residuos: los borra la persona |
| Stacks en `ROLLBACK_COMPLETE`, `DELETE_FAILED`, `*_IN_PROGRESS` | `Cc*-{ambiente}` | La persona los resuelve antes de continuar |

Si el ambiente **ya tiene stacks** (es una actualización), los recursos con esos nombres son suyos y no
se marcan; los secretos pendientes de borrado se marcan siempre.

### 3.7 Contextos de CDK (`-Contexto clave=valor`)

| Ambiente | Obligatorios | Notas |
|---|---|---|
| `test` (`permite_borrado: true`) | Ninguno | `empresa_id_whatsapp` opcional (PQ-07); `respaldo=false` omite `CcBackup` |
| `prod` (`permite_borrado: false`) | `certificado_alb_arn`, `dominio_interno`, `repositorio_pipeline` (salvo `pipeline=false`) y el archivo `infra/config/cloudfront-{ambiente}.pub.pem` con la llave **pública** | También usa `dominio_origen_api`, `certificado_origen_api_arn`, `zona_hospedada_id` |

```powershell
.\scripts\desplegar.ps1 -Ambiente prod -SoloRevisar `
  -Contexto certificado_alb_arn=arn:aws:acm:us-east-1:123456789012:certificate/xxxx, dominio_interno=cc.interno.ejemplo.com, pipeline=false
```

Solo se aceptan las claves y las formas de la lista de `CONTEXTOS_PERMITIDOS` en `scripts/desplegar.py`.
`pipeline=true` no se acepta: este script nunca despliega `CcPipeline`.

### 3.8 Revisar antes de desplegar

```powershell
.\scripts\desplegar.ps1 -Ambiente cliente-a -SoloRevisar -Dias 14
```

Hace los pasos 1 a 4: guardia, verificación previa, empaquetado, `cdk diff` y costo. **No despliega ni
crea recursos del proyecto.** Para el costo admite `-Dias N` y `-HorasServiciosPorDia H` (horas al día con
los servicios de ECS encendidos). Variantes:

- `-SoloSynth`: solo `cdk synth` (con cdk-nag) **sin credenciales y sin llamar a AWS**, para validar el
  código en cualquier equipo.
- `-Simular` (o `-WhatIf`): imprime lo que haría y el costo, sin ejecutar ningún comando.

### 3.9 Desplegar

```powershell
.\scripts\desplegar.ps1 -Ambiente cliente-a
```

Muestra el diff y el costo, y pide la frase exacta. Con cualquier otra respuesta, termina sin desplegar.

## 4. Costo estimado de la ventana

El script calcula el costo de la ventana (por defecto 14 días) con `infra/config/costos.json`
(tarifas públicas de us-east-1 y el inventario de recursos) y los parámetros del ambiente, y lo compara
con el presupuesto mensual. **Son estimaciones con tarifas recordadas, no la lista de precios de AWS ni
una factura**: antes de aprobar se contrastan con la calculadora de precios de AWS. No incluyen el gasto
previo de la cuenta ni la transferencia de datos.

Si la estimación supera el presupuesto, el script lo dice y muestra alcances menores: servicios de ECS
con `desired_count 0` entre pruebas (`-HorasServiciosPorDia`), sin las alarmas por servicio, una ventana
más corta y destruir (la persona) en cuanto terminen las pruebas. En `test` con todo encendido 24 horas
la estimación de 14 días es de unos 67 USD; con los servicios 8 horas al día, unos 42 USD.

## 5. `cdk diff` y el bucket de assets

`cdk diff` publica las plantillas (y los assets) en el bucket del `CDKToolkit`, que puede estar
compartido con otros proyectos de la cuenta. Es lo único que escribe `-SoloRevisar`; no crea recursos del
proyecto. El script lo avisa en su salida. Si no se quiere ni eso, use `-SoloSynth`.

## 6. Pasos manuales después del despliegue

1. **Primer usuario** (`bootstrap_admin`, lo ejecuta LA PERSONA). El script imprime los cuatro comandos
   al terminar: iniciar la tarea `ops` con `--enable-execute-command`, esperar a que corra, ejecutar
   `./ops.sh bootstrap --razon-social "..."` con `aws ecs execute-command` y detener la tarea. El código de
   invitación se muestra **una sola vez**, en la consola de la persona; el script nunca lo ve ni lo
   registra (ECS Exec no graba la sesión en CloudWatch; la auditoría queda en CloudTrail).

   **Ejecute los comandos uno por uno, no pegados juntos.** El agente de ECS Exec tarda uno o dos
   minutos en quedar listo: `aws ecs execute-command` falla con `execute command agent isn't running`
   si se lanza justo al pasar la tarea a `RUNNING`. Antes de ejecutarlo, espere con:

   ```powershell
   do { Start-Sleep 8; $agente = aws ecs describe-tasks --cluster cc-<ambiente> --tasks $tarea --query "tasks[0].containers[0].managedAgents[?name=='ExecuteCommandAgent']|[0].lastStatus" --output text --profile <perfil> --region <region> } until ($agente -eq "RUNNING")
   ```

   **Con `economia.registro = ABIERTO` la empresa debe existir antes de que alguien se registre.**
   `post-confirmation` asigna a quien se registra a la única empresa activa; si aún no hay ninguna lo
   rechaza (`sin_empresa_unica`) y la SPA muestra el mensaje genérico de registro. Cognito deja al
   usuario `CONFIRMED` sin fila en la base: hay que borrarlo (`aws cognito-idp admin-delete-user
   --user-pool-id <id> --username <correo> --profile <perfil>`) y registrarse de nuevo. El código de
   invitación que imprime `bootstrap` no se usa en ese modo.
2. **`empresa_id_whatsapp`**: tras crear la empresa, anote su id y vuelva a ejecutar el script con
   `-Contexto empresa_id_whatsapp=<id>` para que el worker de WhatsApp lo reciba (las migraciones y las
   contraseñas son idempotentes).
3. **Correo de SES**: al desplegar `CcMessaging`, SES envía un correo de verificación al correo del
   presupuesto del ambiente; hay que abrir el enlace. Para enviar a cualquier destinatario, salir del modo
   de pruebas de SES (solicitud a AWS) y, con dominio, configurar DKIM.
4. **Llave pública de CloudFront**: en `prod`, `infra/config/cloudfront-{ambiente}.pub.pem` (pública) antes
   del despliegue; después cargar la llave privada en el secreto `cc/{ambiente}/cf-signing-key`
   (procedimiento de la desviación 24 de `docs/desviaciones.md`). En `test` se usa una llave inerte.
5. **Credenciales de Meta** (después de la vinculación, PQ-07): ya no se cargan a mano. Se capturan en
   Command Center (módulo Integraciones, "Conexión con Meta") siguiendo `docs/meta-configuracion.md`.
6. **Pipeline (solo si se crea)**: autorizar la conexión de GitHub `cc-{ambiente}-github` en la consola
   (docs/ambientes.md, sección 5.1). Este script no despliega el pipeline.
7. **Cuota de Lambda** si la verificación previa la detuvo (sección 3.5).

## 7. Comprobar el despliegue

```powershell
$env:AWS_PROFILE = "cc-test"
.\scripts\verificar_f1.ps1 -Ambiente test      # solo lectura: stacks, RDS cifrado, Object Lock, colas, Cognito con MFA, etiquetas
```

Las pruebas de humo de T-229 (`/salud` de cada servicio, un `POST /webhook/meta` firmado con el simulador,
una consulta autenticada, y el 403 sin firma) las agrega esa tarea en `scripts/humo.ps1`.

## 8. Destruir el ambiente (lo hace LA PERSONA, regla 8)

El script y el agente **no** destruyen nada. La persona ejecuta, con el mismo perfil y los mismos
contextos con los que se desplegó:

```powershell
$env:AWS_PROFILE = "cc-test"
.\scripts\aws_guard.ps1 -Ambiente test
cd infra
cdk list -c ambiente=test --profile cc-test            # qué se borraría
cdk destroy --all -c ambiente=test --profile cc-test   # el borrado
```

Orden: CloudFormation borra en el orden inverso de las dependencias (Backup, Observability, Frontend,
Edge, Api, WorkersLambdas, Compute, ComputeBase, Auth, Messaging, Data, Storage, Network, Security). Antes
y después, estas son las trampas:

| Trampa | Qué hacer |
|---|---|
| **Bóveda de AWS Backup con puntos de recuperación**: CloudFormation no la borra; `CcBackup-{env}` queda en `DELETE_FAILED` y `--all` se detiene | Antes del `destroy`, la persona borra los puntos de recuperación (`aws backup list-recovery-points-by-backup-vault` y `delete-recovery-point`) o espera a que venzan (1 día en `test`). En `prod` la bóveda tiene bloqueo y política que niega el borrado: es deliberado |
| **Buckets con Object Lock** (`constancias`): los objetos con retención vigente no se borran; el vaciado automático falla | En `test` (GOVERNANCE, 1 día) esperar un día o que la persona borre con `BypassGovernanceRetention`. En `prod` se conservan |
| **Llaves de KMS**: quedan en espera de borrado 7 días (30 en `prod`) y cobran | Nada: se borran solas. No se pueden cancelar desde este procedimiento |
| **Secretos de Secrets Manager**: quedan 7 días en recuperación (30 en `prod`) y **bloquean el nombre** si se vuelve a desplegar | Esperar, o borrado forzado por la persona |
| **Imágenes de ECR**: los repositorios `cc-{env}/migrar` y `cc-{env}/ops` se vacían al destruir en `test`; las imágenes de los servicios están en el repositorio de assets del `CDKToolkit` y no se borran | Revisar el `CDKToolkit` si importa el costo |
| **Interfaces de red de las Lambdas en la VPC**: tardan en liberarse y pueden retrasar el borrado de subredes y grupos de seguridad | Repetir `cdk destroy` pasados unos minutos |
| **Tarea `ops` en ejecución** (ECS Exec) | Detenerla antes (`aws ecs stop-task`, la persona) |
| **Instantáneas manuales de RDS** y copias en `us-east-2` | No las borra `destroy`; la persona las borra |
| **`CDKToolkit`** | Se conserva (puede estar compartido) |
| **Presupuesto de AWS Budgets** | No lo crea CDK: se conserva o se borra a mano |
| Grupos de logs creados por Lambda fuera de CDK | Revisar con la etiqueta `proyecto=command-center` |

Revisión posterior por etiqueta:

```powershell
aws resourcegroupstaggingapi get-resources --tag-filters Key=proyecto,Values=command-center --profile cc-test --region us-east-1
```

## 9. Problemas frecuentes

| Síntoma | Causa y acción |
|---|---|
| `PERFIL_INCORRECTO` | `$env:AWS_PROFILE` no es el perfil del ambiente. Defínalo con el valor de `ambientes.json` |
| `SESION_VENCIDA` | `aws sso login --profile <perfil>` y repetir |
| `CUENTA_INCORRECTA` | La sesión apunta a otra cuenta. No continúe: revise el perfil |
| "No hay consola interactiva" | Ejecute el script en una consola de PowerShell (no por una tubería ni desde un proceso sin consola) |
| "bootstrap de CDK ausente" | La persona ejecuta `cdk bootstrap` (sección 3.3) |
| "sin emulación arm64" | `docker run --privileged --rm tonistiigi/binfmt --install arm64` |
| "cuota de concurrencia de Lambda" | Sección 3.5 |
| La tarea `migrar` sale con código distinto de 0 | Revise el grupo de logs `/cc/{ambiente}/migrar` (no contiene contraseñas ni URLs); corrija y repita el script |
| `docker login` falla con el almacén de credenciales | El script ya usa una carpeta temporal; si persiste, cierre sesión de Docker Desktop y repita |
