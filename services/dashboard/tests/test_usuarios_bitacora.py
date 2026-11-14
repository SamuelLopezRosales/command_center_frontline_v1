"""T-035: DSH-08 (listado), DSH-09 (desactivación) y DSH-05 (bitácora)."""

import base64

import psycopg
import pytest
from ayudantes_dashboard import CognitoFalso, cab, emitir
from cc_common.paginacion import codificar_cursor

pytestmark = pytest.mark.docker


def _segundo_usuario(datos, sub="sub-a2", nombre="Carla RH", empresa=None):
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        return c.execute(
            "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (empresa or datos["a"], nombre, f"{sub}@a.com", sub),
        ).fetchone()[0]


def _activo(datos, usuario_id):
    with psycopg.connect(datos["bd"].url_admin) as c:
        return c.execute(
            "SELECT activo FROM identidad.usuario WHERE id = %s", (usuario_id,)
        ).fetchone()[0]


# --- DSH-08 ---------------------------------------------------------------------------------


async def test_listado_solo_de_la_empresa_y_sin_sub(cliente, datos):
    r = await cliente.get("/api/v1/usuarios", headers=cab(emitir("sub-a", datos["a"])))
    assert r.status_code == 200
    items = r.json()["items"]
    assert {i["id"] for i in items} == {datos["ua"], datos["ui"]}
    assert [i["activo"] for i in items] == [True, False]
    assert "sub-a" not in r.text and "cognito_sub" not in r.text


async def test_listado_requiere_token(cliente):
    assert (await cliente.get("/api/v1/usuarios")).status_code == 401


# --- DSH-09 ---------------------------------------------------------------------------------


async def test_desactivar_llama_a_cognito_y_registra_bitacora(cliente, datos, cognito):
    otro = _segundo_usuario(datos)
    h = cab(emitir("sub-a", datos["a"]), **{"CloudFront-Viewer-Address": "198.51.100.9:443"})
    r = await cliente.post(f"/api/v1/usuarios/{otro}/desactivar", headers=h)
    assert r.status_code == 204
    assert _activo(datos, otro) is False
    assert cognito.llamadas == ["sub-a2"]
    with psycopg.connect(datos["bd"].url_admin) as c:
        fila = c.execute(
            "SELECT usuario_id, entidad_id, host(ip) FROM auditoria.bitacora "
            "WHERE accion = 'USUARIO_DESACTIVADO'"
        ).fetchall()
    assert fila == [(datos["ua"], otro, "198.51.100.9")]


async def test_no_puede_desactivarse_a_si_mismo(cliente, datos, cognito):
    _segundo_usuario(datos)
    r = await cliente.post(
        f"/api/v1/usuarios/{datos['ua']}/desactivar", headers=cab(emitir("sub-a", datos["a"]))
    )
    assert r.status_code == 409 and r.json()["codigo"] == "NO_PUEDE_DESACTIVARSE"
    assert _activo(datos, datos["ua"]) is True and cognito.llamadas == []


async def test_desactivarse_tras_quedar_solo_sigue_siendo_409(cliente, datos):
    otro = _segundo_usuario(datos)
    h = cab(emitir("sub-a", datos["a"]))
    assert (await cliente.post(f"/api/v1/usuarios/{otro}/desactivar", headers=h)).status_code == 204
    r = await cliente.post(f"/api/v1/usuarios/{datos['ua']}/desactivar", headers=h)
    assert r.status_code == 409
    assert _activo(datos, datos["ua"]) is True


