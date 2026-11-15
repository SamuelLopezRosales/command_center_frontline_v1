"""T-206: INT-COL-09 (faltantes por campo) e INT-COL-10 (uso de un campo)."""

import httpx
import psycopg
import pytest
from ayudantes_colaboradores import StubCampos, construir_app, interno
from cc_colaboradores.campos_cliente import CacheCampos, DefinicionCampo

pytestmark = pytest.mark.docker


@pytest.fixture
async def mundo(datos, motor, cifrador):
    c = datos["campos"]
    defs = [
        DefinicionCampo(c["nss"], "NSS", "nss", "CAMP-0001", "TEXTO", es_sensible=True),
        DefinicionCampo(c["area"], "Área", "area", "CAMP-0002", "LISTA"),
        DefinicionCampo(c["sueldo"], "Sueldo", "sueldo", "CAMP-0003", "NUMERO", es_sensible=True),
    ]
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as cx:
        org = cx.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'O', 'O') RETURNING id",
            (datos["a"],),
        ).fetchone()[0]
        planta = cx.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'P') RETURNING id",
            (datos["a"],),
        ).fetchone()[0]
        ids = []
        for i, estatus in enumerate(["ACTIVO", "ACTIVO", "ACTIVO", "BAJA"], start=1):
            ids.append(
                cx.execute(
                    "INSERT INTO colaboradores.colaborador (empresa_id, organizacion_id, planta_id, "
                    "numero_empleado, nombres, apellido_paterno, apellido_materno, celular_cifrado, "
                    "celular_hash, celular_ultimos4, fecha_ingreso, puesto, tipo_empleado, estatus) "
                    "VALUES (%s, %s, %s, %s, 'N', 'A', 'M', '\\x00', decode(md5(%s) || md5(%s), "
                    "'hex'), '0000', '2020-01-01', 'P', 'OPERATIVO', %s) RETURNING id",
                    (datos["a"], org, planta, f"E-{i}", str(i), f"x{i}", estatus),
                ).fetchone()[0]
            )
        # área: la tiene el colaborador 1 (activo) y el 4 (baja); nss: solo el 2
        for cid, campo, columna, valor in (
            (ids[0], c["area"], "valor_opcion_id", datos["opcion"]),
            (ids[3], c["area"], "valor_opcion_id", datos["opcion"]),
            (ids[1], c["nss"], "valor_cifrado", b"x"),
        ):
            cx.execute(
                f"INSERT INTO colaboradores.valor_campo (empresa_id, colaborador_id, campo_id, "  # noqa: S608
                f"{columna}) VALUES (%s, %s, %s, %s)",
                (datos["a"], cid, campo, valor),
            )
    campos = CacheCampos(StubCampos({datos["a"]: defs}))
    app = construir_app(motor, cifrador, campos=campos)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as h:
        yield {"http": h, "datos": datos, "campos": campos, "defs": defs}


async def _faltantes(m, codigos, servicio="constancias", empresa="a"):
    return await m["http"].post(
        "/internal/colaboradores/faltantes:contar",
        json={"codigos_internos": codigos},
        headers=interno(servicio, m["datos"][empresa]),
    )


async def test_faltantes_cuenta_solo_activos_sin_valor_por_campo(mundo):
    r = await _faltantes(mundo, ["CAMP-0001", "CAMP-0002", "CAMP-0003"])
    assert r.status_code == 200
    # 3 activos: área la tiene 1 (el de baja no cuenta); nss la tiene 1; sueldo nadie
    assert r.json() == {"CAMP-0001": 2, "CAMP-0002": 2, "CAMP-0003": 3}


async def test_faltantes_sin_colaboradores_activos_devuelve_cero(mundo):
    with psycopg.connect(mundo["datos"]["bd"].url_admin, autocommit=True) as cx:
        cx.execute("UPDATE colaboradores.colaborador SET estatus = 'BAJA', fecha_baja = now()")
    assert (await _faltantes(mundo, ["CAMP-0001"])).json() == {"CAMP-0001": 0}


async def test_faltantes_valida_la_entrada_y_el_token(mundo):
    r = await _faltantes(mundo, ["CAMP-9999"])
    assert r.status_code == 422 and r.json()["codigo"] == "CAMPO_DESCONOCIDO"
    assert (await _faltantes(mundo, [])).status_code == 422
    assert (await _faltantes(mundo, ["CAMP-0001"], servicio="whatsapp")).status_code == 401
    r = await mundo["http"].post(
        "/internal/colaboradores/faltantes:contar", json={"codigos_internos": ["CAMP-0001"]}
    )
    assert r.status_code == 401


async def test_faltantes_pide_otra_vez_las_definiciones_si_el_campo_es_nuevo(mundo):
    """Un campo recién creado aún no está en la caché de 60 segundos."""
    d = mundo["datos"]
    nuevo = DefinicionCampo(d["campos"]["antiguedad_fecha"], "Antig", "antig", "CAMP-0004", "FECHA")
    cache = mundo["campos"]
    await cache.definiciones(d["a"])  # llena la caché sin el campo nuevo
    cache._origen.por_empresa[d["a"]].append(nuevo)
    assert (await _faltantes(mundo, ["CAMP-0004"])).json() == {"CAMP-0004": 3}


async def test_faltantes_es_por_empresa(mundo):
    r = await _faltantes(mundo, ["CAMP-0001"], empresa="b")
    assert r.status_code == 422  # la empresa B no tiene ese campo


async def test_uso_de_campo(mundo):
    d = mundo["datos"]
    for campo, esperado in (("area", True), ("nss", True), ("sueldo", False)):
        r = await mundo["http"].get(
            f"/internal/campos/{d['campos'][campo]}/uso", headers=interno("campos", d["a"])
        )
        assert r.status_code == 200 and r.json() == {"con_valores": esperado}, campo
    # de otra empresa o inexistente: sin valores
    r = await mundo["http"].get(
        f"/internal/campos/{d['campos']['area']}/uso", headers=interno("campos", d["b"])
    )
    assert r.json() == {"con_valores": False}
    r = await mundo["http"].get("/internal/campos/999999/uso", headers=interno("campos", d["a"]))
    assert r.json() == {"con_valores": False}


async def test_uso_de_campo_exige_el_servicio_campos(mundo):
    d = mundo["datos"]
    ruta = f"/internal/campos/{d['campos']['area']}/uso"
    assert (
        await mundo["http"].get(ruta, headers=interno("constancias", d["a"]))
    ).status_code == 401
    assert (await mundo["http"].get(ruta)).status_code == 401
