-- Permisos por servicio (design.md §2.6, T-030). Idempotente.
-- Regla: cada rol de servicio lee y escribe solo su esquema. La única excepción de lectura son
-- las vistas contractuales del dashboard. Todos insertan en la bitácora; nadie la modifica.

DO $$
DECLARE
  par record;
BEGIN
  FOR par IN
    SELECT * FROM (VALUES ('svc_dashboard', 'identidad'), ('svc_campos', 'campos'),
                          ('svc_colaboradores', 'colaboradores'), ('svc_whatsapp', 'whatsapp'),
                          ('svc_constancias', 'constancias'), ('svc_notificaciones', 'notificaciones')) v(rol, esquema)
  LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', par.esquema, par.rol);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO %I', par.esquema, par.rol);
    EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I', par.esquema, par.rol);
    EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA %I TO %I', par.esquema, par.rol);
    -- Bitácora: solo inserción.
    EXECUTE format('GRANT USAGE ON SCHEMA auditoria TO %I', par.rol);
    EXECUTE format('GRANT INSERT ON auditoria.bitacora TO %I', par.rol);
    EXECUTE format('GRANT USAGE ON ALL SEQUENCES IN SCHEMA auditoria TO %I', par.rol);
    EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON auditoria.bitacora FROM %I', par.rol);
  END LOOP;
END $$;

-- La alembic_version de cada esquema es solo para el migrador.
DO $$
DECLARE
  par record;
BEGIN
  FOR par IN
    SELECT * FROM (VALUES ('svc_dashboard', 'identidad'), ('svc_campos', 'campos'),
                          ('svc_colaboradores', 'colaboradores'), ('svc_whatsapp', 'whatsapp'),
                          ('svc_constancias', 'constancias'), ('svc_notificaciones', 'notificaciones')) v(rol, esquema)
  LOOP
    IF to_regclass(format('%I.alembic_version', par.esquema)) IS NOT NULL THEN
      EXECUTE format('REVOKE ALL ON %I.alembic_version FROM %I', par.esquema, par.rol);
    END IF;
  END LOOP;
END $$;

-- dashboard: lectura de la bitácora y de las vistas contractuales (nunca de las tablas).
GRANT SELECT ON auditoria.bitacora TO svc_dashboard;
GRANT USAGE ON SCHEMA colaboradores, constancias TO svc_dashboard;
GRANT SELECT ON colaboradores.v_resumen, colaboradores.v_alertas,
                constancias.v_resumen, constancias.v_historial,
                constancias.v_solicitudes_recientes, constancias.v_alertas TO svc_dashboard;
GRANT EXECUTE ON FUNCTION identidad.validar_invitacion(bytea), identidad.usuario_por_sub(text) TO svc_dashboard;

-- Las funciones de las vistas de colaboradores no deben ejecutarse por otros roles.
REVOKE EXECUTE ON FUNCTION colaboradores.f_unaccent(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION colaboradores.f_unaccent(text) TO svc_colaboradores;

-- El migrador administra todos los esquemas.
GRANT USAGE, CREATE ON SCHEMA identidad, auditoria, campos, colaboradores, whatsapp, constancias,
  notificaciones TO migrador;
