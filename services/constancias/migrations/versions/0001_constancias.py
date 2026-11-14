"""Esquema constancias (design.md §2.2, §2.3, §2.4, §2.7, §5).

Revisión: 0001
Anterior: ninguna (requiere identidad, colaboradores y whatsapp 0001)

Tablas: plantilla_constancia, version_plantilla (inmutable), borrador_plantilla,
solicitud_constancia, constancia_generada (inmutable salvo entrega y vigencia),
contador_folio, token_descarga, alerta_plantilla, clave_datos, outbox y evento_procesado.
Vistas contractuales del dashboard: v_resumen, v_historial, v_solicitudes_recientes, v_alertas.

Desviación de design.md §2.6: las vistas no son ``security_invoker``. Pertenecen al rol dueño y
filtran explícitamente por ``app.empresa_id``; ``svc_dashboard`` solo recibe SELECT sobre
las vistas, nunca sobre las tablas de este esquema.
Requisitos: CC-REQ-011, 012, 013, 064, 066, 079, 081, 082, 084, 087, 090.
"""

from alembic import op
from cc_common.outbox import ddl

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

EMPRESA_ACTUAL = "NULLIF(current_setting('app.empresa_id', true), '')::bigint"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE constancias.plantilla_constancia (
          id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id          bigint NOT NULL REFERENCES identidad.empresa (id),
          nombre              text NOT NULL CHECK (length(nombre) BETWEEN 1 AND 120),
          descripcion         text,
          activa              boolean NOT NULL DEFAULT false,
          eliminada           boolean NOT NULL DEFAULT false,
          fecha_creacion      timestamptz NOT NULL DEFAULT now(),
          fecha_modificacion  timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT plantilla_eliminada_inactiva CHECK (NOT (eliminada AND activa))
        );
        CREATE UNIQUE INDEX plantilla_nombre_key ON constancias.plantilla_constancia (empresa_id, lower(nombre))
          WHERE NOT eliminada;

        CREATE TABLE constancias.version_plantilla (
          id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id             bigint NOT NULL REFERENCES identidad.empresa (id),
          plantilla_id           bigint NOT NULL REFERENCES constancias.plantilla_constancia (id),
          numero                 int NOT NULL CHECK (numero > 0),
          contenido_s3_key       text NOT NULL,
          hash_sha256            char(64) NOT NULL CHECK (hash_sha256 ~ '^[0-9a-f]{64}$'),
          creada_por_usuario_id  bigint NOT NULL REFERENCES identidad.usuario (id),
          fecha_creacion         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT version_plantilla_plantilla_id_numero_key UNIQUE (plantilla_id, numero)
        );

        CREATE FUNCTION constancias.version_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'Una versión publicada no se modifica (CC-REQ-066)'
            USING ERRCODE = 'insufficient_privilege';
        END $$;
        CREATE TRIGGER version_sin_cambios BEFORE UPDATE OR DELETE ON constancias.version_plantilla
          FOR EACH ROW EXECUTE FUNCTION constancias.version_inmutable();

        CREATE TABLE constancias.borrador_plantilla (
          plantilla_id                bigint PRIMARY KEY REFERENCES constancias.plantilla_constancia (id),
          empresa_id                  bigint NOT NULL REFERENCES identidad.empresa (id),
          contenido_s3_key            text NOT NULL,
          hash_sha256                 char(64) NOT NULL CHECK (hash_sha256 ~ '^[0-9a-f]{64}$'),
          actualizado_por_usuario_id  bigint REFERENCES identidad.usuario (id),
          fecha_modificacion          timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE constancias.solicitud_constancia (
          id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id            bigint NOT NULL REFERENCES identidad.empresa (id),
          colaborador_id        bigint NOT NULL REFERENCES colaboradores.colaborador (id),
          conversacion_id       bigint REFERENCES whatsapp.conversacion_whatsapp (id),
          version_plantilla_id  bigint REFERENCES constancias.version_plantilla (id),
          estado                text NOT NULL DEFAULT 'RECIBIDA',
          motivo_fallo          text,
          fecha_solicitud       timestamptz NOT NULL DEFAULT now(),
          fecha_atencion        timestamptz,
          colaborador_nombre    text NOT NULL,
          folio_reservado       text,
          intentos_entrega      smallint NOT NULL DEFAULT 0 CHECK (intentos_entrega BETWEEN 0 AND 2),
          CONSTRAINT solicitud_estado_valido CHECK (estado IN ('RECIBIDA', 'EN_PROCESO', 'GENERADA', 'ENTREGADA', 'FALLIDA', 'CANCELADA')),
          CONSTRAINT solicitud_motivo_si_fallida CHECK (estado <> 'FALLIDA' OR motivo_fallo IS NOT NULL)
        );
        CREATE UNIQUE INDEX solicitud_una_abierta_por_conversacion ON constancias.solicitud_constancia (conversacion_id)
          WHERE estado IN ('RECIBIDA', 'EN_PROCESO');
        CREATE INDEX solicitud_estado_fecha ON constancias.solicitud_constancia (empresa_id, estado, fecha_solicitud DESC);

        CREATE TABLE constancias.constancia_generada (
          id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id               bigint NOT NULL REFERENCES identidad.empresa (id),
          solicitud_id             bigint NOT NULL REFERENCES constancias.solicitud_constancia (id),
          colaborador_id           bigint NOT NULL REFERENCES colaboradores.colaborador (id),
          version_plantilla_id     bigint NOT NULL REFERENCES constancias.version_plantilla (id),
          generada_por_usuario_id  bigint REFERENCES identidad.usuario (id),
          folio                    text NOT NULL CHECK (folio ~ '^CG-[0-9]{4}-[0-9]{4,}$'),
          pdf_s3_key               text NOT NULL,
          pdf_hash_sha256          char(64) NOT NULL CHECK (pdf_hash_sha256 ~ '^[0-9a-f]{64}$'),
          datos_snapshot_json      jsonb NOT NULL CHECK (jsonb_typeof(datos_snapshot_json) = 'object'),
          estado_entrega           text NOT NULL DEFAULT 'PENDIENTE',
          fecha_generacion         timestamptz NOT NULL DEFAULT now(),
          fecha_entrega            timestamptz,
          colaborador_nombre       text NOT NULL,
          numero_empleado          text NOT NULL,
          codigo_verificacion      text NOT NULL,
          estado_vigencia          text NOT NULL DEFAULT 'VIGENTE',
          fecha_cancelacion        timestamptz,
          motivo_cancelacion       text,
          CONSTRAINT constancia_solicitud_id_key UNIQUE (solicitud_id),
          CONSTRAINT constancia_empresa_id_folio_key UNIQUE (empresa_id, folio),
          CONSTRAINT constancia_codigo_verificacion_key UNIQUE (codigo_verificacion),
          CONSTRAINT constancia_estado_entrega_valido CHECK (estado_entrega IN ('PENDIENTE', 'ENTREGADA', 'FALLIDA')),
          CONSTRAINT constancia_vigencia_valida CHECK (estado_vigencia IN ('VIGENTE', 'CANCELADA')),
          CONSTRAINT constancia_sin_generador_rh CHECK (generada_por_usuario_id IS NULL),
          CONSTRAINT constancia_codigo_largo CHECK (length(codigo_verificacion) >= 22)
        );
        CREATE INDEX constancia_fecha ON constancias.constancia_generada (empresa_id, fecha_generacion DESC, id DESC);
        CREATE INDEX constancia_version ON constancias.constancia_generada (empresa_id, version_plantilla_id);
        CREATE INDEX constancia_colaborador ON constancias.constancia_generada (empresa_id, colaborador_id);
        CREATE INDEX constancia_estado ON constancias.constancia_generada (empresa_id, estado_entrega);
        CREATE INDEX constancia_nombre_trgm ON constancias.constancia_generada USING gin (lower(colaborador_nombre) gin_trgm_ops);
        CREATE INDEX constancia_folio_trgm ON constancias.constancia_generada USING gin (lower(folio) gin_trgm_ops);

        -- Una constancia emitida solo cambia su entrega y su vigencia (RN-11, CC-REQ-082).
        CREATE FUNCTION constancias.constancia_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Una constancia emitida no se borra' USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF (NEW.id, NEW.empresa_id, NEW.solicitud_id, NEW.colaborador_id, NEW.version_plantilla_id,
              NEW.generada_por_usuario_id, NEW.folio, NEW.pdf_s3_key, NEW.pdf_hash_sha256,
              NEW.datos_snapshot_json, NEW.fecha_generacion, NEW.colaborador_nombre,
              NEW.numero_empleado, NEW.codigo_verificacion)
             IS DISTINCT FROM
             (OLD.id, OLD.empresa_id, OLD.solicitud_id, OLD.colaborador_id, OLD.version_plantilla_id,
              OLD.generada_por_usuario_id, OLD.folio, OLD.pdf_s3_key, OLD.pdf_hash_sha256,
              OLD.datos_snapshot_json, OLD.fecha_generacion, OLD.colaborador_nombre,
              OLD.numero_empleado, OLD.codigo_verificacion) THEN
            RAISE EXCEPTION 'Una constancia emitida no se modifica' USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER constancia_sin_cambios BEFORE UPDATE OR DELETE ON constancias.constancia_generada
          FOR EACH ROW EXECUTE FUNCTION constancias.constancia_inmutable();

        CREATE TABLE constancias.contador_folio (
          empresa_id  bigint NOT NULL REFERENCES identidad.empresa (id),
          anio        int NOT NULL CHECK (anio BETWEEN 2020 AND 2200),
          ultimo      int NOT NULL DEFAULT 0 CHECK (ultimo >= 0),
          PRIMARY KEY (empresa_id, anio)
        );

        CREATE TABLE constancias.token_descarga (
          id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id     bigint NOT NULL REFERENCES identidad.empresa (id),
          constancia_id  bigint NOT NULL REFERENCES constancias.constancia_generada (id),
          token_hash     bytea NOT NULL CHECK (octet_length(token_hash) = 32),
          fecha_creacion timestamptz NOT NULL DEFAULT now(),
          fecha_expira   timestamptz NOT NULL,
          usado_en       timestamptz,
          generado_por   text NOT NULL,
          usuario_id     bigint REFERENCES identidad.usuario (id),
          CONSTRAINT token_descarga_token_hash_key UNIQUE (token_hash),
          CONSTRAINT token_generado_por_valido CHECK (generado_por IN ('BOT', 'RH_REENVIO')),
          CONSTRAINT token_vigencia_24h CHECK (fecha_expira <= fecha_creacion + interval '24 hours')
        );

        CREATE TABLE constancias.alerta_plantilla (
          id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id       bigint NOT NULL REFERENCES identidad.empresa (id),
          plantilla_id     bigint NOT NULL REFERENCES constancias.plantilla_constancia (id),
          codigo_interno   text NOT NULL,
          total_afectados  int NOT NULL CHECK (total_afectados >= 0),
          fecha_calculo    timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT alerta_plantilla_campo_key UNIQUE (plantilla_id, codigo_interno)
        );

        CREATE TABLE constancias.clave_datos (
          empresa_id      bigint NOT NULL REFERENCES identidad.empresa (id),
          version         int NOT NULL CHECK (version > 0),
          dek_cifrada     bytea NOT NULL,
          activa          boolean NOT NULL DEFAULT true,
          fecha_creacion  timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (empresa_id, version)
        );
        CREATE UNIQUE INDEX clave_datos_una_activa ON constancias.clave_datos (empresa_id) WHERE activa;
        """
    )
    op.execute(ddl("constancias"))
    op.execute(
        f"""
        CREATE VIEW constancias.v_historial AS
          SELECT c.id, c.empresa_id, c.folio, c.colaborador_id, c.colaborador_nombre,
                 p.id AS plantilla_id, p.nombre AS plantilla_nombre, v.numero AS version,
                 c.fecha_generacion AS fecha, 'WHATSAPP'::text AS canal, c.estado_entrega,
                 c.estado_vigencia
          FROM constancias.constancia_generada c
          JOIN constancias.version_plantilla v ON v.id = c.version_plantilla_id
          JOIN constancias.plantilla_constancia p ON p.id = v.plantilla_id
          WHERE c.empresa_id = {EMPRESA_ACTUAL};

        CREATE VIEW constancias.v_solicitudes_recientes AS
          SELECT s.id, s.empresa_id, s.colaborador_nombre, p.nombre AS plantilla_nombre,
                 v.numero AS version, s.estado, s.fecha_solicitud
          FROM constancias.solicitud_constancia s
          LEFT JOIN constancias.version_plantilla v ON v.id = s.version_plantilla_id
          LEFT JOIN constancias.plantilla_constancia p ON p.id = v.plantilla_id
          WHERE s.empresa_id = {EMPRESA_ACTUAL};

        CREATE VIEW constancias.v_resumen AS
          SELECT e.id AS empresa_id,
                 (SELECT count(*) FROM constancias.constancia_generada c
                   WHERE c.empresa_id = e.id
                     AND c.fecha_generacion >= (date_trunc('month', now() AT TIME ZONE e.zona_horaria)
                                                AT TIME ZONE e.zona_horaria)) AS constancias_mes,
                 (SELECT count(*) FROM constancias.solicitud_constancia s
                   WHERE s.empresa_id = e.id AND s.estado IN ('RECIBIDA', 'EN_PROCESO', 'GENERADA')) AS solicitudes_en_proceso,
                 (SELECT count(*) FROM constancias.plantilla_constancia p
                   WHERE p.empresa_id = e.id AND p.activa AND NOT p.eliminada) AS plantillas_activas
          FROM identidad.empresa e
          WHERE e.id = {EMPRESA_ACTUAL};

        CREATE VIEW constancias.v_alertas AS
          SELECT 'CONSTANCIA_FALLIDA'::text AS tipo, c.id AS referencia_id, c.colaborador_nombre AS dato,
                 1 AS total, c.fecha_generacion AS fecha
          FROM constancias.constancia_generada c
          WHERE c.empresa_id = {EMPRESA_ACTUAL} AND c.estado_entrega = 'FALLIDA'
          UNION ALL
          SELECT 'CAMPO_VACIO_EN_PLANTILLA', a.plantilla_id, a.codigo_interno, a.total_afectados,
                 a.fecha_calculo
          FROM constancias.alerta_plantilla a
          JOIN constancias.plantilla_constancia p ON p.id = a.plantilla_id AND p.activa
          WHERE a.empresa_id = {EMPRESA_ACTUAL} AND a.total_afectados > 0;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW IF EXISTS constancias.v_alertas;
        DROP VIEW IF EXISTS constancias.v_resumen;
        DROP VIEW IF EXISTS constancias.v_solicitudes_recientes;
        DROP VIEW IF EXISTS constancias.v_historial;
        DROP TABLE IF EXISTS constancias.evento_procesado;
        DROP TABLE IF EXISTS constancias.outbox;
        DROP TABLE IF EXISTS constancias.clave_datos;
        DROP TABLE IF EXISTS constancias.alerta_plantilla;
        DROP TABLE IF EXISTS constancias.token_descarga;
        DROP TABLE IF EXISTS constancias.contador_folio;
        DROP TABLE IF EXISTS constancias.constancia_generada;
        DROP TABLE IF EXISTS constancias.solicitud_constancia;
        DROP TABLE IF EXISTS constancias.borrador_plantilla;
        DROP TABLE IF EXISTS constancias.version_plantilla;
        DROP TABLE IF EXISTS constancias.plantilla_constancia;
        DROP FUNCTION IF EXISTS constancias.version_inmutable();
        DROP FUNCTION IF EXISTS constancias.constancia_inmutable();
        """
    )
