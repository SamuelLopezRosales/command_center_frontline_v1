# Progreso de implementación

Se actualiza al empezar y al terminar cada tarea. Estados: pendiente, en curso, completada, bloqueada.

| Tarea | Título | Fase | Estado | Fecha | Verificación | Notas |
|---|---|---|---|---|---|---|
| T-001 | Crear la estructura del monorepo y las herramientas de calidad | 0 | completada | 2026-11-13 | lint OK; detect-secrets bloquea llave AWS falsa; .gitignore verificado | make no instalado: scripts/dev.ps1 equivale. gitleaks sustituido por detect-secrets (sin Go ni binario). Python 3.12 instalado con uv (el equipo trae 3.14). git init local sin commits. |
| T-002 | Definir la configuración de ambientes y la lista permitida de cuentas | 0 | completada | 2026-11-13 | 15 pruebas pasan: esquema, cuentas, perfil, etiquetas, sin llaves | Incluye bloque economía de test (A-E) |
| T-003 | Inicializar la aplicación de CDK en Python | 0 | completada | 2026-11-13 | cdk synth -c ambiente=test ejecuta la app (sin stacks); sin ambiente o desconocido falla con ConfiguracionInvalida | La CLI devuelve 1 si no hay stacks; scripts/verificar_synth.py lo distingue |
| T-004 | Implementar la guardia de cuenta en la aplicación de CDK | 0 | completada | 2026-11-13 | 29 pruebas pasan; cdk synth: cuenta 111111111111 y cuenta ausente fallan, 034362033822 pasa | HALLAZGO: el perfil por defecto del equipo apunta a la cuenta 686699774254 (no es la de prueba); la guardia la rechazó. verificar_synth aísla credenciales. |
| T-005 | Aplicar las etiquetas obligatorias en el nivel de la aplicación | 0 | completada | 2026-11-13 | aserción CDK: 3 etiquetas con valores exactos; prueba AST: sin Tags.of fuera de etiquetas.py | Corregido 1 vez: CDK ordena las etiquetas por clave |
| T-006 | Escribir el script de verificación de sesión y de cuenta | 0 | completada | 2026-11-13 | 16 pruebas con salidas simuladas: sesión vencida, otro perfil, cuenta distinta, llaves en entorno, región | Lógica en scripts/aws_guard.py; aws_guard.ps1 es el punto de entrada |
| T-007 | Ejecutar la verificación de sesión con el perfil cc-test (lectura) | 0 | completada | 2026-11-13 | PA-1 a PA-3 OK: cuenta 034362033822, arn user/samuel.lopez.labs-inovacion | Perfil cc-test con aws login (login_session, credenciales temporales); sin llaves en credentials. Regla 1 actualizada con aprobación de Samuel. |
| T-008 | Preparar la definición y el script del presupuesto | 0 | completada | 2026-11-13 | 5 pruebas; -WhatIf muestra 50 USD y 3 alertas sin llamar a AWS | Script idempotente con guardia PA antes de llamadas reales |
| T-009 | Verificar o crear el presupuesto con alertas en cc-test | 0 | bloqueada | 2026-11-14 | Presupuesto creado (50 USD, 3 alertas), en ALARM por gasto ajeno de la cuenta | Pendiente por decisión de Samuel: filtrar por etiqueta proyecto requiere activar la etiqueta en la cuenta de administración 758167202044 |
| T-010 | Documentar las diferencias test y producción y el procedimiento de limpieza | 0 | en curso | 2026-11-13 | docs/ambientes.md escrito | Verificación = revisión de Samuel (pendiente) |
| T-011 | Implementar la política de retención por ambiente en los constructos de CDK | 0 | completada | 2026-11-13 | 3 pruebas: test DESTROY/sin protección/Object Lock 1 día; prod RETAIN; prod con borrado se rechaza |  |
| T-012 | Ejecutar cdk bootstrap en cc-test | 0 | completada | 2026-11-14 | Solo lectura: CDKToolkit UPDATE_COMPLETE, versión 32 (2025-10-06) | No se ejecutó cdk bootstrap: CDKToolkit compartido con otros proyectos. Tarea redefinida con aprobación de Samuel. |
| T-013 | Crear el stack CcSecurity (KMS, secretos y parámetros) | 0 | completada | 2026-11-13 | aserciones CDK: 2 llaves con rotación anual, 5 secretos cifrados sin valor en plantilla, parámetros SSM, sin Resource * en IAM | cdk-nag 3: supresiones vía Validations.acknowledge (infra/constructs/nag.py) |
| T-014 | Crear el stack CcNetwork con la configuración mínima de test | 0 | completada | 2026-11-13 | 9 aserciones CDK: además disco NAT cifrado (gp3) y zonas fijas us-east-1a/b | Corregido con visto bueno de Samuel: override del disco NAT, EC23 reconocida, availability_zones fijas sin búsqueda en AWS |
| T-015 | Integrar cdk-nag y la síntesis de todos los stacks | 0 | completada | 2026-11-13 | cdk synth con AwsSolutions sin errores ni hallazgos sin reconocer; cada reconocimiento con motivo; guardia OK (5 casos) | cdk-nag 3 usa Validations.acknowledge. app.py quita infra/ de sys.path (infra/constructs tapaba el paquete constructs) |
| T-016 | Armar el pipeline mínimo de integración (sin despliegue) | 0 | completada | 2026-11-13 | scripts/ci.ps1 (make ci): lint OK, 72 pruebas, cdk synth con cdk-nag OK, imágenes omitidas (sin Dockerfile); sin AWS; buildspec sin credenciales | Corregí 2 errores del propio script antes de que corriera la verificación: codificación de .ps1 (ahora UTF-8 con BOM, para PowerShell 5.1) y enumeración de variables AWS_* |
| T-017 | Mostrar el cdk diff de CcSecurity (lectura) | 0 | completada | 2026-11-14 | cdk diff CcSecurity-test: 17 recursos nuevos (2 KMS, 2 alias, 5 secretos, 7 parámetros SSM), 0 cambios/reemplazos; sin colisiones de nombres | El diff publicó la plantilla en el bucket de assets del CDKToolkit compartido y usó un change set de solo lectura (comportamiento normal de cdk diff) |
| T-018 | Desplegar CcSecurity en cc-test | 0 | completada | 2026-11-14 | CcSecurity-test CREATE_COMPLETE (18/18, 30 s) | Llaves: datos 09cfe4f4-..., infra 549e7a11-... |
| T-019 | Verificar etiquetas y recursos desplegados | 0 | completada | 2026-11-14 | Solo lectura: 15 recursos etiquetados (2 KMS, 5 secretos, 7 parámetros, el stack) con las 3 etiquetas correctas; 0 incorrectos | Los alias de KMS y CDK::Metadata no admiten etiquetas |
| T-020 | Punto de control de la Fase 0 | 0 | completada | 2026-11-14 | Punto de control aprobado por Samuel (apruebo fase 0) | T-009 pendiente (filtro por etiqueta) y T-010 pendiente de revisión, por decisión de Samuel |
| T-021 | Crear la base de `cc_common`: configuración, errores, logging y tipos de validación | 1 | completada | 2026-11-14 | 47 pruebas: problem+json sin eco del valor, 500 genérico, violación de unicidad sin texto de PostgreSQL, filtro de logs (celular, RFC, CURP, NSS, correo, llave AWS), tipos de §10.1 con hypothesis | Dependencias de servicios en el grupo uv "servicios" |
| T-022 | Montar el entorno local de pruebas (PostgreSQL 16 y LocalStack) | 1 | completada | 2026-11-14 | 3 pruebas: PostgreSQL 16 con pg_trgm/unaccent/pgcrypto vía Testcontainers, base nueva por prueba, LocalStack 4.4 (S3, SQS, EventBridge, SNS, SES) | Corregido el healthcheck de LocalStack (estado available). docker compose en el puerto 55432 y 4566 |
| T-023 | Implementar `cc_common.db` (motor, sesión, `app.empresa_id` y paginación) | 1 | completada | 2026-11-14 | 9 pruebas con PostgreSQL real: RLS aísla empresa 1 y 2, sin empresa no ve filas, no inserta en otra empresa, app.empresa_id dura solo la transacción, reintento ante 40001 (3 intentos), sin reintento para otros errores, cursor estable | Hallazgo para T-030: la política RLS debe usar NULLIF(current_setting(...), '')::bigint |
| T-024 | Implementar `cc_common.crypto` (cifrado de sobre y HMAC) | 1 | completada | 2026-11-14 | 8 pruebas con KMS simulado: ida y vuelta AES-GCM, nonce distinto, AAD de otra fila u otra empresa no descifra, rotación por versión de DEK, caché de 15 min, HMAC de celular con llave | Formato bytea: versión|versión DEK|nonce|cifrado |
| T-025 | Implementar `cc_common.auth` (claims, usuario actual y permisos) | 1 | completada | 2026-11-14 | 15 pruebas: firma, iss, client_id, token_use, exp, empresa_id y rol; 401/403; RH con todos los permisos; detector de rutas sin permiso | ruta_publica() marca explícita para rutas públicas |
| T-026 | Implementar bitácora, outbox, eventos y cliente interno en `cc_common` | 1 | completada | 2026-11-14 | 16 pruebas: bitácora con detalle permitido (rechaza valor, nombre, celular, rfc), outbox se revierte con la transacción, 2 relays sin duplicar 120 mensajes, fallo deja pendiente, consumo idempotente; cliente interno con token HS256, reintento solo idempotente, corte de circuito |  |
| T-027 | Escribir las migraciones de `identidad` y `auditoria` | 1 | completada | 2026-11-14 | 6 pruebas: tablas e índices de identidad y auditoria, unicidad de correo sin mayúsculas y de cognito_sub, rol solo RH, horario válido, invitación solo con hash de 32 bytes, bitácora sin UPDATE/DELETE/TRUNCATE, detalle con claves permitidas, upgrade y downgrade | Alembic con tabla de versiones identidad.alembic_version; helper cc_common.migraciones |
| T-028 | Escribir las migraciones de `campos` y `colaboradores` | 1 | completada | 2026-11-14 | 12 pruebas: tablas de campos y colaboradores, unicidad por empresa (nombres de restricción del catálogo de errores), CHECK de tipo, estatus, número normalizado, fecha de baja, valor único por campo, código interno y valor de opción inmutables, índice trigrama usado en la búsqueda, upgrade y downgrade | f_unaccent IMMUTABLE envuelve unaccent para poder indexar |
| T-029 | Escribir las migraciones de `whatsapp`, `constancias` y `notificaciones`, con vistas y funciones | 1 | completada | 2026-11-14 | 8 pruebas: tablas de whatsapp, constancias y notificaciones; versión y constancia inmutables (solo cambian entrega y vigencia); folio único por empresa y con formato; token de 24 h máx.; una conversación abierta por número; rango de estados ordenado; excluido exige motivo; vistas filtradas por empresa; baja completa | Desviación de design §2.6: vistas sin security_invoker, con filtro explícito por app.empresa_id (svc_dashboard solo ve vistas). Corregido 1 vez: regex {1,512} no válida en PostgreSQL (máx 255). Vistas de colaboradores en colaboradores 0002. |
| T-030 | Escribir el script de roles de base de datos y políticas RLS | 1 | completada | 2026-11-14 | roles.sql, rls.sql y grants.sql idempotentes (2 corridas sin error); roles sin superusuario ni BYPASSRLS; RLS activo en todas las tablas con empresa_id | Política con NULLIF. Agregados al diseño: outbox y evento_procesado sin RLS (relay); funciones SECURITY DEFINER validar_invitacion y usuario_por_sub para los triggers de Cognito |
| T-031 | Construir el script `migrar_todo` y la imagen de migraciones | 1 | completada | 2026-11-14 | migrar_todo aplica 6 servicios + 3 scripts en orden; imagen cc-migrar construida y probada contra PostgreSQL local (2 corridas, exit 0); exit 1 con URL inválida sin mostrar la contraseña; exit 2 sin URL | Corregido 1 vez: faltaba sqlalchemy[asyncio] (greenlet) en la imagen |
| T-032 | Probar el esquema: restricciones, inmutabilidad, RLS y permisos entre esquemas | 1 | completada | 2026-11-14 | 17 pruebas (tests/integracion/test_esquema.py): unicidad, inmutabilidad, RLS aísla empresas, sin empresa no hay filas, permission denied en 7 lecturas entre esquemas, dashboard solo vistas y bitácora, bitácora sin UPDATE/DELETE/SELECT para servicios, alembic_version solo migrador, funciones definer |  |
| T-033 | Crear el esqueleto del servicio `dashboard` y la exportación de OpenAPI | 1 | completada | 2026-11-14 | 5 pruebas: /salud 200, 404 y 405 en problem+json con correlacion_id, OpenAPI determinista, contrato del repositorio al día (--verificar), ninguna ruta sin permiso | Paquete cc_dashboard en vez de app (evita choque entre servicios). Dockerfile con usuario no root. cc_common.recursos crea el motor con credenciales de Secrets Manager. Manejador HTTPException en cc_common.errores |
| T-034 | Implementar DSH-06, DSH-07 y DSH-10 (sesión, usuario actual e invitaciones) | 1 | completada | 2026-11-14 | pytest dashboard 19 ok; ruff ok; OpenAPI regenerado | DSH-06, DSH-07, DSH-10 |
| T-035 | Implementar DSH-08, DSH-09 y DSH-05 (usuarios, desactivación y bitácora) | 1 | completada | 2026-11-14 | pytest dashboard+shared 134 ok; ruff ok; OpenAPI regenerado | DSH-05, DSH-08, DSH-09. Rango maximo de bitacora no aplicado (PQ-20 por confirmar) |
| T-036 | Implementar las Lambdas `cognito-pre-signup` y `cognito-post-confirmation` | 1 | completada | 2026-11-14 | pytest lambdas 24 ok (suite 270 ok); ruff ok | LAM-07/08. Desviacion: el codigo viaja en custom:codigo_invitacion (SignUp userAttributes), no en ClientMetadata; CcAuth (T-042) debe definirlo. pre-signup solo acepta PreSignUp_SignUp |
| T-037 | Implementar la Lambda `cognito-pre-token` | 1 | completada | 2026-11-14 | pytest lambdas 24 ok; ruff ok | LAM-09. Interpretacion: la inactividad de 30 min se aplica solo al renovar tokens (RefreshTokens), no en el inicio interactivo; el usuario inactivo se rechaza siempre |
| T-038 | Escribir `bootstrap_admin.py` (empresa e invitación inicial) | 1 | completada | 2026-11-14 | pytest bootstrap 13 ok; ruff ok | No siembra campos sugeridos (INT-CAM-02 depende del servicio campos); correo se exige solo con --correo-destino |
| T-039 | Crear los stacks CcStorage y su prueba | 1 | completada | 2026-11-14 | pytest infra 71 ok; ruff ok; cdk synth sin hallazgos de cdk-nag | CcStorage: 5 buckets. En test sin deny de borrado de plantillas (impediria cdk destroy); Object Lock 1 dia; CORS cargas https://*.cloudfront.net hasta tener dominio (PQ-22); sin replica a us-east-2 (Fase 7). CcSecurity-test ganara un export de la llave al desplegar. Corregido nombre de reporte en test_nag |
| T-040 | Crear el stack CcData (RDS, RDS Proxy opcional y secretos de roles) | 1 | completada | 2026-11-14 | pytest infra 86 ok; ruff ok; cdk synth con cdk-nag sin hallazgos | CcData. Desviaciones: sin rotacion de 30 dias (Fase 7); test sin Performance Insights (t4g.micro no lo admite), sin monitoreo ni export de logs. Los roles no tienen contrasena: T-047 debe asignarla desde cc/{env}/db/{rol} (migrar usa cc/{env}/db/admin). Llave y SG se importan sin modificar para evitar ciclos: los stacks siguientes deben hacer igual |
| T-041 | Crear el stack CcMessaging (colas, bus, Scheduler, SNS y SES) | 1 | completada | 2026-11-14 | pytest infra 111 ok; ruff ok; cdk-nag sin hallazgos | CcMessaging completo. Decision A aprobada por Samuel: SecurityStack agrega sentencia ServiciosDeAwsDeMensajeria (events/ses/cloudwatch, Decrypt y GenerateDataKey*, aws:SourceAccount) a la llave cc-{env}-infra; aparecera en el cdk diff de CcSecurity-test (T-044). Sin suscripciones SNS (PQ-17). SES envia correo de verificacion a samuel.lopez@honne.com al desplegar. Alarmas de DLQ en CcObservability |
| T-042 | Crear el stack CcAuth (Cognito y triggers) | 1 | completada | 2026-11-14 | pytest infra 129 ok; ruff ok; cdk-nag sin hallazgos; synth con build/lambdas real ok | CcAuth. Desviaciones: codigo de invitacion en custom:codigo_invitacion (T-036); Lambdas con alias live (Cognito invoca el alias); build/lambdas obligatorio para cdk diff/deploy (scripts/empaquetar_lambdas.py; build/ en .gitignore); pruebas usan CC_LAMBDAS_DESDE_FUENTE=1; sin cifrado KMS en logs de Lambda (CcObservability). Pendiente en T-044: sesion de cc-test vencida; verificar cuota de concurrencia de Lambda de la cuenta (reservada 5 x3 exige cuota total suficiente). Plan Essentials de Cognito tiene costo por usuario activo |
| T-043 | Crear el stack base de CcCompute (clúster, ECR y tareas `migrar` y `ops`) | 1 | completada | 2026-11-14 | pytest infra 144 ok; asignar_contrasenas 9 ok; ruff ok; cdk-nag sin hallazgos; imagen ops construida en local | CcComputeBase: cluster, repos migrar/ops, tareas migrar y ops. Decisiones: (1) migrar y ops usan cc_admin (secreto db/admin), no migrador; (2) la URL se compone al arrancar (sh -c / ops.sh); (3) ECS Exec sin registro de sesion en CloudWatch (grabaria el codigo de invitacion de T-049), auditoria en CloudTrail; (4) nuevo scripts/asignar_contrasenas.py + ops.sh: PASO NUEVO antes de T-050: ops.sh contrasenas (los roles se crean sin password); (5) T-046: construir imagenes con --platform linux/arm64 (Fargate ARM64), etiqueta 0.1.0; (6) .gitattributes fuerza LF en *.sh y Dockerfile |
| T-044 | Mostrar el cdk diff de los stacks de la Fase 1 (lectura) | 1 | completada | 2026-11-14 | cdk diff de 7 stacks (solo lectura), exit 0; cuota Lambda 1000; sin colisiones de nombres | Diff: 6 stacks nuevos (Network, Storage, Data, Messaging, Auth, ComputeBase) y 1 modificacion (llave KMS de CcSecurity: sentencia events/ses/cloudwatch). Sin borrados ni reemplazos. Costo nuevo ~24.5 USD/mes encendido (RDS 11.68+2.30, NAT 3.07+0.64+IPv4 3.65, secretos 3.20); ~0.81 USD/dia. Esperando apruebo T-045 |
| T-045 | Desplegar los stacks de la Fase 1 en cc-test | 1 | completada | 2026-11-14 | 7 stacks COMPLETE; correcciones desplegadas: NAT t4g.micro, kms:Decrypt en tareas y Lambdas, tarea migrar rev 2 (0.1.1) | Despliegues aprobados por Samuel en 4 rondas |
| T-046 | Construir y publicar la imagen de migraciones en ECR | 1 | completada | 2026-11-14 | ECR: migrar 0.1.0 (sha256:697a6015e8cf) y 0.1.1 (sha256:e3abfba44636), ops 0.1.0 (sha256:ca7dd4844c6b) | arm64 con buildx; credenciales Docker en carpeta temporal borrada tras cada subida |
| T-047 | Ejecutar las migraciones, los roles y las políticas RLS en cc-test | 1 | completada | 2026-11-14 | run-task migrar x2: exit 0 ambas; orden dashboard, campos, colaboradores, whatsapp, constancias, notificaciones, roles.sql, rls.sql, grants.sql; registros sin password ni URL | 3 defectos encontrados y corregidos: NAT sin memoria, falta kms:Decrypt, ALTER ROLE sin superusuario (roles.sql, autorizado). Idempotencia: 2a ejecucion identica y exit 0 (Alembic sin revisiones pendientes) |
| T-048 | Verificar los recursos de la Fase 1 (lectura) | 1 | completada | 2026-11-14 | scripts/verificar_f1.ps1: exit 0, 0 fallas (7 stacks, RDS, Object Lock, 20 colas, Cognito MFA, 110 recursos etiquetados) | Solo lectura |
| T-049 | Ejecutar bootstrap_admin en cc-test | 1 | completada | 2026-11-14 | Empresa 1 activa; invitacion 1 vigente, sin usar, 72 h, hash de 32 bytes, sin correo exigido; bitacora INVITACION_CREADA (SISTEMA); 0 usuarios; registro /cc/test/ops de la sesion sin eventos; CloudTrail ExecuteCommand de samuel.lopez.labs-inovacion | Samuel ejecuto ops.sh bootstrap por ECS Exec; el agente no vio el codigo. Razon social quedo "Tu Empresa SA de CV" (ejemplo de la guia). Tarea ops detenida. Plugin session-manager 1.2.896.0 instalado con winget (autorizado) |
| T-050 | Probar el registro, el MFA y el inicio de sesión con Cognito real | 1 | en_curso | 2026-11-14 |  |  |
| T-051 | Punto de control de la Fase 1 | 1 | pendiente | | | |
| T-052 | Crear el esqueleto del servicio `colaboradores` y el cliente de definiciones de campos | 2 | pendiente | | | |
| T-053 | Implementar los repositorios de colaborador y valor de campo con cifrado | 2 | pendiente | | | |
| T-054 | Implementar organizaciones, logotipo y plantas (COL-08 a COL-15) | 2 | pendiente | | | |
| T-055 | Implementar el alta de colaborador (COL-02) | 2 | pendiente | | | |
| T-056 | Implementar el detalle y la edición (COL-03 y COL-04) | 2 | pendiente | | | |
| T-057 | Implementar baja, reactivación, consentimiento y elegibilidad (COL-05 a COL-07) | 2 | pendiente | | | |
| T-058 | Implementar el listado, la búsqueda y los filtros (COL-01) | 2 | pendiente | | | |
| T-059 | Implementar las interfaces internas de colaboradores (INT-COL-01 a 05, 07 y 08) | 2 | pendiente | | | |
| T-060 | Generar la plantilla de carga de Excel (COL-16) | 2 | pendiente | | | |
| T-061 | Implementar el lector y el validador de filas de la carga | 2 | pendiente | | | |
| T-062 | Implementar el `worker-cargas` (upsert por lotes) | 2 | pendiente | | | |
| T-063 | Implementar los endpoints de cargas (COL-17 a COL-22) | 2 | pendiente | | | |
| T-064 | Probar la carga con la plantilla real del cliente y el aislamiento por empresa | 2 | pendiente | | | |
| T-065 | Punto de control de la Fase 2 | 2 | pendiente | | | |
| T-066 | Crear el servicio `campos` con listado, creación y detalle (CAM-01 a CAM-03) | 3 | pendiente | | | |
| T-067 | Implementar la actualización de campos con sus protecciones (CAM-04) | 3 | pendiente | | | |
| T-068 | Implementar la eliminación y el reordenamiento (CAM-05 y CAM-06) | 3 | pendiente | | | |
| T-069 | Implementar las opciones de campos de lista (CAM-07 a CAM-09) | 3 | pendiente | | | |
| T-070 | Implementar el catálogo sembrado y las interfaces internas de campos (INT-CAM-01 y INT-CAM-02) | 3 | pendiente | | | |
| T-071 | Agregar a `colaboradores` las consultas INT-COL-09 e INT-COL-10 | 3 | pendiente | | | |
| T-072 | Publicar `campo.actualizado`, consumirlo y reemplazar el stub de `colaboradores` | 3 | pendiente | | | |
| T-073 | Extender `bootstrap_admin.py` con la siembra de campos | 3 | pendiente | | | |
| T-074 | Probar la integración de campos dinámicos con colaboradores | 3 | pendiente | | | |
| T-075 | Punto de control de la Fase 3 | 3 | pendiente | | | |
| T-076 | Crear el servicio `constancias` con el CRUD de plantillas (CON-01 a CON-06) | 4 | pendiente | | | |
| T-077 | Definir el esquema JSON del contenido y los borradores (CON-07 y CON-08) | 4 | pendiente | | | |
| T-078 | Implementar el catálogo de variables y el resolutor (CON-15) | 4 | pendiente | | | |
| T-079 | Implementar las variables derivadas (sueldo mensual, importe en letra y fechas) | 4 | pendiente | | | |
| T-080 | Implementar la validación, la publicación y las versiones (CON-09 a CON-12) | 4 | pendiente | | | |
| T-081 | Implementar la restauración de versiones (CON-13) | 4 | pendiente | | | |
| T-082 | Implementar el renderizador de HTML, el logotipo y el QR | 4 | pendiente | | | |
| T-083 | Generar el PDF con WeasyPrint y la vista previa (CON-14) | 4 | pendiente | | | |
| T-084 | Implementar el folio y las interfaces de solicitudes (INT-CON-01 a 05) | 4 | pendiente | | | |
| T-085 | Implementar el `worker-pdf` (generación, snapshot y almacenamiento) | 4 | pendiente | | | |
| T-086 | Implementar los enlaces de un solo uso y la estrategia de entrega (CON-20 y CON-21) | 4 | pendiente | | | |
| T-087 | Implementar el detalle, la descarga y el reenvío de constancias (CON-16 a CON-18) | 4 | pendiente | | | |
| T-088 | Implementar la verificación pública (CON-19) | 4 | pendiente | | | |
| T-089 | Implementar INT-CON-06 y el trabajo de `alerta_plantilla` | 4 | pendiente | | | |
| T-090 | Probar rendimiento del PDF y concurrencia de folios | 4 | pendiente | | | |
| T-091 | Probar la seguridad del renderizado y de los enlaces | 4 | pendiente | | | |
| T-092 | Punto de control de la Fase 4 | 4 | pendiente | | | |
| T-093 | Crear el servicio `whatsapp` y el simulador de la API de Meta | 5 | pendiente | | | |
| T-094 | Implementar la Lambda `webhook-meta` | 5 | pendiente | | | |
| T-095 | Implementar la Lambda `estados-entrega` | 5 | pendiente | | | |
| T-096 | Implementar la Lambda `enviador` y `VentanaService` | 5 | pendiente | | | |
| T-097 | Implementar el bot: máquina de estados, mensajes y verificación | 5 | pendiente | | | |
| T-098 | Implementar el bot: menú y solicitud de constancia | 5 | pendiente | | | |
| T-099 | Implementar el `worker-whatsapp-entrada`, el antiabuso y el cierre por inactividad | 5 | pendiente | | | |
| T-100 | Implementar el consumidor de estados en `constancias` y los avisos a RH | 5 | pendiente | | | |
| T-101 | Implementar los indicadores, solicitudes recientes y alertas del dashboard (DSH-01 a DSH-04) | 5 | pendiente | | | |
| T-102 | Implementar el historial de constancias (DSH-11) | 5 | pendiente | | | |
| T-103 | Probar el flujo completo de solicitud de constancia con el simulador | 5 | pendiente | | | |
| T-104 | Punto de control de la Fase 5 | 5 | pendiente | | | |
| T-105 | Crear el servicio `notificaciones` y las audiencias (NOT-01 a NOT-05) | 6 | pendiente | | | |
| T-106 | Implementar `AudienciaQueryService` e INT-COL-06 en `colaboradores` (y NOT-06) | 6 | pendiente | | | |
| T-107 | Implementar el embudo y la revisión (NOT-18) | 6 | pendiente | | | |
| T-108 | Implementar las plantillas de mensaje y el cliente de Meta (NOT-07 a NOT-13) | 6 | pendiente | | | |
| T-109 | Implementar el CRUD de notificaciones, duplicar e indicadores (NOT-14 a NOT-17, NOT-21, NOT-23 y NOT-24) | 6 | pendiente | | | |
| T-110 | Implementar la confirmación, el horario y la programación (NOT-19) | 6 | pendiente | | | |
| T-111 | Implementar la Lambda `despachador` | 6 | pendiente | | | |
| T-112 | Implementar la Lambda `conciliador` | 6 | pendiente | | | |
| T-113 | Implementar los consumidores de eventos y la máquina de estados de la notificación | 6 | pendiente | | | |
| T-114 | Implementar la Lambda `respaldo-correo` | 6 | pendiente | | | |
| T-115 | Implementar reintentar, cancelar y las variables de plantilla (NOT-20, NOT-22 e INT-COL-05 ampliado) | 6 | pendiente | | | |
| T-116 | Implementar el chat de RH (WAP-01 a WAP-05) | 6 | pendiente | | | |
| T-117 | Probar el flujo completo de notificaciones con el simulador | 6 | pendiente | | | |
| T-118 | Punto de control de la Fase 6 | 6 | pendiente | | | |
| T-119 | Crear el proyecto React, el cliente de API tipado y el manejo de errores | 7 | pendiente | | | |
| T-120 | Implementar el acceso: inicio de sesión con MFA, registro y recuperación | 7 | pendiente | | | |
| T-121 | Implementar el diseño base, la navegación, el cierre por inactividad y las cabeceras de desarrollo | 7 | pendiente | | | |
| T-122 | Implementar el dashboard (`cv1_01`) | 7 | pendiente | | | |
| T-123 | Implementar el listado y el formulario de colaboradores (`cv1_02` y `cv1_03`) | 7 | pendiente | | | |
| T-124 | Implementar la configuración de campos (`cv1_04`) | 7 | pendiente | | | |
| T-125 | Implementar la carga masiva, las organizaciones y las plantas | 7 | pendiente | | | |
| T-126 | Implementar el listado de plantillas y el editor visual (`cv1_05` y `cv1_06`) | 7 | pendiente | | | |
| T-127 | Implementar la vista previa, la validación y las versiones del editor | 7 | pendiente | | | |
| T-128 | Implementar el historial de constancias y la página pública de verificación (`cv1_07`) | 7 | pendiente | | | |
| T-129 | Implementar el listado de notificaciones y las plantillas de mensaje (`cv1_08`) | 7 | pendiente | | | |
| T-130 | Implementar la nueva notificación con el embudo y el detalle de envío (`cv1_09` y `cv1_10`) | 7 | pendiente | | | |
| T-131 | Implementar el chat de RH y la administración de usuarios e invitaciones | 7 | pendiente | | | |
| T-132 | Probar localización, accesibilidad básica y contratos de la SPA | 7 | pendiente | | | |
| T-133 | Probar de extremo a extremo la SPA con Playwright contra el stack local | 7 | pendiente | | | |
| T-134 | Punto de control de la Fase 7 | 7 | pendiente | | | |
| T-135 | Crear los stacks de cómputo: servicios de ECS, ALB y reglas por ruta | 8 | pendiente | | | |
| T-136 | Crear los workers y las Lambdas de mensajería en CDK | 8 | pendiente | | | |
| T-137 | Crear el stack CcApi (API Gateway, VPC Link y autorizador JWT) | 8 | pendiente | | | |
| T-138 | Crear el stack CcEdge en us-east-1 (CloudFront, WAF y firma de descargas) | 8 | pendiente | | | |
| T-139 | Crear los stacks CcFrontend y CcObservability | 8 | pendiente | | | |
| T-140 | Crear los stacks CcBackup y CcPipeline | 8 | pendiente | | | |
| T-141 | Completar las aserciones de infraestructura y la revisión de IAM | 8 | pendiente | | | |
| T-142 | Ejecutar pruebas de carga con k6 en local | 8 | pendiente | | | |
| T-143 | Ejecutar las pruebas de seguridad | 8 | pendiente | | | |
| T-144 | Escribir los runbooks y documentar la brecha de retención y borrado a solicitud | 8 | pendiente | | | |
| T-145 | Construir y publicar las imágenes de los servicios y los paquetes de las Lambdas | 8 | pendiente | | | |
| T-146 | Mostrar el cdk diff completo de la Fase 8 (lectura) | 8 | pendiente | | | |
| T-147 | Desplegar cómputo, workers, Lambdas y API en cc-test | 8 | pendiente | | | |
| T-148 | Desplegar el borde, la SPA y la observabilidad en cc-test | 8 | pendiente | | | |
| T-149 | Ejecutar migraciones y pruebas de humo en cc-test | 8 | pendiente | | | |
| T-150 | Ejecutar las pruebas de extremo a extremo y de carga en cc-test | 8 | pendiente | | | |
| T-151 | Probar la restauración de RDS a un punto en el tiempo en cc-test | 8 | pendiente | | | |
| T-152 | Registrar resultados, ajustes y brechas | 8 | pendiente | | | |
| T-153 | Preparar la guía de limpieza de cc-test, que ejecuta Samuel a mano | 8 | pendiente | | | |
| T-154 | Punto de control de la Fase 8 y cierre del plan | 8 | pendiente | | | |
