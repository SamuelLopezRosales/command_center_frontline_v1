"""T-142: p95 del dashboard y del historial con datos grandes (CC-NFR-002, candidato 1 s).

Datos: la empresa A con 10,000 colaboradores (8,000 sin consentimiento, para las alertas) y 6,000
constancias de un año (unas 500 por mes, con solicitud, tres plantillas y entregas mezcladas); la
empresa B con 2,000 constancias más, para que el filtro por empresa trabaje con datos ajenos. Se
mide en proceso (app ASGI real, PostgreSQL de Testcontainers, rol ``svc_dashboard``): cada ruta 100
veces en serie y 200 con 10 en vuelo.
"""

import hashlib

import psycopg
import pytest
from ayudantes_dashboard import cab, emitir
from ayudantes_medicion import fixtures_de, medir_concurrente, medir_secuencial, p95, registrar

pytestmark = [pytest.mark.carga, pytest.mark.docker]

_c = fixtures_de("services/dashboard/tests/conftest.py", "conf_dashboard_carga")
datos, cognito, cliente = _c.datos, _c.cognito, _c.cliente

LIMITE_S = 1.0  # candidato de §15.3
H64 = hashlib.sha256(b"carga").hexdigest()

SQL_COLABORADORES = """
INSERT INTO colaboradores.colaborador
  (empresa_id, organizacion_id, planta_id, numero_empleado, nombres, apellido_paterno,
   apellido_materno, celular_cifrado, celular_hash, celular_ultimos4, fecha_ingreso, puesto,
   tipo_empleado, consentimiento_whatsapp)
SELECT %(e)s, %(o)s, %(p)s, 'N' || lpad(g::text, 5, '0'),
       (ARRAY['María','José','Ana','Luis','Carmen','Jorge'])[1 + mod(g, 6)] || ' ' || g,
       (ARRAY['Ramírez','Martínez','López','García','Hernández'])[1 + mod(g, 5)],
       'Materno', 'x'::bytea, sha256((%(e)s::text || '-' || g::text)::bytea), '0000',
       DATE '2020-01-01', 'Puesto', 'OPERATIVO', g %% 5 = 0
FROM generate_series(1, %(n)s) g
"""

SQL_SOLICITUDES = """
INSERT INTO constancias.solicitud_constancia
  (empresa_id, colaborador_id, version_plantilla_id, estado, colaborador_nombre, fecha_solicitud)
SELECT %(e)s, c.id, v.id, 'GENERADA', c.nombres || ' ' || c.apellido_paterno,
       now() - (g * interval '1 hour') * 365 * 24 / %(n)s
FROM generate_series(1, %(n)s) g
JOIN (SELECT id, nombres, apellido_paterno, row_number() OVER (ORDER BY id) AS rn
        FROM colaboradores.colaborador WHERE empresa_id = %(e)s) c
  ON c.rn = 1 + mod(g, (SELECT count(*) FROM colaboradores.colaborador WHERE empresa_id = %(e)s))
JOIN (SELECT id, row_number() OVER (ORDER BY id) AS rn
        FROM constancias.version_plantilla WHERE empresa_id = %(e)s) v
  ON v.rn = 1 + mod(g, 3)
"""

SQL_CONSTANCIAS = """
INSERT INTO constancias.constancia_generada
  (empresa_id, solicitud_id, colaborador_id, version_plantilla_id, folio, pdf_s3_key,
   pdf_hash_sha256, datos_snapshot_json, estado_entrega, fecha_generacion, colaborador_nombre,
   numero_empleado, codigo_verificacion)
SELECT s.empresa_id, s.id, s.colaborador_id, s.version_plantilla_id,
       'CG-2026-' || lpad(row_number() OVER (ORDER BY s.id)::text, 4, '0'), 'pdf', %(h)s,
       '{"p": 1}'::jsonb,
       CASE mod(s.id, 10) WHEN 0 THEN 'FALLIDA' WHEN 1 THEN 'PENDIENTE' ELSE 'ENTREGADA' END,
       s.fecha_solicitud, s.colaborador_nombre, 'N00001',
       md5(s.id::text) || md5(s.id::text || 'x')
FROM constancias.solicitud_constancia s WHERE s.empresa_id = %(e)s
"""


