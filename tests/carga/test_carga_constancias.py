"""T-142: 500 constancias de un mes simulado y concurrencia de folios (CC-NFR-001, 003, 004).

La emisión usa el worker real (``procesar_solicitud``) con PostgreSQL de Testcontainers (RLS, rol
``svc_constancias``), el bucket con Object Lock de LocalStack y un renderizador de PDF inyectado
(``FalsoPdf``): lo que se mide es todo MENOS el dibujo del PDF. El PDF real (WeasyPrint) solo corre
en contenedor Linux y lo midió T-210 con ``scripts/probar_pdf.ps1 -Recursos`` (ver
docs/resultados-carga-local.md).
"""

import asyncio
import time

import pytest
from ayudantes_constancias import CLIENTE, EMISOR, crear_colaborador, sql
from ayudantes_emision import plantilla_activa, solicitud
from ayudantes_medicion import fixtures_de, p95, registrar
from cc_common.db import transaccion
from cc_constancias.clientes import DefinicionCampo
from cc_constancias.config import ConfigConstancias
from cc_constancias.repos import solicitudes as repo
from cc_constancias.workers.worker_pdf import procesar_solicitud

pytestmark = [pytest.mark.carga, pytest.mark.docker]

_c = fixtures_de("services/constancias/tests/conftest.py", "conf_constancias_carga")
datos, motor, s3_plantillas, campos, colaboradores = (
    _c.datos,
    _c.motor,
    _c.s3_plantillas,
    _c.campos,
    _c.colaboradores,
)
s3_constancias, cifrador = _c.s3_constancias, _c.cifrador

NSS = DefinicionCampo(1, "NSS", "nss", "CAMP-0002", "TEXTO", es_sensible=True)
MES = 500


class FalsoPdf:
    def __call__(self, html: str) -> bytes:
        return b"%PDF-1.7 falso " + html.encode()


@pytest.fixture
def mundo(datos, campos, colaboradores, s3_plantillas, s3_constancias, cifrador, motor):
    campos.por_empresa[datos["a"]] = [NSS]
    colaborador = crear_colaborador(datos)
    colaboradores.valores[colaborador] = {"nombre_completo": "Ana Pérez", "nss": "12345678901"}
    colaboradores.resumenes[colaborador] = {"numero_empleado": "E-77", "organizacion": {"id": 0}}
    pid = plantilla_activa(datos, s3_plantillas[0])
    cfg = ConfigConstancias(
        cognito_emisor=EMISOR, cognito_client_id=CLIENTE, dominio="cc.prueba.test",
        max_intentos_pdf=3, retencion_constancias_dias=1,
    )  # fmt: skip

    async def emitir(sid):
        return await procesar_solicitud(
            motor, cfg,
            almacen=s3_plantillas[0], almacen_constancias=s3_constancias[0], cifrador=cifrador,
            campos=campos, colaboradores=colaboradores, cargador_logotipo=None,
            empresa_id=datos["a"], solicitud_id=sid, generar_pdf=FalsoPdf(),
        )  # fmt: skip

    return {"colaborador": colaborador, "pid": pid, "emitir": emitir}


async def test_500_constancias_en_un_mes(datos, mundo):
    """Un worker atiende las 500 solicitudes de un mes, una tras otra (§15.4: un worker basta)."""
    ids = [solicitud(datos, mundo["colaborador"], mundo["pid"]) for _ in range(MES)]
    tiempos = []
    t_total = time.perf_counter()
    for sid in ids:
        t0 = time.perf_counter()
        assert await mundo["emitir"](sid) == "GENERADA"
        tiempos.append(time.perf_counter() - t0)
    total = time.perf_counter() - t_total
    registrar("constancias 500 emitidas (un worker, PDF inyectado)", f"{total:.1f}", "s en total")
    registrar("constancias emision por solicitud", f"{p95(tiempos) * 1000:.0f}", "ms p95 (sin PDF)")
    registrar("constancias emision por solicitud", f"{max(tiempos) * 1000:.0f}", "ms maximo")
    assert sql(
        datos, "SELECT count(*), count(DISTINCT folio) FROM constancias.constancia_generada"
    ) == [(MES, MES)]
    folios = sorted(f for (f,) in sql(datos, "SELECT folio FROM constancias.constancia_generada"))
    assert folios[0].endswith("-0001") and folios[-1].endswith(f"-{MES:04d}")
    assert p95(tiempos) < 5.0  # CC-NFR-001 (el PDF real se mide aparte, en contenedor)


async def test_folios_con_50_y_200_reservas_simultaneas(datos, mundo, motor):
    ids = [solicitud(datos, mundo["colaborador"]) for _ in range(250)]

    async def reservar(sid):
        async with transaccion(motor, datos["a"]) as conn:
            await repo.obtener(conn, sid, bloquear=True)
            return await repo.reservar_folio(conn, sid, 2026)

    t0 = time.perf_counter()
    folios_50 = await asyncio.gather(*(reservar(s) for s in ids[:50]))
    t50 = time.perf_counter() - t0
    t0 = time.perf_counter()
    folios_200 = await asyncio.gather(*(reservar(s) for s in ids[50:]))
    t200 = time.perf_counter() - t0
    registrar("folios 50 reservas simultaneas", f"{t50 * 1000:.0f}", "ms en total, sin repetidos")
    registrar("folios 200 reservas simultaneas", f"{t200 * 1000:.0f}", "ms en total, sin repetidos")
    todos = [*folios_50, *folios_200]
    assert sorted(todos) == [f"CG-2026-{n:04d}" for n in range(1, 251)]


async def test_50_emisiones_completas_simultaneas(datos, mundo):
    ids = [solicitud(datos, mundo["colaborador"], mundo["pid"]) for _ in range(50)]
    t0 = time.perf_counter()
    estados = await asyncio.gather(*(mundo["emitir"](s) for s in ids))
    registrar(
        "constancias 50 emisiones completas simultaneas", f"{time.perf_counter() - t0:.1f}", "s"
    )
    assert set(estados) == {"GENERADA"}
    folios = [f for (f,) in sql(datos, "SELECT folio FROM constancias.constancia_generada")]
    assert len(set(folios)) == 50
