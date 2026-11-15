"""T-204: carga con la plantilla real del cliente (v1.3), 2,000 filas, rendimiento y aislamiento.

Mediciones frente a los valores candidatos de design.md §15.3 (CC-NFR-002, [POR CONFIRMAR]):
carga de 2,000 filas en menos de 2 minutos; listados y búsquedas con p95 menor a 1 s.
"""

import statistics
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path

import httpx
import psycopg
import pytest
from ayudantes_colaboradores import StubCampos, cab, construir_app, emitir
from cc_colaboradores.campos_cliente import CacheCampos, DefinicionCampo, OpcionCampo
from cc_colaboradores.workers.worker_cargas import procesar_carga
from openpyxl import load_workbook

pytestmark = pytest.mark.docker

PLANTILLA = next(
    (Path(__file__).parents[3] / "kiro_command_center_frontline_v1" / "plantilla_carga").glob(
        "*.xlsx"
    ),
    None,
)
LIMITE_CARGA_S = 120  # candidato de §15.3: 2 minutos para 2,000 filas
LIMITE_LISTADO_S = 1.0  # candidato de §15.3: 1 s (p95)
CURP = r"[A-Z]{4}\d{6}[HMX][A-Z]{2}[B-DF-HJ-NP-TV-Z]{3}[A-Z0-9]\d"

# (clave, nombre, tipo, sensible, opciones, formato)
CAMPOS_CLIENTE = [
    ("area", "Área", "LISTA", False, ["Producción", "Calidad"], None),
    ("departamento", "Departamento", "LISTA", False, ["Línea 2", "Línea 3"], None),
    ("turno", "Turno", "LISTA", False, ["Matutino", "Vespertino", "Nocturno"], None),
    ("ruta_transporte", "Ruta de transporte", "TEXTO", False, [], None),
    ("sueldo", "Sueldo (MXN)", "NUMERO", True, [], None),
    (
        "periodicidad_sueldo",
        "Periodicidad del sueldo",
        "LISTA",
        False,
        ["Semanal", "Catorcenal", "Quincenal", "Mensual"],
        None,
    ),  # fmt: skip
    ("registro_patronal", "Registro Patronal", "TEXTO", True, [], r"[A-Z0-9]{11}"),
    ("nss", "NSS", "TEXTO", True, [], r"\d{11}"),
    ("rfc", "RFC Colaborador", "TEXTO", True, [], r"[A-ZÑ&]{4}\d{6}[A-Z0-9]{3}"),
    ("curp", "CURP", "TEXTO", True, [], CURP),
    ("correo", "Correo electrónico", "TEXTO", False, [], r"[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}"),
]


def _sembrar(datos, empresa: int) -> list[DefinicionCampo]:
    definiciones = []
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        # reemplaza los campos de ejemplo de la fixture por la configuración del cliente
        c.execute("DELETE FROM campos.opcion_campo WHERE empresa_id = %s", (empresa,))
        c.execute("DELETE FROM campos.campo_colaborador WHERE empresa_id = %s", (empresa,))
        for orden, (clave, nombre, tipo, sensible, opciones, formato) in enumerate(
            CAMPOS_CLIENTE, 1
        ):
            codigo = f"CAMP-{900 + orden:04d}"
            campo_id = c.execute(
                "INSERT INTO campos.campo_colaborador (empresa_id, nombre_campo, clave, "
                "codigo_interno, tipo_dato, orden, es_sensible) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (empresa, nombre, clave, codigo, tipo, orden, sensible),
            ).fetchone()[0]
            opcs = []
            for i, etiqueta in enumerate(opciones, 1):
                valor = etiqueta.upper().replace(" ", "_")
                oid = c.execute(
                    "INSERT INTO campos.opcion_campo (empresa_id, campo_id, etiqueta, valor, orden) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (empresa, campo_id, etiqueta, valor, i),
                ).fetchone()[0]
                opcs.append(OpcionCampo(oid, etiqueta, valor, orden=i))
            definiciones.append(
                DefinicionCampo(
                    campo_id, nombre, clave, codigo, tipo, es_sensible=sensible,
                    formato_validacion=formato, orden=orden, opciones=tuple(opcs),
                )
            )  # fmt: skip
        c.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORG01', 'Empresa Ejemplo')",
            (empresa,),
        )
        c.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Planta Apodaca')",
            (empresa,),
        )
    return definiciones