async def test_servicio_rechaza_dejar_la_empresa_sin_activos(datos, monkeypatch):
    """Defensa en profundidad: con un solo activo en la empresa, el objetivo no se desactiva.

    Por API es inalcanzable (el actor siempre es un segundo activo), así que se fuerza el
    conteo del repositorio.
    """
    from cc_common.auth import UsuarioActual
    from cc_common.db import crear_motor
    from cc_common.errores import ErrorConflicto
    from cc_dashboard.repos import usuarios as repo
    from cc_dashboard.servicios import usuarios as servicio

    async def un_activo(_conn):
        return [datos["ua"]]

    monkeypatch.setattr(repo, "bloquear_activos", un_activo)
    motor = crear_motor(datos["bd"].url_rol("svc_dashboard"))
    otro = _segundo_usuario(datos)
    cognito = CognitoFalso()
    actor = UsuarioActual(sub="sub-a", empresa_id=datos["a"], rol="RH", jti="x")
    try:
        with pytest.raises(ErrorConflicto) as exc:
            await servicio.desactivar(motor, cognito, actor, otro, None)
        assert exc.value.codigo == "ULTIMO_USUARIO_ACTIVO"
    finally:
        await motor.dispose()
    assert _activo(datos, otro) is True and cognito.llamadas == []


async def test_desactivar_inexistente_o_de_otra_empresa_404(cliente, datos, cognito):
    h = cab(emitir("sub-a", datos["a"]))
    assert (await cliente.post("/api/v1/usuarios/999999/desactivar", headers=h)).status_code == 404
    r = await cliente.post(f"/api/v1/usuarios/{datos['ub']}/desactivar", headers=h)
    assert r.status_code == 404 and cognito.llamadas == []
    assert _activo(datos, datos["ub"]) is True


async def test_desactivar_ya_inactivo_es_idempotente(cliente, datos, cognito):
    r = await cliente.post(
        f"/api/v1/usuarios/{datos['ui']}/desactivar", headers=cab(emitir("sub-a", datos["a"]))
    )
    assert r.status_code == 204 and cognito.llamadas == []


