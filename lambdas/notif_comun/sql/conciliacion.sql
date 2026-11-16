-- Soporte de las Lambdas despachador, conciliador y respaldo-correo (T-217, parte A).
-- DEBE FORMAR PARTE DE UNA MIGRACION de `services/notificaciones` (p. ej. 0003): `op.execute(...)`.
-- Es idempotente. Las pruebas de `lambdas/` lo aplican como administrador.
--
-- 1) Columna ``reencolada_en``: el conciliador la marca al reencolar un INICIO (PROGRAMADA atrasada)
--    o un respaldo; con ella no repite el trabajo en dos ciclos seguidos.
-- 2) Funciones SECURITY DEFINER de proposito unico (mismo patron que
--    ``whatsapp.mensaje_por_proveedor``): el conciliador recorre TODAS las empresas y la RLS
--    exige ``app.empresa_id``. Solo devuelven ``(id, empresa_id)`` (y la zona horaria); despues la
--    Lambda fija la empresa de cada una y actua con la RLS vigente.

ALTER TABLE notificaciones.notificacion ADD COLUMN IF NOT EXISTS reencolada_en timestamptz;

-- Todas reciben ``p_ahora``: la Lambda pasa su reloj (las pruebas controlan el tiempo).

-- PROGRAMADA con mas de p_minutos de atraso y sin reencolado reciente.
CREATE OR REPLACE FUNCTION notificaciones.conciliar_programadas_atrasadas(p_ahora timestamptz, p_minutos int, p_reintento_minutos int)
  RETURNS TABLE (id bigint, empresa_id bigint)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, notificaciones AS $$
    SELECT n.id, n.empresa_id FROM notificaciones.notificacion n
    WHERE n.estado = 'PROGRAMADA'
      AND n.programada_para <= p_ahora - make_interval(mins => p_minutos)
      AND (n.reencolada_en IS NULL OR n.reencolada_en <= p_ahora - make_interval(mins => p_reintento_minutos))
    ORDER BY n.programada_para LIMIT 500
  $$;

-- ENVIANDO con destinatarios encolados hace mas de p_minutos que siguen PENDIENTE.
CREATE OR REPLACE FUNCTION notificaciones.conciliar_encolados_atascados(p_ahora timestamptz, p_minutos int)
  RETURNS TABLE (id bigint, empresa_id bigint)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, notificaciones AS $$
    SELECT n.id, n.empresa_id FROM notificaciones.notificacion n
    WHERE n.estado = 'ENVIANDO'
      AND EXISTS (SELECT 1 FROM notificaciones.notificacion_destinatario d
                  WHERE d.notificacion_id = n.id AND d.estado_envio = 'PENDIENTE'
                    AND d.encolado_en IS NOT NULL
                    AND d.encolado_en <= p_ahora - make_interval(mins => p_minutos))
    ORDER BY n.id LIMIT 500
  $$;

-- Con respaldo por correo: destinatarios sin atender pasadas p_horas + p_gracia_minutos del envio y
-- sin reencolado reciente. Devuelve tambien la zona (el conciliador respeta el horario).
CREATE OR REPLACE FUNCTION notificaciones.conciliar_respaldos_pendientes(p_ahora timestamptz, p_horas int, p_gracia_minutos int, p_reintento_minutos int)
  RETURNS TABLE (id bigint, empresa_id bigint, zona_horaria text)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, notificaciones AS $$
    SELECT n.id, n.empresa_id, n.zona_horaria FROM notificaciones.notificacion n
    WHERE n.respaldo_correo AND n.estado IN ('ENVIANDO', 'COMPLETADA', 'CON_FALLAS')
      AND (n.reencolada_en IS NULL OR n.reencolada_en <= p_ahora - make_interval(mins => p_reintento_minutos))
      AND EXISTS (SELECT 1 FROM notificaciones.notificacion_destinatario d
                  WHERE d.notificacion_id = n.id AND d.estado_envio IN ('ENVIADO', 'FALLIDO')
                    AND d.respaldo_enviado_en IS NULL AND d.encolado_en IS NOT NULL
                    AND d.encolado_en <= p_ahora - make_interval(hours => p_horas, mins => p_gracia_minutos))
    ORDER BY n.id LIMIT 500
  $$;

-- ENVIANDO sin ningun destinatario PENDIENTE (con o sin encolar): listo para COMPLETADA o CON_FALLAS.
CREATE OR REPLACE FUNCTION notificaciones.conciliar_cierres_pendientes()
  RETURNS TABLE (id bigint, empresa_id bigint)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, notificaciones AS $$
    SELECT n.id, n.empresa_id FROM notificaciones.notificacion n
    WHERE n.estado = 'ENVIANDO'
      AND NOT EXISTS (SELECT 1 FROM notificaciones.notificacion_destinatario d
                      WHERE d.notificacion_id = n.id AND d.estado_envio = 'PENDIENTE')
    ORDER BY n.id LIMIT 500
  $$;

REVOKE ALL ON FUNCTION notificaciones.conciliar_programadas_atrasadas(timestamptz, int, int),
                       notificaciones.conciliar_encolados_atascados(timestamptz, int),
                       notificaciones.conciliar_respaldos_pendientes(timestamptz, int, int, int),
                       notificaciones.conciliar_cierres_pendientes() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION notificaciones.conciliar_programadas_atrasadas(timestamptz, int, int),
                          notificaciones.conciliar_encolados_atascados(timestamptz, int),
                          notificaciones.conciliar_respaldos_pendientes(timestamptz, int, int, int),
                          notificaciones.conciliar_cierres_pendientes() TO svc_notificaciones;
