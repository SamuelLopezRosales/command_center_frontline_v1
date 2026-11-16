# Resultados de las pruebas de carga locales (T-142)

Fecha de la medición: 15 de noviembre de 2026. Valores **medidos** en una sola máquina de
desarrollo; no son valores de AWS ni de producción. Los candidatos son los de `design.md` §15.3
(todos **[POR CONFIRMAR]**, PQ-NFR) y §15.4. Nada de lo que sigue está estimado: lo que no se pudo
medir figura en la sección "Lo que no se midió".

## Condiciones de la medición

| Elemento | Valor |
|---|---|
| Equipo | Windows 10 Pro, Intel Core i7-1255U (10 núcleos, 12 hilos), 15.7 GB de RAM |
| Docker | Docker Desktop 29.8.2, 12 CPU y 7.6 GB de memoria para el motor |
| PostgreSQL | 16.16 en contenedor (Testcontainers, `postgres:16`), con migraciones, RLS y roles `svc_*` reales |
| LocalStack | 4.4 (S3 con Object Lock, SQS FIFO y estándar) |
| Python | 3.12.15 (uv) |
| Cómo se mide | En proceso: app ASGI real (`httpx.ASGITransport`) contra la base real, **sin red, sin API Gateway, sin CloudFront ni ALB**. El tiempo es el de la aplicación y la base. |
| Muestras | Cada ruta: 10 llamadas de calentamiento, 100 en serie y 200 con 10 en vuelo (los 10 VUs de los guiones k6). p95 inclusivo. |
| Interferencias | El equipo corría además el stack local de desarrollo (SPA, pasarela, LocalStack y PostgreSQL) y otras aplicaciones. Los valores con 10 en vuelo incluyen la espera en una sola corrutina de Python (un solo proceso): en AWS habrá varias tareas, así que son pesimistas. |

Cómo repetirlo (las pruebas con marcador `carga` no entran en la corrida normal de `pytest`):

```powershell
uv run pytest tests/carga -m carga -s -p no:cacheprovider                    # todo (unos 8 minutos)
uv run pytest tests/carga/test_carga_colaboradores.py -m carga -s -p no:cacheprovider
uv run pytest services/colaboradores/tests/test_carga_real.py -k "dos_mil or 10000" -s -p no:cacheprovider   # T-204
.\scripts\probar_pdf.ps1 -Recursos                                           # PDF real, 1 vCPU y 2 GB
```

## Resultados

