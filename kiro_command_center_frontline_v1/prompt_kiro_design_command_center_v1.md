# Prompt para Kiro — Fase 2 del spec: design.md de Command Center v1

Copia todo el bloque de abajo (desde "## Rol" hasta el final) en el chat de Kiro, en modo spec, y adjunta o referencia los archivos de la sección "Insumos" con `#File` o `#Folder`. Esta fase solo se ejecuta después de aprobar `.kiro/specs/requirements.md`.

---

## Rol

Actúa como arquitecto de software senior con experiencia en sistemas de recursos humanos, microservicios con FastAPI, arquitecturas serverless en AWS, cumplimiento de datos personales en México (LFPDPPP) e infraestructura como código con AWS CDK.

## Objetivo

Crear el archivo `.kiro/specs/design.md`. Es la fase 2 de spec-driven development. El diseño deriva de `.kiro/specs/requirements.md` y debe quedar aprobado antes de crear `tasks.md`. **No generes tareas de implementación ni código de producción en esta fase.** Puedes incluir fragmentos cortos que ilustren una interfaz, un esquema o un stack de CDK, pero sin implementar nada.

## Fuente de verdad y precedencia

Cuando dos fuentes se contradigan, sigue este orden y registra la contradicción en la sección de supuestos y preguntas abiertas:

1. `.kiro/specs/requirements.md`. Es la fuente principal. Sus decisiones y sus preguntas resueltas (Rondas P1 a P7) no se reabren.
2. `documentos/` (análisis, modelo de datos, flujo de WhatsApp, plantilla de carga y plantillas de constancias).
3. `modelo_entidad_relacion/modelo_completo.dot` (fuente del modelo de datos) y `modelo_entidad_relacion/vistas/`.
4. `arquitectura_aws/arquitectura_command_center_v1.png` y `generar_arquitectura.py`.
5. `disenos/` (pantallas `cv1_01` a `cv1_10` y `01_login.png`). Son la referencia visual; no definen comportamiento por sí solos.

## Insumos

| Insumo | Qué aporta al diseño |
|---|---|
| `.kiro/specs/requirements.md` | Requisitos `CC-REQ-nnn`, no funcionales `CC-NFR-nnn`, supuestos `CC-ASM-nnn`, preguntas `PQ-nn` y matriz de trazabilidad. |
| `documentos/02_modelo_datos.md` | Diccionario de datos, reglas de integridad y validación de la carga. |
| `documentos/03_flujo_whatsapp.md` | Estados de la solicitud y de la conversación, y casos de error. |
| `documentos/04_plantilla_carga_colaboradores.md` | Validaciones de la carga masiva y decisiones confirmadas. |
| `documentos/05_plantillas_constancias.md` | Variables de las plantillas, cálculo de sueldo mensual y correcciones. |
| `casos_de_uso/casos_de_uso_command_center_v1.docx` | Flujos principales y alternos de UC-01 a UC-29. |
| `modelo_entidad_relacion/modelo_completo.dot` | 20 entidades, llaves, relaciones y atributos del modelo PostgreSQL. |
| `arquitectura_aws/` | Servicios y disposición de la arquitectura de referencia. |
| `flujos/flujo_whatsapp.dot` | Diagrama del flujo de solicitud de constancia. |
| `plantillas_constancias/*.docx` | Ejemplos de plantillas con las variables a resolver. |
| `plantilla_carga/*.xlsx` | Columnas reales de la carga masiva del cliente. |

**No uses** `mockups/`, `prototipo_admin/`, `prototipo_empresa_rh/` ni los `requirements.md` o prompts de otros proyectos (en particular Expo Tu Casa, con P1 y P2).

## Decisiones ya confirmadas (no las reabras)

**De las rondas de requisitos:**
- P1: el inicio de sesión incluye un formulario de registro de usuarios RH que crea la cuenta en Cognito.
- P2: en v1 existe un solo rol, RH. Todos los usuarios RH tienen los mismos permisos, incluida la vista de datos sensibles (CC-ASM-008). El modelo debe permitir agregar roles después (CC-NFR-017).
- P3: tipo de empleado es obligatorio.
- P4: los colaboradores cargados por Excel quedan sin consentimiento.
- P5: RH no genera constancias directamente en v1.
- P6: los borradores de plantilla entran en v1, y "Restaurar" crea una versión nueva.
- P7: la cuenta de WhatsApp Business ya existe; el procedimiento de vinculación se define después.

