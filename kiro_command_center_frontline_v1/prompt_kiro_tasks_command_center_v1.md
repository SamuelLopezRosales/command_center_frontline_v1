# Prompt para Kiro — Fase 3 del spec: tasks.md de Command Center v1

Copia todo el bloque de abajo (desde "## Rol" hasta el final) en el chat de Kiro, en modo spec, y adjunta o referencia los archivos de la sección "Insumos" con `#File` o `#Folder`. Esta fase solo se ejecuta después de aprobar `.kiro/specs/requirements.md` y `.kiro/specs/design.md`.

---

## Rol

Actúa como ingeniero de software senior que planea y ejecuta la implementación de un sistema en AWS con FastAPI, React, PostgreSQL y AWS CDK. Trabajas con disciplina de seguridad: nunca tocas una cuenta de AWS sin una verificación previa.

## Objetivo

Crear el archivo `.kiro/specs/tasks.md`. Es la fase 3 de spec-driven development: una lista de tareas de implementación derivada de `requirements.md` y `design.md`, ordenada por fases y con dependencias explícitas. **Esta fase solo planea.** No implementes código ni despliegues nada al crear `tasks.md`. La ejecución de cada tarea se hace después, por separado, y solo con mi aprobación.

## Insumos

| Insumo | Qué aporta |
|---|---|
| `.kiro/specs/requirements.md` | Requisitos `CC-REQ-nnn`, no funcionales `CC-NFR-nnn` y preguntas `PQ-nn`. |
| `.kiro/specs/design.md` | Arquitectura, microservicios, modelo de datos físico, stacks de CDK y matriz de trazabilidad. |
| `documentos/` y `modelo_entidad_relacion/modelo_completo.dot` | Diccionario de datos y modelo de referencia. |
| `disenos/` | Pantallas de la interfaz, para las tareas de frontend. |

## Reglas de seguridad para AWS (obligatorias)

Estas reglas aplican a todas las tareas que toquen AWS, desde la primera hasta la última. Si una regla no se puede cumplir, detente y pregúntame.

1. **Credenciales.** Nunca pidas, escribas ni guardes llaves de acceso de AWS en el código, en archivos del repositorio ni en el chat. Usa únicamente el perfil de AWS definido en la variable `AWS_PROFILE`. En esta etapa ese perfil es `cc-test`, configurado con IAM Identity Center.
2. **Sesión activa.** Antes de cualquier comando de AWS, verifica la sesión con `aws sts get-caller-identity --profile cc-test`. Si falla, o si la sesión está vencida, detente e indícame que hay que ejecutar `aws sso login --profile cc-test`. No continúes con otro perfil.
3. **Cuenta correcta.** Confirma que el número de cuenta devuelto coincide con el número de la cuenta de prueba que te indique al inicio. Si no coincide, detente.
4. **Guardia en el código de CDK.** La aplicación de CDK debe rechazar la síntesis y el despliegue si la cuenta de `CDK_DEFAULT_ACCOUNT` no está en la lista permitida de cada ambiente. La lista vive en configuración, no en el código de los stacks. Esta guardia es una tarea de la fase 0 y debe probarse antes que cualquier otro despliegue.
5. **Revisión antes de cambiar.** Antes de cada `cdk deploy` ejecuta `cdk diff` y muéstrame el resultado. No despliegues hasta que yo lo apruebe.
6. **Etiquetas obligatorias.** Todos los recursos llevan las etiquetas `proyecto=command-center`, `ambiente=<ambiente>` y `responsable=<mi nombre>`. Añádelas en el nivel de la aplicación de CDK, no recurso por recurso.
7. **Presupuesto.** Antes del primer despliegue, crea o verifica un presupuesto con alertas en la cuenta de prueba. Es una tarea explícita de la fase 0.
8. **Sin borrado sin confirmación.** No ejecutes `cdk destroy`, `aws ... delete` ni cualquier otro comando que borre recursos sin mi confirmación escrita. Antes de borrar, muestra qué stacks o recursos se afectarán.
9. **Procedimiento de limpieza.** Si un despliegue termina en una cuenta equivocada, se borra con el mismo perfil con el que se creó: `cdk destroy --all --profile <perfil>`. Después se revisa la consola por etiqueta `proyecto=command-center`. Registra cualquier recurso que no se pueda borrar, por ejemplo llaves de KMS en espera o buckets con Object Lock.
10. **Bootstrap.** La primera vez que se despliega en una cuenta y región, ejecuta `cdk bootstrap` solo después de confirmar la cuenta. Es una tarea de la fase 0.
11. **Recursos con retención.** Los recursos con protección contra borrado (RDS con protección, buckets con Object Lock, secretos con periodo de recuperación) deben tener en el ambiente de prueba una configuración que permita borrarlos. Documenta las diferencias contra producción, pero no las implementes en producción sin revisión.

