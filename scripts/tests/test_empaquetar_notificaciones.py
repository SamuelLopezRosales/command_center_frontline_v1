"""T-217 (parte A): el paquete de las Lambdas despachador, conciliador y respaldo-correo."""

import subprocess
import sys

from scripts.empaquetar_lambdas import (
    PAQUETES_NOTIFICACIONES,
    copiar_fuentes_notificaciones,
)


def test_el_paquete_trae_las_lambdas_y_sin_pruebas(tmp_path):
    salida = copiar_fuentes_notificaciones(tmp_path / "paquete")
    for nombre in (*PAQUETES_NOTIFICACIONES, "cc_common"):
        assert (salida / nombre / "__init__.py").is_file()
    for lam in ("despachador", "conciliador", "respaldo_correo"):
        assert (salida / lam / "handler.py").is_file()
    assert (salida / "notif_comun" / "sql" / "conciliacion.sql").is_file()
    assert not list(salida.rglob("tests"))
    assert not list(salida.rglob("pruebas.py"))
    assert not list(salida.rglob("__pycache__"))


def test_los_handlers_se_importan_solo_con_el_paquete(tmp_path):
    """Sin ``services/`` ni ``lambdas/`` en la ruta: lo que no esté empaquetado fallaría aquí."""
    salida = copiar_fuentes_notificaciones(tmp_path / "paquete")
    codigo = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "import despachador.handler as d, conciliador.handler as c, respaldo_correo.handler as r;"
        "assert callable(d.lambda_handler) and callable(c.lambda_handler) and callable(r.lambda_handler)"
    )
    r = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", codigo, str(salida)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
