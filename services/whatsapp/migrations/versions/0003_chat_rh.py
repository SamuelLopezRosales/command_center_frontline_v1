"""Chat de RH (WAP-01 a WAP-05): comprobación de usuarios asignables e índices del listado.

Revisión: 0003
Anterior: 0002
Cambios:
- ``whatsapp.usuario_asignable(empresa, usuario)``: función ``SECURITY DEFINER`` de propósito único.
  El rol ``svc_whatsapp`` no puede leer ``identidad.usuario`` (cada servicio lee solo su esquema,
  design.md §2.6), y la llave foránea de ``asignada_a_usuario_id`` solo comprueba que el usuario
  exista en *alguna* empresa (DS-05: no valida que siga activo). La función devuelve únicamente
  verdadero o falso y exige que el usuario sea de la misma empresa. Decisión conservadora: no se
  agrega ninguna lectura de ``identidad`` al rol del servicio ni una interfaz con `dashboard`.
  ``grants.sql`` (que corre después de las migraciones) concede ``EXECUTE`` a ``svc_whatsapp``.
- Índices del listado de conversaciones y de los mensajes de notificación de un colaborador
  (filtro ``notificacion_id`` de WAP-01 y hilo de WAP-02).
Requisitos: CC-REQ-115, 116.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION whatsapp.usuario_asignable(p_empresa bigint, p_usuario bigint)
          RETURNS boolean
          LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, identidad AS $$
            SELECT EXISTS (
              SELECT 1 FROM identidad.usuario u WHERE u.id = p_usuario AND u.empresa_id = p_empresa
            )
          $$;
        REVOKE ALL ON FUNCTION whatsapp.usuario_asignable(bigint, bigint) FROM PUBLIC;

        CREATE INDEX mensaje_colaborador_origen
          ON whatsapp.mensaje_whatsapp (colaborador_id, origen_tipo, origen_id)
          WHERE direccion = 'SALIENTE';
        CREATE INDEX conversacion_listado
          ON whatsapp.conversacion_whatsapp (empresa_id, fecha_ultimo_mensaje DESC, id DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS whatsapp.conversacion_listado;
        DROP INDEX IF EXISTS whatsapp.mensaje_colaborador_origen;
        DROP FUNCTION IF EXISTS whatsapp.usuario_asignable(bigint, bigint);
        """
    )
