"""Esquema notificaciones (design.md §2.2, §2.3, §2.4, §6).

Revisión: 0001
Anterior: ninguna (requiere identidad y whatsapp 0001)

Tablas: audiencia, plantilla_mensaje, notificacion, notificacion_destinatario, outbox y
evento_procesado; función ``rango_estado_envio`` (los estados de entrega solo avanzan).
Requisitos: CC-REQ-100, 101, 105, 106, 112, 114, 117, 119, 121.
"""

from alembic import op
from cc_common.outbox import ddl

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE notificaciones.audiencia (
          id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id             bigint NOT NULL REFERENCES identidad.empresa (id),
          nombre                 text NOT NULL,
          activa                 boolean NOT NULL DEFAULT true,
          criterios_json         jsonb NOT NULL CHECK (jsonb_typeof(criterios_json) = 'object'),
          creada_por_usuario_id  bigint NOT NULL REFERENCES identidad.usuario (id),
          fecha_creacion         timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX audiencia_nombre_key ON notificaciones.audiencia (empresa_id, lower(nombre)) WHERE activa;

        CREATE TABLE notificaciones.plantilla_mensaje (
          id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id             bigint NOT NULL REFERENCES identidad.empresa (id),
          creada_por_usuario_id  bigint NOT NULL REFERENCES identidad.usuario (id),
          nombre                 text NOT NULL CHECK (nombre ~ '^[a-z0-9_]+$' AND length(nombre) <= 512),
          categoria              text NOT NULL,
          texto_con_variables    text NOT NULL,
          estado_meta            text NOT NULL DEFAULT 'BORRADOR',
          id_plantilla_meta      text,
          motivo_rechazo         text,
          idioma                 text NOT NULL DEFAULT 'es_MX',
          ejemplos_json          jsonb,
          fecha_creacion         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT plantilla_mensaje_empresa_id_nombre_key UNIQUE (empresa_id, nombre),
          CONSTRAINT plantilla_mensaje_estado_valido CHECK (estado_meta IN ('BORRADOR', 'EN_REVISION', 'APROBADA', 'RECHAZADA')),
          CONSTRAINT plantilla_mensaje_categoria_valida CHECK (categoria IN ('UTILITY', 'MARKETING', 'AUTHENTICATION'))
        );

        CREATE TABLE notificaciones.notificacion (
          id                        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id                bigint NOT NULL REFERENCES identidad.empresa (id),
          usuario_id                bigint NOT NULL REFERENCES identidad.usuario (id),
          audiencia_id              bigint REFERENCES notificaciones.audiencia (id),
          plantilla_mensaje_id      bigint REFERENCES notificaciones.plantilla_mensaje (id),
          canal                     text NOT NULL DEFAULT 'PLANTILLA_META',
          mensaje                   text,
          variables_json            jsonb,
          criterios_snapshot_json   jsonb,
          respaldo_correo           boolean NOT NULL DEFAULT false,
          programada_para           timestamptz,
          zona_horaria              text NOT NULL,
          estado                    text NOT NULL DEFAULT 'BORRADOR',
          total_seleccionados       int,
          total_excluidos           int,
          fecha_creacion            timestamptz NOT NULL DEFAULT now(),
          fecha_envio               timestamptz,
          titulo                    text NOT NULL,
          modo                      text NOT NULL,
          revisada_en               timestamptz,
          confirmada_fuera_horario  boolean NOT NULL DEFAULT false,
          schedule_nombre           text,
          motivo_cancelacion        text,
          CONSTRAINT notificacion_canal_valido CHECK (canal IN ('PLANTILLA_META', 'RESPUESTA_24H')),
          CONSTRAINT notificacion_estado_valido CHECK (estado IN ('BORRADOR', 'PROGRAMADA', 'ENVIANDO', 'COMPLETADA', 'CON_FALLAS', 'CANCELADA')),
          CONSTRAINT notificacion_modo_valido CHECK (modo IN ('CRITERIOS', 'INDIVIDUAL', 'GRUPO')),
          CONSTRAINT notificacion_programada_con_fecha CHECK (estado <> 'PROGRAMADA' OR programada_para IS NOT NULL)
        );
        CREATE INDEX notificacion_empresa_estado ON notificaciones.notificacion (empresa_id, estado, fecha_creacion DESC);
        CREATE INDEX notificacion_programadas ON notificaciones.notificacion (estado, programada_para) WHERE estado = 'PROGRAMADA';

        CREATE TABLE notificaciones.notificacion_destinatario (
          id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id            bigint NOT NULL REFERENCES identidad.empresa (id),
          notificacion_id       bigint NOT NULL REFERENCES notificaciones.notificacion (id),
          colaborador_id        bigint NOT NULL,
          conversacion_id       bigint REFERENCES whatsapp.conversacion_whatsapp (id),
          estado_envio          text NOT NULL DEFAULT 'PENDIENTE',
          motivo_exclusion      text,
          canal_usado           text,
          id_mensaje_proveedor  text,
          intentos              int NOT NULL DEFAULT 0,
          fecha_estado          timestamptz NOT NULL DEFAULT now(),
          colaborador_nombre    text NOT NULL,
          planta_nombre         text,
          celular_ultimos4      char(4),
          encolado_en           timestamptz,
          motivo_fallo          text,
          respaldo_enviado_en   timestamptz,
          CONSTRAINT destinatario_notificacion_id_colaborador_id_key UNIQUE (notificacion_id, colaborador_id),
          CONSTRAINT destinatario_estado_valido CHECK (estado_envio IN ('PENDIENTE', 'EXCLUIDO', 'ENVIADO', 'ENTREGADO', 'LEIDO', 'RESPONDIO', 'FALLIDO')),
          CONSTRAINT destinatario_motivo_valido CHECK (motivo_exclusion IN ('SIN_CONSENTIMIENTO', 'ESTATUS_BAJA', 'SIN_CELULAR_VALIDO')),
          CONSTRAINT destinatario_canal_valido CHECK (canal_usado IN ('WHATSAPP', 'CORREO')),
          CONSTRAINT destinatario_excluido_con_motivo CHECK ((estado_envio = 'EXCLUIDO') = (motivo_exclusion IS NOT NULL))
        );
        CREATE INDEX destinatario_pendientes ON notificaciones.notificacion_destinatario (notificacion_id)
          WHERE estado_envio = 'PENDIENTE' AND encolado_en IS NULL;
        CREATE INDEX destinatario_estado ON notificaciones.notificacion_destinatario (notificacion_id, estado_envio);
        CREATE INDEX destinatario_proveedor ON notificaciones.notificacion_destinatario (id_mensaje_proveedor)
          WHERE id_mensaje_proveedor IS NOT NULL;

        -- Orden de estados del destinatario: los estados de entrega solo avanzan (RN-21).
        CREATE FUNCTION notificaciones.rango_estado_envio(e text) RETURNS int
          LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
            SELECT CASE e WHEN 'PENDIENTE' THEN 0 WHEN 'ENVIADO' THEN 10 WHEN 'FALLIDO' THEN 15
                          WHEN 'ENTREGADO' THEN 20 WHEN 'LEIDO' THEN 30 WHEN 'RESPONDIO' THEN 40
                          WHEN 'EXCLUIDO' THEN 1000 ELSE NULL END
          $$;
        """
    )
    op.execute(ddl("notificaciones"))


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS notificaciones.evento_procesado;
        DROP TABLE IF EXISTS notificaciones.outbox;
        DROP TABLE IF EXISTS notificaciones.notificacion_destinatario;
        DROP TABLE IF EXISTS notificaciones.notificacion;
        DROP TABLE IF EXISTS notificaciones.plantilla_mensaje;
        DROP TABLE IF EXISTS notificaciones.audiencia;
        DROP FUNCTION IF EXISTS notificaciones.rango_estado_envio(text);
        """
    )
