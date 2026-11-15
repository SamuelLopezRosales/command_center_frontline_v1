"""T-213: DSH-01 a DSH-04 e historial DSH-11 sobre las vistas contractuales."""

import hashlib
import json
import uuid

import psycopg
import pytest
from ayudantes_dashboard import cab, emitir

pytestmark = pytest.mark.docker

H64 = "a" * 64


class Sembrador:
    """Inserta datos con el rol administrador (el servicio solo lee vistas)."""

    def __init__(self, url_admin: str):
        self.c = psycopg.connect(url_admin, autocommit=True)
        self._ctx: dict[int, dict] = {}
        self._n = 0

    def cerrar(self):
        self.c.close()

    def _empresa(self, emp: int, usuario_id: int):
        if emp not in self._ctx:
            org = self.c.execute(
                "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
                "VALUES (%s, 'ORG01', 'Org') RETURNING id",
                (emp,),
            ).fetchone()[0]
            pla = self.c.execute(
                "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'P') RETURNING id",
                (emp,),
            ).fetchone()[0]
            self._ctx[emp] = {"org": org, "pla": pla, "usu": usuario_id}
        return self._ctx[emp]

    def colaborador(self, emp, usu, nombres="Ana", consentimiento=True, estatus="ACTIVO"):
        x = self._empresa(emp, usu)
        self._n += 1
        h = hashlib.sha256(f"{emp}-{self._n}".encode()).digest()
        return self.c.execute(
            "INSERT INTO colaboradores.colaborador (empresa_id, organizacion_id, planta_id, "
            "numero_empleado, nombres, apellido_paterno, apellido_materno, celular_cifrado, "
            "celular_hash, celular_ultimos4, fecha_ingreso, puesto, tipo_empleado, "
            "consentimiento_whatsapp, estatus) VALUES (%s,%s,%s,%s,%s,'López','Ruiz',%s,%s,'5678',"
            "'2021-03-15','Analista','ADMINISTRATIVO',%s,%s) RETURNING id",
            (
                emp,
                x["org"],
                x["pla"],
                f"EMP-{self._n:04d}",
                nombres,
                b"\x01x",
                h,
                consentimiento,
                estatus,
            ),
        ).fetchone()[0]

    def plantilla(self, emp, usu, nombre="Laboral", activa=True):
        pla = self.c.execute(
            "INSERT INTO constancias.plantilla_constancia (empresa_id, nombre, activa) "
            "VALUES (%s,%s,%s) RETURNING id",
            (emp, nombre, activa),
        ).fetchone()[0]
        ver = self.c.execute(
            "INSERT INTO constancias.version_plantilla (empresa_id, plantilla_id, numero, "
            "contenido_s3_key, hash_sha256, creada_por_usuario_id) VALUES (%s,%s,3,'k',%s,%s) "
            "RETURNING id",
            (emp, pla, H64, usu),
        ).fetchone()[0]
        return pla, ver

    def solicitud(self, emp, col, ver, estado="EN_PROCESO", nombre="Ana López Ruiz"):
        return self.c.execute(
            "INSERT INTO constancias.solicitud_constancia (empresa_id, colaborador_id, "
            "version_plantilla_id, estado, colaborador_nombre, motivo_fallo) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (emp, col, ver, estado, nombre, "X" if estado == "FALLIDA" else None),
        ).fetchone()[0]

    def constancia(
        self, emp, col, ver, folio, estado="ENTREGADA", nombre="Ana López Ruiz", fecha=None
    ):
        sol = self.solicitud(emp, col, ver, estado="GENERADA", nombre=nombre)
        cid = self.c.execute(
            "INSERT INTO constancias.constancia_generada (empresa_id, solicitud_id, colaborador_id, "
            "version_plantilla_id, folio, pdf_s3_key, pdf_hash_sha256, datos_snapshot_json, "
            "colaborador_nombre, numero_empleado, codigo_verificacion, estado_entrega) "
            "VALUES (%s,%s,%s,%s,%s,'pdf',%s,%s,%s,'EMP-0001',%s,%s) RETURNING id",
            (
                emp,
                sol,
                col,
                ver,
                folio,
                H64,
                json.dumps({"p": 1}),
                nombre,
                uuid.uuid4().hex,
                estado,
            ),
        ).fetchone()[0]
        if fecha:
            # La fecha se fija con SET session_replication_role para esquivar el trigger de inmutabilidad.
            with self.c.transaction():
                self.c.execute("SET LOCAL session_replication_role = replica")
                self.c.execute(
                    "UPDATE constancias.constancia_generada SET fecha_generacion = %s WHERE id = %s",
                    (fecha, cid),
                )
        return cid


