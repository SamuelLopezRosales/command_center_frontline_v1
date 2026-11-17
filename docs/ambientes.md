# Ambientes, diferencias con producción y limpieza

Documento de la tarea T-010, revisado en T-227 (tras T-224 a T-226). Fuente de los valores:
`infra/config/ambientes.json`, `infra/constructs/retencion.py` y `infra/config/costos.json`. El
procedimiento para desplegar en esta u otra cuenta está en [despliegue.md](despliegue.md); aquí quedan los
datos de cada ambiente, sus diferencias y la limpieza.

## 1. Ambiente de prueba

| Dato | Valor |
|---|---|
| Ambiente | `test` |
| Cuenta permitida | `034362033822` (la guardia de CDK rechaza cualquier otra) |
| Región | `us-east-1` |
| Perfil | `cc-test` (IAM Identity Center). Es el único permitido |
| Presupuesto | 50 USD al mes; alertas al 80 % real, 100 % real y 100 % pronosticado a `samuel.lopez@honne.com` |
| Vida útil prevista | De 1 a 2 semanas. Después Samuel lo destruye a mano |
| Despliegue | Un solo despliegue completo (T-229) con `scripts/desplegar.ps1 -Ambiente test`; los stacks de las fases 0 y 1 que se probaron en T-018 y T-045 a T-049 ya se destruyeron |
| Frase de aprobación del script | `apruebo T-229` (`infra/config/despliegue.json`) |
| Contextos `-c` obligatorios | Ninguno (los opcionales: `empresa_id_whatsapp`, `respaldo`) |

## 1b. Ambiente `samuel` (cuenta nueva de la organización)

Es donde se hace el despliegue final de T-229 y T-230 (el ambiente `test` y su cuenta quedan sin tocar).

| Dato | Valor |
|---|---|
| Ambiente | `samuel` |
| Cuenta permitida | `795359731321` |
| Región | `us-east-1` |
| Perfil | `cc-samuel-sdk`: llaves de acceso del usuario IAM `samuel-depliegue-sdk-command-center` (nunca del usuario raíz), guardadas por `aws configure` fuera del repositorio. Se desactivan al terminar la ventana |
| Presupuesto | 70 USD al mes (`command-center-samuel-mensual`); mismas alertas, a `samuel.lopez@honne.com` |
| Frase de aprobación del script | `apruebo despliegue samuel` |
| Economía | Igual que `test` (NAT por instancia, sin Multi-AZ, sin WAF, workers en 0) |
| Diferencias propias | Sin reserva de concurrencia de Lambda (`reservar_concurrencia: false`, cuota de 10) y **sin MFA** (`mfa: OFF`); ver `desviaciones.md` |
| Costo de la ventana (14 días, todo encendido) | 66.81 USD estimados por el script; no incluye transferencia de datos |
| Limpieza | La ejecuta Samuel: `cdk destroy --all --profile cc-samuel-sdk` y después desactivar las llaves de acceso. La guía de T-230 irá en `docs/limpieza-samuel.md` |

## 2. Diferencias entre `test` y producción

`prod` conserva el diseño de `design.md`. Ningún valor de `test` se aplica a `prod` sin revisión: `retencion.py` rechaza un `prod` con borrado permitido. **Un ambiente es "tipo prod" cuando su `economia.permite_borrado` es `false`** (retención `RETAIN`, región de recuperación, pipeline por defecto, contextos obligatorios). Hoy `ambientes.json` solo define `test`: `prod` se prueba con un ambiente sintético en `infra/tests` y en `scripts/tests/test_desplegar.py`.