@pytest.fixture
async def mundo(datos, motor, cifrador, s3_cargas):
    if PLANTILLA is None:
        pytest.skip("No está la plantilla real del cliente en plantilla_carga/")
    defs_a = _sembrar(datos, datos["a"])
    # la empresa B solo necesita su organización y planta (sin campos dinámicos)
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        c.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORG01', 'Otra')",
            (datos["b"],),
        )
        c.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Planta Apodaca')",
            (datos["b"],),
        )
    campos = CacheCampos(StubCampos({datos["a"]: defs_a, datos["b"]: []}), ttl_s=0)
    almacen, cliente_s3, bucket = s3_cargas
    app = construir_app(motor, cifrador, almacen_cargas=almacen, campos=campos)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as h:
        yield {
            "http": h, "datos": datos, "almacen": almacen, "motor": motor,
            "cifrador": cifrador, "campos": campos,
        }  # fmt: skip


def _h(datos, empresa="a"):
    sub, uid = ("sub-a", datos["ua"]) if empresa == "a" else ("sub-b", datos["ub"])
    return cab(emitir(sub, datos[empresa], uid))


def _sql(datos, sql, params=()):
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        cur = c.execute(sql, params)
        return cur.fetchall() if cur.description else []


def _plantilla_con(n: int, *, desde_fila: int = 4, errores: dict[int, dict] | None = None) -> bytes:
    """La plantilla real del cliente con ``n`` colaboradores a partir de ``desde_fila`` (la fila 3
    trae el ejemplo ``EJEMPLO-001``; con ``desde_fila=3`` se reemplaza)."""
    wb = load_workbook(PLANTILLA)
    ws = wb["Colaboradores"]
    for i in range(n):
        fila = desde_fila + i
        valores = {
            "A": f"EMP-{i + 1:05d}",
            "B": "María Fernanda",
            "C": "Ramírez",
            "D": "Ortiz",
            "E": f"81{i + 1:08d}",
            "F": "ORG01",
            "G": datetime(2021, 3, 15),
            "H": "Operador de producción",
            "I": "Operativo",
            "J": "Planta Apodaca",
            "K": "Producción",
            "L": "Línea 2",
            "M": "Matutino",
            "N": f"Ruta {i % 9}",
            "O": "ACTIVO",
            "P": 9500,
            "Q": "Quincenal",
            "R": "A0000000000",
            "S": "00000000000",
            "T": "XAXX010101000",
            "U": "XEXX010101HNEXXXA4",
            "V": f"emp{i + 1}@ejemplo.com",
        }
        valores.update((errores or {}).get(i, {}))
        for columna, valor in valores.items():
            ws[f"{columna}{fila}"] = valor
    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()


async def _cargar(m, contenido: bytes, empresa="a"):
    """Flujo completo: inicia, sube, confirma y procesa. Devuelve (carga, segundos del worker)."""
    d = m["datos"]
    http = m["http"]
    r = await http.post(
        "/api/v1/cargas",
        json={"nombre_archivo": "real.xlsx", "tamano": len(contenido)},
        headers=_h(d, empresa),
    )
    assert r.status_code == 201, r.text
    c = r.json()
    async with httpx.AsyncClient(timeout=120) as externo:
        put = await externo.put(
            c["url_subida"],
            content=contenido,
            headers={"Content-Type": c["content_type"]},
        )
    assert put.status_code == 200
    r = await http.post(f"/api/v1/cargas/{c['carga_id']}/confirmar", headers=_h(d, empresa))
    assert r.status_code == 202, r.text
    t0 = time.perf_counter()
    estado = await procesar_carga(
        m["motor"], m["cifrador"], m["campos"], m["almacen"],
        empresa_id=d[empresa], carga_id=c["carga_id"],
    )  # fmt: skip
    segundos = time.perf_counter() - t0
    assert estado == "TERMINADA"
    detalle = (await http.get(f"/api/v1/cargas/{c['carga_id']}", headers=_h(d, empresa))).json()
    return detalle["carga"], segundos


