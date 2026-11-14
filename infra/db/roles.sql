-- Roles de base de datos (design.md §2.6, T-030). Idempotente: se puede ejecutar varias veces.
-- Las contraseñas NO se fijan aquí: las asigna scripts/asignar_contrasenas.py desde Secrets
-- Manager (cc/{env}/db/{rol}).
--
-- Corre con el usuario maestro de RDS, que NO es superusuario (tiene CREATEROLE). PostgreSQL
-- exige ser superusuario para ejecutar ALTER ROLE ... NOSUPERUSER/NOBYPASSRLS aunque el rol ya
-- tenga esos atributos (falló en T-047). Por eso el ALTER solo se intenta si un rol realmente
-- tiene SUPERUSER o BYPASSRLS; en ese caso el error es intencional: un rol de servicio con esos
-- atributos rompería el aislamiento por empresa (RLS) y no debe pasar en silencio.
DO $$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['svc_dashboard', 'svc_colaboradores', 'svc_campos', 'svc_constancias',
                           'svc_notificaciones', 'svc_whatsapp']
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      -- NOSUPERUSER y NOBYPASSRLS son los valores por defecto de CREATE ROLE.
      EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', r);
    END IF;
    -- Los roles de servicio nunca son dueños de tablas ni evitan RLS.
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r AND (rolsuper OR rolbypassrls)) THEN
      EXECUTE format('ALTER ROLE %I NOSUPERUSER NOBYPASSRLS', r);
    END IF;
  END LOOP;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'migrador') THEN
    CREATE ROLE migrador LOGIN NOSUPERUSER NOCREATEROLE;
  END IF;
END $$;
