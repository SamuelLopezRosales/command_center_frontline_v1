# Retención de datos y derechos ARCO: brecha y opciones

> **BLOQUEADO por PQ-12 y PQ-24.** CC-REQ-160 **no tiene componente**: los insumos no definen plazo
> de retención ni procedimiento de atención al titular, y el diseño lo dejó registrado sin resolver
> (`design.md` §11.7, §17). Este documento describe la brecha y propone opciones; **no fija plazos
> legales ni sustituye la decisión del área jurídica**. Todo plazo aparece como **[PENDIENTE
> JURÍDICO]**. T-144 / T-228. Complementa `docs/cumplimiento-lfpdppp.md`.

## 1. Qué falta

| Falta | Detalle | Bloqueado por |
|---|---|---|
| Plazo de retención por categoría | No hay plazo definido para colaboradores, constancias, bitácora, chat, logs ni notificaciones | PQ-12 |
| Procedimiento de atención al titular (acceso, rectificación, cancelación y oposición) | Quién recibe la solicitud, cómo se verifica la identidad, quién ejecuta, plazo de respuesta y evidencia | PQ-12 |
| Borrado a solicitud | Ningún endpoint ni script borra o anonimiza a un colaborador de forma definitiva; la baja es lógica (CC-REQ-161) | PQ-12 |
| Conflicto con Object Lock | Los PDF de constancias no se pueden borrar durante la retención del bucket | PQ-24 |
| Notificación de vulneraciones | No hay procedimiento ni plazo | PQ-12 |

## 2. Estado actual del sistema (hechos verificables)

- **Eliminación lógica** de colaboradores, campos, organizaciones, plantas y plantillas: se marcan
  inactivos y se conserva el historial (`services/colaboradores/tests/test_organizaciones_plantas.py::test_clave_inmutable_y_desactivar_en_lugar_de_borrar`).
- **Baja y consentimiento:** un colaborador en `BAJA` o sin consentimiento vigente no recibe
  constancias ni notificaciones (CC-REQ-157). Retirar el consentimiento detiene el tratamiento por
  WhatsApp, pero **no borra** datos.
- **Bitácora inmutable** (CC-REQ-155): sin `UPDATE` ni `DELETE` para los roles de servicio
  (`tests/integracion/test_esquema.py::test_bitacora_sin_update_ni_delete_para_servicios`). No guarda datos
  personales en su texto (CC-REQ-156), por lo que borrar a un colaborador no obliga a editarla.
- **Constancias:** el PDF y su registro son inmutables
  (`services/constancias/tests/test_migraciones_t029.py::test_version_y_constancia_inmutables`); el
  PDF está en S3 con Object Lock.
- **Datos personales sensibles** cifrados con una DEK por empresa y servicio.
- **Retenciones técnicas que ya existen:** DLQ 14 días; cargas de Excel 7 días (propuesta); PITR de
  RDS 14 días y respaldos de AWS Backup 35 días; logs de aplicación 30 días y CloudTrail 1 año
  (propuestas de §15.1, aún no creadas, T-225). Ninguno viene de una decisión jurídica.

## 3. Dónde viven los datos personales de un colaborador

Necesario para cualquier solicitud de acceso o cancelación. Un borrado completo tiene que cubrir **todas** estas ubicaciones:

| Ubicación | Qué contiene | ¿Se puede borrar hoy? |
|---|---|---|
| `colaboradores.colaborador` y `valor_campo` | Nombre, número de empleado, celular cifrado y su hash, valores de campos (sensibles cifrados) | Solo baja lógica |
| `constancias.constancia` y snapshot cifrado | Datos usados en la constancia, folio, hash | No: inmutable por diseño |
| S3 `constancias/{empresa}/{año}/{folio}.pdf` | PDF con nombre, puesto, sueldo, etc. | No hasta que venza Object Lock (§4); la réplica a `us-east-2` también |
| `whatsapp.conversacion_whatsapp`, `mensaje_whatsapp` | Conversaciones; contenido cifrado | No hay procedimiento |
| `whatsapp.outbox`, `constancias.outbox` (y otros `outbox`) | **Texto, códigos y tokens en claro tras publicar** (brecha §5) | No hay procedimiento |
| `notificaciones.notificacion_destinatario` | Quién recibió qué y su estado | No hay procedimiento |
| `identidad.bitacora` | Acciones con `colaborador_id`, sin datos personales en texto | No: inmutable, y no contiene datos personales directos |
| Respaldos (PITR 14 días, AWS Backup 35 días, copia en `us-east-2`) | Todo lo anterior | Los respaldos se expiran por tiempo; no se editan |
| Logs de CloudWatch (30 días propuestos) | Identificadores, sin datos personales por diseño | Expiran por tiempo |
| Meta (WhatsApp) y SES | Mensajes y correos ya entregados | Fuera del control del sistema |

