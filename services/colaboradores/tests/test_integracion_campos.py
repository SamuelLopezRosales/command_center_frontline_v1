"""T-206: integración de extremo a extremo de `campos` con `colaboradores` (en proceso, con las
dos aplicaciones conectadas por su cliente HTTP interno, PostgreSQL real y LocalStack).

Un campo de lista personalizado se usa en un alta y en una carga; el tipo no cambia con valores;
al desactivarlo los valores se conservan; la plantilla de Excel refleja cada cambio y el evento
``campo.actualizado`` invalida la caché de definiciones.
"""

import asyncio
import json
import uuid
from io import BytesIO

import httpx
import psycopg
import pytest
from ayudantes_carga import fila_valida
from ayudantes_colaboradores import (
    CLIENTE,
    EMISOR,
    LLAVE,
    SECRETO_INTERNO,
    cab,
    construir_app,
    emitir,
    interno,
)
from cc_campos.clientes import ColaboradoresHttp, StubConstancias
from cc_campos.config import ConfigCampos
from cc_campos.main import crear_app as crear_app_campos
from cc_colaboradores.campos_cliente import CacheCampos, CamposHttp
from cc_colaboradores.consumidores import manejar_evento
from cc_colaboradores.workers.worker_cargas import procesar_carga
from cc_common import outbox
from cc_common.auth import VerificadorToken
from cc_common.db import crear_motor
from cc_common.internal_client import ClienteInterno
from cc_common.tareas import consumidor_sqs, relay_outbox
from openpyxl import load_workbook

pytestmark = pytest.mark.docker

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class _Diferido:
    """Referencia que se completa después: las dos aplicaciones se llaman entre sí."""

    destino = None

    def __getattr__(self, nombre):
        return getattr(self.destino, nombre)


def _cliente_interno(app, servicio):
    return ClienteInterno(
        "http://interno",
        servicio=servicio,
        secreto=lambda: SECRETO_INTERNO,
        transporte=httpx.ASGITransport(app=app),
        reintentos=0,
    )


@pytest.fixture
async def sistema(datos, motor, cifrador, s3_cargas):
    """`campos` y `colaboradores` conectados; la empresa A con organización y planta."""
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as cx:
        cx.execute("DELETE FROM campos.opcion_campo WHERE empresa_id = %s", (datos["a"],))
        cx.execute(
            "DELETE FROM campos.campo_colaborador WHERE empresa_id = %s",
            (datos["a"],),
        )  # la fixture trae campos de ejemplo: aquí manda el servicio `campos`
        cx.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORG1', 'Org')",
            (datos["a"],),
        )
        cx.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Norte')",
            (datos["a"],),
        )
    motor_campos = crear_motor(datos["bd"].url_rol("svc_campos"))
    puente = _Diferido()
    app_campos = crear_app_campos(
        ConfigCampos(cognito_emisor=EMISOR, cognito_client_id=CLIENTE),
        motor=motor_campos,
        verificador=VerificadorToken(EMISOR, CLIENTE, resolver_llave=lambda _t: LLAVE.public_key()),
        colaboradores=puente,
        constancias=StubConstancias(),
        secreto_interno=lambda: SECRETO_INTERNO,
    )
    cache = CacheCampos(CamposHttp(_cliente_interno(app_campos, "colaboradores")))
    almacen, cliente_s3, bucket = s3_cargas
    app_col = construir_app(motor, cifrador, almacen_cargas=almacen, campos=cache)
    puente.destino = ColaboradoresHttp(_cliente_interno(app_col, "campos"))
    h = {"Authorization": cab(emitir("sub-a", datos["a"], datos["ua"]))["Authorization"]}
    async with (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app_campos), base_url="http://c") as c,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app_col), base_url="http://k") as k,
    ):
        yield {
            "campos": c, "col": k, "h": h, "datos": datos, "cache": cache, "motor": motor,
            "motor_campos": motor_campos, "cifrador": cifrador, "almacen": almacen,
            "s3": cliente_s3, "bucket": bucket,
        }  # fmt: skip
    await motor_campos.dispose()


def _sql(datos, consulta, params=()):
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as cx:
        cur = cx.execute(consulta, params)
        return cur.fetchall() if cur.description else []


