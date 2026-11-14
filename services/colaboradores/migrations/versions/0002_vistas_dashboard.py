"""Vistas contractuales del dashboard sobre colaboradores (design.md §2.6, T-029).

Revisión: 0002
Anterior: 0001

Igual que en constancias, las vistas filtran explícitamente por ``app.empresa_id`` y
``svc_dashboard`` solo recibe SELECT sobre ellas (no sobre las tablas).
Requisitos: CC-REQ-011, 013.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

EMPRESA_ACTUAL = "NULLIF(current_setting('app.empresa_id', true), '')::bigint"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE VIEW colaboradores.v_resumen AS
          SELECT {EMPRESA_ACTUAL} AS empresa_id,
                 count(*) FILTER (WHERE estatus = 'ACTIVO') AS colaboradores_activos,
                 count(*) AS colaboradores_registrados
          FROM colaboradores.colaborador
          WHERE empresa_id = {EMPRESA_ACTUAL};

        -- Colaboradores ACTIVOS sin consentimiento vigente (alerta de cv1_01).
        CREATE VIEW colaboradores.v_alertas AS
          SELECT 'SIN_CONSENTIMIENTO'::text AS tipo, c.id AS referencia_id,
                 c.nombres || ' ' || c.apellido_paterno || ' ' || c.apellido_materno AS dato,
                 c.fecha_modificacion AS fecha
          FROM colaboradores.colaborador c
          WHERE c.empresa_id = {EMPRESA_ACTUAL}
            AND c.estatus = 'ACTIVO'
            AND NOT (c.consentimiento_whatsapp
                     AND (c.consentimiento_vigente_hasta IS NULL OR c.consentimiento_vigente_hasta > now()));
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP VIEW IF EXISTS colaboradores.v_alertas; DROP VIEW IF EXISTS colaboradores.v_resumen;"
    )