## 4. Conflicto con Object Lock (PQ-24)

El bucket `constancias` tiene Object Lock en modo GOVERNANCE, versionado y réplica (`infra/stacks/storage.py`).
Hoy en `prod` **no tiene retención por defecto** hasta resolver PQ-24 (prueba:
`infra/tests/test_storage.py::test_prod_object_lock_sin_retencion_por_defecto_hasta_resolver_pq24`), y en `test` el bucket usa GOVERNANCE con la
retención mínima que define la configuración del ambiente (ver `infra/tests/test_storage.py::test_constancias_con_object_lock_versionado_y_governance_minimo`).

- Con retención activa, un PDF no se puede borrar ni sobrescribir antes de vencer, **salvo** que
  quien tenga el permiso especial `s3:BypassGovernanceRetention` lo haga con GOVERNANCE (con
  COMPLIANCE ni siquiera esa persona). Los roles de servicio no tienen `DeleteObject` sobre
  `constancias/` (§12).
- Una solicitud de cancelación de un titular podría chocar con la obligación de conservar la
  constancia emitida. Si existe una obligación legal de conservar (por ejemplo laboral o fiscal),
  la cancelación puede no proceder o quedar bloqueada hasta el vencimiento: **lo determina
  jurídico; no se afirma aquí**.
- La réplica en `us-east-2` y los respaldos conservan la copia: un borrado debe considerar ambas.
- El modo (GOVERNANCE o COMPLIANCE) y el plazo son decisiones jurídicas y de negocio; COMPLIANCE es irreversible.

## 5. Brecha adicional: datos en claro en el `outbox` tras publicar (4 xfail estrictos)

Relacionada con la cancelación, porque deja copias de datos personales fuera de los lugares donde
el diseño dice que están cifrados o ausentes. Las pruebas están como `xfail(strict=True)` y **no se
corrigen en T-228** (decisión de diseño de varios servicios; ver `docs/cumplimiento-lfpdppp.md` §4):

| # | Brecha | Prueba |
|---|---|---|
| B1 | Código de verificación en claro en `whatsapp.outbox.payload` | `tests/e2e/test_flujo_constancia.py::test_el_codigo_no_queda_en_claro_en_el_outbox` |
| B2 | Token del enlace de descarga en claro en `constancias.outbox.payload` | `tests/e2e/test_flujo_constancia.py::test_el_token_del_enlace_no_queda_en_claro_en_el_outbox` |
| B3 | Texto del chat de RH en claro en `whatsapp.outbox.payload` | `tests/e2e/test_flujo_notificacion.py::test_el_texto_del_chat_no_queda_en_claro_en_el_outbox` |
| B4 | Falta el aviso al colaborador por entrega fallida (diseño §7.4) | `tests/e2e/test_flujo_constancia.py::test_entrega_fallida_avisa_tambien_al_colaborador` |

### Opciones para B1 a B3

| Opción | Cómo | Riesgos | Impacto en las pruebas E2E |
|---|---|---|---|
| **A. Vaciar el payload tras publicar** | El relay (`services/shared/cc_common/outbox.py`) ya actualiza la fila al marcar `publicado_en`; en el mismo `UPDATE` reemplaza `payload` por un valor mínimo | Si el proceso muere entre publicar y vaciar, queda en claro hasta el siguiente ciclo; la fila ya no sirve para republicar ni auditar el contenido; hay que revisar todos los servicios con `outbox` (colaboradores, constancias, notificaciones, whatsapp, campos); filas ya publicadas antes del cambio siguen en claro (requiere limpieza única) | Las pruebas que obtienen el código o el token leyendo `outbox` (`codigo_recibido`, `enlace_recibido` en `tests/e2e/ayudantes_e2e.py`) deben leer del mensaje en la cola simulada |
| **B. Cifrar el payload con la DEK** | Cifrar el campo sensible del payload al escribir; el `enviador` lo descifra | El `enviador` hoy no tiene `kms:Decrypt` ni cifra (`docs/desviaciones.md`, fila 9): agregar permisos y una llamada a KMS por mensaje; el mensaje viaja en claro por SQS (protegido por el cifrado de la cola); las filas conservan datos cifrados indefinidamente (siguen siendo datos personales para efectos de retención) | Las pruebas deben descifrar para leer el código o el token |
| **C. Publicar directo sin guardar el secreto** | Generar y publicar sin pasar por `outbox` | Pierde la atomicidad base de datos + mensaje: puede perderse o duplicarse un envío si falla entre ambos; cambia el patrón de consistencia del diseño | Cambia el flujo completo; las pruebas E2E se reescriben |