async def _aplicar_eventos(s) -> int:
    """Entrega al consumidor de `colaboradores` los eventos que `campos` dejó en su outbox."""
    filas = _sql(
        s["datos"],
        "SELECT evento_id, tipo, payload FROM campos.outbox WHERE publicado_en IS NULL ORDER BY id",
    )
    for evento_id, tipo, payload in filas:
        await manejar_evento(
            s["motor"], s["cache"], {"evento_id": str(evento_id), "tipo": tipo, **payload}
        )
    _sql(s["datos"], "UPDATE campos.outbox SET publicado_en = now()")
    return len(filas)


async def _crear_zona(s):
    r = await s["campos"].post(
        "/api/v1/campos",
        json={"nombre_campo": "Zona", "clave": "zona", "tipo_dato": "LISTA"},
        headers=s["h"],
    )
    assert r.status_code == 201, r.text
    campo = r.json()
    for etiqueta, valor in (("Zona norte", "NORTE"), ("Zona sur", "SUR")):
        o = await s["campos"].post(
            f"/api/v1/campos/{campo['id']}/opciones",
            json={"etiqueta": etiqueta, "valor": valor},
            headers=s["h"],
        )
        assert o.status_code == 201, o.text
    return campo


def _alta(**campos):
    return {
        "numero_empleado": "E-1",
        "nombres": "Ana",
        "apellido_paterno": "Pérez",
        "apellido_materno": "Ruiz",
        "celular": "8111111111",
        "organizacion_id": 0,
        "planta_id": 0,
        "fecha_ingreso": "01/02/2020",
        "puesto": "Operadora",
        "tipo_empleado": "OPERATIVO",
        "campos": campos,
    }


async def _post_colaborador(s, **cuerpo):
    d = s["datos"]
    org = _sql(d, "SELECT id FROM colaboradores.organizacion")[0][0]
    planta = _sql(d, "SELECT id FROM colaboradores.planta")[0][0]
    base = _alta() | {"organizacion_id": org, "planta_id": planta}
    return await s["col"].post("/api/v1/colaboradores", json=base | cuerpo, headers=s["h"])


async def _plantilla_claves(s) -> list[str]:
    r = await s["col"].get("/api/v1/cargas/plantilla", headers=s["h"])
    assert r.status_code == 200
    ws = load_workbook(BytesIO(r.content))["Colaboradores"]
    return [c.value for c in ws[2]]


def _libro_con_filas(plantilla: bytes, filas: list[dict]) -> bytes:
    wb = load_workbook(BytesIO(plantilla))
    ws = wb["Colaboradores"]
    columna = {ws.cell(row=2, column=i).value: i for i in range(1, ws.max_column + 1)}
    for r, fila in enumerate(filas, start=3):
        for clave, valor in fila.items():
            ws.cell(row=r, column=columna[clave], value=valor)
    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()


async def _cargar(s, contenido: bytes) -> dict:
    h, d = s["h"], s["datos"]
    r = await s["col"].post(
        "/api/v1/cargas", json={"nombre_archivo": "z.xlsx", "tamano": len(contenido)}, headers=h
    )
    c = r.json()
    async with httpx.AsyncClient(timeout=60) as externo:
        put = await externo.put(c["url_subida"], content=contenido, headers={"Content-Type": XLSX})
    assert put.status_code == 200
    assert (
        await s["col"].post(f"/api/v1/cargas/{c['carga_id']}/confirmar", headers=h)
    ).status_code == 202
    estado = await procesar_carga(
        s["motor"], s["cifrador"], s["cache"], s["almacen"],
        empresa_id=d["a"], carga_id=c["carga_id"],
    )  # fmt: skip
    assert estado == "TERMINADA"
    return (await s["col"].get(f"/api/v1/cargas/{c['carga_id']}", headers=h)).json()["carga"]


# ------------------------------------------------------------------ flujo de extremo a extremo


