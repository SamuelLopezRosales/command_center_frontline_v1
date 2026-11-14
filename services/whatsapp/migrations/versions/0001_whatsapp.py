"""Esquema whatsapp (design.md §2.2, §2.3, §7).

Revisión: 0001
Anterior: ninguna (requiere identidad 0001 y colaboradores 0001)

Tablas: conversacion_whatsapp, mensaje_whatsapp, codigo_verificacion, clave_datos, outbox y
evento_procesado; función de orden de estados de mensaje.
Requisitos: CC-REQ-073, 074, 086, 114, 115, 116.
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
        CREATE TABLE whatsapp.conversacion_whatsapp (
          id                          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id                  bigint NOT NULL REFERENCES identidad.empresa (id),
          colaborador_id              bigint REFERENCES colaboradores.colaborador (id),
          estado                      text NOT NULL DEFAULT 'VERIFICANDO',
          intentos_verificacion       int NOT NULL DEFAULT 0 CHECK (intentos_verificacion BETWEEN 0 AND 3),
          fecha_inicio                timestamptz NOT NULL DEFAULT now(),
          fecha_ultimo_mensaje        timestamptz NOT NULL DEFAULT now(),
          celular_hash                bytea NOT NULL CHECK (octet_length(celular_hash) = 32),
          origen                      text NOT NULL,
          verificada                  boolean NOT NULL DEFAULT false,
          ultimo_mensaje_entrante_at  timestamptz,
          bloqueada_hasta             timestamptz,
          asignada_a_usuario_id       bigint REFERENCES identidad.usuario (id),
          fecha_asignacion            timestamptz,
          CONSTRAINT conversacion_estado_valido CHECK (estado IN ('VERIFICANDO', 'ACTIVA', 'BLOQUEADA', 'CERRADA')),
          CONSTRAINT conversacion_origen_valido CHECK (origen IN ('CONSTANCIA', 'NOTIFICACION')),
          CONSTRAINT conversacion_bloqueo_coherente CHECK (estado <> 'BLOQUEADA' OR bloqueada_hasta IS NOT NULL)
        );
        CREATE UNIQUE INDEX conversacion_una_verificacion
          ON whatsapp.conversacion_whatsapp (colaborador_id) WHERE estado = 'VERIFICANDO';
        CREATE UNIQUE INDEX conversacion_una_abierta_por_numero
          ON whatsapp.conversacion_whatsapp (empresa_id, celular_hash)
          WHERE estado IN ('VERIFICANDO', 'ACTIVA', 'BLOQUEADA');
        CREATE INDEX conversacion_asignacion
          ON whatsapp.conversacion_whatsapp (empresa_id, asignada_a_usuario_id, fecha_ultimo_mensaje DESC);

        CREATE TABLE whatsapp.mensaje_whatsapp (
          id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id              bigint NOT NULL REFERENCES identidad.empresa (id),
          conversacion_id         bigint REFERENCES whatsapp.conversacion_whatsapp (id),
          colaborador_id          bigint,
          direccion               text NOT NULL,
          tipo                    text NOT NULL,
          plantilla_meta          text,
          contenido_cifrado       bytea,
          id_mensaje_proveedor    text,
          clave_idempotencia      uuid NOT NULL,
          estado                  text NOT NULL,
          origen_tipo             text NOT NULL,
          origen_id               bigint,
          intentos                int NOT NULL DEFAULT 0,
          error_codigo            text,
          enviado_por_usuario_id  bigint REFERENCES identidad.usuario (id),
          fecha_hora              timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT mensaje_clave_idempotencia_key UNIQUE (clave_idempotencia),
          CONSTRAINT mensaje_direccion_valida CHECK (direccion IN ('ENTRANTE', 'SALIENTE')),
          CONSTRAINT mensaje_tipo_valido CHECK (tipo IN ('TEXTO', 'PLANTILLA', 'INTERACTIVO')),
          CONSTRAINT mensaje_estado_valido CHECK (estado IN ('ENCOLADO', 'ENVIADO', 'ENTREGADO', 'LEIDO', 'FALLIDO', 'RECIBIDO')),
          CONSTRAINT mensaje_origen_valido CHECK (origen_tipo IN ('VERIFICACION', 'CONSTANCIA', 'NOTIFICACION', 'CHAT', 'BOT'))
        );
        CREATE UNIQUE INDEX mensaje_id_proveedor_key ON whatsapp.mensaje_whatsapp (id_mensaje_proveedor)
          WHERE id_mensaje_proveedor IS NOT NULL;
        CREATE INDEX mensaje_conversacion_fecha ON whatsapp.mensaje_whatsapp (conversacion_id, fecha_hora DESC);

        CREATE TABLE whatsapp.codigo_verificacion (
          id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id       bigint NOT NULL REFERENCES identidad.empresa (id),
          conversacion_id  bigint NOT NULL REFERENCES whatsapp.conversacion_whatsapp (id),
          codigo_hmac      bytea NOT NULL CHECK (octet_length(codigo_hmac) = 32),
          fecha_creacion   timestamptz NOT NULL DEFAULT now(),
          fecha_expira     timestamptz NOT NULL,
          usado            boolean NOT NULL DEFAULT false,
          CONSTRAINT codigo_expira_10_min CHECK (fecha_expira <= fecha_creacion + interval '10 minutes')
        );
        CREATE INDEX codigo_conversacion ON whatsapp.codigo_verificacion (conversacion_id) WHERE NOT usado;

        CREATE TABLE whatsapp.clave_datos (
          empresa_id      bigint NOT NULL REFERENCES identidad.empresa (id),
          version         int NOT NULL CHECK (version > 0),
          dek_cifrada     bytea NOT NULL,
          activa          boolean NOT NULL DEFAULT true,
          fecha_creacion  timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (empresa_id, version)
        );
        CREATE UNIQUE INDEX clave_datos_una_activa ON whatsapp.clave_datos (empresa_id) WHERE activa;

        -- Orden de estados de un mensaje saliente: solo avanzan (CC-REQ-114, RN-21).
        CREATE FUNCTION whatsapp.rango_estado_mensaje(e text) RETURNS int
          LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
            SELECT CASE e WHEN 'ENCOLADO' THEN 0 WHEN 'ENVIADO' THEN 10 WHEN 'FALLIDO' THEN 15
                          WHEN 'ENTREGADO' THEN 20 WHEN 'LEIDO' THEN 30 WHEN 'RECIBIDO' THEN 100
                          ELSE NULL END
          $$;
        """
    )
    op.execute(ddl("whatsapp"))


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS whatsapp.evento_procesado;
        DROP TABLE IF EXISTS whatsapp.outbox;
        DROP TABLE IF EXISTS whatsapp.clave_datos;
        DROP TABLE IF EXISTS whatsapp.codigo_verificacion;
        DROP TABLE IF EXISTS whatsapp.mensaje_whatsapp;
        DROP TABLE IF EXISTS whatsapp.conversacion_whatsapp;
        DROP FUNCTION IF EXISTS whatsapp.rango_estado_mensaje(text);
        """
    )
