# Prompt para Kiro — Fase 1 del spec: requirements.md de Command Center v1

Copia todo el bloque de abajo (desde "## Rol" hasta el final) en el chat de Kiro, en modo spec, y adjunta o referencia los archivos de la sección "Insumos" con `#File` o `#Folder`.

---

## Rol

Actúa como analista de requerimientos senior y arquitecto de software, con experiencia en sistemas multi-tenant de recursos humanos, cumplimiento de datos personales en México (LFPDPPP) y arquitecturas serverless y de microservicios en AWS.

## Objetivo

Crear el archivo `.kiro/specs/requirements.md`. Es la fase 1 de spec-driven development: los requisitos deben quedar aprobados antes de escribir `design.md` y `tasks.md`. **No generes diseño técnico ni tareas en esta fase.** Si necesitas una decisión técnica para escribir un requisito, márcala como [POR CONFIRMAR].

## Contexto del producto

Command Center v1 es un sistema web para que Recursos Humanos (RH) administre la información de los colaboradores de las empresas que atiende. Son cuatro módulos:

1. **Acceso y dashboard.** Inicio de sesión con Cognito y MFA, resumen de la operación y bitácora de auditoría.
2. **Colaboradores.** Expedientes con campos fijos y campos dinámicos configurables, carga masiva desde Excel y catálogos de organizaciones y plantas.
3. **Constancias.** Editor visual de plantillas con variables, versiones inmutables, generación de PDF con folio y solicitud de constancias por WhatsApp.
4. **Notificaciones.** Mensajes a colaboradores por WhatsApp, dirigidos por criterios, individualmente o a grupos guardados, con revisión de exclusiones, programación y seguimiento de entrega.

Actores:
- **Usuario RH:** personal de RH de la empresa. Opera el panel web.
- **Colaborador:** persona registrada. Interactúa solo por WhatsApp; no tiene acceso web.
- **Tercero:** cualquier persona que verifica una constancia con su código QR. No requiere cuenta.
- **Sistema:** procesos automáticos (workers, enviador, programador de envíos).
- **Meta WhatsApp Cloud API:** plataforma externa de mensajería.

## Insumos (fuentes de verdad)

Lee estos archivos completos antes de escribir. Si hay contradicciones entre ellos, regístralas en la sección de preguntas abiertas y no elijas en silencio.

| Insumo | Qué aporta |
|---|---|
| `documentos/01_analisis_requerimientos.md` | Módulos, requisitos funcionales RF-01 a RF-42, requisitos no funcionales RNF-01 a RNF-11, supuestos, fuera de alcance y propuestas de las dudas abiertas (sección 7). |
| `documentos/02_modelo_datos.md` | Diccionario de datos, reglas de integridad y validación de la carga. |
| `documentos/03_flujo_whatsapp.md` | Proceso de solicitud de constancia por WhatsApp, estados y casos de error. |
| `documentos/04_plantilla_carga_colaboradores.md` | Análisis de la plantilla de carga, validaciones y decisiones confirmadas (sección 8). |
| `documentos/05_plantillas_constancias.md` | Variables que usan las plantillas de constancia y correcciones propuestas. |
| `casos_de_uso/casos_de_uso_command_center_v1.docx` | 29 casos de uso (UC-01 a UC-29) con actor, precondiciones, flujo principal, alternos, postcondiciones y reglas. Es la base de los criterios de aceptación. |
| `modelo_entidad_relacion/modelo_completo.dot` y `vistas/*.dot` | Modelo entidad-relación de PostgreSQL (20 entidades). El `.dot` es la fuente de verdad del modelo. |
| `disenos/svg/cv1_01` a `cv1_10` y `disenos/png/01_login.png` | Pantallas de la interfaz. `01_login.png` es la pantalla de inicio de sesión (ver la nota de la sección de pantallas). |
| `arquitectura_aws/arquitectura_command_center_v1.png` y `generar_arquitectura.py` | Servicios de AWS propuestos y su disposición. |
| `flujos/flujo_whatsapp.dot` | Diagrama del flujo de solicitud de constancia. |
| `plantillas_constancias/*.docx` | Tres plantillas de referencia (laboral, guardería y consulado). |
| `plantilla_carga/*.xlsx` | Plantilla de carga real del cliente (versión 1.3). Úsala como referencia de columnas y validaciones. |

**No uses** como fuente: `mockups/` y `prototipo_admin/`, `prototipo_empresa_rh/` (versión anterior con certificados), ni ningún `requirements.md` o prompt de otros proyectos.

## Decisiones ya confirmadas (no las vuelvas a preguntar)

