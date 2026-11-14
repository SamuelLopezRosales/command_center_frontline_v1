# Ambientes, diferencias con producción y limpieza

Documento de la tarea T-010. Fuente de los valores: `infra/config/ambientes.json` y `infra/constructs/retencion.py`.

## 1. Ambiente de prueba

| Dato | Valor |
|---|---|
| Ambiente | `test` |
| Cuenta permitida | `034362033822` (la guardia de CDK rechaza cualquier otra) |
| Región | `us-east-1` |
| Perfil | `cc-test` (IAM Identity Center). Es el único permitido |
| Presupuesto | 50 USD al mes; alertas al 80 % real, 100 % real y 100 % pronosticado a `samuel.lopez@honne.com` |
| Vida útil prevista | De 1 a 2 semanas. Después Samuel lo destruye a mano |

## 2. Diferencias entre `test` y producción

`prod` conserva el diseño de `design.md`. Ningún valor de `test` se aplica a `prod` sin revisión: `retencion.py` rechaza un `prod` con borrado permitido.

| Elemento | `test` | `prod` | Motivo de la diferencia |
|---|---|---|---|
| NAT | Una instancia NAT `t4g.nano` (cambio A) | Una NAT Gateway por zona | Costo |
| RDS, clase | `db.t4g.micro` (cambio E) | `db.t4g.medium` | Costo |
| RDS, Multi-AZ | No | Sí | Costo |
| RDS, protección contra borrado | No | Sí | Poder destruir el prototipo |
| RDS, retención de respaldos | 1 día | 14 días | Costo y limpieza |
| RDS Proxy | No se despliega; las Lambdas se conectan directo (cambio B) | Sí | Costo |
| WAF | No se crea (cambio C) | Sí, en bloqueo | Costo |
| Workers de ECS (`pdf`, `cargas`, `whatsapp-entrada`) | Mínimo 0 tareas (cambio D) | Mínimo 1 tarea | Costo |
| Tareas por servicio de API | 1 | 2 | Costo |
| Concurrencia aprovisionada del webhook | 0 | 2 | Costo |
| Política de borrado de recursos | `DESTROY` | `RETAIN` | Poder destruir el prototipo |
| Buckets | Vaciado automático al destruir | Se conservan | Poder destruir el prototipo |
| Object Lock (bucket de constancias) | GOVERNANCE, retención de 1 día | GOVERNANCE, retención [POR CONFIRMAR] (PQ-24) | Poder destruir el prototipo |
| Secretos, días de recuperación | 7 (el mínimo de Secrets Manager) | 30 | Limpieza |
| Llaves de KMS, días de espera de borrado | 7 (el mínimo de KMS) | 30 | Limpieza |
| Dominio | Ninguno: dominio de CloudFront y endpoint predeterminado de API Gateway con encabezado secreto de origen (PQ-22) | Dominio propio | Sin dominio para el prototipo |
| WhatsApp | Simulador de Meta | Cuenta real (PQ-07) | Vinculación pendiente |

Consecuencias aceptadas en `test`: la NAT es una sola instancia sin alta disponibilidad; no hay protección de WAF; la primera constancia tras un periodo inactivo tarda en arrancar el worker; el p95 de 5 s del PDF se mide con el worker ya encendido; la prueba de RDS Proxy queda para producción.

## 3. Procedimiento de limpieza (lo ejecuta Samuel)

El agente **no ejecuta** ningún borrado (regla 8). Antes de cada borrado entrega la lista de lo que se afectaría y el comando exacto.

1. Verificar sesión y cuenta:

   ```powershell
   $env:AWS_PROFILE = "cc-test"
   .\scripts\aws_guard.ps1
   ```

2. Ver qué se borraría:

   ```powershell
   cd infra
   cdk list -c ambiente=test --profile cc-test
   ```

3. Destruir todos los stacks del proyecto:

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
| Imágenes de ECR | Se borran si el repositorio se crea con vaciado automático; si no, quedan | Revisar en el paso 4 |
| Stack `CDKToolkit` (bootstrap) | `cdk destroy` no lo borra | Conservarlo si se volverá a desplegar; si no, Samuel lo borra desde CloudFormation |
| Grupos de logs de CloudWatch creados por Lambda | Pueden quedar si no los crea CDK | Revisar en el paso 4 |
| Presupuesto de AWS Budgets | No lo crea CDK (lo crea `crear_presupuesto.ps1`) | Conservarlo o borrarlo a mano |

Cada recurso que no se pueda borrar se registra en `.kiro/specs/progreso.md` con su identificador.

## 5. Hallazgo de seguridad del equipo de desarrollo

Al probar la guardia (T-004), la CLI de CDK resolvió por su cuenta las credenciales por defecto del equipo, que apuntan a la cuenta **686699774254**, distinta de la de prueba. La guardia la rechazó y no se sintetizó ni desplegó nada. Mitigaciones:

- Toda tarea de AWS ejecuta antes `scripts/aws_guard.ps1` con `AWS_PROFILE=cc-test`.
- `scripts/verificar_synth.py` aísla las credenciales del equipo al probar la guardia.
- Recomendación: revisar el perfil `default` de `~/.aws` o pasar siempre `--profile cc-test`.

## 6. Herramientas del equipo

`make` no está instalado: `scripts/dev.ps1` hace lo mismo que el `Makefile`. `gitleaks` no está instalado; la detección de secretos usa `detect-secrets` (hook de pre-commit), más un hook que bloquea archivos `.pem`, `.key`, `.p12`, `credentials` y `.env`. Python 3.12 lo provee `uv` (el equipo trae 3.14).
