"""T-034: DSH-06 (sesión), DSH-07 (usuario actual) y DSH-10 (invitaciones)."""

import hashlib

import psycopg
import pytest
from ayudantes_dashboard import cab, emitir

pytestmark = pytest.mark.docker


def _bitacora(datos, accion):
    with psycopg.connect(datos["bd"].url_admin) as c:
        return c.execute(
            "SELECT ip::text, detalle, usuario_id FROM auditoria.bitacora WHERE accion = %s",
            (accion,),
        ).fetchall()


async def test_yo_devuelve_rol_rh_y_permisos(cliente, datos):
    r = await cliente.get("/api/v1/usuarios/yo", headers=cab(emitir("sub-a", datos["a"])))
    assert r.status_code == 200
    cuerpo = r.json()
    assert (
        cuerpo["rol"] == "RH"
        and cuerpo["empresa_id"] == datos["a"]
        and cuerpo["nombre"] == "Ana RH"
    )
    assert "colaboradores:ver_sensibles" in cuerpo["permisos"]


async def test_sin_token_401(cliente):
    r = await cliente.get("/api/v1/usuarios/yo")
    assert r.status_code == 401 and r.json()["codigo"] == "NO_AUTENTICADO"


async def test_usuario_inactivo_401_y_no_registrado_403(cliente, datos):
    r = await cliente.get("/api/v1/usuarios/yo", headers=cab(emitir("sub-inactivo", datos["a"])))
    assert r.status_code == 401 and r.json()["codigo"] == "USUARIO_INACTIVO"
    r = await cliente.get("/api/v1/usuarios/yo", headers=cab(emitir("sub-fantasma", datos["a"])))
    assert r.status_code == 403 and r.json()["codigo"] == "USUARIO_NO_REGISTRADO"


async def test_token_de_otra_empresa_no_ve_al_usuario(cliente, datos):
    # El usuario sub-b existe en B, pero el token dice empresa A: RLS lo oculta.
    r = await cliente.get("/api/v1/usuarios/yo", headers=cab(emitir("sub-b", datos["a"])))
    assert r.status_code == 403


async def test_login_registra_ip_y_es_idempotente_por_jti(cliente, datos):
    token = emitir("sub-a", datos["a"], jti="jti-fijo")
    h = cab(token, **{"CloudFront-Viewer-Address": "203.0.113.7:51234"})
    assert (await cliente.post("/api/v1/sesion/iniciar", headers=h)).status_code == 204
    assert (await cliente.post("/api/v1/sesion/iniciar", headers=h)).status_code == 204
    filas = _bitacora(datos, "LOGIN")
    assert len(filas) == 1
    ip, detalle, usuario = filas[0]
    assert (
        ip.startswith("203.0.113.7") and detalle == {"jti": "jti-fijo"} and usuario == datos["ua"]
    )
    # Un token nuevo (otro jti) sí registra otro LOGIN.
    await cliente.post("/api/v1/sesion/iniciar", headers=cab(emitir("sub-a", datos["a"])))
    assert len(_bitacora(datos, "LOGIN")) == 2


async def test_login_actualiza_ultima_actividad(cliente, datos):
    await cliente.post("/api/v1/sesion/iniciar", headers=cab(emitir("sub-a", datos["a"])))
    with psycopg.connect(datos["bd"].url_admin) as c:
        assert c.execute(
            "SELECT ultima_actividad IS NOT NULL FROM identidad.usuario WHERE id = %s",
            (datos["ua"],),
        ).fetchone()[0]


async def test_invitacion_codigo_una_vez_solo_hash_72h(cliente, datos):
    r = await cliente.post(
        "/api/v1/usuarios/invitaciones",
        json={"correo_destino": "Nuevo@A.com"},
        headers=cab(emitir("sub-a", datos["a"])),
    )
    assert r.status_code == 201
    codigo = r.json()["codigo"]
    assert len(codigo) >= 22
    with psycopg.connect(datos["bd"].url_admin) as c:
        fila = c.execute(
            "SELECT codigo_hash, correo_destino, fecha_expira - fecha_creacion, creada_por_usuario_id "
            "FROM identidad.invitacion_registro"
        ).fetchone()
        texto_tabla = str(c.execute("SELECT * FROM identidad.invitacion_registro").fetchall())
        texto_bitacora = str(c.execute("SELECT * FROM auditoria.bitacora").fetchall())
    assert bytes(fila[0]) == hashlib.sha256(codigo.encode()).digest()
    assert fila[1] == "nuevo@a.com"
    assert fila[2].total_seconds() == pytest.approx(72 * 3600, abs=5)
    assert fila[3] == datos["ua"]
    assert codigo not in texto_tabla and codigo not in texto_bitacora
    assert len(_bitacora(datos, "INVITACION_CREADA")) == 1


async def test_invitacion_valida_entrada(cliente, datos):
    h = cab(emitir("sub-a", datos["a"]))
    r = await cliente.post(
        "/api/v1/usuarios/invitaciones", json={"correo_destino": "no-es-correo"}, headers=h
    )
    assert r.status_code == 422 and "no-es-correo" not in r.text
    r = await cliente.post("/api/v1/usuarios/invitaciones", json={"otro": 1}, headers=h)
    assert r.status_code == 422