async def test_la_plantilla_real_sin_capturar_trae_solo_el_ejemplo(mundo):
    contenido = PLANTILLA.read_bytes()
    carga, _ = await _cargar(mundo, contenido)
    assert carga["total_filas"] == 0 and carga["version_plantilla"] == "EXTERNA"
    assert _sql(mundo["datos"], "SELECT count(*) FROM colaboradores.colaborador") == [(0,)]


async def test_plantilla_real_con_colaboradores_y_errores(mundo):
    datos = mundo["datos"]
    carga, _ = await _cargar(
        mundo,
        _plantilla_con(
            30,
            errores={
                2: {"E": "123"},  # fila 6: celular inválido
                5: {"F": "ORG99"},  # fila 9: organización inexistente
                7: {"S": "abc"},  # fila 11: NSS con formato inválido
                9: {"P": None},  # fila 13: sueldo sin periodicidad
                11: {"M": "Madrugada"},  # fila 15: turno que no existe
            },
        ),
    )
    assert (carga["total_filas"], carga["filas_ok"], carga["filas_error"]) == (30, 25, 5)
    errores = dict(
        _sql(
            datos,
            "SELECT numero_fila, split_part(mensaje, ':', 1) FROM colaboradores.fila_carga "
            "WHERE resultado = 'ERROR'",
        )
    )
    assert errores == {
        6: "CELULAR_INVALIDO",
        9: "ORGANIZACION_NO_EXISTE",
        11: "FORMATO_INVALIDO",
        13: "SUELDO_SIN_PERIODICIDAD",
        15: "VALOR_LISTA_INVALIDO",
    }
    assert _sql(datos, "SELECT count(*) FROM colaboradores.colaborador") == [(25,)]
    # los once campos dinámicos del cliente quedaron guardados; los sensibles, solo cifrados
    por_campo = dict(
        _sql(
            datos,
            "SELECT campo_id, count(*) FROM colaboradores.valor_campo GROUP BY campo_id",
        )
    )
    assert len(por_campo) == 11 and set(por_campo.values()) == {25}
    cifrados = _sql(
        datos,
        "SELECT count(*) FROM colaboradores.valor_campo "
        "WHERE valor_cifrado IS NOT NULL AND valor_texto IS NULL AND valor_numero IS NULL",
    )
    assert cifrados == [(25 * 5,)]  # sueldo, registro patronal, NSS, RFC y CURP


async def test_dos_mil_filas_con_la_plantilla_real(mundo, record_property):
    datos = mundo["datos"]
    contenido = _plantilla_con(2000, desde_fila=3)  # filas 3 a 2002: el máximo de la plantilla
    assert len(contenido) < 5 * 1024 * 1024
    carga, segundos = await _cargar(mundo, contenido)
    assert (carga["total_filas"], carga["filas_ok"], carga["filas_error"]) == (2000, 2000, 0)
    record_property("segundos_2000_filas_alta", round(segundos, 1))
    print(f"\n[T-204] 2,000 filas (alta): {segundos:.1f} s (candidato: {LIMITE_CARGA_S} s)")
    assert segundos < LIMITE_CARGA_S
    assert _sql(datos, "SELECT count(*) FROM colaboradores.colaborador") == [(2000,)]

    # la misma carga otra vez actualiza a todos sin duplicar ni tocar el consentimiento
    _sql(datos, "UPDATE colaboradores.colaborador SET consentimiento_whatsapp = true")
    carga2, segundos2 = await _cargar(mundo, contenido)
    print(f"[T-204] 2,000 filas (actualización): {segundos2:.1f} s")
    record_property("segundos_2000_filas_actualizacion", round(segundos2, 1))
    assert (carga2["filas_ok"], carga2["filas_error"]) == (2000, 0) and segundos2 < LIMITE_CARGA_S
    assert _sql(
        datos,
        "SELECT count(*), count(*) FILTER (WHERE consentimiento_whatsapp) "
        "FROM colaboradores.colaborador",
    ) == [(2000, 2000)]
    assert _sql(datos, "SELECT count(*) FROM colaboradores.valor_campo") == [(2000 * 11,)]