## Principios de planeación

1. **Fases.** Organiza las tareas en fases con dependencias explícitas: Fase 0 (repositorio, configuración, guardia de cuenta, presupuesto, etiquetas, bootstrap, base de CDK y pipeline mínimo), Fase 1 (base de datos y migraciones), Fase 2 (servicio de colaboradores y carga masiva), Fase 3 (campos dinámicos), Fase 4 (plantillas y generación de PDF), Fase 5 (WhatsApp: verificación, conversación y estados), Fase 6 (notificaciones), Fase 7 (SPA de React), Fase 8 (pruebas de integración, carga, seguridad y despliegue a la cuenta de prueba). Ajusta el orden según el `design.md`.
2. **Tareas atómicas.** Cada tarea debe poder completarse y verificarse en una sola sesión de trabajo. Si una tarea es grande, divídela.
3. **Trazabilidad.** Cada tarea cita los `CC-REQ`, `CC-NFR` y las secciones de `design.md` que cumple. No dejes requisitos sin tareas asociadas.
4. **Archivos concretos.** Cada tarea indica los archivos o módulos que crea o modifica, según la estructura de `design.md`.
5. **Verificación.** Cada tarea incluye su criterio de terminado: prueba unitaria, de integración, aserción de CDK o verificación manual. No pases a la siguiente tarea de una fase sin que la anterior esté verificada.
6. **Paralelismo.** Marca qué tareas pueden ejecutarse en paralelo y cuáles dependen de otras.
7. **Puntos de control.** Pon un punto de control al final de cada fase. En ese punto te pido aprobación antes de continuar, y antes de cualquier despliegue a la cuenta de prueba.

## Formato de cada tarea

```
- [ ] T-nnn. Título corto en infinitivo
  - Fase: n
  - Requisitos: CC-REQ-xxx, CC-NFR-xxx
  - Diseño: design.md §n
  - Archivos: ruta/del/archivo.py
  - Depende de: T-nnn
  - Verificación: qué debe pasar para considerarla terminada
  - Requiere aprobación: sí/no (sí para cualquier comando de AWS que cree, modifique o borre recursos)
```

## Flujo de trabajo

1. **Preguntas antes de escribir.** Hazme en una sola ronda las preguntas que bloqueen la planeación, con un máximo de 5. Por ejemplo: nombre exacto de la cuenta de prueba, si el pipeline de CI/CD se implementa en la fase 0 o en la fase 8, y cuántas tareas quieres por fase.
2. **Redacción.** Escribe `tasks.md` completo, con las fases 0 a 8, las reglas de seguridad al inicio y un anexo con las dependencias entre fases.
3. **Revisión.** Verifica que cada `CC-REQ` y cada `CC-NFR` tenga al menos una tarea, que no haya dependencias circulares y que ninguna tarea de AWS omita la verificación de sesión y de cuenta.
4. **Pausa.** Entrega el documento y espera mi aprobación. No ejecutes ninguna tarea todavía.