@pytest.fixture
def s(datos):
    x = Sembrador(datos["bd"].url_admin)
    yield x
    x.cerrar()


def _h(datos, empresa="a"):
    sub = "sub-a" if empresa == "a" else "sub-b"
    return cab(emitir(sub, datos[empresa]))


# --- DSH-01 ----------------------------------------------------------------------------------


async def test_resumen_cuenta_solo_la_empresa_del_usuario(cliente, datos, s):
    a, ua, b, ub = datos["a"], datos["ua"], datos["b"], datos["ub"]
    for _ in range(3):
        s.colaborador(a, ua)
    s.colaborador(a, ua, estatus="BAJA")
    s.colaborador(b, ub)
    pla, ver = s.plantilla(a, ua)
    col = s.colaborador(a, ua)
    s.constancia(a, col, ver, "CG-2026-0001")
    s.solicitud(a, col, ver, "EN_PROCESO")
    s.solicitud(a, col, ver, "ENTREGADA")
    s.plantilla(a, ua, "Inactiva", activa=False)

    r = await cliente.get("/api/v1/dashboard/resumen", headers=_h(datos))
    assert r.status_code == 200
    assert r.json() == {
        "colaboradores_activos": 4,
        "constancias_mes": 1,
        "solicitudes_en_proceso": 1 + 1,  # la solicitud de la constancia generada también cuenta
        "plantillas_activas": 1,
        "vacio": False,
    }
    otra = (await cliente.get("/api/v1/dashboard/resumen", headers=_h(datos, "b"))).json()
    assert otra["colaboradores_activos"] == 1 and otra["constancias_mes"] == 0


async def test_resumen_sin_datos_marca_vacio(cliente, datos):
    r = await cliente.get("/api/v1/dashboard/resumen", headers=_h(datos))
    assert r.json() == {
        "colaboradores_activos": 0,
        "constancias_mes": 0,
        "solicitudes_en_proceso": 0,
        "plantillas_activas": 0,
        "vacio": True,
    }


async def test_el_mes_es_el_calendario_de_la_zona_de_la_empresa(cliente, datos, s):
    a, ua = datos["a"], datos["ua"]
    _, ver = s.plantilla(a, ua)
    col = s.colaborador(a, ua)
    # Empresa por defecto: America/Mexico_City. Esta constancia es del mes pasado en México.
    s.constancia(a, col, ver, "CG-2026-0001", fecha="2000-01-01T12:00:00Z")
    s.constancia(a, col, ver, "CG-2026-0002")
    r = await cliente.get("/api/v1/dashboard/resumen", headers=_h(datos))
    assert r.json()["constancias_mes"] == 1


# --- DSH-02 y DSH-03 -------------------------------------------------------------------------


async def test_solicitudes_y_constancias_recientes(cliente, datos, s):
    a, ua = datos["a"], datos["ua"]
    _, ver = s.plantilla(a, ua, "Guardería")
    col = s.colaborador(a, ua)
    for i in range(4):
        s.solicitud(a, col, ver, "EN_PROCESO", nombre=f"Persona {i}")
    for i in range(3):
        s.constancia(a, col, ver, f"CG-2026-000{i + 1}")

    r = await cliente.get("/api/v1/dashboard/solicitudes-recientes?limite=2", headers=_h(datos))
    items = r.json()
    assert len(items) == 2
    assert items[0]["plantilla_nombre"] == "Guardería" and items[0]["version"] == 3
    assert {"id", "colaborador_nombre", "estado"} <= set(items[0])

    r = await cliente.get("/api/v1/dashboard/constancias-recientes?limite=2", headers=_h(datos))
    items = r.json()
    assert [i["folio"] for i in items] == ["CG-2026-0003", "CG-2026-0002"]
    assert items[0]["estado_entrega"] == "ENTREGADA" and "id" in items[0]


