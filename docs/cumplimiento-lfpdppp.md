# Cumplimiento de la LFPDPPP: controles, componentes y pruebas

**Estado:** borrador técnico para revisión del área jurídica (PQ-12) y de operación. T-144.
**Este documento no es una opinión legal.** Describe qué hace el sistema, dónde y con qué prueba. No
fija plazos legales ni textos de aviso: eso lo decide el área jurídica y queda marcado **[PENDIENTE
JURÍDICO]**. Fuente: `.kiro/specs/design.md` §11.7 (control de la LFPDPPP, CC-NFR-015), §8.3, §11.5,
§12, §15.1 y requisitos CC-REQ-150 a 162.

Convenciones: las rutas son del repositorio; los nombres de prueba son reales (verificados con
`grep`). Las pruebas de `tests/seguridad/` son de T-228 (T-143) y se corren con `uv run pytest tests/seguridad -q -p no:cacheprovider`. "Sin componente" = el diseño no lo resuelve.

## 1. Resumen

| Estado | Controles |
|---|---|
| Implementado y probado | Consentimiento verificado en cada envío; cifrado de datos sensibles; mínimo acceso (roles de base de datos, RLS, permisos por ruta); bitácora inmutable; datos personales fuera de logs y errores; protección del webhook; enlaces de un solo uso |
| Implementado, texto pendiente | Aviso de privacidad antes de pedir datos (la redacción y la URL son de jurídico, PQ-12) |
| Parcial o pendiente de infraestructura (T-225, T-226) | Retención de logs y CloudTrail; aserciones de IAM de mínimo privilegio por rol; rotación de secretos |
| **Sin componente** | CC-REQ-160: retención y borrado a solicitud del titular; atención de derechos ARCO; plazo de retención; notificación de vulneraciones |
| Brechas abiertas conocidas (xfail estrictos) | Datos en claro en el payload del `outbox` tras publicar (3); aviso al colaborador por entrega fallida (1). Ver §4 |

## 2. Controles de la sección 11.7 del diseño