| Elemento | `test` | `prod` | Motivo de la diferencia |
|---|---|---|---|
| NAT | Una instancia NAT `t4g.micro` (cambio A; `t4g.nano` no arranca por memoria) | Una NAT Gateway por zona | Costo |
| RDS, clase | `db.t4g.micro` (cambio E) | `db.t4g.medium` | Costo |
| RDS, Multi-AZ | No | Sí | Costo |
| RDS, protección contra borrado | No | Sí | Poder destruir el prototipo |
| RDS, retención de respaldos | 1 día | 14 días | Costo y limpieza |
| RDS Proxy | No se despliega; las Lambdas se conectan directo (cambio B) | Sí | Costo |
| WAF | No se crea (cambio C) | Sí, en bloqueo | Costo |
| Workers de ECS (`pdf`, `cargas`, `whatsapp-entrada`) | Mínimo 0 tareas (cambio D) | Mínimo 1 tarea | Costo |
| Tareas por servicio de API | 1 | 2 | Costo |
| ALB interno | Listener HTTP 80 dentro de la VPC (sin dominio, PQ-22); sin registro de acceso | HTTPS 443 con certificado (obligatorio), registro de acceso a un bucket propio, protección contra borrado | Sin dominio no hay certificado; ver `docs/desviaciones.md` |
| Autoescalado de los servicios de API | No (una tarea fija) | Sí, de 2 a 6 por CPU al 60 % | Costo |
| Máximo de tareas de los workers | 1 | 4 (`worker-pdf`), 2 (`worker-cargas`), 4 (`worker-whatsapp-entrada`, mínimo 2) | Costo |
| Concurrencia aprovisionada del webhook | 0 | 2 | Costo |
| Política de borrado de recursos | `DESTROY` | `RETAIN` | Poder destruir el prototipo |
| Buckets | Vaciado automático al destruir | Se conservan | Poder destruir el prototipo |
| Object Lock (bucket de constancias) | GOVERNANCE, retención de 1 día | GOVERNANCE, retención [POR CONFIRMAR] (PQ-24) | Poder destruir el prototipo |
| Secretos, días de recuperación | 7 (el mínimo de Secrets Manager) | 30 | Limpieza |
| Llaves de KMS, días de espera de borrado | 7 (el mínimo de KMS) | 30 | Limpieza |
| Dominio | Ninguno: dominio de CloudFront y endpoint predeterminado de API Gateway con encabezado secreto de origen (PQ-22) | Dominio propio | Sin dominio para el prototipo |
| WhatsApp | Simulador de Meta | Cuenta real (PQ-07) | Vinculación pendiente |
| Credenciales de Meta | Se capturan en Command Center (Integraciones); `notificaciones` escribe `cc/test/meta` | Igual, en `cc/prod/meta` | Ver `docs/meta-configuracion.md` y la desviación de Integraciones en `docs/desviaciones.md` |
| AWS Backup (`CcBackup`, T-226) | Bóveda y plan diario de RDS con retención de 1 día, sin copia, sin bloqueo y borrable | Retención de 35 días, copia diaria a `us-east-2`, bóveda con bloqueo en modo de gobierno y política que niega borrar puntos de recuperación | Costo y limpieza |
| Región de recuperación `us-east-2` (`CcBackupRecuperacion`, T-226) | **No se crea**: la región no está inicializada con `cdk bootstrap` | Llave, bóveda y réplica de `constancias` con Object Lock | Sin bootstrap en esa región; queda definida y probada con un `prod` sintético |
| Réplica de `constancias` a `us-east-2` | No | Sí (sin marcas de borrado) | Igual que la fila anterior |
| Pipeline (`CcPipeline`, T-226) | **No se crea por defecto**; solo con `-c pipeline=true -c repositorio_pipeline=propietario/repo` | Se crea | Costo y una conexión que se autoriza a mano |
| Aprobación manual del pipeline | Sí (si se crea) | Sí | Un pipeline de `test` nunca despliega solo |
| Instantánea de RDS previa a las migraciones | No | Sí (la toma el pipeline) | Costo; en `test` la base es desechable |
| Registro de flujo de la VPC | No | Sí (solo tráfico rechazado, 30 días) | Costo |
| Cuentas permitidas y perfil | `034362033822`; perfil `cc-test` | La cuenta del cliente; su propio perfil | Guardia de cuenta (PA-1 a PA-3) |
| Contextos de CDK obligatorios (`-c`) | Ninguno | `certificado_alb_arn`, `dominio_interno`, `repositorio_pipeline` (salvo `pipeline=false`) y la llave pública `infra/config/cloudfront-prod.pub.pem`; también `dominio_origen_api`, `certificado_origen_api_arn`, `zona_hospedada_id` si hay dominio propio | `infra/app.py`; `desplegar.ps1` los exige en la verificación previa |
| Llave pública de CloudFront | Llave inerte si no hay archivo (ninguna URL firmada valida) | Obligatoria | Desviación 24 |
| Bootstrap de CDK | Región principal (compartido con otros proyectos: no se repite) | Región principal **y** `us-east-2` | `CcBackupRecuperacion` |
| Frase de aprobación del despliegue | `apruebo T-229` | La de `despliegue.json` (por defecto `apruebo despliegue prod`) | Aprobación explícita por persona |
| Costo de la ventana (estimado por `desplegar.ps1`) | Unos 67 USD en 14 días con todo encendido; unos 42 USD con servicios 8 h al día (presupuesto 50 USD) | Mayor (NAT por zona, Multi-AZ, RDS Proxy, WAF, workers con mínimo): lo calcula el script con `-Ambiente prod` | `infra/config/costos.json` (estimaciones, no la lista de precios de AWS) |