@pytest.fixture
def sembrada(datos):
    """Devuelve los ids de las tres plantillas de A tras sembrar los datos grandes."""
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        for empresa, usuario, n_col, n_const in (
            (datos["a"], datos["ua"], 10_000, 6_000),
            (datos["b"], datos["ub"], 2_000, 2_000),
        ):
            org = c.execute(
                "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
                "VALUES (%s, 'ORG1', 'Org') RETURNING id",
                (empresa,),
            ).fetchone()[0]
            pla = c.execute(
                "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'P') "
                "RETURNING id",
                (empresa,),
            ).fetchone()[0]
            c.execute(SQL_COLABORADORES, {"e": empresa, "o": org, "p": pla, "n": n_col})
            for nombre in ("Laboral", "Ingresos", "Antigüedad"):
                pid = c.execute(
                    "INSERT INTO constancias.plantilla_constancia (empresa_id, nombre, activa) "
                    "VALUES (%s, %s, true) RETURNING id",
                    (empresa, nombre),
                ).fetchone()[0]
                c.execute(
                    "INSERT INTO constancias.version_plantilla (empresa_id, plantilla_id, numero, "
                    "contenido_s3_key, hash_sha256, creada_por_usuario_id) "
                    "VALUES (%s, %s, 1, 'k', %s, %s)",
                    (empresa, pid, H64, usuario),
                )
            c.execute(SQL_SOLICITUDES, {"e": empresa, "n": n_const})
            c.execute(SQL_CONSTANCIAS, {"e": empresa, "h": H64})
        c.execute(
            "ANALYZE colaboradores.colaborador; ANALYZE constancias.constancia_generada; "
            "ANALYZE constancias.solicitud_constancia"
        )
        return [r[0] for r in c.execute(
            "SELECT id FROM constancias.plantilla_constancia WHERE empresa_id = %s ORDER BY id",
            (datos["a"],),
        )]  # fmt: skip


async def test_p95_del_dashboard_y_del_historial(cliente, datos, sembrada):
    h = cab(emitir("sub-a", datos["a"]))
    rutas = {
        "dashboard resumen": "/api/v1/dashboard/resumen",
        "dashboard solicitudes recientes": "/api/v1/dashboard/solicitudes-recientes?limite=10",
        "dashboard constancias recientes": "/api/v1/dashboard/constancias-recientes?limite=10",
        "dashboard alertas": "/api/v1/dashboard/alertas",
        "historial primera pagina": "/api/v1/constancias/historial?limite=20",
        "historial por rango de fechas": (
            "/api/v1/constancias/historial?desde=2026-01-01&hasta=2026-12-31&limite=50"
        ),
        "historial por estado": "/api/v1/constancias/historial?estado=FALLIDA&limite=50",
        "historial por plantilla": f"/api/v1/constancias/historial?plantilla_id={sembrada[0]}",
        "historial busqueda por nombre": "/api/v1/constancias/historial?q=maria%20ram",
        "historial busqueda por folio": "/api/v1/constancias/historial?q=CG-2026-0042",
    }
    peor = 0.0
    for nombre, ruta in rutas.items():

        async def una(ruta=ruta):
            r = await cliente.get(ruta, headers=h)
            assert r.status_code == 200, (ruta, r.text)

        await medir_secuencial(una, 10)
        serie = await medir_secuencial(una, 100)
        conc = await medir_concurrente(una, 200, 10)
        registrar(nombre, f"{p95(serie) * 1000:.0f}", "ms p95 serie (n=100)")
        registrar(nombre, f"{p95(conc) * 1000:.0f}", "ms p95 con 10 en vuelo (n=200)")
        peor = max(peor, p95(serie), p95(conc))
    assert peor < LIMITE_S


async def test_historial_recorrido_completo_por_cursor(cliente, datos, sembrada):
    """Recorre las 6,000 constancias por cursor (300 páginas): sin repetir ni saltar."""
    h = cab(emitir("sub-a", datos["a"]))
    vistos: list[int] = []
    tiempos: list[float] = []
    cursor = None
    import time

    while True:
        ruta = "/api/v1/constancias/historial?limite=20" + (f"&cursor={cursor}" if cursor else "")
        t0 = time.perf_counter()
        r = await cliente.get(ruta, headers=h)
        tiempos.append(time.perf_counter() - t0)
        assert r.status_code == 200, r.text
        cuerpo = r.json()
        vistos += [i["id"] for i in cuerpo["items"]]
        cursor = cuerpo["siguiente"]
        if not cursor:
            break
    registrar("historial cursor, 300 paginas", f"{p95(tiempos) * 1000:.0f}", "ms p95 por pagina")
    assert len(vistos) == 6_000 == len(set(vistos))
    assert p95(tiempos) < LIMITE_S