| # | Control (§11.7) | Requisito | Componente que lo implementa | Prueba que lo demuestra | Estado |
|---|---|---|---|---|---|
| 1 | Aviso de privacidad antes de pedir datos | CC-REQ-159 | `services/whatsapp/cc_whatsapp/bot/verificacion.py` (envía el aviso y su enlace antes del código), textos en `bot/mensajes_es.py`; URL en `services/whatsapp/cc_whatsapp/config.py` | `services/whatsapp/tests/test_bot_conversacion.py::test_el_aviso_de_privacidad_precede_al_codigo_que_solo_se_guarda_como_hmac` | Componente listo; **texto y enlace [PENDIENTE JURÍDICO] (PQ-12)**; la prueba usa una URL de prueba |
| 2 | Consentimiento verificado en cada envío | CC-REQ-157 | `services/colaboradores/cc_colaboradores/servicios/elegibilidad.py` y `servicios/colaboradores.py` (otorgar, retirar, vencer); `lambdas/enviador/handler.py` (resuelve INT-COL-05 y no envía si no es elegible; métrica `envios_bloqueados_elegibilidad`); `lambdas/respaldo_correo` | `services/colaboradores/tests/test_colaboradores.py::test_consentimiento_otorgar_retirar_y_vencido`; `services/colaboradores/tests/test_internas.py::test_buscar_sin_consentimiento_no_es_elegible`; `services/whatsapp/tests/test_enviador.py::test_un_colaborador_no_elegible_no_recibe_nada`; `lambdas/respaldo_correo/tests/test_respaldo_correo_lambda.py::test_no_elegible_por_baja_o_sin_consentimiento_no_recibe_correo`; `services/notificaciones/tests/test_embudo_revision.py::test_un_solo_motivo_en_el_orden_consentimiento_estatus_celular`; `tests/e2e/test_flujo_constancia.py::test_baja_y_sin_consentimiento_reciben_servicio_no_disponible_y_se_avisa_a_rh` | Implementado |
| 3 | Cifrado de datos sensibles | CC-REQ-151, 152 | Cifrado de sobre AES-256-GCM con DEK por empresa y servicio: `services/shared/cc_common/crypto.py`; `services/colaboradores/cc_colaboradores/cifrado.py`, `services/constancias/cc_constancias/cifrado.py`, `services/whatsapp/cc_whatsapp/cifrado.py`; cifrado en reposo de RDS, S3 y SQS en `infra/stacks/` | `services/shared/tests/test_crypto.py::test_valor_copiado_a_otra_fila_no_descifra`, `::test_otra_empresa_no_descifra`, `::test_nonce_distinto_por_cifrado`; `services/colaboradores/tests/test_cifrado_repos.py::test_sensibles_solo_en_valor_cifrado_y_enmascarados`, `::test_el_sql_registrado_no_contiene_valores_sensibles`; `services/constancias/tests/test_worker_pdf.py::test_genera_la_constancia_con_pdf_inmutable_y_snapshot_cifrado`; `infra/tests/test_storage.py::test_cifrado_con_kms_y_clave_de_bucket_salvo_frontend_y_logs`; `infra/tests/test_messaging.py::test_todas_cifradas_con_kms_y_exigen_tls` | Implementado. **Excepción abierta:** el `outbox` conserva texto en claro tras publicar (§4) |
| 4 | Sensibles no visibles a terceros ni filtrables | CC-REQ-153 | `services/colaboradores/cc_colaboradores/repos/listado.py` y compilador de audiencias; permiso `colaboradores:ver_sensibles` en `services/shared/cc_common/permisos.py` | `services/colaboradores/tests/test_listado.py::test_los_sensibles_no_se_filtran_ni_se_devuelven`; `services/colaboradores/tests/test_internas.py::test_un_campo_sensible_no_sale_por_contactos_resolver`, `::test_resumen_sin_datos_sensibles`; `services/constancias/tests/test_entrega_publica.py::test_verificacion_publica_sin_datos_sensibles_y_404_uniforme` | Implementado |
| 5 | Mínimo acceso: roles de base de datos y RLS | CC-REQ-150, CC-NFR-008 | Un rol por servicio sin privilegios especiales, RLS por `empresa_id`, esquemas separados (`services/shared/cc_common/db.py`, migraciones por servicio) | `tests/integracion/test_esquema.py::test_roles_sin_privilegios_especiales`, `::test_rls_activo_en_tablas_con_empresa`, `::test_rls_aisla_por_empresa`, `::test_lectura_entre_esquemas_prohibida`; `services/shared/tests/test_db.py::test_rls_aisla_por_empresa`; `services/colaboradores/tests/test_cifrado_repos.py::test_rls_otra_empresa_no_ve_los_datos`; `tests/seguridad/test_aislamiento.py::test_la_empresa_b_no_alcanza_datos_de_la_empresa_a_en_ninguna_ruta`, `::test_ninguna_ruta_de_la_api_acepta_un_token_malo`, `::test_la_empresa_a_no_alcanza_los_datos_de_la_empresa_b_en_una_muestra` | Implementado |
| 6 | Mínimo acceso: permisos por ruta | CC-REQ-153, CC-NFR-017 | `requiere_permiso` en `services/shared/cc_common/auth.py`; catálogo en `permisos.py` | `services/shared/tests/test_auth.py::test_todas_las_rutas_declaran_permiso`, `::test_rh_tiene_todos_los_permisos`, `::test_tokens_invalidos`; y por servicio `test_todas_las_rutas_declaran_permiso` en `services/campos/tests/test_catalogo_campos.py`, `services/colaboradores/tests/test_app_colaboradores.py`, `services/constancias/tests/test_app_constancias.py`, `services/dashboard/tests/test_app.py`, `services/notificaciones/tests/test_app_notificaciones.py`; `tests/seguridad/test_aislamiento.py::test_internal_rechaza_tokens_de_usuario_y_de_servicios_no_autorizados`, `::test_el_token_interno_no_sirve_en_las_rutas_publicas_y_el_de_usuario_tampoco_en_internas`; `services/colaboradores/tests/test_internas.py::test_sin_token_interno_401_y_token_de_usuario_no_sirve` | Implementado |
| 7 | Mínimo acceso: IAM por componente | §12, CC-NFR-008 | `infra/stacks/security.py`, `compute*.py`, `workers_lambdas.py` | `infra/tests/test_security.py::test_sin_politicas_iam_con_recurso_comodin`; aserciones completas por rol: **T-226 (T-141) pendiente** | Parcial: falta la revisión completa de IAM |
| 8 | Bitácora de accesos y de acciones | CC-REQ-154, 156 | `services/shared/cc_common/bitacora.py` (inserta sin devolver fila; rechaza claves personales en el detalle); tabla `identidad.bitacora`; consulta de datos sensibles se registra (`colaboradores`, `constancias` vista previa y datos de constancia) | `services/shared/tests/test_bitacora_outbox.py::test_registrar_bitacora`, `::test_detalle_rechaza_claves_personales`, `::test_accion_desconocida`; `services/constancias/tests/test_vista_previa_api.py::test_con_datos_sensibles_registra_consulta_sensible_sin_valores`; `services/colaboradores/tests/test_internas.py::test_datos_constancia_valores_faltantes_y_bitacora`; `services/notificaciones/tests/test_confirmacion_programacion.py::test_la_bitacora_lleva_criterios_y_totales_sin_datos_personales`; `services/dashboard/tests/test_usuarios_bitacora.py::test_bitacora_filtros` | Implementado. Retención de la bitácora: **[PENDIENTE JURÍDICO]** |
| 9 | Bitácora inmutable | CC-REQ-155 | Sin `UPDATE` ni `DELETE` para roles de servicio; restricciones en la migración de identidad | `tests/integracion/test_esquema.py::test_bitacora_sin_update_ni_delete_para_servicios`; `services/dashboard/tests/test_migraciones_identidad.py::test_bitacora_inmutable_y_detalle_permitido` | Implementado |
| 10 | Datos personales fuera de logs y errores | CC-REQ-162, CC-NFR-010 | Procesador de logs: `services/shared/cc_common/logging.py`; errores sin eco: `services/shared/cc_common/errores.py`; webhook sin cuerpo en logs; uvicorn sin registro de accesos en `constancias` (rutas `/d/{token}`) | `services/shared/tests/test_logging.py::test_enmascara_patrones`, `::test_redacta_claves_sensibles_anidadas`, `::test_salida_json_sin_datos_personales`; `services/shared/tests/test_errores.py::test_validacion_problem_json_sin_eco_del_valor`; `services/whatsapp/tests/test_webhook_meta.py::test_el_cuerpo_y_los_numeros_no_se_registran`; `services/constancias/tests/test_seguridad_render.py::test_tokens_y_codigos_no_aparecen_en_los_logs`, `::test_el_servidor_no_registra_las_rutas_con_token`; `tests/seguridad/test_logs_flujos.py::test_los_logs_de_los_flujos_completos_no_contienen_datos_personales_ni_secretos` (flujos de constancia y notificación completos, caminos de error y consultas de RH), `tests/seguridad/test_webhook_firma.py::test_el_handler_no_registra_cuerpo_ni_numeros_en_ningun_camino` | Implementado (revisión de flujos completos hecha en T-228) |
| 11 | Protección del webhook de Meta | CC-REQ-158 | `lambdas/webhook_meta/handler.py` (firma HMAC-SHA256 en tiempo constante, no encola si es inválida); secreto en Secrets Manager | `services/whatsapp/tests/test_webhook_meta.py::test_firma_invalida_da_403_sin_encolar_y_cuenta_la_metrica`, `::test_get_de_verificacion_valido_e_invalido`; `tests/seguridad/test_webhook_firma.py::test_sin_firma_o_con_firma_invalida_da_403_y_no_encola_nada`, `::test_la_firma_se_calcula_sobre_el_cuerpo_crudo_no_sobre_el_json_reformateado`, `::test_la_verificacion_de_la_suscripcion_no_se_adivina` | Implementado |
| 12 | Enlaces y descargas | CC-REQ-084 a 090 | Token de un solo uso (solo su SHA-256 en la base), URL de CloudFront firmada de 60 s, descarga de RH de 24 h: `services/constancias/cc_constancias/servicios/entrega.py`, `firma_cloudfront.py` | `services/constancias/tests/test_entrega_publica.py::test_la_pagina_no_consume_y_la_descarga_funciona_una_sola_vez`, `::test_token_vencido_inexistente_o_mal_formado`, `::test_descarga_de_rh_exige_entrega_y_dura_24_horas`; `tests/seguridad/test_enumeracion.py::test_el_codigo_no_se_adivina_tres_intentos_y_bloqueo_que_el_dato_correcto_no_levanta`, `::test_codigo_vencido_e_inexistente_son_indistinguibles_y_no_cuentan_intento`, `::test_los_codigos_y_tokens_publicos_no_se_enumeran` | Implementado; **excepción abierta:** el token queda en claro en el `outbox` (§4) |
| 13 | Verificación del colaborador (código y dato adicional) | CC-REQ-073, 074 | `services/whatsapp/cc_whatsapp/bot/verificacion.py` (HMAC del código, 3 intentos, bloqueo) | `services/whatsapp/tests/test_bot_conversacion.py::test_el_dato_se_verifica_con_colaboradores_y_tres_fallos_bloquean_24_horas`, `::test_un_codigo_vencido_envia_otro_sin_contar_intento`, `::test_codigo_correcto_pero_dato_incorrecto_cuenta_intento` | Implementado; **excepción abierta:** el código queda en claro en el `outbox` (§4) |
| 14 | Contenido de PDF y vista previa seguro (XSS) | CC-NFR-008 | `services/constancias/cc_constancias/render/` (escape, sin recursos externos) | `services/constancias/tests/test_seguridad_render.py::test_los_valores_hostiles_se_escapan_en_el_html`, `::test_un_texto_fijo_con_marcado_se_rechaza_al_guardar_la_plantilla`, `::test_vista_previa_escapa_los_valores_hostiles`; `tests/seguridad/test_xss.py::test_cada_variable_hostil_sale_escapada_en_todas_las_plantillas_de_referencia`, `::test_el_editor_no_admite_bloques_atributos_ni_estilos_fuera_del_esquema`, `::test_la_vista_previa_de_la_spa_va_en_un_iframe_con_sandbox_sin_permisos`, `::test_nombres_y_puestos_hostiles_dados_de_alta_por_la_api_se_ven_como_texto` | Implementado |
| 15 | Entradas de importación y validación (CSV, ReDoS) | CC-NFR-008 | `services/colaboradores/cc_colaboradores/excel/`, `validador_campos.py` (motor de expresiones regulares RE2: dependencia `google-re2`) | `tests/seguridad/test_csv_y_redos.py::test_el_reporte_de_errores_no_trae_celdas_con_formulas`, `::test_las_celdas_que_empiezan_como_formula_se_neutralizan`; `tests/seguridad/test_csv_y_redos.py::test_los_patrones_catastroficos_se_aceptan_y_se_validan_en_tiempo_acotado`, `::test_el_servicio_de_campos_rechaza_lo_que_re2_no_admite_y_lo_demasiado_largo`, `::test_ningun_codigo_de_produccion_compila_con_re_un_patron_del_cliente` | Implementado |
| 16 | Eliminación lógica e historial | CC-REQ-161 | Estados `BAJA`/inactivo en lugar de borrado | `services/colaboradores/tests/test_organizaciones_plantas.py::test_clave_inmutable_y_desactivar_en_lugar_de_borrar`; `services/constancias/tests/test_migraciones_t029.py::test_version_y_constancia_inmutables` | Implementado (ver conflicto con borrado a solicitud en `docs/retencion-y-derechos-arco.md`) |
| 17 | Constancias inmutables (Object Lock) | CC-REQ-081, PQ-24 | Bucket `constancias` con Object Lock, versionado y cifrado KMS: `infra/stacks/storage.py` | `infra/tests/test_storage.py::test_constancias_con_object_lock_versionado_y_governance_minimo`, `::test_solo_constancias_tiene_object_lock`, `::test_prod_object_lock_sin_retencion_por_defecto_hasta_resolver_pq24` | Implementado; **retención por defecto sin definir (PQ-24)** |
| 18 | Datos temporales: cargas de Excel | CC-REQ-035, PQ-24 | Bucket `cargas` con expiración a 7 días | `infra/tests/test_storage.py::test_cargas_expiran_a_7_dias_y_cors_solo_put` | Implementado; **los 7 días son propuesta, falta decisión jurídica** |
| 19 | Cifrado en tránsito y buckets privados | CC-NFR-008 | TLS obligatorio y bloqueo de acceso público en S3 y colas | `infra/tests/test_storage.py::test_todos_exigen_tls`, `::test_todos_bloquean_el_acceso_publico`; `infra/tests/test_messaging.py::test_todas_cifradas_con_kms_y_exigen_tls` | Implementado (TLS en el borde: T-225) |
| 20 | Secretos fuera del código y de la base | CC-REQ-158, §11.7 | `infra/stacks/security.py`: secretos `cc/{env}/meta`, `hmac-celular`, `hmac-codigo`, `internal-auth`, `cf-signing-key` y credenciales por rol de base de datos; contraseñas de roles con `scripts/asignar_contrasenas.py` | `infra/tests/test_security.py::test_cinco_secretos_cifrados_con_kms_y_sin_valor_en_la_plantilla`; `tests/integracion/test_asignar_contrasenas.py::test_la_salida_nunca_incluye_las_contrasenas`; `tests/integracion/test_bootstrap_admin.py::test_la_invitacion_es_valida_para_el_trigger_de_registro` | Implementado. Rotación cada 30 días de las credenciales de base de datos: **sin prueba (T-226)**; "solo `colaboradores` lee `hmac-celular`" depende de la revisión de IAM (fila 7) |
| 21 | Retención de logs y CloudTrail | CC-NFR-010, §15.1 | `CcObservability` (T-225): 30 días en CloudWatch **[POR CONFIRMAR, PQ-12]**; CloudTrail con validación de integridad y 1 año en S3 | Pendiente de T-225. Existe `infra/tests/test_storage.py::test_logs_expiran_a_90_dias` solo para el bucket de logs de acceso de S3 | **Sin componente todavía**; plazos **[PENDIENTE JURÍDICO]** |
| 22 | Derechos ARCO y retención | CC-REQ-160 | **Ninguno** | Ninguna | **Sin componente. Bloqueado por PQ-12 y PQ-24.** Ver `docs/retencion-y-derechos-arco.md` |