**De esta fase de diseño (decisiones del cliente):**
- La infraestructura se define con **AWS CDK**. CC-NFR-013 todavía dice "por confirmar"; trata CDK como decidido y registra que ese requisito debe actualizarse.
- La arquitectura de servicios es la de `arquitectura_command_center_v1.png`: microservicios en **FastAPI**; SPA en **React**; PostgreSQL en **RDS** como única base operacional; S3, SQS, EventBridge, Lambda (en Python), SNS, SES, Cognito, KMS, Secrets Manager, WAF, CloudWatch, CloudTrail y Systems Manager.
- La entrega de constancias por WhatsApp es un enlace de un solo uso (CC-ASM-009). Si el requisito cambia, el diseño debe permitir cambiarlo sin rehacer los componentes.

## Stack y restricciones

- **Backend:** FastAPI en Python 3.12, con microservicios desplegados en ECS Fargate detrás de un ALB. Servicios: Colaboradores (incluye la carga masiva), Campos dinámicos, Constancias (plantillas, versiones y generación de PDF), Notificaciones (audiencias, embudo, envíos y respaldo por correo), Dashboard e historial, y WhatsApp (verificación y chat).
- **Funciones Lambda** en Python 3.12: webhook de Meta, enviador de mensajes y servicio de estados de entrega.
- **Frontend:** SPA en React, servida desde S3 con CloudFront y AWS WAF.
- **Acceso:** Route 53, API Gateway y ALB. Las rutas internas del backend se exponen solo a través de API Gateway.
- **Datos:** PostgreSQL en Amazon RDS, Multi-AZ. Es la única base de datos operacional. Cada servicio es dueño de sus tablas.
- **Archivos:** S3 para el frontend, el contenido de las plantillas (JSON), los logotipos, los PDF de constancias (con Object Lock) y las cargas de Excel (temporales).
- **Asíncrono:** colas SQS para generación de PDF, cargas masivas y mensajes de WhatsApp (entrada y salida, con colas de mensajes fallidos). EventBridge para los envíos programados.
- **Mensajería:** Meta WhatsApp Cloud API. SNS para alertas a RH y SES para el correo de respaldo.
- **Seguridad:** Cognito con MFA, KMS, Secrets Manager, IAM de mínimo privilegio y TLS.
- **Operación:** CloudWatch, CloudTrail y Systems Manager.
- **Infraestructura:** AWS CDK. Trata el lenguaje del CDK como una propuesta: Python, por consistencia con el backend. Regístrala en supuestos para su confirmación.
- **Pendientes (marca como [POR CONFIRMAR]):** región principal y de recuperación, RTO y RPO (PQ-15), CI/CD (propuesta: CodePipeline y CodeBuild), herramientas de pruebas de la SPA, y la forma de organizar el código (monorepo o repositorios separados; justifica tu propuesta).

## Estructura obligatoria del design.md

Numera las secciones tal como aparecen abajo. Cada decisión cita el ID de requisito que la origina (`CC-REQ`, `CC-NFR`, `CC-ASM`, `PQ` o la Ronda).

### 0. Visión general
- Resumen de la arquitectura lógica a partir de los requisitos.
- Lista de las interfaces: endpoints REST por microservicio, webhook de Meta y las funciones Lambda. Para cada una: método, ruta, códigos de estado y requisito que la origina.
- Diagrama Mermaid de componentes y de flujo de datos.
- Diagramas de secuencia Mermaid de dos flujos: (a) solicitud de constancia por WhatsApp (UC-14, UC-15, UC-16) y (b) envío programado de notificación (UC-23, UC-24, UC-25).

### 1. Estructura del código
- Árbol de carpetas propuesto, con el código de cada servicio, las Lambdas, la infraestructura en CDK, la SPA, las migraciones, el esquema compartido de contratos y las pruebas.
- Para cada paquete: responsabilidades y clases o módulos principales.
- Decisión de monorepo o repositorios separados, con justificación.

