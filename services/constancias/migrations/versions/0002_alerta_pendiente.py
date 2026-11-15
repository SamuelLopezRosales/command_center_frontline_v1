"""Alerta de constancias sin confirmar entrega (design.md §3.8, T-213).

Revisión: 0002
Anterior: 0001

``v_alertas`` suma ``CONSTANCIA_PENDIENTE``: una constancia generada cuya entrega sigue
``PENDIENTE`` pasadas 24 horas. Se reemplaza la vista con las mismas columnas, así que conserva
los permisos que ya tiene ``svc_dashboard``.
Requisitos: CC-REQ-013, 084.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

EMPRESA_ACTUAL = "NULLIF(current_setting('app.empresa_id', true), '')::bigint"

_FALLIDA = f"""
          SELECT 'CONSTANCIA_FALLIDA'::text AS tipo, c.id AS referencia_id, c.colaborador_nombre AS dato,
                 1 AS total, c.fecha_generacion AS fecha
          FROM constancias.constancia_generada c
          WHERE c.empresa_id = {EMPRESA_ACTUAL} AND c.estado_entrega = 'FALLIDA'
          UNION ALL
          SELECT 'CAMPO_VACIO_EN_PLANTILLA', a.plantilla_id, a.codigo_interno, a.total_afectados,
                 a.fecha_calculo
          FROM constancias.alerta_plantilla a
          JOIN constancias.plantilla_constancia p ON p.id = a.plantilla_id AND p.activa
          WHERE a.empresa_id = {EMPRESA_ACTUAL} AND a.total_afectados > 0
"""


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE VIEW constancias.v_alertas AS
          {_FALLIDA}
          UNION ALL
          SELECT 'CONSTANCIA_PENDIENTE', c.id, c.colaborador_nombre, 1, c.fecha_generacion
          FROM constancias.constancia_generada c
          WHERE c.empresa_id = {EMPRESA_ACTUAL} AND c.estado_entrega = 'PENDIENTE'
            AND c.fecha_generacion < now() - interval '24 hours';
        """
    )


def downgrade() -> None:
    op.execute(f"CREATE OR REPLACE VIEW constancias.v_alertas AS {_FALLIDA};")