## 3. Dependencias de PQ-12 y PQ-24

Nada de lo siguiente se puede cerrar sin el área jurídica o el cliente:

| Pendiente | Qué falta decidir | Afecta a |
|---|---|---|
| PQ-12: texto y enlace del aviso de privacidad | Redacción, finalidad, responsable del tratamiento, canal de contacto del titular | Fila 1; mensajes del bot |
| PQ-12: plazo de retención de datos de colaboradores, bitácora, mensajes de chat y logs | Plazos (no se proponen aquí), qué se anonimiza y qué se borra | Filas 8, 21, 22 |
| PQ-12: procedimiento para atender derechos ARCO | Quién recibe, cómo se verifica identidad, plazo de respuesta, evidencia | Fila 22 |
| PQ-12: notificación de vulneraciones | Cuándo y a quién notificar | `docs/runbooks/perdida-o-corrupcion-de-datos.md` |
| PQ-24: retención de Object Lock de las constancias | Plazo de la retención por defecto y su modo (hoy GOVERNANCE, sin retención por defecto en `prod`) | Fila 17; conflicto con cancelación |
| PQ-24: plazo de las cargas temporales | ¿7 días es adecuado? | Fila 18 |

## 4. Brechas abiertas conocidas

Brechas con prueba en `xfail(strict=True)`: **no se corrigen en T-228** porque la solución afecta a
varios servicios y es una decisión de diseño. Cuando se corrijan, el `xfail` estricto obliga a
quitar la marca (la prueba pasaría y falla la corrida).