### 2. Modelo de datos físico (PostgreSQL)
- Traduce `modelo_completo.dot` a tablas concretas: tipos de dato, llaves primarias y foráneas, restricciones únicas (número de empleado por empresa, hash de celular por empresa, folio por empresa, nombre de plantilla, número de versión por plantilla) y restricciones `CHECK` para los valores de estado y de enumeración.
- Índices para los patrones de acceso de los casos de uso (listados con filtros, búsqueda por nombre o número, consulta de bitácora por fecha, cola de mensajes pendientes).
- Uso de JSONB (criterios de audiencia, snapshot de datos de constancia, contenido de plantilla si se guarda en la base) y su justificación.
- Propiedad de tablas por servicio, incluido el esquema de PostgreSQL por servicio si lo propones.
- Migraciones con una herramienta concreta (por ejemplo Alembic) y estrategia para ejecutarlas en cada despliegue.
- **Brechas del modelo:** el `.dot` no cubre algunos puntos de la pregunta PQ-14 (fecha de baja, cancelación de constancias, cargas y notificaciones, estado inicial de campos sugeridos, borradores, chat, motivo de rechazo, detalle y audiencia en la bitácora, fecha de consentimiento). Propón el cambio mínimo para cada uno y márcalo como cambio al modelo.
- Restricciones de la bitácora: inmutabilidad (CC-REQ-155) y campos de detalle y audiencia (PQ-14).

### 3. Diseño de los microservicios FastAPI
- Un microservicio por módulo de la arquitectura. Para cada uno: responsabilidades, dueño de tablas y capas (routers, servicios de dominio, repositorios).
- Tabla de endpoints por servicio: método, ruta, esquema de request, esquema de response, códigos de estado, reglas de negocio que aplica (CC-REQ) y autenticación.
- Cómo se comunican los servicios: llamadas síncronas (cuando haga falta), eventos asíncronos por SQS o EventBridge, y la regla para evitar acceso directo entre tablas de distintos servicios.

### 4. Funciones Lambda y workers
- Por cada función y cada worker: disparador, evento de entrada, salida, runtime, memoria, timeout, concurrencia reservada, política de reintentos, cola de mensajes fallidos y acción de observabilidad.
- Webhook de Meta: validación de firma (CC-REQ-158), respuesta rápida y procesamiento asíncrono.
- Enviador: procesa destinatarios por lotes, aplica la regla de consentimiento (CC-REQ-157) y la ventana de 24 horas.
- Servicio de estados de entrega y lectura.
- Worker de PDF y worker de cargas masivas: reintentos, idempotencia y procesamiento parcial de lotes.
- Programador de envíos con EventBridge y validación de horario (CC-ASM-010).
- Considera el límite de conexiones de PostgreSQL desde Lambda y propón una solución (por ejemplo RDS Proxy).

### 5. Motor de constancias
- Resolución de variables a partir de `contenido_json` y de los datos del colaborador, incluidas las variables derivadas (sueldo mensual, sueldo en letra y fechas en texto) y la regla de factores de periodicidad (PQ-18).
- Generación de PDF: librería propuesta, plantilla de render, logotipo, código QR y compatibilidad con tamaño carta.
- Folio: formato `CG-AAAA-NNNN` (PQ-16), con generación segura bajo concurrencia.
- Hash del archivo, almacenamiento en S3 con Object Lock y snapshot de datos.
- Qué pasa si una variable falta o un dato obligatorio está vacío (requisitos de la sección 3.3 del requirements.md).

### 6. Motor de notificaciones
- Evaluación de audiencias: traducción de los criterios (con `codigo_interno` y operadores Y/O) a consultas parametrizadas, y cálculo del embudo de exclusiones.
- Máquina de estados de la notificación y de cada destinatario.
- Programación de envíos, validación del horario de 08:00 a 20:00 y confirmación explícita fuera de horario (CC-ASM-010).
- Respaldo por correo con SES tras 24 horas sin entrega (CC-REQ-110).
- Reintentos hasta dos veces, con la diferencia de PQ-21 documentada.

### 7. Flujo de WhatsApp: verificación y conversación
- Máquina de estados de la conversación: VERIFICANDO, ACTIVA, BLOQUEADA y CERRADA.
- Código de verificación de seis dígitos, caducidad de 10 minutos, límite de tres intentos y almacenamiento seguro del código (solo hash).
- Dato adicional de verificación: NSS (últimos cuatro dígitos) o fecha de ingreso en dd/mm si no hay NSS (PQ-05).
- Seguimiento de la ventana de 24 horas y decisión sobre texto libre o plantilla.
- Mensajes de error al colaborador por cada caso (tabla de `03_flujo_whatsapp.md`).
- Adaptación a Meta: decide cómo se valida la firma y cómo se reenvían las plantillas fuera de la ventana. Marca como [POR CONFIRMAR] lo que dependa de la vinculación pendiente (PQ-07).