1. Los **once campos fijos** del colaborador son: número de empleado, nombres, apellido paterno, apellido materno, celular de WhatsApp, organización, planta, fecha de ingreso, puesto, tipo de empleado y estatus. Son obligatorios para todos los casos de uso. Ver la pregunta 1 de la sección de preguntas, porque la plantilla del cliente marca diez como obligatorios.
2. Los campos dinámicos (área, departamento, turno, ruta, sueldo, periodicidad, registro patronal, NSS, RFC, CURP, correo y los que RH agregue) se configuran en una tabla de campos. Al crear una empresa se cargan los sugeridos, que RH puede activar o desactivar, pero no borrar.
3. Cada colaborador pertenece a una **organización** (razón social) con su RFC, registro patronal, domicilio, ciudad y firmante de constancias.
4. La llave de la carga masiva es el **número de empleado**. La carga actualiza por esa llave y no modifica ni da de baja a quien no aparece en el archivo.
5. **Sueldo, NSS, CURP y RFC** son datos sensibles: se capturan desde v1, se cifran y solo los ven usuarios con permiso.
6. Las **versiones de plantilla** son inmutables. El contenido vive en S3, y la base de datos guarda la ruta y el hash. Las constancias emitidas guardan un snapshot de los datos usados.
7. Los **PDF de constancia** se guardan en S3 con Object Lock. La entrega por WhatsApp es un enlace de descarga de un solo uso que caduca a las 24 horas (propuesta del análisis, pendiente de confirmar en la pregunta 4).
8. La autenticación del personal de RH es con **Cognito** con MFA. La base de datos no guarda contraseñas; guarda el identificador de Cognito.
9. La **bitácora** registra altas, cambios, bajas, consultas de datos sensibles, generación y entrega de constancias, y envíos de notificaciones con su audiencia exacta.
10. Un colaborador con estatus **BAJA** o sin consentimiento vigente no recibe constancias ni notificaciones.
11. Ningún mensaje sale sin consentimiento vigente. Los mensajes iniciados por la empresa solo usan plantillas aprobadas por Meta. El texto libre solo se permite dentro de la ventana de 24 horas que abre el colaborador.
12. Los envíos de notificaciones solo se programan o se ejecutan dentro de un horario permitido (propuesta: 08:00 a 20:00, hora de la empresa). Un envío inmediato fuera de ese horario requiere confirmación explícita de RH.

## Arquitectura de referencia (para restricciones no funcionales, no para diseño)

- **Backend:** microservicios en **FastAPI** (Python). Servicios: Colaboradores (incluye carga masiva), Campos dinámicos, Constancias y plantillas, Notificaciones y audiencias, Dashboard e historial, y WhatsApp (verificación y chat). Cada servicio es dueño de sus tablas.
- **Frontend:** SPA en **React**, servida desde S3 con CloudFront.
- **Acceso:** Route 53, CloudFront con AWS WAF, API Gateway, Application Load Balancer y ECS Fargate.
- **Datos:** **PostgreSQL en Amazon RDS**, Multi-AZ, como única base de datos operacional. S3 para plantillas, PDF de constancias (con Object Lock), cargas de Excel temporales y frontend.
- **Procesos asíncronos:** colas SQS para generación de PDF, cargas masivas y mensajes de WhatsApp (entrada y salida). EventBridge para envíos programados. Funciones Lambda para el webhook de Meta, el enviador y los estados de entrega (Python).
- **Mensajería:** Meta WhatsApp Cloud API. SNS para alertas a RH y SES para correo de respaldo.
- **Seguridad y operación:** Cognito, KMS para datos sensibles, Secrets Manager para credenciales de Meta, IAM de mínimo privilegio, CloudWatch, CloudTrail y Systems Manager.
- **Pendientes de arquitectura** (marca como [POR CONFIRMAR]): región principal, región de recuperación y objetivos de RTO y RPO, herramienta de infraestructura como código, disponibilidad objetivo y presupuesto de costo.

## Reglas para escribir el documento

1. Usa IDs con el prefijo `CC-`: `CC-REQ-001` para requisitos funcionales, `CC-NFR-001` para no funcionales y `CC-ASM-001` para supuestos. Cada requisito cita su origen: UC-xx, RF-xx o RNF-xx del análisis, o la sección del documento de origen.
2. Escribe los criterios de aceptación en **EARS**: `CUANDO [disparador] EL SISTEMA DEBERÁ [respuesta]`. Usa también la forma de historia de usuario para cada módulo: "Como [actor], quiero [acción], para [beneficio]".
3. Un requisito pertenece a un solo módulo. Si afecta a varios, va en la sección transversal y se referencia desde cada módulo.
4. **No inventes datos.** Si un valor no está en los insumos, escribe [POR CONFIRMAR] y regístralo en la sección de preguntas.
5. Al final incluye una **matriz de trazabilidad** con las columnas: CC-REQ, caso de uso (UC), requisito del análisis (RF), pantalla (cv1_xx), tabla o entidad del modelo.
6. Incluye una sección **Fuera de alcance** con lo que está excluido de v1: expedientes con nóminas, actas y horarios; ausencias y vacaciones; políticas y FAQ; NOM-035; certificados; administración de múltiples empresas (si se confirma como fuera de alcance); y cualquier función que no esté en los insumos.
7. Redacta en español.

## Flujo de trabajo

