"""Las pruebas de infraestructura no dependen del paquete de las Lambdas (build/lambdas)."""

import os

os.environ["CC_LAMBDAS_DESDE_FUENTE"] = "1"