async def test_aislamiento_por_empresa(mundo):
    datos = mundo["datos"]
    await _cargar(mundo, _plantilla_con(5))
    ids = [r[0] for r in _sql(datos, "SELECT id FROM colaboradores.colaborador ORDER BY id")]
    carga_a = _sql(datos, "SELECT id FROM colaboradores.carga_colaboradores")[0][0]
    # la empresa B carga el mismo archivo: crea sus propios colaboradores, sin chocar con los de A
    carga_b, _ = await _cargar(mundo, _plantilla_con(5), empresa="b")
    assert carga_b["filas_ok"] == 5
    assert _sql(
        datos,
        "SELECT empresa_id, count(*) FROM colaboradores.colaborador GROUP BY 1 ORDER BY 1",
    ) == [(datos["a"], 5), (datos["b"], 5)]
    # un usuario de B recibe 404 sobre los registros de A
    http = mundo["http"]
    for ruta in (f"/api/v1/colaboradores/{ids[0]}", f"/api/v1/cargas/{carga_a}"):
        assert (await http.get(ruta, headers=_h(datos, "b"))).status_code == 404
    listado = (await http.get("/api/v1/colaboradores", headers=_h(datos, "b"))).json()
    assert listado["total"] == 5 and not {i["id"] for i in listado["items"]} & set(ids)
    assert (await http.get(f"/api/v1/colaboradores/{ids[0]}", headers=_h(datos))).status_code == 200


async def test_listado_y_busqueda_con_10000_colaboradores(mundo, record_property):
    datos = mundo["datos"]
    _sql(
        datos,
        """
        INSERT INTO colaboradores.colaborador
          (empresa_id, organizacion_id, planta_id, numero_empleado, nombres, apellido_paterno,
           apellido_materno, celular_cifrado, celular_hash, celular_ultimos4, fecha_ingreso, puesto,
           tipo_empleado)
        SELECT %s, o.id, p.id, 'N-' || lpad(i::text, 6, '0'),
               (ARRAY['María','José','Ana','Luis','Carmen','Jorge'])[1 + mod(i, 6)],
               (ARRAY['Ramírez','Martínez','López','García','Hernández'])[1 + mod(i, 5)],
               'Apellido' || i, '\\x00'::bytea,
               decode(md5(i::text) || md5(i::text || 'x'), 'hex'), lpad(mod(i, 10000)::text, 4, '0'),
               date '2020-01-01' + mod(i, 1000), 'Operador', 'OPERATIVO'
        FROM generate_series(1, 10000) i,
             (SELECT id FROM colaboradores.organizacion WHERE empresa_id = %s) o,
             (SELECT id FROM colaboradores.planta WHERE empresa_id = %s) p
        """,
        (datos["a"], datos["a"], datos["a"]),
    )
    _sql(datos, "ANALYZE colaboradores.colaborador")
    http, h = mundo["http"], _h(datos)
    consultas = {
        "listado": "/api/v1/colaboradores?pagina=3&limite=50",
        "busqueda_nombre": "/api/v1/colaboradores?q=maria%20ramirez",
        "busqueda_numero": "/api/v1/colaboradores?q=N-0042",
        "filtro_estatus": "/api/v1/colaboradores?estatus=ACTIVO&tipo_empleado=OPERATIVO",
    }
    for nombre, ruta in consultas.items():
        tiempos = []
        for _ in range(40):
            t0 = time.perf_counter()
            r = await http.get(ruta, headers=h)
            tiempos.append(time.perf_counter() - t0)
            assert r.status_code == 200
        p95 = statistics.quantiles(tiempos, n=20)[-1]
        print(f"\n[T-204] {nombre} con 10,000 colaboradores: p95 = {p95 * 1000:.0f} ms")
        record_property(f"p95_ms_{nombre}", round(p95 * 1000))
        assert p95 < LIMITE_LISTADO_S, nombre
    assert (await http.get(consultas["listado"], headers=h)).json()["total"] == 10000