| # | Brecha | Prueba (xfail estricto) | Riesgo |
|---|---|---|---|
| B1 | El texto del bot con el **código de verificación** en claro queda en `whatsapp.outbox.payload` tras publicarse. El diseño (§7.2) dice que solo se guarda el HMAC | `tests/e2e/test_flujo_constancia.py::test_el_codigo_no_queda_en_claro_en_el_outbox` | Quien lea la tabla (volcado, respaldo, acceso a base de datos) ve códigos; son de 10 minutos y de un solo uso, riesgo bajo si ya vencieron |
| B2 | El **token del enlace** de descarga en claro queda en `constancias.outbox.payload`. El diseño (§5.6) dice que solo se guarda el SHA-256 | `tests/e2e/test_flujo_constancia.py::test_el_token_del_enlace_no_queda_en_claro_en_el_outbox` | Un token vigente permite descargar una constancia con datos sensibles (un solo uso, 24 h); es el más importante |
| B3 | El **texto del chat de RH** (puede contener datos personales) va en claro en `whatsapp.outbox.payload`, aunque en `mensaje_whatsapp` sí está cifrado | `tests/e2e/test_flujo_notificacion.py::test_el_texto_del_chat_no_queda_en_claro_en_el_outbox` | Datos personales sin el cifrado que el diseño promete; permanece indefinidamente |
| B4 | No se envía al colaborador "No pudimos enviar tu constancia. RH fue notificado." cuando la entrega falla (§7.4); solo se avisa a RH | `tests/e2e/test_flujo_constancia.py::test_entrega_fallida_avisa_tambien_al_colaborador` | Falla de experiencia, no de datos |

