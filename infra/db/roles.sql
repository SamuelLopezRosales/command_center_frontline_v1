-- Roles de base de datos (design.md §2.6, T-030). Idempotente: se puede ejecutar varias veces.
-- Las contraseñas NO se fijan aquí: las asigna la rotación de Secrets Manager (cc/{env}/db/{rol}).
DO $$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['svc_dashboard', 'svc_colaboradores', 'svc_campos', 'svc_constancias',
                           'svc_notificaciones', 'svc_whatsapp']
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', r);
    END IF;
    -- Los roles de servicio nunca son dueños de tablas ni evitan RLS.
    EXECUTE format('ALTER ROLE %I NOSUPERUSER NOBYPASSRLS', r);
  END LOOP;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'migrador') THEN
    CREATE ROLE migrador LOGIN NOSUPERUSER NOCREATEROLE;
  END IF;
END $$;
