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

-- Descargas y verificación públicas de constancias (T-209): no hay sesión ni empresa, así que se
-- resuelven por funciones que solo ven lo mínimo y se ejecutan con los privilegios del dueño.
-- Estado de un token de descarga: VIGENTE, USADO, VENCIDO o NULL si no existe (CON-20).
CREATE OR REPLACE FUNCTION constancias.estado_token(p_hash bytea)
  RETURNS text
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, constancias AS $$
    SELECT CASE WHEN t.usado_en IS NOT NULL THEN 'USADO'
                WHEN t.fecha_expira <= now() THEN 'VENCIDO'
                WHEN c.estado_vigencia <> 'VIGENTE' THEN 'USADO'
                ELSE 'VIGENTE' END
    FROM constancias.token_descarga t
    JOIN constancias.constancia_generada c ON c.id = t.constancia_id
    WHERE t.token_hash = p_hash
  $$;
-- Consume el token una sola vez y devuelve el PDF a servir (CON-21). Atómico.
CREATE OR REPLACE FUNCTION constancias.consumir_token(p_hash bytea)
  RETURNS TABLE (empresa_id bigint, constancia_id bigint, pdf_s3_key text)
  LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, constancias AS $$
    UPDATE constancias.token_descarga t SET usado_en = now()
    FROM constancias.constancia_generada c
    WHERE t.token_hash = p_hash AND t.usado_en IS NULL AND t.fecha_expira > now()
      AND c.id = t.constancia_id AND c.estado_vigencia = 'VIGENTE'
    RETURNING t.empresa_id, t.constancia_id, c.pdf_s3_key
  $$;
-- Verificación pública por código del QR (CON-19): nunca datos sensibles.
CREATE OR REPLACE FUNCTION constancias.verificar_constancia(p_codigo text)
  RETURNS TABLE (nombre text, folio text, fecha timestamptz, estado text)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, constancias AS $$
    SELECT c.colaborador_nombre, c.folio, c.fecha_generacion, c.estado_vigencia
    FROM constancias.constancia_generada c WHERE c.codigo_verificacion = p_codigo
  $$;
REVOKE ALL ON FUNCTION constancias.estado_token(bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION constancias.consumir_token(bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION constancias.verificar_constancia(text) FROM PUBLIC;