Consecuencias aceptadas en `test`: la NAT es una sola instancia sin alta disponibilidad; no hay protección de WAF; la primera constancia tras un periodo inactivo tarda en arrancar el worker; el p95 de 5 s del PDF se mide con el worker ya encendido; la prueba de RDS Proxy queda para producción.

## 3. Procedimiento de limpieza (lo ejecuta Samuel)

El agente **no ejecuta** ningún borrado (regla 8), ni tampoco `desplegar.ps1`, que nunca destruye nada.
Antes de cada borrado entrega la lista de lo que se afectaría y el comando exacto. La guía completa, con
el orden y las trampas, está en [despliegue.md, sección 8](despliegue.md#8-destruir-el-ambiente-lo-hace-la-persona-regla-8).

1. Verificar sesión y cuenta:

   ```powershell
   $env:AWS_PROFILE = "cc-test"
   .\scripts\aws_guard.ps1 -Ambiente test
   ```

2. Ver qué se borraría (con los mismos contextos `-c` con los que se desplegó):

   ```powershell
   cd infra
   cdk list -c ambiente=test --profile cc-test
   ```

3. Destruir todos los stacks del proyecto (primero se resuelven las trampas de la sección 4):

   ```powershell
   cdk destroy --all -c ambiente=test --profile cc-test
   ```

4. Revisar lo que quede, por etiqueta:

   ```powershell
   aws resourcegroupstaggingapi get-resources --tag-filters Key=proyecto,Values=command-center --profile cc-test --region us-east-1
   ```

Si un despliegue terminó en una cuenta equivocada (no debería: la guardia lo impide), se destruye con el **mismo perfil** con el que se creó (regla 9).

## 4. Recursos que no se borran de inmediato

| Recurso | Comportamiento al destruir | Qué hacer |
|---|---|---|
| Llaves de KMS | Quedan en "pendiente de borrado" 7 días; mientras tanto cobran | Nada; se borran solas al cumplirse el plazo |
| Secretos de Secrets Manager | Quedan 7 días en recuperación | Nada; o borrado forzado manual por Samuel si se necesita el nombre |
| Bucket de constancias con Object Lock | Los objetos con retención vigente no se pueden borrar hasta que venza (1 día en `test`) | Esperar 1 día, o que Samuel borre con `BypassGovernanceRetention` (solo en GOVERNANCE) |
| Imágenes de ECR | Los repositorios `cc-{env}/migrar` y `cc-{env}/ops` se vacían solos al destruir en `test` (`empty_on_delete`); en `prod` se conservan. Las imágenes de los servicios y los paquetes de las Lambdas viven en el repositorio y el bucket de assets del `CDKToolkit` y no se borran | Revisar en el paso 4 |
| Interfaces de red de las Lambdas en la VPC | Tardan en liberarse y pueden retrasar el borrado de subredes y grupos de seguridad (`CcNetwork`) | Repetir `cdk destroy` pasados unos minutos |
| Tarea `ops` en ejecución (ECS Exec del primer usuario) | Mantiene interfaces de red y puede bloquear `CcNetwork` | Que la persona la detenga antes (`aws ecs stop-task`) |
| Stack `CDKToolkit` (bootstrap) | `cdk destroy` no lo borra | Conservarlo si se volverá a desplegar; si no, Samuel lo borra desde CloudFormation |
| Grupos de logs de CloudWatch creados por Lambda | Pueden quedar si no los crea CDK | Revisar en el paso 4 |
| Presupuesto de AWS Budgets | No lo crea CDK (lo crea `crear_presupuesto.ps1`) | Conservarlo o borrarlo a mano |
| Bóveda de AWS Backup `cc-test-respaldos` (T-226) | CloudFormation **no borra una bóveda con puntos de recuperación**: `CcBackup-test` queda en `DELETE_FAILED` y, como depende de `CcData-test`, `cdk destroy --all` se detiene ahí | Antes de `cdk destroy --all`: que Samuel borre los puntos de recuperación de la bóveda (`aws backup list-recovery-points-by-backup-vault` y `delete-recovery-point`; lo hace él, regla 8) o esperar a que venzan (1 día). Si ya quedó en `DELETE_FAILED`, repetir `cdk destroy` después de eso |
| Instantáneas manuales de RDS | Las toma el pipeline en `prod` y **no** se borran con la instancia ni con `cdk destroy` | Borrarlas a mano al limpiar un ambiente de prueba (en `test` el pipeline no las toma) |

## 5. Pipeline de CI/CD y respaldo (T-226)

### 5.1 Pasos manuales (los hace una persona; el agente no los ejecuta)

1. **Bootstrap de CDK** de la cuenta en la región principal (`desplegar.ps1` solo lo verifica). En `prod` también en `us-east-2`
   (`cdk bootstrap aws://CUENTA/us-east-2`): sin eso `CcBackupRecuperacion` no se puede desplegar.
2. **Repositorio y conexión.** El pipeline necesita `-c repositorio_pipeline=propietario/repo`
   (y `-c rama_pipeline=main`). Al desplegar `CcPipeline-{env}` se crea la conexión
   `cc-{env}-github` en estado **PENDIENTE**: hay que autorizarla en la consola de AWS
   (Herramientas para desarrolladores, Configuración, Conexiones, "Actualizar conexión
   pendiente", instalar la aplicación de GitHub). Hasta entonces la etapa Fuente falla. También se
   puede reutilizar una conexión que ya exista con `-c conexion_codigo_arn=ARN`.
3. **Llave pública de CloudFront de `prod`**: `*.pem` no se versiona. Crear una vez el parámetro
   de SSM `/cc/prod/pipeline/clave-publica-cloudfront` (tipo `String`) con el PEM **público**; el
   proyecto de compilación lo pasa a `-c cloudfront_public_key_pem`. La llave privada es el
   secreto `cc/prod/cf-signing-key` (procedimiento de la desviación 24).
4. **Quién aprueba.** La etapa `Aprobacion` solo la puede aprobar quien tenga
   `codepipeline:PutApprovalResult` sobre `cc-{env}`. Concederlo únicamente a las personas que
   designe el cliente; los roles de CodeBuild no lo tienen.
5. **Contextos de `prod`** que la síntesis necesita (`certificado_alb_arn`, `dominio_interno`,
   `dominio_origen_api`, `certificado_origen_api_arn`, `zona_hospedada_id`, `empresa_id_whatsapp`):
   se pasan con `-c` al desplegar `CcPipeline-prod` y el pipeline los repite al sintetizar.
6. **Rol de ejecución de CloudFormation del bootstrap.** Por defecto es `AdministratorAccess`:
   es lo que da el poder de despliegue a `cdk deploy`. Se puede acotar con
   `cdk bootstrap --cloudformation-execution-policies`.

### 5.2 Qué se crea en `test` por defecto

`CcBackup-test` sí (bóveda y plan de 1 día; `-c respaldo=false` lo omite). **No** se crean
`CcPipeline-test` (solo con `-c pipeline=true -c repositorio_pipeline=...`) ni
`CcBackupRecuperacion-test` (nunca).

### 5.3 Orden de despliegue

`CcBackupRecuperacion` (solo `prod`), `CcSecurity`, `CcNetwork`, `CcStorage`, `CcData`, `CcMessaging`,
`CcAuth`, `CcComputeBase`, imágenes `migrar` y `ops` en ECR, **migraciones** (tarea `migrar`),
**contraseñas de los roles** (tarea `ops`, `ops.sh contrasenas`), `CcCompute`, `CcWorkersLambdas`,
`CcApi`, `CcEdge`, `CcFrontend`, `CcObservability`, `CcBackup`. `CcPipeline` va aparte y nunca se
despliega a sí mismo. El pipeline lo hace así en las etapas Base, Migraciones y Servicios, y
`scripts/desplegar.ps1` en los mismos tres grupos (Base, migraciones y contraseñas, Servicios) con la
aprobación de una persona entre el `cdk diff` y el primer cambio (ver [despliegue.md](despliegue.md)).

Cada recurso que no se pueda borrar se registra en `.kiro/specs/progreso.md` con su identificador.

## 6. Hallazgo de seguridad del equipo de desarrollo

Al probar la guardia (T-004), la CLI de CDK resolvió por su cuenta las credenciales por defecto del equipo, que apuntan a la cuenta **686699774254**, distinta de la de prueba. La guardia la rechazó y no se sintetizó ni desplegó nada. Mitigaciones:

- Toda tarea de AWS ejecuta antes `scripts/aws_guard.ps1` con `AWS_PROFILE=cc-test`.
- `scripts/verificar_synth.py` aísla las credenciales del equipo al probar la guardia.
- Recomendación: revisar el perfil `default` de `~/.aws` o pasar siempre `--profile cc-test`.

## 7. Herramientas del equipo

`make` no está instalado: `scripts/dev.ps1` hace lo mismo que el `Makefile`. `gitleaks` no está instalado; la detección de secretos usa `detect-secrets` (hook de pre-commit), más un hook que bloquea archivos `.pem`, `.key`, `.p12`, `credentials` y `.env`. Python 3.12 lo provee `uv` (el equipo trae 3.14).