| Métrica | Valor medido | Candidato §15.3 | Veredicto | Condiciones |
|---|---|---|---|---|
| Listado de colaboradores (página aleatoria, límite 50, con total) | p95 62 ms en serie; 282 ms con 10 en vuelo | p95 < 1 s | Cumple | 10,000 colaboradores, en proceso |
| Búsqueda por nombre (sin acentos, parcial) | p95 73 ms; 328 ms con 10 en vuelo | p95 < 1 s | Cumple | Índice trigrama |
| Búsqueda por número de empleado | p95 85 ms; 344 ms con 10 en vuelo | p95 < 1 s | Cumple | |
| Filtros fijos combinados (estatus, organización, tipo) | p95 23 ms; 157 ms con 10 en vuelo | p95 < 1 s | Cumple | |
| Filtro por campo dinámico con columna | p95 39 ms; 255 ms con 10 en vuelo | p95 < 1 s | Cumple | 1,428 coincidencias |
| Listado y búsquedas, repetición de T-204 (`test_carga_real.py`, 40 muestras) | listado 91 ms, búsqueda por nombre 146 ms, por número 116 ms, filtro 47 ms (p95) | p95 < 1 s | Cumple | Datos sembrados por la prueba de T-204, con la plantilla real |
| Carga de 2,000 filas (alta) | 71.1 s | < 2 min | Cumple (59 % del candidato) | Plantilla real v1.3, 11 campos dinámicos (5 cifrados), worker en proceso, S3 de LocalStack |
| Carga de 2,000 filas (actualización de las mismas) | 64.4 s | < 2 min | Cumple | Mismo archivo, sin duplicar |
| 500 constancias de un mes, emisión con un worker | 38.0 s en total; p95 132 ms y máximo 208 ms por solicitud, sin el dibujo del PDF | PDF p95 < 5 s (CC-NFR-001); un worker basta (§15.4) | Cumple, con la salvedad de que el PDF va inyectado | Worker `procesar_solicitud` real, base real, bucket con Object Lock de LocalStack, `FalsoPdf`; 500 folios `0001` a `0500` sin huecos ni repetidos |
| PDF real (WeasyPrint) | p50 0.094 s, p95 0.123 s, máx 0.190 s en 100 generaciones | p95 < 5 s | Cumple | Contenedor Linux con 1 vCPU y 2 GB (`scripts/probar_pdf.ps1 -Recursos`); en T-210 salió p95 0.069 s: la variación es la del equipo |
| Tiempo de 500 constancias con PDF real | No medido como un solo flujo | n/d | Estimación aritmética, no medición: 500 × (132 ms + 123 ms) ≈ 2 min | Solo orientativa |
| Folios, 50 reservas simultáneas | 418 ms en total; sin repetidos ni huecos | Sin repetidos | Cumple | Una transacción por reserva, `gather` |
| Folios, 200 reservas simultáneas | 1,839 ms en total; sin repetidos ni huecos | Sin repetidos | Cumple | Se serializan por el contador; 9 ms por reserva |
| 50 emisiones completas simultáneas | 2.4 s; 50 folios distintos | Sin repetidos | Cumple | Worker real, PDF inyectado |
| Despacho de 10,000 destinatarios, doble de SQS | 1.7 s | Sin candidato de tiempo (§15.4: unas 1,000 llamadas por lotes) | Informativo | Despachador real, base real, 10,000 `mensaje_uuid` únicos, 1,000 lotes |
| Despacho de 10,000 destinatarios, SQS FIFO real (LocalStack) | 55.6 s para publicar; los 10,000 mensajes recibidos y sin duplicados | Sin candidato de tiempo | Informativo; no hay pérdida ni duplicados | LocalStack local (no es el SQS de AWS). Sin Meta ni `enviador`: el envío real lo limita el nivel de mensajería (PQ-27) |
| Dashboard: resumen (DSH-01) | p95 23 ms; 175 ms con 10 en vuelo | p95 < 1 s | Cumple | 10,000 colaboradores y 6,000 constancias (más 2,000 de otra empresa) |
| Dashboard: solicitudes recientes | p95 27 ms; 229 ms | p95 < 1 s | Cumple | |
| Dashboard: constancias recientes | p95 21 ms; 136 ms | p95 < 1 s | Cumple | |
| Dashboard: alertas (8,000 sin consentimiento) | p95 87 ms; 323 ms | p95 < 1 s | Cumple | La más cara de las cuatro |
| Historial: primera página | p95 22 ms; 213 ms | p95 < 1 s | Cumple | 6,000 constancias de un año |
| Historial: por rango de fechas | p95 22 ms; 188 ms | p95 < 1 s | Cumple | |
| Historial: por estado | p95 18 ms; 217 ms | p95 < 1 s | Cumple | |
| Historial: por plantilla | p95 33 ms; 266 ms | p95 < 1 s | Cumple | |
| Historial: búsqueda por nombre | p95 46 ms; 221 ms | p95 < 1 s | Cumple | Índice trigrama |
| Historial: búsqueda por folio | p95 48 ms; 308 ms | p95 < 1 s | Cumple | Índice trigrama |
| Historial: recorrido completo por cursor | 300 páginas de 20, p95 33 ms por página; 6,000 constancias sin repetir ni saltar | p95 < 1 s | Cumple | |
| Webhook de Meta (handler real, firma HMAC y encolado) | p95 0.06 ms con SQS en memoria; 55 ms con SQS FIFO de LocalStack (300 mensajes); 53 ms para estados | < 1 s | Cumple en proceso | **No incluye** arranque en frío de la Lambda, API Gateway ni red; solo se mide en AWS |

Conclusión: con los datos de §15.4 (10,000 colaboradores, 500 constancias al mes, 2,000 filas por
carga, 10,000 destinatarios), todos los valores medidos quedan por debajo de los candidatos de
§15.3, con un margen de al menos 1.7 veces (la carga de 2,000 filas) y de 3 o más en el resto. Eso valida el diseño de datos y los índices, no la
latencia final de AWS: falta sumar red, API Gateway, ALB y el arranque en frío.

