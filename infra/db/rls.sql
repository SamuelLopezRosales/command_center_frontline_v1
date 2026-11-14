-- Seguridad a nivel de fila por empresa (design.md §2.1, T-030). Idempotente.
--
-- Política: empresa_id = NULLIF(current_setting('app.empresa_id', true), '')::bigint
--   El NULLIF es necesario: una conexión del pool que ya usó set_config(..., true) devuelve ''
--   en lugar de NULL, y ''::bigint sería un error (hallazgo de T-023). Sin empresa no hay filas.
--
-- Excepciones (agregado al diseño, registrado en progreso.md):
--   - outbox y evento_procesado: tablas técnicas que el relay recorre para todas las empresas.
--   - identidad.empresa usa su propio id.
--   - Dos funciones SECURITY DEFINER de propósito único para los triggers de Cognito, que aún no
--     conocen la empresa: validar_invitacion y usuario_por_sub. Solo devuelven lo necesario.

DO $$
DECLARE
  t record;
  expr constant text := 'NULLIF(current_setting(''app.empresa_id'', true), '''')::bigint';
BEGIN
  FOR t IN
    SELECT c.table_schema, c.table_name
    FROM information_schema.columns c
    JOIN information_schema.tables tb
      ON tb.table_schema = c.table_schema AND tb.table_name = c.table_name AND tb.table_type = 'BASE TABLE'
    WHERE c.column_name = 'empresa_id'
      AND c.table_schema IN ('identidad', 'auditoria', 'campos', 'colaboradores', 'whatsapp',
                             'constancias', 'notificaciones')
      AND c.table_name NOT IN ('outbox', 'evento_procesado')
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', t.table_schema, t.table_name);
    EXECUTE format('DROP POLICY IF EXISTS por_empresa ON %I.%I', t.table_schema, t.table_name);
    EXECUTE format('CREATE POLICY por_empresa ON %I.%I USING (empresa_id = %s) WITH CHECK (empresa_id = %s)',
                   t.table_schema, t.table_name, expr, expr);
  END LOOP;

  ALTER TABLE identidad.empresa ENABLE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS por_empresa ON identidad.empresa;
  EXECUTE format('CREATE POLICY por_empresa ON identidad.empresa USING (id = %s) WITH CHECK (id = %s)',
                 expr, expr);
END $$;

-- Valida un código de invitación sin conocer la empresa (cognito-pre-signup).
-- Devuelve la empresa y el correo exigido solo si la invitación está vigente y sin usar.
CREATE OR REPLACE FUNCTION identidad.validar_invitacion(p_hash bytea)
  RETURNS TABLE (invitacion_id bigint, empresa_id bigint, correo_destino text)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, identidad AS $$
    SELECT i.id, i.empresa_id, i.correo_destino
    FROM identidad.invitacion_registro i
    JOIN identidad.empresa e ON e.id = i.empresa_id AND e.activa
    WHERE i.codigo_hash = p_hash AND i.usada_por_usuario_id IS NULL AND i.fecha_expira > now()
  $$;

-- Busca un usuario por su identificador de Cognito (cognito-pre-token).
CREATE OR REPLACE FUNCTION identidad.usuario_por_sub(p_sub text)
  RETURNS TABLE (usuario_id bigint, empresa_id bigint, rol text, activo boolean, ultima_actividad timestamptz)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, identidad AS $$
    SELECT u.id, u.empresa_id, u.rol, u.activo, u.ultima_actividad
    FROM identidad.usuario u WHERE u.cognito_sub = p_sub
  $$;

REVOKE ALL ON FUNCTION identidad.validar_invitacion(bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION identidad.usuario_por_sub(text) FROM PUBLIC;