async def test_campo_de_lista_personalizado_de_punta_a_punta(sistema):
    s, d = sistema, sistema["datos"]
    r = await s["campos"].post(
        f"/internal/empresas/{d['a']}/campos-sugeridos", headers=interno("dashboard", d["a"])
    )
    assert r.json() == {"creados": 11, "existentes": 0}
    zona = await _crear_zona(s)
    codigo = zona["codigo_interno"]
    assert codigo == "CAMP-0012"

    # `colaboradores` ve el campo por INT-CAM-01 (cliente real): alta con una opción de la lista
    r = await _post_colaborador(s, campos={codigo: "NORTE"})
    assert r.status_code == 201, r.text
    assert codigo in r.json()["campos"]
    r = await _post_colaborador(
        s, numero_empleado="E-2", celular="8122222222", campos={codigo: "X"}
    )
    assert r.status_code == 422  # opción que no existe

    # la plantilla de Excel refleja el campo y una carga lo llena por etiqueta
    claves = await _plantilla_claves(s)
    assert claves[-1] == "zona" and "nss" in claves and "ruta_transporte" not in claves
    plantilla = (await s["col"].get("/api/v1/cargas/plantilla", headers=s["h"])).content
    carga = await _cargar(
        s,
        _libro_con_filas(
            plantilla,
            [
                fila_valida(5, organizacion="ORG1", planta="Norte", zona="zona SUR"),
                fila_valida(6, organizacion="ORG1", planta="Norte", zona="Zona norte"),
            ],
        ),
    )
    assert (carga["filas_ok"], carga["filas_error"]) == (2, 0)
    por_opcion = _sql(
        d,
        "SELECT o.valor, count(*) FROM colaboradores.valor_campo v "
        "JOIN campos.opcion_campo o ON o.id = v.valor_opcion_id GROUP BY 1 ORDER BY 1",
    )
    assert por_opcion == [("NORTE", 2), ("SUR", 1)]

    # con valores, el tipo y la sensibilidad no cambian y el campo no se elimina (INT-COL-10)
    r = await s["campos"].patch(
        f"/api/v1/campos/{zona['id']}", json={"tipo_dato": "TEXTO"}, headers=s["h"]
    )
    assert r.status_code == 409 and r.json()["codigo"] == "CAMPO_TIPO_INMUTABLE"
    r = await s["campos"].delete(f"/api/v1/campos/{zona['id']}", headers=s["h"])
    assert r.status_code == 409 and r.json()["codigo"] == "CAMPO_CON_VALORES"

    # desactivarlo conserva los valores; la plantilla, mientras la caché no se invalide, sigue igual
    r = await s["campos"].patch(
        f"/api/v1/campos/{zona['id']}", json={"activo": False}, headers=s["h"]
    )
    assert r.status_code == 200 and r.json()["activo"] is False
    assert "zona" in await _plantilla_claves(s)  # caché de 60 s todavía vigente
    assert await _aplicar_eventos(s) >= 1  # campo.actualizado invalida la caché
    assert "zona" not in await _plantilla_claves(s)
    assert _sql(
        d, "SELECT count(*) FROM colaboradores.valor_campo WHERE campo_id = %s", (zona["id"],)
    ) == [(3,)]
    ficha = await s["col"].get(
        f"/api/v1/colaboradores/{_sql(d, 'SELECT id FROM colaboradores.colaborador ORDER BY id')[0][0]}",
        headers=s["h"],
    )
    assert codigo in ficha.json()["campos"]  # el valor de un campo inactivo se sigue mostrando
    # y ya no se puede capturar en un alta
    r = await _post_colaborador(
        s, numero_empleado="E-3", celular="8133333333", campos={codigo: "SUR"}
    )
    assert r.status_code == 422


async def test_un_cambio_de_opciones_no_se_ve_hasta_que_llega_el_evento(sistema):
    s = sistema
    zona = await _crear_zona(s)
    codigo = zona["codigo_interno"]
    assert (await _post_colaborador(s, campos={codigo: "NORTE"})).status_code == 201  # llena caché
    r = await s["campos"].post(
        f"/api/v1/campos/{zona['id']}/opciones",
        json={"etiqueta": "Zona centro", "valor": "CENTRO"},
        headers=s["h"],
    )
    assert r.status_code == 201
    obsoleta = await _post_colaborador(
        s, numero_empleado="E-2", celular="8122222222", campos={codigo: "CENTRO"}
    )
    assert obsoleta.status_code == 422  # la caché todavía no conoce la opción
    await _aplicar_eventos(s)
    nueva = await _post_colaborador(
        s, numero_empleado="E-2", celular="8122222222", campos={codigo: "CENTRO"}
    )
    assert nueva.status_code == 201, nueva.text
    # un evento repetido no se vuelve a procesar (CC-NFR-007)
    evento_id = _sql(s["datos"], "SELECT evento_id FROM campos.outbox ORDER BY id")[0][0]
    evento = {
        "evento_id": str(evento_id),
        "tipo": "campo.actualizado",
        "empresa_id": s["datos"]["a"],
    }
    assert await manejar_evento(s["motor"], s["cache"], evento) is False
    assert (
        await manejar_evento(s["motor"], s["cache"], {"tipo": "otro.evento", "empresa_id": 1})
        is False
    )


# ------------------------------------------------------------------ EventBridge, SQS y relay


