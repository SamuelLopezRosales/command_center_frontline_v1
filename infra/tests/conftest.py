"""Las pruebas de infraestructura no dependen del paquete de las Lambdas (build/lambdas)."""

import os

os.environ["CC_LAMBDAS_DESDE_FUENTE"] = "1"


import pytest  # noqa: E402


@pytest.fixture(scope="session")
def ensamblado_test():
    """Todos los stacks de ``test`` y sus plantillas, construidos una sola vez (T-225)."""
    from aws_cdk.assertions import Template

    from infra.app import construir_stacks, crear_app

    app, amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": "034362033822"})
    stacks = construir_stacks(app, amb, destino)
    return stacks, {nombre: Template.from_stack(s) for nombre, s in stacks.items()}


# ------------------------------------------------------------------ revisión global (T-226)
# Se sintetizan como la CLI (con el ``context`` de infra/cdk.json) y con todos los stacks de cada
# ambiente: ``test`` tal como está en ambientes.json; ``prod`` es sintético (no existe en el JSON).
@pytest.fixture(scope="session")
def global_test():
    """``Ensamblado`` de ``test`` con sus valores por defecto (sin pipeline)."""
    from infra.tests.ayudas_globales import construir_test

    return construir_test()


@pytest.fixture(scope="session")
def global_test_con_pipeline():
    """``test`` con ``-c pipeline=true``: solo así se define el pipeline en ese ambiente."""
    from infra.tests.ayudas_globales import construir_test

    return construir_test({"pipeline": "true", "repositorio_pipeline": "organizacion/repo"})


@pytest.fixture(scope="session")
def global_prod():
    """``Ensamblado`` del ``prod`` sintético con TODOS los stacks."""
    from infra.tests.ayudas_globales import construir_prod

    return construir_prod()
