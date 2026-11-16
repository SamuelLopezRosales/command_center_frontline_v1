"""Soporte del conciliador y de las Lambdas de notificaciones (T-217).

Revisión: 0003
Anterior: 0002

- ``notificacion.reencolada_en``: el conciliador la marca al reencolar un INICIO (una PROGRAMADA
  atrasada) o un respaldo por correo; con ella no repite el trabajo en dos ciclos seguidos.
- Cuatro funciones ``SECURITY DEFINER`` de propósito único ``notificaciones.conciliar_*`` (mismo
  patrón que ``plantillas_en_revision_por_nombre``): el conciliador recorre **todas** las empresas y
  la RLS exige ``app.empresa_id``, así que las funciones devuelven solo ``(id, empresa_id)`` (y la
  zona horaria en los respaldos). Después la Lambda fija la empresa de cada fila y actúa con la RLS
  vigente. Reciben ``p_ahora`` (el reloj de la Lambda; las pruebas lo controlan).

El SQL es el de ``lambdas/notif_comun/sql/conciliacion.sql`` (lo aplican las pruebas de las Lambdas
como administrador); una prueba de este servicio comprueba que no diverjan. Es idempotente
(``IF NOT EXISTS`` y ``CREATE OR REPLACE``). ``REVOKE`` a PUBLIC y ``GRANT EXECUTE`` a
``svc_notificaciones``; el ``GRANT`` solo se emite si el rol ya existe (``infra/db/roles.sql`` se
aplica después de las migraciones y ``grants.sql`` concede lo mismo de forma general).

Requisitos: CC-REQ-108, 110, 111, 113.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

FUNCIONES = (
    "notificaciones.conciliar_programadas_atrasadas(timestamptz, int, int)",
    "notificaciones.conciliar_encolados_atascados(timestamptz, int)",
    "notificaciones.conciliar_respaldos_pendientes(timestamptz, int, int, int)",
    "notificaciones.conciliar_cierres_pendientes()",
)

SQL_CONCILIACION = """
ALTER TABLE notificaciones.notificacion ADD COLUMN IF NOT EXISTS reencolada_en timestamptz;

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
"""

SQL_PERMISOS = (
    "REVOKE ALL ON FUNCTION "
    + ",\n                       ".join(FUNCIONES)
    + " FROM PUBLIC;\n"
    + "DO $$ BEGIN\n"
    + "  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_notificaciones') THEN\n"
    + "    GRANT EXECUTE ON FUNCTION "
    + ",\n                              ".join(FUNCIONES)
    + " TO svc_notificaciones;\n"
    + "  END IF;\n"
    + "END $$;\n"
)


def upgrade() -> None:
    op.execute(SQL_CONCILIACION)
    op.execute(SQL_PERMISOS)


def downgrade() -> None:
    for funcion in FUNCIONES:
        op.execute(f"DROP FUNCTION IF EXISTS {funcion}")
    op.execute("ALTER TABLE notificaciones.notificacion DROP COLUMN IF EXISTS reencolada_en")