async def test_los_recientes_no_mezclan_empresas(cliente, datos, s):
    b, ub = datos["b"], datos["ub"]
    _, ver = s.plantilla(b, ub)
    col = s.colaborador(b, ub)
    s.constancia(b, col, ver, "CG-2026-0001")
    assert (
        await cliente.get("/api/v1/dashboard/constancias-recientes", headers=_h(datos))
    ).json() == []
    assert (
        await cliente.get("/api/v1/dashboard/solicitudes-recientes", headers=_h(datos))
    ).json() == []


# --- DSH-04 ----------------------------------------------------------------------------------


async def test_alertas_de_consentimiento_con_tres_nombres_y_el_resto(cliente, datos, s):
    a, ua = datos["a"], datos["ua"]
    for n in ("Ricardo", "Valeria", "Mario", "Luisa"):
        s.colaborador(a, ua, nombres=n, consentimiento=False)
    s.colaborador(a, ua, nombres="Con consentimiento")
    s.colaborador(a, ua, nombres="Baja", consentimiento=False, estatus="BAJA")

    r = await cliente.get("/api/v1/dashboard/alertas", headers=_h(datos))
    [alerta] = r.json()
    assert alerta["tipo"] == "SIN_CONSENTIMIENTO"
    assert alerta["total"] == 4
    assert alerta["titulo"] == "4 colaboradores sin consentimiento de WhatsApp"
    assert alerta["detalle"].endswith("y 1 más") and alerta["detalle"].count(",") == 2
    assert alerta["enlace"] == "/colaboradores"


async def test_alertas_de_constancias_fallidas_pendientes_y_campos_vacios(cliente, datos, s):
    a, ua = datos["a"], datos["ua"]
    pla, ver = s.plantilla(a, ua)
    col = s.colaborador(a, ua)
    s.constancia(a, col, ver, "CG-2026-0001", estado="FALLIDA", nombre="Miguel Herrera")
    s.constancia(a, col, ver, "CG-2026-0002", estado="PENDIENTE", fecha="2000-01-01T00:00:00Z")
    s.constancia(a, col, ver, "CG-2026-0003", estado="PENDIENTE")  # reciente: no alerta
    s.c.execute(
        "INSERT INTO constancias.alerta_plantilla (empresa_id, plantilla_id, codigo_interno, "
        "total_afectados) VALUES (%s,%s,'NSS',2)",
        (a, pla),
    )

    por_tipo = {
        x["tipo"]: x
        for x in (await cliente.get("/api/v1/dashboard/alertas", headers=_h(datos))).json()
    }
    assert set(por_tipo) == {
        "CONSTANCIA_FALLIDA",
        "CONSTANCIA_PENDIENTE",
        "CAMPO_VACIO_EN_PLANTILLA",
    }
    assert "Miguel Herrera" in por_tipo["CONSTANCIA_FALLIDA"]["detalle"]
    assert por_tipo["CONSTANCIA_PENDIENTE"]["total"] == 1
    assert por_tipo["CAMPO_VACIO_EN_PLANTILLA"]["titulo"] == "NSS vacío en 2 colaboradores"


async def test_alertas_aisladas_por_empresa_y_vacias_sin_problemas(cliente, datos, s):
    b, ub = datos["b"], datos["ub"]
    s.colaborador(b, ub, consentimiento=False)
    assert (await cliente.get("/api/v1/dashboard/alertas", headers=_h(datos))).json() == []


async def test_dashboard_exige_token(cliente):
    for ruta in ("resumen", "solicitudes-recientes", "constancias-recientes", "alertas"):
        assert (await cliente.get(f"/api/v1/dashboard/{ruta}")).status_code == 401
    assert (await cliente.get("/api/v1/constancias/historial")).status_code == 401


# --- DSH-11 ----------------------------------------------------------------------------------