1. **Preguntas antes de redactar.** Revisa los insumos y hazme en **una sola ronda** las preguntas bloqueantes, con un máximo de 10. Agrúpalas por módulo. Las que no bloquean la redacción quedan como [POR CONFIRMAR] en el documento.
2. **Redacción.** Escribe el documento completo en un solo `requirements.md`, siguiendo la estructura de abajo.
3. **Revisión de consistencia.** Antes de entregar, verifica que los IDs no se repitan, que cada UC tenga al menos un requisito, que los nombres de campos y tablas coincidan con el modelo, y que las cifras (límites, plazos y números de reintentos) coincidan con los insumos.
4. **Pausa.** Entrega el documento y espera mi aprobación antes de crear `design.md`.

## Estructura del requirements.md

0. Contexto y glosario.
1. Alcance: dentro, fuera y supuestos.
2. Actores.
3. Requisitos funcionales por módulo: Acceso y dashboard, Colaboradores, Constancias y Notificaciones. Cada módulo incluye su historia de usuario, sus requisitos y sus criterios EARS.
4. Requisitos transversales: seguridad, datos sensibles, bitácora, cumplimiento y auditoría.
5. Requisitos no funcionales: rendimiento, capacidad, disponibilidad, recuperación, observabilidad, costo y mantenibilidad. Donde no haya valor, [POR CONFIRMAR].
6. Interfaces de usuario: referencia a las pantallas `cv1_01` a `cv1_10` y `01_login` y los criterios de comportamiento de cada una (por ejemplo, el embudo de exclusiones en la pantalla de nueva notificación). Para `01_login`: el diseño muestra correo, contraseña, botón de iniciar sesión y enlace de recuperación, pero **no tiene el paso de código MFA** que exige UC-01. El requisito de inicio de sesión debe incluir ese paso y marcar la diferencia con el diseño como [POR CONFIRMAR].
7. Reglas de negocio consolidadas.
8. Preguntas abiertas.
9. Matriz de trazabilidad.

## Preguntas que debes considerar (incluye las que sigan abiertas al escribir)

1. **Tipo de empleado.** La lista aprobada tiene once campos fijos, pero la plantilla del cliente solo marca diez como obligatorios; tipo de empleado es opcional en la plantilla. ¿Es obligatorio en el sistema o campo opcional?
2. **Volumen de carga.** La plantilla acepta hasta 2,000 filas por archivo, y el requisito de capacidad es de 10,000 colaboradores por empresa. ¿Se suben varios archivos o se aumenta el límite?
3. **Verificación del colaborador por WhatsApp.** Propuesta: código de seis dígitos y los últimos cuatro dígitos del NSS, o la fecha de ingreso si la empresa no captura NSS. ¿Se confirma?
4. **Entrega del PDF.** Propuesta: enlace de descarga de un solo uso, válido 24 horas. ¿Se confirma, o se adjunta el archivo?
5. **Código QR de verificación pública.** Propuesta: sí, con nombre, folio, fecha y estatus, sin datos sensibles. ¿Se confirma?
6. **Factores de sueldo mensual.** Propuesta: semanal × 52/12, catorcenal × 26/12, quincenal × 2 y mensual × 1. Debe validarlo contabilidad o RH. ¿Se confirma o se muestra el sueldo con su periodicidad?
7. **Horario de envíos.** Propuesta: 08:00 a 20:00 en la zona horaria de la empresa. ¿Se confirma?
8. **Una empresa o varias.** Propuesta: v1 opera para una empresa por instancia, con `empresa_id` en todas las tablas. ¿Se confirma?
9. **Alta de usuarios RH.** No hay caso de uso para crear y desactivar usuarios de RH. ¿Quién los da de alta (el sistema o invitación por correo), y cómo se recupera la contraseña?
10. **Respaldo por correo.** Solo aplica a colaboradores con correo registrado, y ese campo es condicional. ¿Debe ser obligatorio para usar el respaldo?
11. **Plantillas de WhatsApp.** Las plantillas deben aprobarlas Meta. ¿Quién las crea y cuánto tarda la aprobación? ¿Hay un catálogo inicial?
12. **Aviso de privacidad.** ¿Qué texto muestra el bot antes de pedir datos, y lo valida el área jurídica?
13. **Retención y borrado.** No hay política de retención de datos personales ni procedimiento de borrado a solicitud del titular. ¿Cuál es el plazo y quién lo atiende?
14. **Alcance de WhatsApp.** ¿Ya existe la cuenta de WhatsApp Business y el número para la primera entrega, o se entrega primero con un simulador?
15. **Recuperación y objetivos.** ¿Cuál es el RTO y el RPO aceptables, la región de recuperación y la disponibilidad objetivo?

Si una pregunta ya tiene una propuesta en los insumos (por ejemplo en `documentos/01_analisis_requerimientos.md`, sección 7), usa esa propuesta marcada como [POR CONFIRMAR] y regístrala aquí, pero no la preguntes otra vez.
