"""Esquemas identidad y auditoria (design.md §2.2, §2.3, §2.4, §2.7).

Revisión: 0001
Anterior: ninguna

Tablas: identidad.empresa, identidad.usuario, identidad.invitacion_registro y
auditoria.bitacora (inmutable, con detalle limitado a claves permitidas).
Requisitos: CC-REQ-007, 008, 010, 150, 154, 155, 156; CC-NFR-017.
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Debe coincidir con cc_common.bitacora.CLAVES_DETALLE (lo comprueba una prueba).
CLAVES_DETALLE = (
    "campos",
    "codigos_internos",
    "criterios",
    "totales",
    "estado_anterior",
    "estado_nuevo",
    "motivo",
    "folio",
    "plantilla_id",
    "version",
    "notificacion_id",
    "carga_id",
    "conversacion_id",
    "solicitud_id",
    "jti",
    "confirmada_fuera_horario",
    "proposito",
    "celular_hash",
)


def upgrade() -> None:
    lista = ", ".join(f"'{c}'" for c in CLAVES_DETALLE)
    op.execute(
        """
        CREATE TABLE identidad.empresa (
          id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          razon_social         text NOT NULL,
          rfc                  text,
          activa               boolean NOT NULL DEFAULT true,
          zona_horaria         text NOT NULL DEFAULT 'America/Mexico_City',
          horario_envio_inicio time NOT NULL DEFAULT '08:00',
          horario_envio_fin    time NOT NULL DEFAULT '20:00',
          fecha_creacion       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT empresa_horario_valido CHECK (horario_envio_inicio < horario_envio_fin)
        );

        CREATE TABLE identidad.usuario (
          id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id        bigint NOT NULL REFERENCES identidad.empresa (id),
          nombre            text NOT NULL,
          correo            text NOT NULL,
          cognito_sub       text NOT NULL,
          activo            boolean NOT NULL DEFAULT true,
          rol               text NOT NULL DEFAULT 'RH',
          ultima_actividad  timestamptz,
          fecha_creacion    timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT usuario_cognito_sub_key UNIQUE (cognito_sub),
          CONSTRAINT usuario_rol_valido CHECK (rol IN ('RH'))
        );
        CREATE UNIQUE INDEX usuario_correo_key ON identidad.usuario (lower(correo));
        CREATE INDEX usuario_empresa ON identidad.usuario (empresa_id, activo);

        CREATE TABLE identidad.invitacion_registro (
          id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id             bigint NOT NULL REFERENCES identidad.empresa (id),
          codigo_hash            bytea NOT NULL,
          correo_destino         text,
          creada_por_usuario_id  bigint REFERENCES identidad.usuario (id),
          fecha_creacion         timestamptz NOT NULL DEFAULT now(),
          fecha_expira           timestamptz NOT NULL,
          usada_por_usuario_id   bigint REFERENCES identidad.usuario (id),
          fecha_uso              timestamptz,
          CONSTRAINT invitacion_codigo_hash_key UNIQUE (codigo_hash),
          CONSTRAINT invitacion_hash_sha256 CHECK (octet_length(codigo_hash) = 32),
          CONSTRAINT invitacion_uso_coherente CHECK ((usada_por_usuario_id IS NULL) = (fecha_uso IS NULL))
        );
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION auditoria.detalle_permitido(d jsonb) RETURNS boolean
          LANGUAGE sql IMMUTABLE AS $$
            SELECT jsonb_typeof(d) = 'object'
               AND NOT EXISTS (SELECT 1 FROM jsonb_object_keys(d) k WHERE k NOT IN ({lista}))
          $$;

        CREATE TABLE auditoria.bitacora (
          id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id      bigint NOT NULL REFERENCES identidad.empresa (id),
          usuario_id      bigint REFERENCES identidad.usuario (id),
          colaborador_id  bigint,
          accion          text NOT NULL,
          entidad         text NOT NULL,
          entidad_id      bigint,
          fecha_hora      timestamptz NOT NULL DEFAULT now(),
          ip              inet,
          origen          text NOT NULL,
          detalle         jsonb NOT NULL DEFAULT '{{}}',
          CONSTRAINT bitacora_origen_valido CHECK (origen IN ('USUARIO', 'SISTEMA')),
          CONSTRAINT bitacora_detalle_permitido CHECK (auditoria.detalle_permitido(detalle))
        );
        CREATE INDEX bitacora_empresa_fecha ON auditoria.bitacora (empresa_id, fecha_hora DESC);
        CREATE INDEX bitacora_usuario_fecha ON auditoria.bitacora (empresa_id, usuario_id, fecha_hora DESC);
        CREATE INDEX bitacora_colaborador_fecha ON auditoria.bitacora (empresa_id, colaborador_id, fecha_hora DESC);
        CREATE INDEX bitacora_accion_fecha ON auditoria.bitacora (empresa_id, accion, fecha_hora DESC);

        CREATE FUNCTION auditoria.bitacora_inmutable() RETURNS trigger
          LANGUAGE plpgsql AS $$
          BEGIN
            RAISE EXCEPTION 'La bitácora no se modifica ni se borra (CC-REQ-155)'
              USING ERRCODE = 'insufficient_privilege';
          END $$;
        CREATE TRIGGER bitacora_sin_cambios BEFORE UPDATE OR DELETE ON auditoria.bitacora
          FOR EACH ROW EXECUTE FUNCTION auditoria.bitacora_inmutable();
        CREATE TRIGGER bitacora_sin_truncate BEFORE TRUNCATE ON auditoria.bitacora
          FOR EACH STATEMENT EXECUTE FUNCTION auditoria.bitacora_inmutable();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS auditoria.bitacora;
        DROP FUNCTION IF EXISTS auditoria.bitacora_inmutable();
        DROP FUNCTION IF EXISTS auditoria.detalle_permitido(jsonb);
        DROP TABLE IF EXISTS identidad.invitacion_registro;
        DROP TABLE IF EXISTS identidad.usuario;
        DROP TABLE IF EXISTS identidad.empresa;
        """
    )
