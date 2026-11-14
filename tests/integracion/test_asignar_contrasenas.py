"""T-043: ``scripts/asignar_contrasenas.py`` contra una base migrada."""

from pathlib import Path

import psycopg
import pytest

from scripts.asignar_contrasenas import (
    ROLES,
    ErrorContrasenas,
    asignar,
    contrasenas_desde_entorno,
    main,
)

RAIZ = Path(__file__).resolve().parents[2]


def _entorno(sufijo="A"):
    return {f"CC_PWD_{r.upper()}": f"clave-{r}-{sufijo}-0123456789" for r in ROLES}


def test_lee_las_siete_contrasenas_del_entorno():
    contras = contrasenas_desde_entorno(_entorno())
    assert set(contras) == set(ROLES) and len(ROLES) == 7


def test_exige_todas_y_con_longitud_minima():
    env = _entorno()
    del env["CC_PWD_SVC_CAMPOS"]
    env["CC_PWD_MIGRADOR"] = "corta"
    with pytest.raises(ErrorContrasenas) as exc:
        contrasenas_desde_entorno(env)
    assert "svc_campos" in str(exc.value)
    env["CC_PWD_SVC_CAMPOS"] = "clave-svc_campos-0123456789"
    with pytest.raises(ErrorContrasenas, match="demasiado cortas"):
        contrasenas_desde_entorno(env)


@pytest.mark.docker
def test_cada_rol_puede_conectarse_con_su_contrasena_y_es_idempotente(bd_migrada):
    url = bd_migrada.base.url_sync
    # bd_migrada deja la contraseña de cada rol igual a su nombre; se reemplaza.
    asignar(url, contrasenas_desde_entorno(_entorno("A")))
    asignar(url, contrasenas_desde_entorno(_entorno("A")))  # repetir no cambia nada
    for rol in ROLES:
        destino = bd_migrada.url_admin.replace("cc:cc@", f"{rol}:clave-{rol}-A-0123456789@")
        with psycopg.connect(destino) as c:
            assert c.execute("SELECT current_user").fetchone()[0] == rol
        viejo = bd_migrada.url_admin.replace("cc:cc@", f"{rol}:{rol}@")
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(viejo)


@pytest.mark.docker
def test_rotacion_vuelve_a_alinear_la_base(bd_migrada):
    asignar(bd_migrada.base.url_sync, contrasenas_desde_entorno(_entorno("A")))
    asignar(bd_migrada.base.url_sync, contrasenas_desde_entorno(_entorno("B")))
    destino = bd_migrada.url_admin.replace(
        "cc:cc@", "svc_dashboard:clave-svc_dashboard-B-0123456789@"
    )
    with psycopg.connect(destino) as c:
        assert c.execute("SELECT 1").fetchone()[0] == 1


@pytest.mark.docker
def test_rol_inexistente_se_reporta_sin_cambiar_nada(bd_migrada):
    with psycopg.connect(bd_migrada.url_admin, autocommit=True) as c:
        c.execute("DROP OWNED BY migrador CASCADE")
        c.execute("DROP ROLE migrador")
    with pytest.raises(ErrorContrasenas, match="migrador"):
        asignar(bd_migrada.base.url_sync, contrasenas_desde_entorno(_entorno()))


@pytest.mark.docker
def test_la_salida_nunca_incluye_las_contrasenas(bd_migrada, capsys, monkeypatch):
    for k, v in _entorno("Z").items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CC_MIGRAR_URL", bd_migrada.base.url_sync)
    assert main() == 0
    salida = capsys.readouterr()
    for v in _entorno("Z").values():
        assert v not in salida.out + salida.err
    assert "7 roles" in salida.out


def test_sin_url_falla(monkeypatch, capsys):
    monkeypatch.delenv("CC_MIGRAR_URL", raising=False)
    assert main() == 2


@pytest.mark.docker
def test_error_de_conexion_no_filtra_la_url(capsys, monkeypatch):
    for k, v in _entorno().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CC_MIGRAR_URL", "postgresql+psycopg://x:secreto-url@127.0.0.1:1/nada")
    assert main() == 1
    salida = capsys.readouterr()
    assert "secreto-url" not in salida.out + salida.err


def test_ops_sh_compone_la_url_y_rechaza_ordenes_desconocidas():
    sh = RAIZ / "infra" / "docker" / "ops" / "ops.sh"
    texto = sh.read_text(encoding="utf-8")
    assert "\r" not in texto  # LF: corre en Linux
    assert texto.startswith("#!/bin/sh")
    assert "sslmode=require" in texto
    assert "asignar_contrasenas.py" in texto and "bootstrap_admin.py" in texto
    # El script nunca imprime la contraseña ni la URL.
    assert "echo" not in texto.replace('echo "Uso:', "")
