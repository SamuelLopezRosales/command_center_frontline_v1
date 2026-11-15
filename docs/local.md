# Stack local de desarrollo

Prueba el sistema completo en tu máquina, en el navegador, **sin AWS**: PostgreSQL y LocalStack en Docker,
los cinco servicios, los workers, una pasarela local y la SPA. Todo lo de aquí es solo de desarrollo.

## Requisitos

- Windows con Git Bash o PowerShell, **Docker Desktop encendido**, `uv` y Node 20 o superior.
- Dependencias ya instaladas: `uv sync --python 3.12` y, en `frontend/`, `npm ci`
  (el comando `up` hace `npm ci` si falta `node_modules`).
- Los puertos 4566, 55432, 5173 y 8000 a 8105 deben estar libres.

## Comandos

```powershell
.\scripts\local.ps1 up                 # levanta todo (idempotente: se puede repetir)
.\scripts\local.ps1 estado             # qué corre y qué responde
.\scripts\local.ps1 logs dashboard     # registro de un proceso (también: worker-pdf)
.\scripts\local.ps1 down               # detiene todo y CONSERVA los datos
.\scripts\local.ps1 down --borrar      # detiene y borra los datos
.\scripts\local.ps1 reiniciar-datos    # borra base y LocalStack y vuelve a sembrar
.\scripts\local.ps1 up --sin-pdf       # sin el worker de PDF (no toca Docker para eso)
.\scripts\local.ps1 up --sin-spa       # sin Vite
```

Desde Git Bash: `uv run python -m scripts.local.stack up` (mismos comandos).

`up` hace, en orden: `docker compose up`, migraciones y roles de base, contraseñas de roles, buckets, colas,
bus de eventos, llave KMS y secretos en LocalStack, empresa y usuarios de desarrollo, procesos, y datos de
ejemplo. Registros, PIDs, la llave del proveedor de identidad y los secretos generados viven en `.local/`
(ignorado por git).

## URLs

| Qué | URL |
| --- | --- |
| SPA | http://localhost:5173 (abre **localhost**, no 127.0.0.1: la política de seguridad de desarrollo y las URL firmadas de S3 lo usan) |
| Pasarela (API) | http://127.0.0.1:8000 |
| Servicios | dashboard 8101, colaboradores 8102, campos 8103, constancias 8104, whatsapp 8105 (`/docs` de cada uno) |
| LocalStack | http://localhost:4566 |
| PostgreSQL | `127.0.0.1:55432`, base `command_center` |

## Usuarios de desarrollo

Empresa: **Empresa Demo SA de CV**.

| Correo | Contraseña |
| --- | --- |
| `ana.rh@demo.test` | `Desarrollo-Local-1!` |
| `luis.rh@demo.test` | `Desarrollo-Local-1!` |

Después de la contraseña aparece la pantalla de MFA: acepta **cualquier código de 6 dígitos** (por ejemplo `000000`).

Datos de ejemplo: 2 organizaciones, 2 plantas, 8 colaboradores (5 con consentimiento y 3 sin él, con lo que el
dashboard muestra una alerta), la plantilla publicada «Constancia laboral» y 3 constancias ya generadas.

## Cómo funciona

- **Pasarela** (`scripts/local/pasarela.py`, puerto 8000): reenvía por prefijo a cada servicio como lo hará el ALB
  y **no** expone `/internal/*`. También es el proveedor de identidad de desarrollo: publica
  `/.well-known/jwks.json` con una llave RSA local (`.local/idp_llave.pem`) y emite tokens con los claims de
  `cognito-pre-token`. Los servicios validan esos tokens con su código normal (`CC_COGNITO_EMISOR` apunta a la
  pasarela). Se niega a arrancar si `CC_AMBIENTE` no es `local`.
- **SPA**: `npm run dev` con `VITE_AUTH_LOCAL=true` usa `frontend/src/shared/sesion/authLocal.ts`. Esa rama solo
  existe con `import.meta.env.DEV`: la compilación de producción la descarta (verificado con `npm run build`).
- **AWS**: todos los procesos corren con `AWS_ENDPOINT_URL=http://localhost:4566` y credenciales ficticias; nada llega
  a AWS real.
- **Worker de PDF**: WeasyPrint no carga en Windows (sin Pango). Corre en el contenedor `cc-local-worker-pdf`, con la
  imagen `cc-pruebas-pdf` (la misma de `scripts/probar_pdf.ps1`; se construye una vez) y el repositorio montado de
  solo lectura. Por eso `campos` y `colaboradores` escuchan en todas las interfaces mientras corre (`--sin-pdf` lo evita).
- **Llave KMS**: se crea con material fijo guardado en `.local/secretos.json`; si recreas LocalStack, los datos ya
  cifrados en la base siguen siendo legibles.

## Qué NO funciona en local

- **Cognito real**: no hay registro con invitación, confirmación de correo ni recuperación de contraseña
  (las pantallas avisan que no están disponibles). Las invitaciones sí se generan, pero no se pueden canjear.
  Desactivar un usuario solo se registra, no cierra sesiones.
- **Descarga de constancias** (`Descargar` en el historial, `POST /api/v1/constancias/{id}/descarga`): el servicio exige
  una URL firmada de CloudFront y no hay CloudFront local; responde 500. El PDF sí se genera y queda en el bucket
  `cc-local-constancias` de LocalStack (con Object Lock).
- **Meta / WhatsApp real**: no hay webhook ni Lambda enviador. Los mensajes de entrega se quedan en la cola
  `wa-salida.fifo` y el estado de entrega queda en «Pendiente». El worker de entrada corre pero nadie le escribe.
  Las Lambdas no se levantan.
- **PDF en Windows sin Docker**: con `--sin-pdf` las solicitudes de constancia quedan sin generar.
- CloudFront, WAF, RDS Proxy, Scheduler, SES y las alarmas no existen en local.

## Reiniciar los datos

`.\scripts\local.ps1 reiniciar-datos` detiene todo, elimina los contenedores de PostgreSQL y LocalStack y vuelve a
levantar con los datos de ejemplo. Conserva `.local/` (llaves y secretos). Para empezar totalmente de cero, borra
también la carpeta `.local/`.

## Problemas frecuentes

- *«No se pudo levantar docker compose»*: enciende Docker Desktop.
- Un proceso no responde: `.\scripts\local.ps1 logs <nombre>` (`pasarela`, `dashboard`, `colaboradores`, `campos`,
  `constancias`, `whatsapp`, `worker-cargas`, `worker-whatsapp`, `spa`, `worker-pdf`).
- El puerto 4566 o 55432 está ocupado por otro compose: `docker compose down` en el otro proyecto.
