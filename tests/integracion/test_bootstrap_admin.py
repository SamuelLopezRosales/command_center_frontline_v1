"""T-038: ``scripts/bootstrap_admin.py`` contra una base migrada."""

import hashlib
import logging
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

from scripts.bootstrap_admin import ErrorBootstrap, bootstrap, main

pytestmark = pytest.mark.docker

RAIZ = Path(__file__).resolve().parents[2]


def _url(bd):
    return bd.base.url_sync  # postgresql+psycopg://cc:cc@... (dueño de los esquemas)


def _q(bd, sql, params=()):
    with psycopg.connect(bd.url_admin) as c:
        return c.execute(sql, params).fetchall()


def test_crea_empresa_e_invitacion_y_guarda_solo_el_hash(bd_migrada):
    r = bootstrap(
        _url(bd_migrada),
        razon_social="Acme SA de CV",
        rfc="acm010101abc",
        puede_mostrar_codigo=True,
    )
    assert r.empresa_creada and r.codigo and len(r.codigo) >= 22
    assert _q(bd_migrada, "SELECT razon_social, rfc, activa FROM identidad.empresa") == [
        ("Acme SA de CV", "ACM010101ABC", True)
    ]
    fila = _q(
        bd_migrada,
        "SELECT codigo_hash, correo_destino, creada_por_usuario_id, "
        "fecha_expira - fecha_creacion FROM identidad.invitacion_registro",
    )[0]
    assert bytes(fila[0]) == hashlib.sha256(r.codigo.encode()).digest()
    assert fila[1] is None and fila[2] is None
    assert fila[3].total_seconds() == pytest.approx(72 * 3600, abs=5)
    # El código no queda en ninguna tabla.
    todo = str(_q(bd_migrada, "SELECT * FROM identidad.invitacion_registro")) + str(
        _q(bd_migrada, "SELECT * FROM auditoria.bitacora")
    )
    assert r.codigo not in todo
    assert _q(bd_migrada, "SELECT accion, origen FROM auditoria.bitacora") == [
        ("INVITACION_CREADA", "SISTEMA")
    ]


def test_la_invitacion_es_valida_para_el_trigger_de_registro(bd_migrada):
    r = bootstrap(_url(bd_migrada), razon_social="Acme", puede_mostrar_codigo=True)
    fila = _q(
        bd_migrada,
        "SELECT empresa_id FROM identidad.validar_invitacion(%s)",
        (hashlib.sha256(r.codigo.encode()).digest(),),
    )
    assert fila == [(r.empresa_id,)]


def test_es_idempotente_sin_bandera(bd_migrada):
    primera = bootstrap(_url(bd_migrada), razon_social="Acme", puede_mostrar_codigo=True)
    segunda = bootstrap(_url(bd_migrada), razon_social="  ACME ", puede_mostrar_codigo=True)
    assert segunda.empresa_id == primera.empresa_id
    assert not segunda.empresa_creada and segunda.codigo is None
    assert _q(bd_migrada, "SELECT count(*) FROM identidad.empresa") == [(1,)]
    assert _q(bd_migrada, "SELECT count(*) FROM identidad.invitacion_registro") == [(1,)]


def test_bandera_explicita_genera_otra_invitacion_con_correo(bd_migrada):
    primera = bootstrap(_url(bd_migrada), razon_social="Acme", puede_mostrar_codigo=True)
    otra = bootstrap(
        _url(bd_migrada),
        razon_social="Acme",
        correo_destino=" Ana@Acme.com ",
        horas=24,
        nueva_invitacion=True,
        puede_mostrar_codigo=True,
    )
    assert otra.empresa_id == primera.empresa_id and otra.codigo != primera.codigo
    assert _q(bd_migrada, "SELECT count(*) FROM identidad.empresa") == [(1,)]
    assert _q(
        bd_migrada,
        "SELECT correo_destino FROM identidad.invitacion_registro WHERE id = %s",
        (otra.invitacion_id,),
    ) == [("ana@acme.com",)]


def test_sin_consola_interactiva_no_crea_nada(bd_migrada):
    with pytest.raises(ErrorBootstrap):
        bootstrap(_url(bd_migrada), razon_social="Acme", puede_mostrar_codigo=False)
    assert _q(bd_migrada, "SELECT count(*) FROM identidad.empresa") == [(0,)]
    assert _q(bd_migrada, "SELECT count(*) FROM identidad.invitacion_registro") == [(0,)]


@pytest.mark.parametrize(
    "kw",
    [
        {"razon_social": "  "},
        {"razon_social": "A", "rfc": "XX"},
        {"razon_social": "A", "correo_destino": "no-es-correo"},
        {"razon_social": "A", "horas": 0},
        {"razon_social": "A", "horas": 169},
    ],
)
def test_entradas_invalidas(bd_migrada, kw):
    with pytest.raises(ErrorBootstrap):
        bootstrap(_url(bd_migrada), puede_mostrar_codigo=True, **kw)
    assert _q(bd_migrada, "SELECT count(*) FROM identidad.empresa") == [(0,)]


def test_el_script_por_consola_sin_terminal_se_niega_y_no_imprime_nada_sensible(bd_migrada):
    """Con la salida redirigida (como en CI), el script falla sin escribir el código."""
    env = {**os.environ, "CC_MIGRAR_URL": _url(bd_migrada)}
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(RAIZ / "scripts" / "bootstrap_admin.py"), "--razon-social", "Acme"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 2
    assert "consola interactiva" in r.stderr
    assert "CÓDIGO" not in r.stdout + r.stderr
    assert "cc:cc" not in r.stdout + r.stderr  # la URL no se imprime
    assert _q(bd_migrada, "SELECT count(*) FROM identidad.empresa") == [(0,)]


def test_main_muestra_el_codigo_una_vez_en_consola_y_no_lo_registra(
    bd_migrada, monkeypatch, capsys, caplog
):
    monkeypatch.setenv("CC_MIGRAR_URL", _url(bd_migrada))
    monkeypatch.setattr("scripts.bootstrap_admin._interactiva", lambda: True)
    with caplog.at_level(logging.DEBUG):
        assert main(["--razon-social", "Acme"]) == 0
    salida = capsys.readouterr().out
    assert salida.count("CÓDIGO DE INVITACIÓN:") == 1
    codigo = salida.split("CÓDIGO DE INVITACIÓN:")[1].split()[0]
    assert len(codigo) >= 22 and codigo not in caplog.text
    # Segunda ejecución: no vuelve a mostrar ni crea otra invitación.
    assert main(["--razon-social", "Acme"]) == 0
    salida2 = capsys.readouterr().out
    assert "ya existe" in salida2 and codigo not in salida2
    assert _q(bd_migrada, "SELECT count(*) FROM identidad.invitacion_registro") == [(1,)]


def test_main_sin_url_falla(monkeypatch, capsys):
    monkeypatch.delenv("CC_MIGRAR_URL", raising=False)
    assert main(["--razon-social", "Acme"]) == 2
