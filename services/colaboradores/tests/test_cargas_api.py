"""T-204: endpoints de carga masiva COL-16 a COL-22 con PostgreSQL y LocalStack."""

import hashlib
from io import BytesIO

import httpx
import psycopg
import pytest
from ayudantes_carga import fila_valida, libro, plantilla_llena
from ayudantes_colaboradores import StubCampos, cab, construir_app, emitir
from cc_colaboradores.campos_cliente import CacheCampos, DefinicionCampo
from cc_colaboradores.excel.modelo import CLAVES_FIJAS
from cc_colaboradores.servicios.cargas import neutralizar
from cc_colaboradores.workers.worker_cargas import procesar_carga
from openpyxl import load_workbook

pytestmark = pytest.mark.docker

FIJAS = list(CLAVES_FIJAS)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
COLA = "cola-cargas-prueba"


@pytest.fixture
async def api(datos, motor, cifrador, s3_cargas):
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        c.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORG1', 'Org')",
            (datos["a"],),
        )
        c.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Norte')",
            (datos["a"],),
        )
    stub = StubCampos({datos["a"]: []})
    campos = CacheCampos(stub, ttl_s=0)  # sin caché para ver los cambios del stub de inmediato
    almacen, cliente_s3, bucket = s3_cargas
    app = construir_app(
        motor, cifrador, almacen_cargas=almacen, campos=campos, cola_cargas_url=COLA
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as h:
        yield {
            "http": h, "datos": datos, "stub": stub, "s3": cliente_s3, "bucket": bucket,
            "almacen": almacen, "motor": motor, "cifrador": cifrador, "campos": campos,
        }  # fmt: skip


def _h(datos, empresa="a"):
    sub, uid = ("sub-a", datos["ua"]) if empresa == "a" else ("sub-b", datos["ub"])
    return cab(emitir(sub, datos[empresa], uid))


def _sql(datos, sql, params=()):
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        cur = c.execute(sql, params)
        return cur.fetchall() if cur.description else []


async def _iniciar(api, nombre="empleados.xlsx", tamano=1000, empresa="a"):
    r = await api["http"].post(
        "/api/v1/cargas",
        json={"nombre_archivo": nombre, "tamano": tamano},
        headers=_h(api["datos"], empresa),
    )
    return r


async def _subir(api, url, contenido):
    async with httpx.AsyncClient(timeout=60) as externo:
        r = await externo.put(url, content=contenido, headers={"Content-Type": XLSX})
    assert r.status_code == 200, r.text


async def _carga_subida(api, contenido, empresa="a"):
    r = await _iniciar(api, tamano=len(contenido), empresa=empresa)
    assert r.status_code == 201, r.text
    c = r.json()
    await _subir(api, c["url_subida"], contenido)
    return c


async def _confirmar(api, carga_id, empresa="a"):
    return await api["http"].post(
        f"/api/v1/cargas/{carga_id}/confirmar", headers=_h(api["datos"], empresa)
    )


def _contenido(n=3, **cambios):
    return libro([fila_valida(i, **cambios) for i in range(1, n + 1)], claves=FIJAS)


def _existe(api, clave) -> bool:
    try:
        api["s3"].head_object(Bucket=api["bucket"], Key=clave)
    except Exception:  # noqa: BLE001
        return False
    return True


# ------------------------------------------------------------------ COL-16


async def test_plantilla_se_descarga_y_refleja_los_campos_activos(api):
    h = _h(api["datos"])
    r = await api["http"].get("/api/v1/cargas/plantilla", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == XLSX
    assert "plantilla_colaboradores.xlsx" in r.headers["content-disposition"]
    ws = load_workbook(BytesIO(r.content))["Colaboradores"]
    assert [c.value for c in ws[2]] == FIJAS
    # al activar un campo en el stub aparece en la siguiente descarga (CC-REQ-034)
    api["stub"].por_empresa[api["datos"]["a"]].append(
        DefinicionCampo(
            api["datos"]["campos"]["area"], "Área", "area", "CAMP-0002", "TEXTO", orden=1
        )
    )
    r = await api["http"].get("/api/v1/cargas/plantilla", headers=h)
    ws = load_workbook(BytesIO(r.content))["Colaboradores"]
    assert [c.value for c in ws[2]][-1] == "area" and ws.cell(row=1, column=12).value == "Área"
    assert (await api["http"].get("/api/v1/cargas/plantilla")).status_code == 401


async def test_la_plantilla_descargada_se_puede_llenar_y_cargar(api):
    r = await api["http"].get("/api/v1/cargas/plantilla", headers=_h(api["datos"]))
    wb = load_workbook(BytesIO(r.content))
    assert wb["Organizaciones"]["A3"].value == "ORG1" and wb["Catálogos"]["A2"].value == "Norte"
    contenido = plantilla_llena([], [fila_valida(1), fila_valida(2)])
    c = await _carga_subida(api, contenido)
    assert (await _confirmar(api, c["carga_id"])).status_code == 202


# ------------------------------------------------------------------ COL-17 y COL-18


async def test_flujo_completo_subida_confirmacion_worker_detalle_y_reporte(api):
    datos = api["datos"]
    filas = [fila_valida(1), fila_valida(2, celular_whatsapp="12"), fila_valida(3)]
    contenido = libro(filas, claves=FIJAS)
    r = await _iniciar(api, tamano=len(contenido))
    assert r.status_code == 201
    c = r.json()
    assert "X-Amz-Expires=900" in c["url_subida"] and c["s3_key"].startswith(f"{datos['a']}/")
    await _subir(api, c["url_subida"], contenido)

    r = await _confirmar(api, c["carga_id"])
    assert r.status_code == 202, r.text
    carga = r.json()
    assert carga["confirmada"] is True and carga["estado"] == "EN_PROCESO"
    assert carga["total_filas"] == 3 and carga["version_plantilla"] == "EXTERNA"
    sha = _sql(datos, "SELECT hash_archivo FROM colaboradores.carga_colaboradores")[0][0]
    assert sha == hashlib.sha256(contenido).hexdigest()
    salida = _sql(datos, "SELECT destino_tipo, destino, tipo, payload FROM colaboradores.outbox")
    assert salida == [
        ("SQS", COLA, "carga.confirmada", {"carga_id": c["carga_id"], "empresa_id": datos["a"]})
    ]
    assert [b[0] for b in _sql(datos, "SELECT accion FROM auditoria.bitacora")] == [
        "CARGA_INICIADA"
    ]
    # una segunda confirmación no encola otra vez
    assert (await _confirmar(api, c["carga_id"])).status_code == 409

    assert (
        await procesar_carga(
            api["motor"], api["cifrador"], api["campos"], api["almacen"],
            empresa_id=datos["a"], carga_id=c["carga_id"],
        )
        == "TERMINADA"
    )  # fmt: skip
    r = await api["http"].get(f"/api/v1/cargas/{c['carga_id']}", headers=_h(datos))
    d = r.json()
    assert d["carga"]["estado"] == "TERMINADA" and d["carga"]["filas_ok"] == 2
    assert d["carga"]["filas_error"] == 1 and d["filas"]["total"] == 3
    assert [(f["numero_fila"], f["resultado"]) for f in d["filas"]["items"]] == [
        (3, "NUEVO"), (4, "ERROR"), (5, "NUEVO"),
    ]  # fmt: skip
    assert d["filas"]["items"][1]["errores"] == [
        {"codigo": "CELULAR_INVALIDO", "mensaje": "El celular debe tener 10 dígitos."}
    ]
    solo = await api["http"].get(
        f"/api/v1/cargas/{c['carga_id']}?resultado=ERROR", headers=_h(datos)
    )
    assert solo.json()["filas"]["total"] == 1

    lista = (await api["http"].get("/api/v1/cargas", headers=_h(datos))).json()
    assert lista["total"] == 1 and lista["items"][0]["id"] == c["carga_id"]

    csv = await api["http"].get(f"/api/v1/cargas/{c['carga_id']}/errores", headers=_h(datos))
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert csv.content.startswith(b"\xef\xbb\xbf")  # UTF-8 con BOM
    texto = csv.content.decode("utf-8-sig")
    assert texto.splitlines() == [
        "fila,codigo,mensaje",
        "4,CELULAR_INVALIDO,El celular debe tener 10 dígitos.",
    ]
    for dato_personal in ("María", "Ramírez", "8100000001", "E-0001"):
        assert dato_personal not in texto


async def test_validaciones_de_iniciar(api):
    assert (await _iniciar(api, nombre="datos.csv")).status_code == 422
    assert (await _iniciar(api, nombre="datos.xlsx", tamano=5 * 1024 * 1024 + 1)).status_code == 422
    assert (await _iniciar(api, nombre="../../etc/pass.xlsx")).json()["s3_key"].endswith(".xlsx")
    nombre = _sql(api["datos"], "SELECT nombre_archivo FROM colaboradores.carga_colaboradores")[0][
        0
    ]
    assert nombre == "pass.xlsx"  # sin ruta


async def test_confirmar_sin_haber_subido_el_archivo_no_cancela_la_carga(api):
    c = (await _iniciar(api)).json()
    r = await _confirmar(api, c["carga_id"])
    assert r.status_code == 422 and r.json()["codigo"] == "ARCHIVO_NO_SUBIDO"
    assert _sql(api["datos"], "SELECT estado FROM colaboradores.carga_colaboradores") == [
        ("EN_PROCESO",)
    ]
    await _subir(api, c["url_subida"], _contenido())
    assert (await _confirmar(api, c["carga_id"])).status_code == 202


@pytest.mark.parametrize(
    "contenido",
    [
        b"%PDF-1.7 esto no es un libro de Excel",
        libro([fila_valida(1)], claves=["numero_empleado", "nombres"]),
        libro([fila_valida(i) for i in range(1, 2002)], claves=FIJAS),
    ],
    ids=["no_es_xlsx", "estructura_ajena", "mas_de_2000_filas"],
)
async def test_archivo_ajeno_se_rechaza_y_la_carga_queda_cancelada(api, contenido):
    c = await _carga_subida(api, contenido)
    r = await _confirmar(api, c["carga_id"])
    assert r.status_code == 422 and r.json()["codigo"] == "CARGA_ARCHIVO_INVALIDO"
    fila = _sql(
        api["datos"],
        "SELECT estado, motivo_cierre, hash_archivo, fecha_fin FROM colaboradores.carga_colaboradores",
    )[0]
    assert fila[:3] == ("CANCELADA", "CARGA_ARCHIVO_INVALIDO", None) and fila[3] is not None
    assert not _existe(api, c["s3_key"])
    assert _sql(api["datos"], "SELECT count(*) FROM colaboradores.outbox") == [(0,)]
    assert [b[0] for b in _sql(api["datos"], "SELECT accion FROM auditoria.bitacora")] == [
        "CARGA_CANCELADA"
    ]


# ------------------------------------------------------------------ vencimiento y cancelación


async def test_carga_sin_confirmar_en_una_hora_se_cancela(api):
    datos = api["datos"]
    c = await _carga_subida(api, _contenido())
    _sql(
        datos,
        "UPDATE colaboradores.carga_colaboradores SET fecha_carga = now() - interval '2 hours'",
    )
    r = await api["http"].get("/api/v1/cargas", headers=_h(datos))
    item = r.json()["items"][0]
    assert item["estado"] == "CANCELADA" and item["motivo_cierre"] == "NO_CONFIRMADA"
    assert not _existe(api, c["s3_key"])
    # ya no se puede confirmar
    assert (await _confirmar(api, c["carga_id"])).status_code == 409
    acciones = _sql(datos, "SELECT accion, detalle FROM auditoria.bitacora")
    assert acciones == [("CARGA_CANCELADA", {"carga_id": c["carga_id"], "motivo": "NO_CONFIRMADA"})]


async def test_una_carga_confirmada_no_vence(api):
    c = await _carga_subida(api, _contenido())
    assert (await _confirmar(api, c["carga_id"])).status_code == 202
    _sql(
        api["datos"],
        "UPDATE colaboradores.carga_colaboradores SET fecha_carga = now() - interval '5 hours'",
    )
    r = await api["http"].get("/api/v1/cargas", headers=_h(api["datos"]))
    assert r.json()["items"][0]["estado"] == "EN_PROCESO"


async def test_cancelar_solo_en_proceso(api):
    datos = api["datos"]
    c = await _carga_subida(api, _contenido())
    await _confirmar(api, c["carga_id"])
    r = await api["http"].post(f"/api/v1/cargas/{c['carga_id']}/cancelar", headers=_h(datos))
    assert r.status_code == 200
    assert (
        r.json()["estado"] == "CANCELADA" and r.json()["motivo_cierre"] == "CANCELADA_POR_USUARIO"
    )
    assert not _existe(api, c["s3_key"])
    r = await api["http"].post(f"/api/v1/cargas/{c['carga_id']}/cancelar", headers=_h(datos))
    assert r.status_code == 409 and r.json()["codigo"] == "ESTADO_INVALIDO"
    # el worker ignora una carga cancelada
    assert (
        await procesar_carga(
            api["motor"], api["cifrador"], api["campos"], api["almacen"],
            empresa_id=datos["a"], carga_id=c["carga_id"],
        )
        == "IGNORADA"
    )  # fmt: skip


# ------------------------------------------------------------------ reporte y aislamiento


def test_neutraliza_celdas_que_excel_interpretaria_como_formula():
    for peligrosa in ("=1+1", "+cmd", "-2", "@SUMA(A1)", "\tabc", "\rabc"):
        assert neutralizar(peligrosa) == "'" + peligrosa
    assert neutralizar("CELULAR_INVALIDO") == "CELULAR_INVALIDO"


async def test_reporte_csv_neutraliza_formulas(api):
    datos = api["datos"]
    c = await _carga_subida(api, _contenido())
    carga = c["carga_id"]
    _sql(
        datos,
        "INSERT INTO colaboradores.fila_carga (empresa_id, carga_id, numero_fila, resultado, mensaje) "
        "VALUES (%s, %s, 3, 'ERROR', %s)",
        (datos["a"], carga, "=HYPERLINK(1): +cmd\n@x: -y"),
    )
    r = await api["http"].get(f"/api/v1/cargas/{carga}/errores", headers=_h(datos))
    lineas = r.content.decode("utf-8-sig").splitlines()
    assert lineas[1:] == ["3,'=HYPERLINK(1),'+cmd", "3,'@x,'-y"]


async def test_otra_empresa_recibe_404_y_no_ve_las_cargas(api):
    datos = api["datos"]
    c = await _carga_subida(api, _contenido())
    carga = c["carga_id"]
    for metodo, ruta in (
        ("get", f"/api/v1/cargas/{carga}"),
        ("get", f"/api/v1/cargas/{carga}/errores"),
        ("post", f"/api/v1/cargas/{carga}/confirmar"),
        ("post", f"/api/v1/cargas/{carga}/cancelar"),
    ):
        r = await getattr(api["http"], metodo)(ruta, headers=_h(datos, "b"))
        assert r.status_code == 404, (metodo, ruta, r.text)
    assert (await api["http"].get("/api/v1/cargas", headers=_h(datos, "b"))).json()["total"] == 0
    # y la carga de A sigue intacta
    assert _sql(datos, "SELECT estado FROM colaboradores.carga_colaboradores") == [("EN_PROCESO",)]