async def test_el_evento_viaja_por_eventbridge_y_sqs_hasta_invalidar_la_cache(sistema, localstack):
    import boto3

    s, d = sistema, sistema["datos"]
    credenciales = {
        "endpoint_url": localstack,
        "region_name": "us-east-1",
        "aws_access_key_id": "test",
        "aws_secret_access_key": "test",
    }
    eventos, sqs = boto3.client("events", **credenciales), boto3.client("sqs", **credenciales)
    sufijo = uuid.uuid4().hex[:8]
    bus, cola = f"cc-prueba-{sufijo}", f"ev-colaboradores-{sufijo}"
    eventos.create_event_bus(Name=bus)
    url = sqs.create_queue(QueueName=cola)["QueueUrl"]
    arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"][
        "QueueArn"
    ]
    eventos.put_rule(
        Name=f"regla-{sufijo}",
        EventBusName=bus,
        EventPattern=json.dumps({"detail-type": ["campo.actualizado"]}),
    )
    eventos.put_targets(
        Rule=f"regla-{sufijo}", EventBusName=bus, Targets=[{"Id": "cola", "Arn": arn}]
    )

    zona = await _crear_zona(s)
    codigo = zona["codigo_interno"]
    assert (await _post_colaborador(s, campos={codigo: "NORTE"})).status_code == 201  # llena caché
    await s["campos"].post(
        f"/api/v1/campos/{zona['id']}/opciones",
        json={"etiqueta": "Zona centro", "valor": "CENTRO"},
        headers=s["h"],
    )
    _sql(d, "UPDATE campos.outbox SET destino = %s", (bus,))  # el bus de la prueba

    # relay-outbox de `campos`: publica en EventBridge y marca los mensajes
    parar = asyncio.Event()
    relay = asyncio.create_task(
        relay_outbox(
            s["motor_campos"], "campos", outbox.publicador_aws(sqs, eventos, fuente="cc.campos"),
            parar, intervalo_s=0.1,
        )
    )  # fmt: skip
    for _ in range(100):
        pendientes = _sql(d, "SELECT count(*) FROM campos.outbox WHERE publicado_en IS NULL")[0][0]
        if pendientes == 0:
            break
        await asyncio.sleep(0.1)
    parar.set()
    await relay
    assert pendientes == 0

    # consumidor-eventos de `colaboradores`: lee la cola y procesa el evento
    visto = asyncio.Event()
    parar_consumidor = asyncio.Event()

    async def manejador(evento):
        assert evento["tipo"] == "campo.actualizado" and evento["empresa_id"] == d["a"]
        await manejar_evento(s["motor"], s["cache"], evento)
        visto.set()
        parar_consumidor.set()

    consumidor = asyncio.create_task(
        consumidor_sqs(sqs, url, manejador, parar_consumidor, espera_s=1)
    )
    await asyncio.wait_for(visto.wait(), timeout=30)
    await asyncio.wait_for(consumidor, timeout=10)
    nueva = await _post_colaborador(
        s, numero_empleado="E-2", celular="8122222222", campos={codigo: "CENTRO"}
    )
    assert nueva.status_code == 201, nueva.text
    assert sqs.receive_message(QueueUrl=url, WaitTimeSeconds=1).get("Messages") is None  # se borró


async def test_la_siembra_del_bootstrap_es_igual_a_la_de_int_cam_02(sistema):
    """Las dos siembras comparten el catálogo; esta prueba detecta cualquier deriva."""
    from scripts.bootstrap_admin import sembrar_campos

    s, d = sistema, sistema["datos"]
    r = await s["campos"].post(
        f"/internal/empresas/{d['a']}/campos-sugeridos", headers=interno("dashboard", d["a"])
    )
    assert r.json()["creados"] == 11
    with psycopg.connect(d["bd"].url_admin) as cx, cx.transaction():
        assert sembrar_campos(cx, d["b"]) == 11

    def forma(empresa):
        return _sql(
            d,
            "SELECT c.clave, c.codigo_interno, c.nombre_campo, c.tipo_dato, c.formato_validacion, "
            "c.obligatorio, c.orden, c.activo, c.es_sensible, c.es_sugerido, "
            "coalesce((SELECT json_agg(json_build_array(o.etiqueta, o.valor, o.orden) "
            "ORDER BY o.orden) FROM campos.opcion_campo o WHERE o.campo_id = c.id), '[]'::json) "
            "FROM campos.campo_colaborador c WHERE c.empresa_id = %s ORDER BY c.orden",
            (empresa,),
        )

    assert forma(d["a"]) == forma(d["b"])