### 8. Capa de acceso a datos
- Mapeo de cada operación de negocio a su consulta (por ejemplo `INSERT ... ON CONFLICT` para la carga masiva, consultas con `FOR UPDATE` para el folio o las versiones, y consultas con índices para listados).
- Transacciones y control de concurrencia en las versiones de plantilla y en los contadores de envío.
- Cifrado de campos sensibles: envelope encryption con KMS y clave de datos por campo o por registro. Define qué columnas se cifran a nivel de aplicación y cuáles dependen del cifrado en reposo de RDS.
- Búsqueda por celular con `celular_hash` y la llave HMAC en Secrets Manager (la llave no se guarda en la base).

### 9. Estrategia de manejo de errores
- Jerarquía de excepciones de dominio por microservicio.
- Tabla de excepciones con: código HTTP, código de error del cuerpo de respuesta, política de reintento, acción de observabilidad (log, métrica o alarma) y requisito que la origina.
- Idempotencia de operaciones de escritura y de consumo de colas.
- Regla de no incluir datos personales en errores (CC-REQ-162).

### 10. Validación de entrada
- Reglas por campo a partir de los requisitos: celular de 10 dígitos, RFC de 13 o 12 o 13 (PQ-13), CURP de 18, NSS de 11, fecha dd/mm/aaaa, estatus ACTIVO o BAJA, tipo de empleado obligatorio (P3), sueldo y periodicidad juntos, validación de `formato_validacion` de los campos dinámicos.
- Enfoque concreto (modelos Pydantic por endpoint) y cómo se convierten los fallos en respuestas con detalle por campo.
- Validación de la carga masiva: mismas reglas en el servidor que en la plantilla de Excel, y reporte de errores por fila.

### 11. Seguridad y autorización
- Autenticación de cada interfaz: API Gateway con autorizador de Cognito o validación del JWT en FastAPI. Decide y justifica.
- Inicio de sesión con MFA, flujo de registro de usuarios RH (PQ-10) y recuperación de contraseña.
- Protección del webhook de Meta (CC-REQ-158) y de los endpoints de descarga por URL firmada de 24 horas.
- WAF y reglas de limitación de tasa, TLS, CORS y encabezados de seguridad de la SPA.
- Política de datos personales en logs (CC-REQ-162) y tratamiento del identificador del colaborador.
- Preparación para roles futuros sin implementarlos (CC-NFR-017, CC-REQ-153).

### 12. Roles de IAM
- Una política de mínimo privilegio por función Lambda, por tarea de ECS y por servicio de CDK.
- Lista de acciones permitidas y los ARN a los que se limitan: tablas, colas, buckets, claves KMS, secretos, reglas de EventBridge, identidades de SES y recursos de Cognito.

### 13. Infraestructura en CDK
- Propón los stacks y sus dependencias. Como referencia, considera stacks de red, datos, almacenamiento, mensajería, autenticación, cómputo, API, borde (CloudFront, WAF, Route 53 y certificados), frontend, observabilidad y pipeline de CI/CD.
- **Restricción importante:** los recursos de CloudFront y WAF deben crearse en **us-east-1**, y el certificado de ACM para CloudFront también. Refleja esta restricción en la división de stacks.
- Para cada recurso: configuración clave (memoria, timeout, concurrencia, retención de logs, cifrado, PITR, Object Lock, Multi-AZ, TTL de las colas) y el requisito que lo exige.
- Parámetros por ambiente (desarrollo, pruebas, producción) con CDK context o parámetros de SSM.
- Cómo se cablea cada interfaz con su cómputo y su autenticación.
- Qué se despliega una sola vez y qué se actualiza con cada versión.

### 14. Despliegue y operación
- Estrategia de ambientes, promoción entre ambientes y aprobaciones.
- CI/CD: pipeline con CodePipeline y CodeBuild (propuesta), pruebas antes del despliegue, migraciones de base de datos y rollback.
- Estrategia de despliegue de ECS (propón una y márcala como [POR CONFIRMAR]).
- Respaldos: PITR de RDS y, si se propone, AWS Backup. Restauración y prueba de restauración.
- Runbooks para las alertas más críticas.

### 15. Aspectos no funcionales
- Logging estructurado con identificadores de correlación (folio, identificador de notificación, identificador de conversación) y reglas de qué no se registra.
- Métricas, alarmas y dashboards. Los umbrales de alarma son [POR CONFIRMAR] (CC-NFR-010, PQ-20).
- Rendimiento: el objetivo de latencia de los listados y de la carga no está definido (CC-NFR-002). Propón la estrategia y deja el valor como [POR CONFIRMAR]. Incluye cómo se evitan cold starts en las Lambdas del webhook.
- Capacidad: dimensionamiento para 10,000 colaboradores por empresa, 500 constancias al mes y 2,000 filas por carga (CC-NFR-003 y CC-NFR-004).
- Continuidad: RPO y RTO según PQ-15 y CC-NFR-006. Describe el diseño de recuperación según lo que se confirme.
- Costo: estimación de los componentes principales y qué parte depende de las conversaciones de WhatsApp (CC-NFR-011).

