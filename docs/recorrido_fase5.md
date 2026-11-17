# Recorrido grabado de la Fase 5: constancia por WhatsApp (T-214, punto de control T-104)

Generado por `tests/e2e/test_flujo_constancia.py::test_camino_feliz_de_la_constancia_hasta_entregada`.
Para regenerarlo: `uv run pytest tests/e2e -q -k camino_feliz`. Los tiempos cambian en cada corrida.

Piezas reales: PostgreSQL 16 (RLS y roles de servicio), LocalStack (SQS, EventBridge, SNS, S3 con
Object Lock), servicios `campos`, `colaboradores`, `constancias` y `dashboard` (ASGI con token interno),
bot y `worker_entrada`, Lambdas `webhook-meta`, `enviador` y `estados-entrega`, `worker-pdf`, relays
del outbox y consumidor de eventos. Meta: simulador (`services/whatsapp/tests/simulador_meta`).
Limitación: en Windows el renderizador de PDF se inyecta (WeasyPrint no carga sin Pango); el PDF
real se prueba con el marcador `pdf`. Los secretos se muestran como `***` y los números como `…NNNN`.

## Conversación (colaborador y bot)

| # | Quién | Mensaje |
|---|---|---|
| 1 | COLABORADOR | constancia |
| 2 | BOT -> ...5678 | Antes de continuar, consulta el aviso de privacidad: https://cc.e2e.test/privacidad |
| 3 | BOT -> ...5678 | Tu código de verificación es *** (vence en 10 minutos). Respóndeme en un solo mensaje el código y los últimos 4 dígitos de tu NSS. |
| 4 | COLABORADOR | *** **** |
| 5 | BOT -> ...5678 | Estamos preparando tu constancia; te la enviaremos en un momento. |
| 6 | BOT -> ...5678 | Tu constancia CG-2026-0001 está lista. Descárgala aquí (un solo uso): https://cc.e2e.test/d/*** |

## Pasos y tiempos

| Paso | Tiempo (s) |
|---|---|
| colaborador escribe: constancia | 2.05 |
| colaborador escribe: *** **** | 2.65 |
| Meta reporta delivered | 1.01 |
| Meta reporta sent | 0.59 |
| Meta reporta read | 0.99 |

Trabajo hecho por pieza en el bombeo (acumulado):

- worker-whatsapp-entrada: 2
- relay-outbox whatsapp: 9
- lambda enviador: 4
- consumidor ev-constancias: 6
- relay-outbox constancias: 2
- worker-pdf: 1
- lambda estados-entrega: 3

## Estado final

- Solicitud 1: `ENTREGADA` (motivo: ninguno).
- Constancia 1: folio `CG-2026-0001`, entrega `ENTREGADA`.
- Objeto en S3 (bucket de constancias con Object Lock, modo GOVERNANCE): `constancias/1/2026/CG-2026-0001.pdf`.
- Huella SHA-256 del PDF: `0f31fe770cd908dd…`.
- Enlace de un solo uso: la primera descarga redirige (302) y la segunda responde 410 `ENLACE_NO_VIGENTE`.
- Mensajes de la constancia (tabla `mensaje_whatsapp`):
  - TEXTO, estado `LEIDO`, intentos 1, error ninguno.
- Conversación: estado `ACTIVA`, verificada: True, intentos de verificación: 0.
- Mensajes enviados por Meta al colaborador: 4.
