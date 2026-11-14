"""Esquema campos (design.md §2.2, §2.3, §2.5).

Revisión: 0001
Anterior: ninguna (requiere identidad 0001)

Tablas: campo_colaborador, contador_campo, opcion_campo, outbox y evento_procesado.
Requisitos: CC-REQ-045, 046, 047, 049, 050.
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
        CREATE TABLE campos.campo_colaborador (
          id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id          bigint NOT NULL REFERENCES identidad.empresa (id),
          nombre_campo        text NOT NULL,
          clave               text NOT NULL,
          codigo_interno      text NOT NULL,
          tipo_dato           text NOT NULL,
          formato_validacion  text,
          obligatorio         boolean NOT NULL DEFAULT false,
          orden               int NOT NULL,
          activo              boolean NOT NULL DEFAULT true,
          es_sensible         boolean NOT NULL DEFAULT false,
          es_sugerido         boolean NOT NULL DEFAULT false,
          eliminado           boolean NOT NULL DEFAULT false,
          fecha_creacion      timestamptz NOT NULL DEFAULT now(),
          fecha_modificacion  timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT campo_empresa_id_codigo_interno_key UNIQUE (empresa_id, codigo_interno),
          CONSTRAINT campo_empresa_id_clave_key UNIQUE (empresa_id, clave),
          CONSTRAINT campo_tipo_dato_valido CHECK (tipo_dato IN ('TEXTO', 'NUMERO', 'FECHA', 'LISTA', 'SI_NO')),
          CONSTRAINT campo_clave_formato CHECK (clave ~ '^[a-z][a-z0-9_]{1,40}$'),
          CONSTRAINT campo_codigo_formato CHECK (codigo_interno ~ '^CAMP-[0-9]{4,}$'),
          CONSTRAINT campo_formato_longitud CHECK (formato_validacion IS NULL OR length(formato_validacion) <= 200),
          CONSTRAINT campo_sugerido_no_eliminado CHECK (NOT (es_sugerido AND eliminado)),
          CONSTRAINT campo_eliminado_inactivo CHECK (NOT (eliminado AND activo))
        );
        CREATE INDEX campo_empresa_orden ON campos.campo_colaborador (empresa_id, orden) WHERE NOT eliminado;

        CREATE TABLE campos.contador_campo (
          empresa_id  bigint PRIMARY KEY REFERENCES identidad.empresa (id),
          ultimo      int NOT NULL DEFAULT 0 CHECK (ultimo >= 0)
        );

        CREATE TABLE campos.opcion_campo (
          id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id   bigint NOT NULL REFERENCES identidad.empresa (id),
          campo_id     bigint NOT NULL REFERENCES campos.campo_colaborador (id),
          etiqueta     text NOT NULL,
          valor        text NOT NULL,
          descripcion  text,
          orden        int NOT NULL DEFAULT 0,
          activo       boolean NOT NULL DEFAULT true,
          CONSTRAINT opcion_campo_id_valor_key UNIQUE (campo_id, valor)
        );
        CREATE INDEX opcion_campo_orden ON campos.opcion_campo (campo_id, orden);

        -- El valor de una opción no cambia después de crearse (design.md §2.2).
        CREATE FUNCTION campos.opcion_valor_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.valor IS DISTINCT FROM OLD.valor OR NEW.campo_id IS DISTINCT FROM OLD.campo_id THEN
            RAISE EXCEPTION 'El valor de una opción no se modifica' USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER opcion_valor_sin_cambios BEFORE UPDATE ON campos.opcion_campo
          FOR EACH ROW EXECUTE FUNCTION campos.opcion_valor_inmutable();

        -- El código interno no cambia (CC-REQ-046).
        CREATE FUNCTION campos.codigo_interno_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.codigo_interno IS DISTINCT FROM OLD.codigo_interno OR NEW.empresa_id IS DISTINCT FROM OLD.empresa_id THEN
            RAISE EXCEPTION 'El código interno no se modifica' USING ERRCODE = 'check_violation';
          END IF;
          NEW.fecha_modificacion := now();
          RETURN NEW;
        END $$;
        CREATE TRIGGER campo_codigo_sin_cambios BEFORE UPDATE ON campos.campo_colaborador
          FOR EACH ROW EXECUTE FUNCTION campos.codigo_interno_inmutable();
        """
    )
    op.execute(ddl("campos"))


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS campos.evento_procesado;
        DROP TABLE IF EXISTS campos.outbox;
        DROP TABLE IF EXISTS campos.opcion_campo;
        DROP TABLE IF EXISTS campos.contador_campo;
        DROP TABLE IF EXISTS campos.campo_colaborador;
        DROP FUNCTION IF EXISTS campos.opcion_valor_inmutable();
        DROP FUNCTION IF EXISTS campos.codigo_interno_inmutable();
        """
    )