async def test_falla_de_cognito_revierte_la_desactivacion(datos):
    import httpx
    from ayudantes_dashboard import CLIENTE, EMISOR, LLAVE
    from cc_common.auth import VerificadorToken
    from cc_common.db import crear_motor
    from cc_dashboard.config import ConfigDashboard
    from cc_dashboard.main import crear_app

    otro = _segundo_usuario(datos)
    motor = crear_motor(datos["bd"].url_rol("svc_dashboard"))
    app = crear_app(
        ConfigDashboard(cognito_emisor=EMISOR, cognito_client_id=CLIENTE),
        motor=motor,
        verificador=VerificadorToken(EMISOR, CLIENTE, resolver_llave=lambda _t: LLAVE.public_key()),
        cognito=CognitoFalso(falla=True),
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            r = await c.post(
                f"/api/v1/usuarios/{otro}/desactivar", headers=cab(emitir("sub-a", datos["a"]))
            )
        assert r.status_code == 502 and r.json()["codigo"] == "COGNITO_NO_DISPONIBLE"
        assert _activo(datos, otro) is True
        with psycopg.connect(datos["bd"].url_admin) as c2:
            assert not c2.execute(
                "SELECT 1 FROM auditoria.bitacora WHERE accion = 'USUARIO_DESACTIVADO'"
            ).fetchall()
    finally:
        await motor.dispose()


# --- DSH-05 ---------------------------------------------------------------------------------


@pytest.fixture
def bitacora_sembrada(datos):
    """Seis registros de A con fechas conocidas (dos comparten marca de tiempo) y uno de B."""
    filas = [
        ("2026-01-01T10:00:00Z", "ALTA", datos["ua"], 11),
        ("2026-01-02T10:00:00Z", "MODIFICACION", datos["ua"], 11),
        ("2026-01-03T10:00:00Z", "ALTA", datos["ui"], 12),
        ("2026-01-04T10:00:00Z", "CONSULTA_DETALLE", datos["ua"], 12),
        ("2026-01-05T10:00:00Z", "ALTA", datos["ua"], 13),
        ("2026-01-05T10:00:00Z", "BAJA", datos["ua"], 13),
    ]
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        for fecha, accion, usuario, colab in filas:
            c.execute(
                "INSERT INTO auditoria.bitacora (empresa_id, usuario_id, colaborador_id, accion, "
                "entidad, entidad_id, fecha_hora, origen) VALUES (%s,%s,%s,%s,'colaborador',%s,%s,'USUARIO')",
                (datos["a"], usuario, colab, accion, colab, fecha),
            )
        c.execute(
            "INSERT INTO auditoria.bitacora (empresa_id, usuario_id, accion, entidad, fecha_hora, origen) "
            "VALUES (%s,%s,'ALTA','colaborador','2026-01-03T10:00:00Z','USUARIO')",
            (datos["b"], datos["ub"]),
        )
    return datos


def _h(datos):
    return cab(emitir("sub-a", datos["a"]))


async def test_bitacora_orden_descendente_por_defecto_y_aislada(cliente, bitacora_sembrada):
    r = await cliente.get("/api/v1/bitacora", headers=_h(bitacora_sembrada))
    assert r.status_code == 200
    fechas = [i["fecha_hora"] for i in r.json()["items"]]
    assert fechas == sorted(fechas, reverse=True)
    assert len(fechas) == 6 and r.json()["siguiente"] is None  # la fila de B no aparece


async def test_bitacora_orden_ascendente(cliente, bitacora_sembrada):
    r = await cliente.get("/api/v1/bitacora?orden=asc", headers=_h(bitacora_sembrada))
    items = r.json()["items"]
    assert [i["fecha_hora"] for i in items] == sorted(i["fecha_hora"] for i in items)
    assert items[0]["accion"] == "ALTA" and items[0]["colaborador_id"] == 11
    assert items[0]["usuario_nombre"] == "Ana RH"


async def test_bitacora_filtros(cliente, bitacora_sembrada):
    d = bitacora_sembrada
    consulta = lambda q: cliente.get(f"/api/v1/bitacora?{q}", headers=_h(d))  # noqa: E731
    por_accion = (await consulta("accion=ALTA")).json()["items"]
    assert {i["accion"] for i in por_accion} == {"ALTA"} and len(por_accion) == 3
    por_usuario = (await consulta(f"usuario_id={d['ui']}")).json()["items"]
    assert [i["usuario_id"] for i in por_usuario] == [d["ui"]]
    por_colab = (await consulta("colaborador_id=13")).json()["items"]
    assert len(por_colab) == 2
    rango = (await consulta("desde=2026-01-02T00:00:00Z&hasta=2026-01-04T23:59:59Z")).json()
    assert len(rango["items"]) == 3
    combinado = (await consulta(f"accion=ALTA&usuario_id={d['ua']}&colaborador_id=13")).json()
    assert len(combinado["items"]) == 1


@pytest.mark.parametrize("orden", ["asc", "desc"])
async def test_bitacora_cursor_recorre_todo_sin_repetir(cliente, bitacora_sembrada, orden):
    vistos, cursor = [], None
    for _ in range(10):
        q = f"orden={orden}&limite=2" + (f"&cursor={cursor}" if cursor else "")
        cuerpo = (await cliente.get(f"/api/v1/bitacora?{q}", headers=_h(bitacora_sembrada))).json()
        vistos += [i["id"] for i in cuerpo["items"]]
        cursor = cuerpo["siguiente"]
        if cursor is None:
            break
    assert len(vistos) == 6 and len(set(vistos)) == 6  # incluye las dos con la misma fecha
    assert (
        (vistos == sorted(vistos)) if orden == "asc" else (vistos == sorted(vistos, reverse=True))
    )


async def test_bitacora_valida_parametros(cliente, bitacora_sembrada):
    h = _h(bitacora_sembrada)
    for q in (
        "accion=INVENTADA",
        "orden=lateral",
        "limite=0",
        "limite=101",
        "usuario_id=abc",
        "desde=2026-02-01T00:00:00Z&hasta=2026-01-01T00:00:00Z",
        "cursor=basura",
        f"cursor={base64.urlsafe_b64encode(b'[1,2]').decode()}",
        f"cursor={codificar_cursor(('x',))}",
    ):
        r = await cliente.get(f"/api/v1/bitacora?{q}", headers=h)
        assert r.status_code == 422, q


async def test_bitacora_requiere_token(cliente):
    assert (await cliente.get("/api/v1/bitacora")).status_code == 401