**Recomendación técnica:** opción A para B1 y B2 (secretos de corta vida), con limpieza única de filas
anteriores, y opción B para B3 (el texto del chat sí debe conservarse cifrado y puede ser
necesario para reintentos). Decisión de Samuel. Para B4: enviar el aviso desde el consumidor de
`constancia.fallida` con motivo `ENTREGA_FALLIDA`.

## 6. Notificación de vulneraciones

No existe procedimiento. Hoy lo más cercano es el runbook `docs/runbooks/perdida-o-corrupcion-de-datos.md`
(detención de escrituras, reconstrucción, escalamiento a jurídico). **Plazos y destinatarios de la
notificación: [PENDIENTE JURÍDICO].** Mientras tanto, la regla operativa es: todo incidente con
posible exposición de datos personales se escala al área jurídica de inmediato y no se comunica a
los titulares por iniciativa del equipo técnico.

## 7. Opciones para retención y derechos ARCO y recomendación

| Opción | Descripción | Pros | Contras |
|---|---|---|---|
| **1. Procedimiento manual documentado** | Jurídico define el procedimiento; operación ejecuta consultas y baja/anonimización con la tarea `ops` y un runbook | Rápido; sin código nuevo; permite validar el procedimiento antes de automatizarlo | Propenso a errores; cada solicitud es trabajo manual; las ubicaciones de §3 deben cubrirse a mano; hoy la tarea `ops` solo tiene `contrasenas` y `bootstrap` |
| **2. Anonimización en lugar de borrado** | Un comando de operación reemplaza nombre, número, celular, correo y valores de campo por marcadores y borra el celular cifrado y su hash, conservando folio, hash y totales | Compatible con registros inmutables y conteos; no borra constancias | Debe vaciar también el `outbox`, los mensajes y el snapshot cifrado; el PDF con Object Lock sigue teniendo los datos; necesita aprobación jurídica de que anonimizar basta |
| **3. Borrado físico + expiración por plazo** | Jobs de retención con plazo por categoría y endpoint de borrado a solicitud | Cumple de forma más completa si el plazo lo exige | Choca con Object Lock y con las tablas inmutables (constancia, bitácora); riesgo alto de borrar de más; depende del plazo de PQ-12 |
| **4. Cifrado con destrucción de llave ("crypto-shredding") por empresa** | Destruir la DEK de una empresa vuelve ilegibles sus datos cifrados | Eficaz para sensibles | Es por empresa, no por titular; no cubre nombres ni datos no cifrados; irreversible |

**Recomendación (a validar por jurídico):** empezar con la opción 1 (procedimiento manual con
evidencia), diseñar la opción 2 como herramienta de operación una vez que PQ-12 fije los plazos, y
**no** implementar la opción 3 hasta resolver PQ-24 (modo y plazo de Object Lock). Ninguna se
implementa en T-228.

## 8. Decisiones pendientes para Samuel y jurídico

| # | Decisión | Dependencia |
|---|---|---|
| D1 | Plazo de retención por categoría (colaboradores, constancias, bitácora, chat, notificaciones, logs, respaldos) | PQ-12 |
| D2 | Procedimiento, responsable y plazo de respuesta para derechos ARCO; verificación de identidad del titular | PQ-12 |
| D3 | Modo (GOVERNANCE o COMPLIANCE) y plazo de la retención del bucket `constancias`; qué hacer con una solicitud de cancelación durante la retención | PQ-24 |
| D4 | Si anonimizar cumple la cancelación en las ubicaciones inmutables | PQ-12, PQ-24 |
| D5 | Opción para el payload del `outbox` (A, B o C de §5) | Samuel |
| D6 | Notificación de vulneraciones: plazos y destinatarios | PQ-12 |
| D7 | Plazo de las cargas temporales (hoy 7 días, propuesta) | PQ-24 |
| D8 | Texto del aviso de privacidad y evidencia del consentimiento | PQ-12 |