## Lo que no se midió

- **k6 no está instalado.** Los guiones están escritos y sin ejecutar: `colaboradores_k6.js`,
  `dashboard_k6.js`, `historial_k6.js`, `despacho_k6.js` y `webhook_k6.js` en `tests/carga/`. Se corren
  con `docker run ... grafana/k6` contra AWS (T-229/T-230) o contra el stack local. No se validó su
  sintaxis con k6; se revisaron las rutas y los parámetros contra los OpenAPI de `contracts/openapi/`.
- **Arranque en frío del webhook** y concurrencia aprovisionada (§15.3): solo medible en Lambda.
- **Latencia de extremo a extremo** (CloudFront, WAF, API Gateway, VPC Link, ALB, Fargate): solo en AWS.
- **500 constancias con PDF real en un solo flujo:** el PDF real solo corre en contenedor Linux; se
  midió aparte (p95 0.123 s) y la emisión sin PDF aparte (p95 0.132 s).
- **Despacho con el SQS y Meta reales:** LocalStack no refleja los límites de SQS FIFO de AWS
  (300 mensajes por segundo por API y por grupo) ni el nivel de mensajería de Meta (PQ-27).
- **RDS Proxy y "pinning":** no hay RDS Proxy en local ni en `test` (ver más abajo).
- **Concurrencia mayor a 10 en vuelo** y pruebas de resistencia (horas): no se hicieron.
- La carga se corrió en un solo proceso de Python; no se midió el escalado horizontal de ECS.

## RDS Proxy y "pinning" con `set_config` local

El Proxy ancla una conexión de cliente a una de base de datos cuando la sesión cambia de estado.
El diseño fija `app.empresa_id` con `set_config('app.empresa_id', ..., true)`, que es local a la
transacción y no ancla.

**Garantizado en local** (`tests/test_sin_pinning.py`, corre en la suite normal):

1. Todo `set_config` del código de producción (`services/`, `lambdas/`, `scripts/`) usa `true` como
   tercer argumento.
2. No hay `SET`/`SET SESSION`/`RESET` de parámetros, ni `set_config(..., false)`, ni `options=-c`
   en la conexión, ni candados consultivos de sesión, ni `PREPARE`/`LISTEN` en el código.
3. Solo las herramientas de operación (`scripts/`) usan `autocommit` (con autocommit un `set_config`
   local se perdería y RLS no filtraría).
4. Con un grupo de una conexión, la empresa de una transacción no sobrevive a la siguiente
   (también al fallar), en el motor asíncrono de los servicios y en la conexión síncrona de las Lambdas.

**Se verifica solo en `prod`** (donde existirá RDS Proxy, `design.md` §13.8):

- La métrica de CloudWatch `DatabaseConnectionsCurrentlySessionPinned` del Proxy debe mantenerse en
  0 (o muy cercana) bajo una carga de las rutas de las Lambdas y de los servicios, y
  `DatabaseConnectionsBorrowLatency` no debe crecer con la carga.
- En los logs del Proxy no deben aparecer mensajes de "pinned" (habilitar el registro detallado
  durante la prueba y desactivarlo después).
- Los controladores usados (`asyncpg` en los servicios, `psycopg` en las Lambdas) no deben usar
  sentencias preparadas con nombre; `asyncpg` las usa por defecto con SQLAlchemy y el Proxy las
  puede anclar. **Riesgo a confirmar en `prod`:** si la métrica sube, hay que desactivar la caché de
  sentencias (`statement_cache_size=0` en `asyncpg`; hoy `crear_motor` no lo fija). No se modificó
  código de producción por esto porque no se puede reproducir sin un RDS Proxy.

## Hallazgos de la medición

- No hubo defectos de rendimiento. La consulta más cara es la de alertas del dashboard (p95 87 ms
  en serie); no requiere acción.
- El tiempo con 10 en vuelo es de 4 a 10 veces el de serie porque Python atiende todo en un hilo:
  en AWS lo repartirán varias tareas. Se reporta como cota pesimista.
- El despacho local en SQS FIFO (55.6 s) está dominado por 1,000 llamadas de LocalStack (unos 55 ms
  cada una). No se midió contra el SQS de AWS, así que no se puede decir cuánto tardará allá.