**Opciones para B1 a B3** (decisión de Samuel; detalle y riesgos en `docs/retencion-y-derechos-arco.md` §5):

1. **Vaciar el payload tras publicar.** El relay (`services/shared/cc_common/outbox.py`) ya hace un
   `UPDATE` de la fila al marcar `publicado_en`; bastaría reemplazar `payload` por un objeto vacío o
   mínimo en el mismo `UPDATE`. Pro: cambio pequeño; el secreto vive solo hasta publicar. Contra: el
   vaciado debe ocurrir solo tras confirmar la publicación (si el proceso muere entre publicar y
   vaciar, queda en claro hasta el siguiente ciclo); la fila ya no sirve para republicar ni para
   auditar el contenido; hay que revisar quién más lee `payload` después de publicar; y las pruebas
   E2E que leen el `outbox` para obtener el código o el token (`codigo_recibido`, `enlace_recibido`
   en `tests/e2e/ayudantes_e2e.py`) dejan de funcionar y deben leer del mensaje en la cola.
2. **Cifrar el payload con la DEK del servicio.** Pro: no se pierde el mensaje para reintentos del
   relay. Contra: el `enviador` y el relay deberían descifrar (KMS adicional, permisos
   `kms:Decrypt` para el `enviador`, hoy no concedidos, ver `docs/desviaciones.md` fila 9); el
   mensaje en SQS sigue en claro (cifrado de la cola con KMS lo cubre en reposo); las pruebas E2E que
   leen el `outbox` deben descifrar.
3. **Publicar directo sin guardar el secreto** (generar el token o el código y publicar sin pasar por
   `outbox`). Pro: elimina el secreto de la base. Contra: pierde la atomicidad del `outbox` (riesgo de
   mensaje perdido o duplicado si falla entre la base y SQS); cambia el patrón de consistencia.

## 5. Revisión por el área jurídica: lista de verificación

1. Texto del aviso de privacidad y su enlace (fila 1).
2. Plazos de retención de cada categoría (§3), sin los cuales no se puede implementar CC-REQ-160.
3. Procedimiento ARCO y su responsable.
4. Base legal del consentimiento por WhatsApp (el sistema registra otorgar, retirar y vencer; no
   guarda el texto del consentimiento ni su evidencia documental: **brecha a validar**).
5. Transferencias a terceros (Meta como encargado del tratamiento; Amazon Web Services). Los
   contratos no están en el alcance técnico.
6. Plazo de la bitácora y de los logs (fila 21).
7. Notificación de vulneraciones (§3).
