# Command Center v1

Sistema web para que Recursos Humanos administre colaboradores, constancias y notificaciones por WhatsApp.

La especificación vive en `.kiro/specs/`:

- `requirements.md`: requisitos.
- `design.md`: diseño.
- `tasks.md`: plan de tareas y reglas de seguridad de AWS.
- `progreso.md`: avance de la implementación.

Los insumos originales (documentos, diseños, modelo, plantillas) están en `kiro_command_center_frontline_v1/`.

## Estructura

| Carpeta | Contenido |
|---|---|
| `infra/` | AWS CDK en Python (stacks, constructos, configuración de ambientes) |
| `services/` | Microservicios FastAPI y el paquete compartido `cc_common` |
| `lambdas/` | Funciones Lambda |
| `contracts/` | OpenAPI y esquemas de eventos y mensajes |
| `frontend/` | SPA de React |
| `scripts/` | Utilidades de operación |
| `docs/` | Documentación y runbooks |
| `tests/` | Pruebas de extremo a extremo, carga y seguridad |

## Desarrollo local (Windows)

Requisitos: `uv`, Docker y Node.js. Python 3.12 lo instala `uv`.

```powershell
.\scripts\dev.ps1 setup   # entorno de Python 3.12 y dependencias
.\scripts\dev.ps1 hooks   # instala los hooks de pre-commit
.\scripts\dev.ps1 lint
.\scripts\dev.ps1 test
```

Si `make` está instalado, `make lint` y `make test` hacen lo mismo.

## Seguridad

- No hay llaves de AWS en el repositorio. El acceso a AWS usa únicamente el perfil `cc-test` con IAM Identity Center.
- Las reglas completas están en `.kiro/specs/tasks.md`, sección 0.
