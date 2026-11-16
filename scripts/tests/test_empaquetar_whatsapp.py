"""T-224: el paquete de las Lambdas webhook-meta, enviador y estados-entrega."""

import subprocess
import sys

from scripts.empaquetar_lambdas import PAQUETES_WHATSAPP, copiar_fuentes_whatsapp


def test_el_paquete_trae_las_lambdas_cc_whatsapp_y_cc_common_sin_pruebas(tmp_path):
    salida = copiar_fuentes_whatsapp(tmp_path / "paquete")
    for nombre in (*PAQUETES_WHATSAPP, "cc_whatsapp", "cc_common"):
        assert (salida / nombre / "__init__.py").is_file()
    for lam in PAQUETES_WHATSAPP:
        assert (salida / lam / "handler.py").is_file()
    assert not list(salida.rglob("tests"))
    assert not list(salida.rglob("__pycache__"))


def test_los_handlers_se_importan_solo_con_el_paquete(tmp_path):
    """Sin ``services/`` ni ``lambdas/`` en la ruta: lo que falte en el paquete fallaría aquí. Y
    ninguna función necesita FastAPI (no se empaqueta)."""
    salida = copiar_fuentes_whatsapp(tmp_path / "paquete")
    codigo = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "import webhook_meta.handler as w, enviador.handler as e, estados_entrega.handler as s;"
        "assert callable(w.lambda_handler) and callable(e.lambda_handler)"
        " and callable(s.lambda_handler);"
        "import cc_whatsapp.recursos, cc_common.recursos;"
        "assert 'fastapi' not in sys.modules"
    )
    r = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", codigo, str(salida)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
