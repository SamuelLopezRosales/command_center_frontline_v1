import aws_cdk as cdk
import pytest

from infra.config import esquema
from infra.constructs.retencion import politica_retencion


def _amb_prod() -> esquema.Ambiente:
    base = esquema.obtener_ambiente("test")
    eco = esquema.Economia(
        nat="gateway",
        rds_clase="db.t4g.medium",
        rds_multi_az=True,
        rds_proxy=True,
        waf_habilitado=True,
        workers_min_tareas=1,
        tareas_por_servicio=2,
        concurrencia_aprovisionada_webhook=2,
        retencion_respaldos_dias=14,
        permite_borrado=False,
    )
    return esquema.Ambiente(
        nombre="prod",
        cuentas_permitidas=("000000000000",),
        region="us-east-1",
        perfil="cc-prod",
        etiquetas={**base.etiquetas, "ambiente": "prod"},
        presupuesto=base.presupuesto,
        economia=eco,
        dominio=None,
    )


def test_test_permite_borrar():
    p = politica_retencion(esquema.obtener_ambiente("test"))
    assert p.removal_policy == cdk.RemovalPolicy.DESTROY
    assert p.proteccion_borrado_rds is False
    assert p.auto_borrar_objetos is True
    assert p.object_lock_dias == 1
    assert p.object_lock_modo == "GOVERNANCE"
    assert p.retencion_respaldos_dias == 1
    assert p.secretos_dias_recuperacion == 7
    assert p.kms_dias_espera == 7


def test_prod_conserva_y_protege():
    p = politica_retencion(_amb_prod())
    assert p.removal_policy == cdk.RemovalPolicy.RETAIN
    assert p.proteccion_borrado_rds is True
    assert p.auto_borrar_objetos is False
    assert p.retencion_respaldos_dias == 14
    assert p.secretos_dias_recuperacion == 30
    assert p.kms_dias_espera == 30
    # La retención de Object Lock de producción está por confirmar (PQ-24).
    assert p.object_lock_dias is None


def test_prod_nunca_recibe_valores_de_test():
    """Aunque prod declare permite_borrado por error, la política no lo acepta."""
    amb = _amb_prod()
    amb_mal = esquema.Ambiente(
        **{
            **amb.__dict__,
            "economia": esquema.Economia(**{**amb.economia.__dict__, "permite_borrado": True}),
        }
    )
    with pytest.raises(ValueError, match="revisión"):
        politica_retencion(amb_mal)
