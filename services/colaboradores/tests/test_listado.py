"""T-202: listado, búsqueda y filtros (COL-01) con 10,000 colaboradores."""

import time

import httpx
import psycopg
import pytest
from ayudantes_colaboradores import StubCampos, cab, construir_app, emitir
from cc_colaboradores.campos_cliente import CacheCampos, DefinicionCampo, OpcionCampo

pytestmark = pytest.mark.docker

TOTAL = 10_000


@pytest.fixture
async def http_10k(motor, cifrador, datos):
    """10,000 colaboradores de A (SQL directo, sin cifrado real: el listado no lo lee)."""
    c_area, c_nss = datos["campos"]["area"], datos["campos"]["nss"]
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        org1 = c.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORG1', 'Uno') RETURNING id",
            (datos["a"],),
        ).fetchone()[0]
        org2 = c.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORG2', 'Dos') RETURNING id",
            (datos["a"],),
        ).fetchone()[0]
        planta = c.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Norte') RETURNING id",
            (datos["a"],),
        ).fetchone()[0]
        c.execute(
            """
            INSERT INTO colaboradores.colaborador
              (empresa_id, organizacion_id, planta_id, numero_empleado, nombres, apellido_paterno,
               apellido_materno, celular_cifrado, celular_hash, celular_ultimos4, fecha_ingreso,
               puesto, tipo_empleado, estatus, fecha_baja, consentimiento_whatsapp)
            SELECT %(e)s, CASE WHEN g %% 2 = 0 THEN %(o1)s ELSE %(o2)s END, %(p)s,
                   'N' || lpad(g::text, 5, '0'),
                   CASE WHEN g = 4242 THEN 'Ángel' ELSE 'Nombre' || g END,
                   CASE WHEN g = 4242 THEN 'Muñoz' ELSE 'Paterno' || (g %% 97) END,
                   'Materno', '\\x00'::bytea, sha256(g::text::bytea), '0000', DATE '2020-01-01',
                   'Puesto', CASE WHEN g %% 3 = 0 THEN 'ADMINISTRATIVO' ELSE 'OPERATIVO' END,
                   CASE WHEN g %% 10 = 0 THEN 'BAJA' ELSE 'ACTIVO' END,
                   CASE WHEN g %% 10 = 0 THEN DATE '2026-01-01' END, g %% 5 = 0
            FROM generate_series(1, %(n)s) g
            """,
            {"e": datos["a"], "o1": org1, "o2": org2, "p": planta, "n": TOTAL},
        )
        # Área VENTAS en los múltiplos de 7; NSS (sensible) en todos los múltiplos de 7 también.
        c.execute(
            "INSERT INTO colaboradores.valor_campo (empresa_id, colaborador_id, campo_id, valor_opcion_id) "
            "SELECT %s, id, %s, %s FROM colaboradores.colaborador WHERE substr(numero_empleado, 2)::int %% 7 = 0",
            (datos["a"], c_area, datos["opcion"]),
        )
        c.execute(
            "INSERT INTO colaboradores.valor_campo (empresa_id, colaborador_id, campo_id, valor_cifrado) "
            "SELECT %s, id, %s, '\\x01'::bytea FROM colaboradores.colaborador "
            "WHERE substr(numero_empleado, 2)::int %% 7 = 0",
            (datos["a"], c_nss),
        )
        c.execute("ANALYZE colaboradores.colaborador; ANALYZE colaboradores.valor_campo")
    defs = [
        DefinicionCampo(c_nss, "NSS", "nss", "CAMP-0001", "TEXTO", es_sensible=True),
        DefinicionCampo(
            c_area,
            "Área",
            "area",
            "CAMP-0002",
            "LISTA",
            opciones=(OpcionCampo(datos["opcion"], "Ventas", "VENTAS"),),
        ),
    ]
    app = construir_app(motor, cifrador, campos=CacheCampos(StubCampos({datos["a"]: defs})))
    datos.update(org1=org1, org2=org2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as h:
        yield h


def _h(datos, empresa="a", usuario="ua"):
    return cab(emitir("sub", datos[empresa], datos[usuario]))


async def _get(h, datos, consulta=""):
    r = await h.get(f"/api/v1/colaboradores?{consulta}", headers=_h(datos))
    assert r.status_code == 200, r.text
    return r.json()


async def test_paginacion_con_total_y_orden_estable(http_10k, datos):
    p1 = await _get(http_10k, datos, "limite=100")
    p2 = await _get(http_10k, datos, "limite=100&pagina=2")
    assert p1["total"] == TOTAL and len(p1["items"]) == 100 and p1["limite"] == 100
    assert not {i["id"] for i in p1["items"]} & {i["id"] for i in p2["items"]}
    assert all(i["celular"] == "******0000" for i in p1["items"])
    r = await http_10k.get("/api/v1/colaboradores?limite=101", headers=_h(datos))
    assert r.status_code == 422


async def test_busqueda_sin_acentos_parcial_y_por_numero(http_10k, datos):
    for q in ("angel", "ÁNGEL", "ngel mu", "MUÑOZ", "munoz"):
        r = await _get(http_10k, datos, f"q={q}")
        assert [i["numero_empleado"] for i in r["items"]] == ["N04242"], q
    r = await _get(http_10k, datos, "q=n0424")
    assert r["total"] == 10  # prefijo del número: N04240 a N04249
    r = await _get(http_10k, datos, "q=%25")  # comodín de LIKE literal: no devuelve todo
    assert r["total"] == 0


async def test_filtros_fijos_y_combinados(http_10k, datos):
    assert (await _get(http_10k, datos, "estatus=BAJA"))["total"] == TOTAL // 10
    assert (await _get(http_10k, datos, f"organizacion_id={datos['org1']}"))["total"] == TOTAL // 2
    assert (await _get(http_10k, datos, "tipo_empleado=ADMINISTRATIVO"))["total"] == TOTAL // 3
    combinado = await _get(
        http_10k,
        datos,
        f"estatus=ACTIVO&organizacion_id={datos['org1']}&tipo_empleado=ADMINISTRATIVO",
    )
    esperado = sum(1 for g in range(1, TOTAL + 1) if g % 10 and g % 2 == 0 and g % 3 == 0)
    assert combinado["total"] == esperado


async def test_filtro_y_columna_por_campo_dinamico_no_sensible(http_10k, datos):
    r = await _get(http_10k, datos, "f.CAMP-0002=VENTAS&columnas=CAMP-0002&limite=5")
    assert r["total"] == TOTAL // 7
    assert all(i["campos"] == {"CAMP-0002": datos["opcion"]} for i in r["items"])


async def test_los_sensibles_no_se_filtran_ni_se_devuelven(http_10k, datos):
    for consulta in ("f.CAMP-0001=12345678901", "columnas=CAMP-0001"):
        r = await http_10k.get(f"/api/v1/colaboradores?{consulta}", headers=_h(datos))
        assert r.status_code == 422
        assert r.json()["errores"][0]["codigo"] == "CAMPO_SENSIBLE_NO_FILTRABLE"
        assert "12345678901" not in r.text
    r = await http_10k.get("/api/v1/colaboradores?f.CAMP-0999=x", headers=_h(datos))
    assert r.status_code == 422


async def test_otra_empresa_no_ve_nada(http_10k, datos):
    r = await http_10k.get("/api/v1/colaboradores", headers=_h(datos, "b", "ub"))
    assert r.json()["total"] == 0


async def test_rendimiento_de_la_pagina(http_10k, datos):
    inicio = time.perf_counter()
    for consulta in ("", "q=angel", "f.CAMP-0002=VENTAS", "estatus=ACTIVO&pagina=50"):
        await _get(http_10k, datos, consulta)
    assert (time.perf_counter() - inicio) / 4 < 1.0  # promedio por página, con total


def test_la_busqueda_por_nombre_usa_el_indice_trigrama(http_10k, datos):
    """Misma expresión que ``colaborador_nombre_trgm``: el plan usa el índice."""
    from cc_colaboradores.repos.listado import NOMBRE_INDEXADO

    with psycopg.connect(datos["bd"].url_admin) as c:
        c.execute("SET enable_seqscan = off")  # demuestra que el índice coincide con la expresión
        plan = "\n".join(
            f[0]
            for f in c.execute(
                f"EXPLAIN SELECT id FROM colaboradores.colaborador c WHERE {NOMBRE_INDEXADO} "
                "LIKE colaboradores.f_unaccent('%%angel%%')"
            ).fetchall()
        )
    assert "colaborador_nombre_trgm" in plan, plan
