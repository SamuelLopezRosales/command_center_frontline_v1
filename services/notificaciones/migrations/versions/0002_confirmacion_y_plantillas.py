"""Confirmación del envío y estado de plantillas por evento (T-216).

Revisión: 0002
Anterior: 0001

- ``notificacion``: ``modo_envio`` (AHORA o PROGRAMAR), ``confirmada_en`` y
  ``confirmada_por_usuario_id`` (quién confirmó y cuándo; con ``confirmada_fuera_horario`` deja
  constancia de quién autorizó un envío fuera de horario, CC-REQ-109).
- ``plantillas_en_revision_por_nombre``: función ``SECURITY DEFINER`` de propósito único. El evento
  ``wa.plantilla_estado`` identifica la plantilla solo por su nombre (la cuenta de WhatsApp es
  única) y no trae empresa, así que el consumidor no puede fijarla antes de leer; la función
  devuelve únicamente ``(id, empresa_id)`` de las plantillas EN_REVISION con ese nombre
  (mismo patrón que ``whatsapp.mensaje_por_proveedor``). Después el consumidor fija la empresa de
  cada una y actualiza con RLS vigente.

Requisitos: CC-REQ-108, 109, 117, 120.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE notificaciones.notificacion
          ADD COLUMN modo_envio text,
          ADD COLUMN confirmada_en timestamptz,
          ADD COLUMN confirmada_por_usuario_id bigint REFERENCES identidad.usuario (id),
          ADD CONSTRAINT notificacion_modo_envio_valido CHECK (modo_envio IN ('AHORA', 'PROGRAMAR'));

        CREATE FUNCTION notificaciones.plantillas_en_revision_por_nombre(p_nombre text)
          RETURNS TABLE (id bigint, empresa_id bigint)
          LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, notificaciones AS $$
            SELECT p.id, p.empresa_id FROM notificaciones.plantilla_mensaje p
            WHERE p.nombre = p_nombre AND p.estado_meta = 'EN_REVISION'
          $$;
        REVOKE ALL ON FUNCTION notificaciones.plantillas_en_revision_por_nombre(text) FROM PUBLIC;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS notificaciones.plantillas_en_revision_por_nombre(text);
        ALTER TABLE notificaciones.notificacion
          DROP CONSTRAINT IF EXISTS notificacion_modo_envio_valido,
          DROP COLUMN IF EXISTS confirmada_por_usuario_id,
          DROP COLUMN IF EXISTS confirmada_en,
          DROP COLUMN IF EXISTS modo_envio;
        """
    )
