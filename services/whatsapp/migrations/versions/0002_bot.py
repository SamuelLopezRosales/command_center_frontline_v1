"""Bot de WhatsApp: solicitud en curso por conversación y contadores de uso por número.

Revisión: 0002
Anterior: 0001
Cambios: ``conversacion_whatsapp.solicitud_constancia_id`` (solicitud abierta de la conversación,
sin llave foránea: pertenece a `constancias`) y ``uso_numero`` (antiabuso: mensajes por minuto y
solicitudes por día de cada número, DS-17).
Requisitos: CC-REQ-071, 073, 074, 091, 159.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE whatsapp.conversacion_whatsapp ADD COLUMN solicitud_constancia_id bigint;

        CREATE TABLE whatsapp.uso_numero (
          id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id     bigint NOT NULL REFERENCES identidad.empresa (id),
          celular_hash   bytea NOT NULL CHECK (octet_length(celular_hash) = 32),
          tipo           text NOT NULL CHECK (tipo IN ('MENSAJE', 'SOLICITUD')),
          ventana        timestamptz NOT NULL,
          total          int NOT NULL DEFAULT 0 CHECK (total >= 0),
          CONSTRAINT uso_numero_ventana_key UNIQUE (empresa_id, celular_hash, tipo, ventana)
        );
        CREATE INDEX uso_numero_ventana ON whatsapp.uso_numero (ventana);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS whatsapp.uso_numero;
        ALTER TABLE whatsapp.conversacion_whatsapp DROP COLUMN IF EXISTS solicitud_constancia_id;
        """
    )
