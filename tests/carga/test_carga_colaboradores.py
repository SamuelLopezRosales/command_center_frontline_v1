"""T-142: listados y búsquedas con 10,000 colaboradores (CC-NFR-002, candidato de §15.3: p95 < 1 s).

Mide en proceso (app ASGI real, PostgreSQL 16 de Testcontainers con RLS y el rol
``svc_colaboradores``): cada consulta 100 veces en serie y 200 veces con 10 en vuelo (los 10 VUs
del guion k6). El tiempo no incluye red ni API Gateway: es el costo de la app y de la base.
"""

import random

import httpx
import psycopg
import pytest
from ayudantes_colaboradores import StubCampos, cab, construir_app, emitir
from ayudantes_medicion import fixtures_de, medir_concurrente, medir_secuencial, p95, registrar
from cc_colaboradores.campos_cliente import CacheCampos, DefinicionCampo, OpcionCampo

pytestmark = [pytest.mark.carga, pytest.mark.docker]

_c = fixtures_de("services/colaboradores/tests/conftest.py", "conf_colaboradores_carga")
datos, kms, cifrador, motor = _c.datos, _c.kms, _c.cifrador, _c.motor

TOTAL = 10_000
LIMITE_S = 1.0  # candidato de §15.3


@pytest.fixture
async def http_10k(motor, cifrador, datos):
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
                   (ARRAY['María','José','Ana','Luis','Carmen','Jorge'])[1 + mod(g, 6)] || ' ' || g,
                   (ARRAY['Ramírez','Martínez','López','García','Hernández'])[1 + mod(g, 5)],
                   'Materno' || g, '\\x00'::bytea, sha256(g::text::bytea), '0000',
                   DATE '2020-01-01' + mod(g, 1000),
                   'Puesto', CASE WHEN g %% 3 = 0 THEN 'ADMINISTRATIVO' ELSE 'OPERATIVO' END,
                   CASE WHEN g %% 10 = 0 THEN 'BAJA' ELSE 'ACTIVO' END,
                   CASE WHEN g %% 10 = 0 THEN DATE '2026-01-01' END, g %% 5 = 0
            FROM generate_series(1, %(n)s) g
            """,
            {"e": datos["a"], "o1": org1, "o2": org2, "p": planta, "n": TOTAL},
        )
        c.execute(
            "INSERT INTO colaboradores.valor_campo (empresa_id, colaborador_id, campo_id, "
            "valor_opcion_id) SELECT %s, id, %s, %s FROM colaboradores.colaborador "
            "WHERE substr(numero_empleado, 2)::int %% 7 = 0",
            (datos["a"], c_area, datos["opcion"]),
        )
        c.execute(
            "INSERT INTO colaboradores.valor_campo (empresa_id, colaborador_id, campo_id, "
            "valor_cifrado) SELECT %s, id, %s, '\\x01'::bytea FROM colaboradores.colaborador",
            (datos["a"], c_nss),
        )
        c.execute("ANALYZE colaboradores.colaborador; ANALYZE colaboradores.valor_campo")
    defs = [
        DefinicionCampo(c_nss, "NSS", "nss", "CAMP-0001", "TEXTO", es_sensible=True),
        DefinicionCampo(
            c_area, "Área", "area", "CAMP-0002", "LISTA",
            opciones=(OpcionCampo(datos["opcion"], "Ventas", "VENTAS"),),
        ),
    ]  # fmt: skip
    app = construir_app(motor, cifrador, campos=CacheCampos(StubCampos({datos["a"]: defs})))
    datos.update(org1=org1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as h:
        yield h


async def test_p95_de_listados_y_busquedas_con_10000(http_10k, datos):
    h = cab(emitir("sub-a", datos["a"], datos["ua"]))
    azar = random.Random(7)
    consultas = {
        "listado (pagina aleatoria, limite 50)": lambda: (
            f"/api/v1/colaboradores?pagina={azar.randint(1, 200)}&limite=50"
        ),
        "busqueda por nombre": lambda: (
            f"/api/v1/colaboradores?q={azar.choice(['maria', 'jose 12', 'ramirez', 'luis garcia'])}"
        ),
        "busqueda por numero de empleado": lambda: (
            f"/api/v1/colaboradores?q=N{azar.randint(0, 9999):05d}"
        ),
        "filtros fijos combinados": lambda: (
            f"/api/v1/colaboradores?estatus=ACTIVO&organizacion_id={datos['org1']}"
            f"&tipo_empleado=ADMINISTRATIVO&pagina={azar.randint(1, 20)}&limite=50"
        ),
        "filtro por campo dinamico y columna": lambda: (
            "/api/v1/colaboradores?f.CAMP-0002=VENTAS&columnas=CAMP-0002&limite=50"
        ),
    }
    for nombre, ruta in consultas.items():

        async def una(ruta=ruta):
            r = await http_10k.get(ruta(), headers=h)
            assert r.status_code == 200, r.text

        await medir_secuencial(una, 10)  # calentamiento: plan, cache de campos, conexiones
        serie = await medir_secuencial(una, 100)
        conc = await medir_concurrente(una, 200, 10)
        registrar(f"colaboradores {nombre}", f"{p95(serie) * 1000:.0f}", "ms p95 serie (n=100)")
        registrar(
            f"colaboradores {nombre}", f"{p95(conc) * 1000:.0f}", "ms p95 con 10 en vuelo (n=200)"
        )
        assert p95(serie) < LIMITE_S and p95(conc) < LIMITE_S, nombre
