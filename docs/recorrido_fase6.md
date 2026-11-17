# Recorrido grabado de la Fase 6: notificación por WhatsApp (T-218, punto de control T-118)

Generado por `tests/e2e/test_flujo_notificacion.py::test_camino_feliz_de_la_notificacion_hasta_el_chat_y_el_respaldo`.
Para regenerarlo: `uv run pytest tests/e2e/test_flujo_notificacion.py -q -k camino_feliz`.
Los tiempos cambian en cada corrida.

Piezas reales: PostgreSQL 16 (RLS y roles de servicio), LocalStack (SQS, EventBridge, SNS, SES),
servicios `campos`, `colaboradores`, `notificaciones` y `whatsapp` (chat de RH) como apps ASGI con
token interno, bot y `worker_entrada`, Lambdas `webhook-meta`, `despachador`, `enviador`,
`estados-entrega` y `respaldo-correo`, relays del outbox y consumidor de `ev-notificaciones`.
Meta: simulador (`services/whatsapp/tests/simulador_meta`). Simulado: EventBridge Scheduler
(`StubScheduler`; el cuerpo del schedule se entrega a mano a `notif-despacho`) y los relojes de las
piezas con horario. Los números se muestran como `…NNNN`, el nombre del colaborador en las
plantillas como `<nombre>` (los de los pasos son ficticios) y no se incluye ningún correo, código ni token.

## Pasos

| # | Paso | Qué ocurrió |
|---|---|---|
| 1 | Plantilla `aviso_cita` | BORRADOR -> EN_REVISION (API de Meta simulada) -> APROBADA (`wa.plantilla_estado` por webhook firmado) |
| 2 | Revisión (embudo) | 5 seleccionados -> 4 con consentimiento -> 3 activos -> 3 con celular válido; excluidos: 1 SIN_CONSENTIMIENTO y 1 ESTATUS_BAJA |
| 3 | Programación | PROGRAMADA para las 14:00 de Ciudad de México; schedule `cc-notif-1` |
| 4 | Despacho | el despachador publica 3 mensajes en `wa-salida.fifo`; el enviador los manda a Meta; la notificación queda COMPLETADA (Darío y Elena no reciben nada) |
| 5 | Estados de Meta | Ana `sent`, Beto `delivered`, Carla `delivered` y `read` -> ENVIADO, ENTREGADO y LEIDO |
| 6 | Respuesta | Carla responde; el bot abre su conversación y emite `wa.respuesta_recibida` (solo ids); el destinatario pasa a RESPONDIO y queda ligado a la conversación |
| 7 | Chat de RH | RH ve la conversación (ventana abierta), lee la respuesta descifrada y le contesta; Meta recibe el texto y reporta `delivered` |
| 8 | Ventana de 24 horas | cerrada: texto libre -> 409 `VENTANA_24H_CERRADA`; plantilla aprobada -> 202 y Meta la recibe |
| 9 | Respaldo por correo | a las 24 horas solo Ana (ENVIADO) recibe el correo por SES; Beto (ENTREGADO) y Carla (RESPONDIO) no; repetir el mensaje no reenvía |

## Conversación con el colaborador (lo que Meta entregó y lo que él escribió)

| # | Quién | Mensaje |
|---|---|---|
| 1 | Meta -> ...0001 | [plantilla aviso_cita] <nombre>, 20 de noviembre |
| 2 | Meta -> ...0002 | [plantilla aviso_cita] <nombre>, 20 de noviembre |
| 3 | Meta -> ...0003 | [plantilla aviso_cita] <nombre>, 20 de noviembre |
| 4 | COLABORADOR | Gracias, ahí estaré |
| 5 | Meta -> ...0003 | Perfecto, te esperamos puntual. |
| 6 | Meta -> ...0003 | [plantilla aviso_cita] <nombre>, viernes |

## Tiempos del bombeo

| Paso | Tiempo (s) |
|---|---|
| Meta aprueba la plantilla aviso_cita | 1.55 |
| Scheduler dispara el despacho | 2.41 |
| Meta reporta sent | 0.88 |
| Meta reporta delivered | 1.56 |
| Meta reporta delivered | 1.55 |
| Meta reporta read | 1.55 |
| colaborador escribe: Gracias, ahí estaré | 1.47 |
| RH responde por el chat | 1.57 |
| Meta reporta delivered | 1.49 |
| RH envía una plantilla con la ventana cerrada | 1.60 |
| respaldo por correo a las 24 horas | 0.94 |
| el mismo respaldo se repite | 0.90 |

Trabajo hecho por pieza en el bombeo (acumulado):

- lambda estados-entrega: 6
- relay-outbox whatsapp: 13
- consumidor ev-notificaciones: 11
- lambda despachador: 1
- lambda enviador: 5
- consumidor ev-constancias: 9
- worker-whatsapp-entrada: 1
- lambda respaldo-correo: 2

## Estado final

- Notificación 1: `COMPLETADA`.
- Destinatarios:
  - Ana: `ENVIADO`, canal `CORREO`.
  - Beto: `ENTREGADO`, canal `WHATSAPP`.
  - Carla: `RESPONDIO`, canal `WHATSAPP`.
  - Dario: `EXCLUIDO`, motivo `SIN_CONSENTIMIENTO`.
  - Elena: `EXCLUIDO`, motivo `ESTATUS_BAJA`.
- Conversación 1: `ACTIVA`, no verificada, origen `NOTIFICACION`; ventana de 24 horas cerrada a propósito para probar el 409.
- Mensajes del chat de RH (tabla `mensaje_whatsapp`, contenido cifrado en la base):
  - TEXTO, estado `ENTREGADO`, intentos 1, error ninguno.
  - PLANTILLA, estado `ENVIADO`, intentos 1, error ninguno.
- Correos de respaldo en SES (LocalStack): 1 (solo a quien no recibió el WhatsApp).
- Mensajes enviados por Meta: 5.
