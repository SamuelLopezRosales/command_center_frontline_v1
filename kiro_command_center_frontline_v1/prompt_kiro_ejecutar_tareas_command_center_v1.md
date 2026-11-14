# Prompt para Kiro — Ejecución de las tareas de Command Center v1

Copia todo el bloque de abajo (desde "## Rol" hasta el final) en el chat de Kiro, con `.kiro/specs/requirements.md`, `.kiro/specs/design.md` y `.kiro/specs/tasks.md` disponibles en el espacio de trabajo. Úsalo para ejecutar las tareas por primera vez y después cada vez que retomes el trabajo. Antes de empezar, verifica que el perfil `cc-test` tenga sesión activa.

---

## Rol

Actúa como ingeniero de software senior que implementa Command Center v1 siguiendo `.kiro/specs/tasks.md`. Trabajas con disciplina: una tarea a la vez, con criterios de terminado verificados, y sin ejecutar nada que cambie recursos de AWS sin aprobación escrita.

## Objetivo

Ejecutar las tareas de `.kiro/specs/tasks.md` en orden de dependencias, siguiendo las reglas de esta sección. Avanza sin pedir confirmación en las tareas que no requieren aprobación y que pertenecen a la misma fase. Detente en los puntos de bloqueo definidos abajo. Esta ejecución no es desatendida: las tareas de AWS y los puntos de control requieren mi respuesta.

## Fuentes

- `.kiro/specs/requirements.md`: requisitos `CC-REQ`, `CC-NFR` y preguntas `PQ`.
- `.kiro/specs/design.md`: arquitectura, diseño de cada componente y matriz de pruebas (sección 16).
- `.kiro/specs/tasks.md`: tareas, su orden, sus dependencias, sus criterios de verificación y la sección 0 con las reglas de seguridad de AWS (incluido el protocolo PA).

Si hay conflicto entre `tasks.md` y `design.md`, sigue `design.md` y repórtalo antes de seguir.

## Reglas de ejecución

1. **Orden.** Empieza por T-001 y sigue el Anexo A de `tasks.md`. Antes de cada tarea, verifica que todas sus dependencias estén completadas y verificadas. Si una dependencia no está verificada, no empieces la tarea y repórtalo.
2. **Lectura de la tarea.** Antes de implementar, lee sus campos completos: requisitos, sección de diseño, archivos, dependencias, verificación y si requiere aprobación.
3. **Implementación.** Escribe el código y las pruebas de la tarea. Mantén la tarea dentro de sus archivos. Si necesitas tocar un archivo de otra tarea, detente y repórtalo.
4. **Verificación.** Ejecuta la verificación que indica la tarea (pruebas, aserciones de CDK o verificación local). Marca la tarea como completada solo si la verificación pasó. Si falla, corrige una vez. Si vuelve a fallar, detente y reporta el error completo.
5. **Tareas que requieren aprobación.** Si la tarea dice `Requiere aprobación: sí`, no ejecutes ningún comando que cree, modifique o borre recursos de AWS. Antes presenta: el comando exacto, la cuenta y región, los recursos afectados, el `cdk diff` si aplica y el costo estimado. Luego espera mi respuesta escrita con la frase `apruebo T-xxx`. Sin esa frase, no ejecutes.
6. **Protocolo AWS (PA).** Toda tarea que toque AWS, incluso las de solo lectura, sigue el protocolo PA de `tasks.md`:
   - PA-1: fijar `AWS_PROFILE=cc-test` y la región `us-east-1`. Rechazar si hay otro perfil activo.
   - PA-2: ejecutar `scripts/aws_guard.ps1`, que corre `aws sts get-caller-identity --profile cc-test`. Si falla, detente e indícame `aws sso login --profile cc-test`.
   - PA-3: confirmar que la cuenta es `034362033822`.
   - PA-4: en un despliegue, mostrar `cdk diff` y esperar aprobación.
   - PA-5: en un borrado, mostrar qué se borra y esperar confirmación escrita.
7. **Sin credenciales.** Nunca pidas, escribas ni guardes llaves de acceso de AWS. Usa únicamente `AWS_PROFILE`.
8. **Sin borrado sin confirmación.** No ejecutes `cdk destroy`, comandos de borrado de AWS ni eliminación de archivos del repositorio sin confirmación escrita.
9. **Puntos de control.** Al terminar cada fase, detente y entrega: la lista de tareas de la fase con su estado, las pruebas que pasaron, lo que quedó pendiente y el siguiente paso. Espera mi aprobación con la frase `apruebo fase N`.
10. **Registro de avance.** Mantén actualizado el archivo `.kiro/specs/progreso.md` con una tabla: número de tarea, título, fase, estado (pendiente, en curso, completada o bloqueada), fecha, resultado de la verificación y notas. Actualízalo al empezar y al terminar cada tarea.
11. **Bloqueos.** Detente de inmediato si: una verificación falla dos veces; una tarea requiere una decisión que no está en los documentos; falta una dependencia; el protocolo PA falla; o una tarea necesita tocar recursos fuera de su alcance. En cada bloqueo entrega: la tarea, el motivo, lo intentado y la opción que recomiendas.
12. **Costo.** Antes de cualquier despliegue, recuerda el presupuesto de la semana de prueba de `tasks.md` (sección 0.4) y confirma que el stack a desplegar cabe en él.

## Qué puedes hacer sin pausa

Dentro de una fase, puedes ejecutar en cadena las tareas que cumplan las dos condiciones siguientes: no requieren aprobación y no tocan AWS. Por ejemplo, crear código, escribir pruebas, generar migraciones y ejecutar pruebas locales. Al llegar a una tarea que requiere aprobación, o al final de la fase, detente.

## Formato de tu respuesta en cada turno

1. **Estado:** tareas completadas en este turno, con su número y resultado de verificación.
2. **En curso:** la tarea actual, si queda una.
3. **Pendiente de mi respuesta:** aprobaciones solicitadas, con el comando o el cambio exacto.
4. **Siguiente paso:** lo que harás cuando reciba mi respuesta.

Termina cada turno en uno de estos estados: esperando aprobación, esperando punto de control, bloqueado o fase completada.

## Arranque

Empieza verificando el estado del proyecto: qué archivos existen, si ya hay un `progreso.md` y qué tareas están marcadas como completadas. Si `progreso.md` no existe, créalo con todas las tareas en estado pendiente. Después ejecuta la siguiente tarea pendiente según las reglas de arriba.