### 16. Estrategia de pruebas
- Pruebas unitarias de dominio y de servicios.
- Pruebas de integración de los endpoints con PostgreSQL en contenedor.
- Pruebas de contrato (OpenAPI) entre la SPA y los microservicios.
- Pruebas de las Lambdas con eventos simulados de SQS, EventBridge y del webhook de Meta.
- Pruebas de infraestructura con aserciones de CDK (por ejemplo cifrado, Multi-AZ y Object Lock).
- Pruebas de extremo a extremo de la SPA en los flujos de los casos de uso.
- Pruebas de carga y seguridad.
- **Matriz de trazabilidad:** cada `CC-REQ` y cada `CC-NFR` debe enlazarse con el componente que lo cumple y con la prueba que lo valida.

### 17. Supuestos y preguntas abiertas
- Supuestos que no estén en los requisitos (por ejemplo lenguaje del CDK, estructura del repositorio, herramienta de migraciones, librería de PDF).
- **Preguntas bloqueantes** (máximo 10, en una sola ronda, al inicio de la redacción): se detallan en la sección de preguntas.
- Preguntas no bloqueantes: regístralas con su PQ de origen.

### 18. Plan de implementación
- No escribas `tasks.md` todavía. Solo enumera las fases de implementación propuestas (por ejemplo: base de CDK y datos; servicio de colaboradores; campos; carga; plantillas y PDF; WhatsApp; notificaciones; SPA; pruebas de carga y despliegue) y la dependencia entre ellas. Esto servirá de entrada para `tasks.md`.

## Reglas para escribir el documento

1. **No inventes.** Si algo no está en los insumos, decide solo cuando sea una decisión de diseño y márcala como propuesta. Si requiere decisión del cliente, márcala como [POR CONFIRMAR] con su PQ.
2. **Trazabilidad:** cada decisión cita su `CC-REQ`, `CC-NFR`, `CC-ASM`, `PQ` o Ronda.
3. **Un componente pertenece a un solo microservicio.** Si lo usan varios, va en una sección transversal y se referencia.
4. **Tablas para mapeos** (interfaz → cómputo, operación → consulta, excepción → código HTTP) y **diagramas Mermaid** para flujos.
5. **No cambies nombres de requisitos ni de campos** del modelo, salvo que propongas un cambio explícito en la sección 2.
6. Redacta en español.

## Flujo de trabajo

1. **Preguntas antes de redactar.** Revisa los insumos y hazme en **una sola ronda** las preguntas bloqueantes, con un máximo de 10. Propón, para cada una, una respuesta por defecto y di qué parte del diseño depende de ella. Estas son las que deben quedar resueltas antes de escribir el diseño de datos y de seguridad:
   - Número de empleado y reglas de unicidad por empresa: confirma que la llave de carga es única por empresa.
   - Mecanismo que autoriza el registro de usuarios RH (PQ-10): código de invitación, dominio de correo o aprobación.
   - Estructura de servicios y base de datos: ¿un solo esquema con tablas agrupadas por servicio, o un esquema por servicio?
   - Mecanismo de programación de envíos: EventBridge Scheduler o un worker que consulte la base.
   - Formato de folio y si reinicia por año (PQ-16).
   - Librería o motor de render de PDF.
   - Forma de organizar el código: monorepo o repositorios separados.
   - Lenguaje del CDK (propuesta: Python).
   - Región principal, región de recuperación, RTO y RPO (PQ-15).
   - Entrega del PDF por enlace de un solo uso o adjunto (PQ-03).
2. **Redacción en un solo documento.** Escribe el `design.md` completo siguiendo la estructura de las secciones 0 a 18. Como no hay subagentes en este flujo, redacta en secuencia: primero la visión general, después el modelo de datos y los servicios, y al final la infraestructura y las pruebas.
3. **Revisión de cobertura.** Antes de entregar, verifica que cada `CC-REQ` y cada `CC-NFR` esté cubierto por al menos un componente de la sección 3 a 16. Reporta cualquier requisito sin cobertura. Verifica también que los nombres de tablas y campos coincidan con `modelo_completo.dot`, y que las cifras (límites, plazos, umbrales y reintentos) coincidan con los requisitos.
4. **Pausa.** Entrega el documento y espera mi aprobación antes de crear `tasks.md`.
