"""Esquema colaboradores (design.md §2.2, §2.3, §2.4).

Revisión: 0001
Anterior: ninguna (requiere identidad 0001 y campos 0001)

Tablas: organizacion, planta, colaborador, valor_campo, carga_colaboradores, fila_carga,
clave_datos, outbox y evento_procesado.
Requisitos: CC-REQ-020, 022, 023, 024, 029, 035, 036, 040, 043, 044, 151, 152.

Nota de implementación: ``unaccent`` no es IMMUTABLE y no puede usarse en un índice; se
envuelve en ``colaboradores.f_unaccent`` (patrón documentado de PostgreSQL).
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
        CREATE EXTENSION IF NOT EXISTS pg_trgm;
        CREATE EXTENSION IF NOT EXISTS unaccent;

        CREATE FUNCTION colaboradores.f_unaccent(text) RETURNS text
          LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
          AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;

        CREATE TABLE colaboradores.organizacion (
          id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id         bigint NOT NULL REFERENCES identidad.empresa (id),
          clave              text NOT NULL,
          razon_social       text NOT NULL,
          rfc                text,
          registro_patronal  text,
          domicilio_fiscal   text,
          ciudad             text,
          logotipo_s3_key    text,
          nombre_firmante    text,
          cargo_firmante     text,
          correo_firmante    text,
          activa             boolean NOT NULL DEFAULT true,
          CONSTRAINT organizacion_empresa_id_clave_key UNIQUE (empresa_id, clave),
          CONSTRAINT organizacion_rfc_longitud CHECK (rfc IS NULL OR length(rfc) IN (12, 13))
        );

        CREATE TABLE colaboradores.planta (
          id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id  bigint NOT NULL REFERENCES identidad.empresa (id),
          nombre      text NOT NULL,
          activa      boolean NOT NULL DEFAULT true
        );
        CREATE UNIQUE INDEX planta_empresa_id_nombre_key ON colaboradores.planta (empresa_id, lower(nombre));

        CREATE TABLE colaboradores.colaborador (
          id                             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id                     bigint NOT NULL REFERENCES identidad.empresa (id),
          organizacion_id                bigint NOT NULL REFERENCES colaboradores.organizacion (id),
          planta_id                      bigint NOT NULL REFERENCES colaboradores.planta (id),
          numero_empleado                text NOT NULL,
          nombres                        text NOT NULL,
          apellido_paterno               text NOT NULL,
          apellido_materno               text NOT NULL,
          celular_cifrado                bytea NOT NULL,
          celular_hash                   bytea NOT NULL,
          celular_ultimos4               char(4) NOT NULL,
          celular_invalido               boolean NOT NULL DEFAULT false,
          fecha_ingreso                  date NOT NULL,
          puesto                         text NOT NULL,
          tipo_empleado                  text NOT NULL,
          estatus                        text NOT NULL DEFAULT 'ACTIVO',
          fecha_baja                     date,
          consentimiento_whatsapp        boolean NOT NULL DEFAULT false,
          fecha_consentimiento           timestamptz,
          consentimiento_vigente_hasta   timestamptz,
          consentimiento_registrado_por  bigint REFERENCES identidad.usuario (id),
          fecha_creacion                 timestamptz NOT NULL DEFAULT now(),
          fecha_modificacion             timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT colaborador_empresa_id_numero_empleado_key UNIQUE (empresa_id, numero_empleado),
          CONSTRAINT colaborador_empresa_id_celular_hash_key UNIQUE (empresa_id, celular_hash),
          CONSTRAINT colaborador_numero_normalizado CHECK (numero_empleado = upper(btrim(numero_empleado)) AND numero_empleado <> ''),
          CONSTRAINT colaborador_tipo_empleado_valido CHECK (tipo_empleado IN ('ADMINISTRATIVO', 'OPERATIVO')),
          CONSTRAINT colaborador_estatus_valido CHECK (estatus IN ('ACTIVO', 'BAJA')),
          CONSTRAINT colaborador_fecha_baja_coherente CHECK (estatus = 'BAJA' OR fecha_baja IS NULL),
          CONSTRAINT colaborador_ultimos4 CHECK (celular_ultimos4 ~ '^[0-9]{4}$'),
          CONSTRAINT colaborador_hash_32 CHECK (octet_length(celular_hash) = 32)
        );
        CREATE INDEX colaborador_filtros ON colaboradores.colaborador (empresa_id, estatus, organizacion_id, planta_id);
        CREATE INDEX colaborador_tipo ON colaboradores.colaborador (empresa_id, tipo_empleado);
        CREATE INDEX colaborador_nombre_trgm ON colaboradores.colaborador
          USING gin (colaboradores.f_unaccent(lower(nombres || ' ' || apellido_paterno || ' ' || apellido_materno)) gin_trgm_ops);
        CREATE INDEX colaborador_numero_prefijo ON colaboradores.colaborador (empresa_id, numero_empleado text_pattern_ops);

        CREATE TABLE colaboradores.valor_campo (
          id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id       bigint NOT NULL REFERENCES identidad.empresa (id),
          colaborador_id   bigint NOT NULL REFERENCES colaboradores.colaborador (id),
          campo_id         bigint NOT NULL REFERENCES campos.campo_colaborador (id),
          valor_texto      text,
          valor_numero     numeric(18, 4),
          valor_fecha      date,
          valor_opcion_id  bigint REFERENCES campos.opcion_campo (id),
          valor_cifrado    bytea,
          CONSTRAINT valor_campo_colaborador_id_campo_id_key UNIQUE (colaborador_id, campo_id),
          CONSTRAINT valor_campo_un_solo_valor CHECK (num_nonnulls(valor_texto, valor_numero, valor_fecha, valor_opcion_id, valor_cifrado) = 1)
        );
        CREATE INDEX valor_campo_texto ON colaboradores.valor_campo (campo_id, valor_texto) WHERE valor_texto IS NOT NULL;
        CREATE INDEX valor_campo_opcion ON colaboradores.valor_campo (campo_id, valor_opcion_id) WHERE valor_opcion_id IS NOT NULL;
        CREATE INDEX valor_campo_fecha ON colaboradores.valor_campo (campo_id, valor_fecha) WHERE valor_fecha IS NOT NULL;
        CREATE INDEX valor_campo_numero ON colaboradores.valor_campo (campo_id, valor_numero) WHERE valor_numero IS NOT NULL;

        CREATE TABLE colaboradores.carga_colaboradores (
          id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id         bigint NOT NULL REFERENCES identidad.empresa (id),
          usuario_id         bigint NOT NULL REFERENCES identidad.usuario (id),
          nombre_archivo     text NOT NULL,
          version_plantilla  text NOT NULL,
          hash_archivo       char(64),
          total_filas        int,
          filas_ok           int NOT NULL DEFAULT 0,
          filas_error        int NOT NULL DEFAULT 0,
          estado             text NOT NULL DEFAULT 'EN_PROCESO',
          fecha_carga        timestamptz NOT NULL DEFAULT now(),
          s3_key             text,
          motivo_cierre      text,
          fecha_fin          timestamptz,
          CONSTRAINT carga_estado_valido CHECK (estado IN ('EN_PROCESO', 'TERMINADA', 'CANCELADA')),
          CONSTRAINT carga_total_maximo CHECK (total_filas IS NULL OR total_filas BETWEEN 0 AND 2000)
        );
        CREATE INDEX carga_empresa_fecha ON colaboradores.carga_colaboradores (empresa_id, fecha_carga DESC);

        CREATE TABLE colaboradores.fila_carga (
          id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          empresa_id       bigint NOT NULL REFERENCES identidad.empresa (id),
          carga_id         bigint NOT NULL REFERENCES colaboradores.carga_colaboradores (id),
          colaborador_id   bigint REFERENCES colaboradores.colaborador (id),
          numero_fila      int NOT NULL,
          numero_empleado  text,
          resultado        text NOT NULL,
          mensaje          text,
          CONSTRAINT fila_carga_carga_id_numero_fila_key UNIQUE (carga_id, numero_fila),
          CONSTRAINT fila_resultado_valido CHECK (resultado IN ('NUEVO', 'ACTUALIZADO', 'ERROR', 'OMITIDO'))
        );

        CREATE TABLE colaboradores.clave_datos (
          empresa_id      bigint NOT NULL REFERENCES identidad.empresa (id),
          version         int NOT NULL CHECK (version > 0),
          dek_cifrada     bytea NOT NULL,
          activa          boolean NOT NULL DEFAULT true,
          fecha_creacion  timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (empresa_id, version)
        );
        CREATE UNIQUE INDEX clave_datos_una_activa ON colaboradores.clave_datos (empresa_id) WHERE activa;
        """
    )
    op.execute(ddl("colaboradores"))


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS colaboradores.evento_procesado;
        DROP TABLE IF EXISTS colaboradores.outbox;
        DROP TABLE IF EXISTS colaboradores.clave_datos;
        DROP TABLE IF EXISTS colaboradores.fila_carga;
        DROP TABLE IF EXISTS colaboradores.carga_colaboradores;
        DROP TABLE IF EXISTS colaboradores.valor_campo;
        DROP TABLE IF EXISTS colaboradores.colaborador;
        DROP TABLE IF EXISTS colaboradores.planta;
        DROP TABLE IF EXISTS colaboradores.organizacion;
        DROP FUNCTION IF EXISTS colaboradores.f_unaccent(text);
        """
    )