@pytest.fixture
def historial(datos, s):
    a, ua = datos["a"], datos["ua"]
    p1, v1 = s.plantilla(a, ua, "Laboral")
    p2, v2 = s.plantilla(a, ua, "Guardería")
    ana = s.colaborador(a, ua)
    luis = s.colaborador(a, ua, nombres="Luis")
    s.constancia(a, ana, v1, "CG-2026-0001", "ENTREGADA", "Ana López Ruiz", "2026-11-10T15:00:00Z")
    s.constancia(a, ana, v2, "CG-2026-0002", "FALLIDA", "Ana López Ruiz", "2026-11-11T15:00:00Z")
    s.constancia(a, luis, v1, "CG-2026-0003", "PENDIENTE", "Luis Pérez Gil", "2026-11-12T15:00:00Z")
    s.constancia(a, luis, v2, "CG-2026-0004", "ENTREGADA", "Luis Pérez Gil", "2026-11-13T15:00:00Z")
    return {"p1": p1, "p2": p2, "ana": ana, "luis": luis}


def _folios(r):
    return [i["folio"] for i in r.json()["items"]]


async def test_historial_ordenado_con_canal_whatsapp(cliente, datos, historial):
    r = await cliente.get("/api/v1/constancias/historial", headers=_h(datos))
    assert r.status_code == 200
    assert _folios(r) == ["CG-2026-0004", "CG-2026-0003", "CG-2026-0002", "CG-2026-0001"]
    assert {i["canal"] for i in r.json()["items"]} == {"WHATSAPP"}
    assert r.json()["siguiente"] is None
    primero = r.json()["items"][0]
    assert (
        primero["version"] == 3 and primero["plantilla_nombre"] == "Guardería" and "id" in primero
    )


@pytest.mark.parametrize(
    ("consulta", "esperados"),
    [
        ("estado=FALLIDA", ["CG-2026-0002"]),
        ("desde=2026-11-12", ["CG-2026-0004", "CG-2026-0003"]),
        ("hasta=2026-11-11", ["CG-2026-0002", "CG-2026-0001"]),
        ("desde=2026-11-11&hasta=2026-11-12", ["CG-2026-0003", "CG-2026-0002"]),
        ("q=cg-2026-0003", ["CG-2026-0003"]),
        ("q=luis", ["CG-2026-0004", "CG-2026-0003"]),
        ("q=%25", []),  # el comodín se busca como texto, no como patrón
        ("q=_", []),
    ],
)
async def test_filtros_del_historial(cliente, datos, historial, consulta, esperados):
    r = await cliente.get(f"/api/v1/constancias/historial?{consulta}", headers=_h(datos))
    assert r.status_code == 200
    assert _folios(r) == esperados


async def test_filtro_por_plantilla_y_colaborador(cliente, datos, historial):
    h = _h(datos)
    r = await cliente.get(
        f"/api/v1/constancias/historial?plantilla_id={historial['p2']}", headers=h
    )
    assert _folios(r) == ["CG-2026-0004", "CG-2026-0002"]
    r = await cliente.get(
        f"/api/v1/constancias/historial?colaborador_id={historial['ana']}", headers=h
    )
    assert _folios(r) == ["CG-2026-0002", "CG-2026-0001"]


async def test_paginacion_por_cursor_sin_repetir_ni_saltar(cliente, datos, historial):
    h = _h(datos)
    vistos, cursor = [], None
    for _ in range(5):
        url = "/api/v1/constancias/historial?limite=3" + (f"&cursor={cursor}" if cursor else "")
        r = await cliente.get(url, headers=h)
        vistos += _folios(r)
        cursor = r.json()["siguiente"]
        if not cursor:
            break
    assert vistos == ["CG-2026-0004", "CG-2026-0003", "CG-2026-0002", "CG-2026-0001"]


async def test_historial_valida_entradas(cliente, datos, historial):
    h = _h(datos)
    assert (
        await cliente.get("/api/v1/constancias/historial?cursor=basura", headers=h)
    ).status_code == 422
    r = await cliente.get(
        "/api/v1/constancias/historial?desde=2026-12-01&hasta=2026-11-01", headers=h
    )
    assert r.status_code == 422 and r.json()["codigo"] == "RANGO_INVALIDO"
    assert (
        await cliente.get("/api/v1/constancias/historial?estado=OTRO", headers=h)
    ).status_code == 422


async def test_historial_aislado_por_empresa(cliente, datos, historial):
    r = await cliente.get("/api/v1/constancias/historial", headers=_h(datos, "b"))
    assert r.json() == {"items": [], "siguiente": None}
