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
    assert _q(
        bd_migrada,
        "SELECT accion, origen FROM auditoria.bitacora WHERE accion <> 'CAMPO_CREADO'",
    ) == [("INVITACION_CREADA", "SISTEMA")]


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


# ------------------------------------------------------------------ siembra de campos (T-206)

CONSULTA_CAMPOS = (
    "SELECT c.clave, c.codigo_interno, c.nombre_campo, c.tipo_dato, c.formato_validacion, "
    "c.obligatorio, c.orden, c.activo, c.es_sensible, c.es_sugerido, "
    "coalesce((SELECT json_agg(json_build_array(o.etiqueta, o.valor, o.orden) ORDER BY o.orden) "
    "         FROM campos.opcion_campo o WHERE o.campo_id = c.id), '[]'::json) "
    "FROM campos.campo_colaborador c ORDER BY c.orden"
)


def test_el_bootstrap_siembra_los_once_campos_sugeridos(bd_migrada):
    r = bootstrap(_url(bd_migrada), razon_social="Acme", puede_mostrar_codigo=True)
    assert r.campos_creados == 11
    filas = _q(bd_migrada, CONSULTA_CAMPOS)
    assert [f[0] for f in filas][:3] == ["area", "departamento", "turno"]
    assert [f[1] for f in filas] == [f"CAMP-{i:04d}" for i in range(1, 12)]
    por_clave = {f[0]: f for f in filas}
    assert por_clave["ruta_transporte"][7] is False
    assert sorted(k for k, f in por_clave.items() if f[8]) == ["curp", "nss", "rfc", "sueldo"]
    assert [o[1] for o in por_clave["periodicidad_sueldo"][10]] == [
        "SEMANAL",
        "CATORCENAL",
        "QUINCENAL",
        "MENSUAL",
    ]
    assert _q(bd_migrada, "SELECT ultimo FROM campos.contador_campo") == [(11,)]
    assert _q(
        bd_migrada, "SELECT count(*) FROM auditoria.bitacora WHERE accion = 'CAMPO_CREADO'"
    ) == [(11,)]


def test_la_siembra_es_idempotente_y_respeta_lo_editado(bd_migrada):
    bootstrap(_url(bd_migrada), razon_social="Acme", puede_mostrar_codigo=True)
    antes = _q(bd_migrada, CONSULTA_CAMPOS)
    # repetir el script (sin invitación nueva) no cambia nada
    r = bootstrap(_url(bd_migrada), razon_social="Acme", puede_mostrar_codigo=True)
    assert r.campos_creados == 0 and r.codigo is None
    assert _q(bd_migrada, CONSULTA_CAMPOS) == antes
    # lo que RH editó se respeta y lo que falte se completa
    with psycopg.connect(bd_migrada.url_admin, autocommit=True) as c:
        c.execute(
            "UPDATE campos.campo_colaborador SET nombre_campo = 'Horario' WHERE clave = 'turno'"
        )
        c.execute("DELETE FROM campos.campo_colaborador WHERE clave = 'correo'")
    r = bootstrap(
        _url(bd_migrada), razon_social="Acme", nueva_invitacion=True, puede_mostrar_codigo=True
    )
    assert r.campos_creados == 1 and r.codigo
    despues = {f[0]: f for f in _q(bd_migrada, CONSULTA_CAMPOS)}
    assert despues["turno"][2] == "Horario" and "correo" in despues
    assert len(despues) == 11


def test_sin_consola_no_siembra_nada(bd_migrada):
    with pytest.raises(ErrorBootstrap):
        bootstrap(_url(bd_migrada), razon_social="Acme", puede_mostrar_codigo=False)
    assert _q(bd_migrada, "SELECT count(*) FROM campos.campo_colaborador") == [(0,)]
