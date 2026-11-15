"""T-209 (T-084, T-089): solicitudes, folios, INT-CON-01 a 06 y alertas de plantilla."""

import asyncio

import pytest
from ayudantes_constancias import crear_colaborador, sql
from ayudantes_emision import (
    CONTENIDO_EMISION,
    conversacion,
    interno,
    plantilla_activa,
    poner_borrador,
    salidas,
    solicitud,
)
from cc_common.db import transaccion
from cc_constancias.clientes import DefinicionCampo
from cc_constancias.repos import solicitudes as repo
from cc_constancias.workers.alertas_plantilla import recalcular

pytestmark = pytest.mark.docker

NSS = DefinicionCampo(1, "NSS", "nss", "CAMP-0002", "TEXTO", es_sensible=True)


@pytest.fixture
def mundo(datos, campos, colaboradores, s3_plantillas):
    campos.por_empresa[datos["a"]] = [NSS]
    colaborador = crear_colaborador(datos)
    colaboradores.valores[colaborador] = {"nombre_completo": "Ana Pérez", "nss": "123"}
    return {"colaborador": colaborador, "almacen": s3_plantillas[0], "datos": datos}


def wa(datos):
    return interno("whatsapp", datos["a"])


async def test_plantillas_disponibles_excluye_inactivas_eliminadas_y_sin_version(
    http, mundo, datos
):
    activa = plantilla_activa(datos, mundo["almacen"], nombre="Activa")
    plantilla_activa(datos, mundo["almacen"], nombre="Inactiva", activa=False)
    borrada = plantilla_activa(datos, mundo["almacen"], nombre="Borrada")
    sql(datos, "UPDATE constancias.plantilla_constancia SET activa = false, eliminada = true "
        "WHERE id = %s", (borrada,))  # fmt: skip
    sql(datos, "INSERT INTO constancias.plantilla_constancia (empresa_id, nombre, activa) "
        "VALUES (%s, 'SinVersion', true)", (datos["a"],))  # fmt: skip
    r = await http.get("/internal/plantillas/activas", headers=wa(datos))
    assert r.status_code == 200
    assert [(p["id"], p["version"]) for p in r.json()["plantillas"]] == [(activa, 1)]


async def test_flujo_de_solicitud_y_unicidad_por_conversacion(http, mundo, datos):
    pid = plantilla_activa(datos, mundo["almacen"])
    conv = conversacion(datos, mundo["colaborador"])
    cuerpo = {
        "colaborador_id": mundo["colaborador"],
        "conversacion_id": conv,
        "colaborador_nombre": "Ana Pérez",
    }
    r = await http.post("/internal/solicitudes", json=cuerpo, headers=wa(datos))
    assert r.status_code == 201 and r.json()["estado"] == "RECIBIDA"
    sid = r.json()["id"]
    dup = await http.post("/internal/solicitudes", json=cuerpo, headers=wa(datos))
    assert dup.status_code == 409 and dup.json()["codigo"] == "SOLICITUD_ABIERTA"

    r = await http.post(f"/internal/solicitudes/{sid}/plantilla", json={"plantilla_id": pid},
                        headers=wa(datos))  # fmt: skip
    assert r.status_code == 200 and r.json()["version_plantilla_id"] is not None
    r = await http.post(f"/internal/solicitudes/{sid}/generar", headers=wa(datos))
    assert r.status_code == 202
    assert salidas(datos, "generar_pdf") == [{"solicitud_id": sid, "empresa_id": datos["a"]}]

    r = await http.post(f"/internal/solicitudes/{sid}/cancelar", headers=wa(datos))
    assert r.status_code == 200 and r.json()["estado"] == "CANCELADA"
    again = await http.post(f"/internal/solicitudes/{sid}/cancelar", headers=wa(datos))
    assert again.status_code == 409
    # con la solicitud cerrada la conversación puede abrir otra
    assert (
        await http.post("/internal/solicitudes", json=cuerpo, headers=wa(datos))
    ).status_code == 201


async def test_generar_sin_plantilla_inactiva_o_de_otra_empresa(http, mundo, datos):
    inactiva = plantilla_activa(datos, mundo["almacen"], activa=False)
    sid = solicitud(datos, mundo["colaborador"])
    r = await http.post(f"/internal/solicitudes/{sid}/generar", headers=wa(datos))
    assert r.status_code == 409 and r.json()["codigo"] == "SIN_PLANTILLA"
    r = await http.post(f"/internal/solicitudes/{sid}/plantilla", json={"plantilla_id": inactiva},
                        headers=wa(datos))  # fmt: skip
    assert r.status_code == 409
    ajena = await http.post(f"/internal/solicitudes/{sid}/generar",
                            headers=interno("whatsapp", datos["b"]))  # fmt: skip
    assert ajena.status_code == 404
    # un servicio que no es `whatsapp` no puede crear solicitudes
    r = await http.post("/internal/solicitudes", headers=interno("campos", datos["a"]),
                        json={"colaborador_id": 1, "colaborador_nombre": "x"})  # fmt: skip
    assert r.status_code in (401, 403)


async def test_campos_faltantes_dejan_la_solicitud_fallida_y_avisan(
    http, mundo, datos, colaboradores
):
    colaboradores.valores[mundo["colaborador"]].pop("nss")
    pid = plantilla_activa(datos, mundo["almacen"])
    sid = solicitud(datos, mundo["colaborador"], pid)
    r = await http.post(f"/internal/solicitudes/{sid}/generar", headers=wa(datos))
    assert r.status_code == 422 and r.json()["codigo"] == "CAMPOS_FALTANTES"
    assert r.json()["detalle"]["campos"] == ["nss"]
    estado = sql(datos, "SELECT estado, motivo_fallo FROM constancias.solicitud_constancia "
                 "WHERE id = %s", (sid,))  # fmt: skip
    assert estado == [("FALLIDA", "CAMPOS_FALTANTES")]
    assert salidas(datos, "generar_pdf") == []
    fallida = salidas(datos, "constancia.fallida")
    assert fallida[0]["solicitud_id"] == sid and fallida[0]["motivo"] == "CAMPOS_FALTANTES"
    assert "123" not in str(fallida)


async def test_cincuenta_reservas_simultaneas_dan_folios_unicos_y_el_reintento_reutiliza(
    motor, datos, mundo
):
    ids = [solicitud(datos, mundo["colaborador"]) for _ in range(50)]

    async def reservar(sid):
        async with transaccion(motor, datos["a"]) as conn:
            await repo.obtener(conn, sid, bloquear=True)
            return await repo.reservar_folio(conn, sid, 2026)

    folios = await asyncio.gather(*(reservar(s) for s in ids))
    assert len(set(folios)) == 50
    assert sorted(folios) == [f"CG-2026-{n:04d}" for n in range(1, 51)]
    assert await reservar(ids[0]) == folios[0]  # el reintento no consume otro número
    ultimo = sql(datos, "SELECT ultimo FROM constancias.contador_folio WHERE empresa_id = %s",
                 (datos["a"],))  # fmt: skip
    assert ultimo == [(50,)]


async def test_uso_de_variable_considera_version_vigente_y_borrador(http, mundo, datos):
    uno = plantilla_activa(datos, mundo["almacen"], nombre="Uno")
    dos = plantilla_activa(datos, mundo["almacen"], nombre="Dos")
    poner_borrador(datos, mundo["almacen"], dos, {"esquema": 1, "bloques": [
        {"tipo": "parrafo", "contenido": [{"var": "puesto"}]}]})  # fmt: skip
    borrada = plantilla_activa(datos, mundo["almacen"], nombre="Borrada")
    sql(datos, "UPDATE constancias.plantilla_constancia SET activa = false, eliminada = true "
        "WHERE id = %s", (borrada,))  # fmt: skip
    r = await http.get(
        "/internal/plantillas/uso-de-variable",
        params=[("variable", "nss"), ("variable", "puesto"), ("variable", "otra")],
        headers=interno("campos", datos["a"]),
    )
    assert r.status_code == 200
    usos = r.json()["usos"]
    assert {p["id"] for p in usos["nss"]} == {uno, dos}  # `nss` está en la versión vigente
    assert usos["puesto"] == [{"id": dos, "nombre": "Dos"}]  # solo en el borrador
    assert usos["otra"] == []


async def test_alertas_cuentan_vacios_y_se_actualizan(motor, mundo, datos, campos, colaboradores):
    pid = plantilla_activa(datos, mundo["almacen"])
    colaboradores.vacios = {"CAMP-0002": 4}
    assert await recalcular(motor, mundo["almacen"], campos, colaboradores, datos["a"]) == 1
    leer = "SELECT codigo_interno, total_afectados FROM constancias.alerta_plantilla " \
           "WHERE plantilla_id = %s"  # fmt: skip
    assert sql(datos, leer, (pid,)) == [("CAMP-0002", 4)]
    colaboradores.vacios = {}
    await recalcular(motor, mundo["almacen"], campos, colaboradores, datos["a"], plantillas=[pid])
    assert sql(datos, leer, (pid,)) == [("CAMP-0002", 0)]  # el dashboard solo muestra > 0
    assert CONTENIDO_EMISION  # el contenido usa `nss`, el campo contado


async def test_el_consumidor_recalcula_solo_con_campo_actualizado(
    motor, mundo, datos, campos, colaboradores
):
    from cc_constancias.consumidores import manejar_evento

    pid = plantilla_activa(datos, mundo["almacen"])
    colaboradores.vacios = {"CAMP-0002": 2}
    args = (motor, mundo["almacen"], campos, colaboradores)
    assert (
        await manejar_evento(*args, {"tipo": "wa.mensaje_estado", "empresa_id": datos["a"]})
        is False
    )
    assert sql(datos, "SELECT count(*) FROM constancias.alerta_plantilla") == [(0,)]
    assert await manejar_evento(*args, {"tipo": "campo.actualizado", "empresa_id": datos["a"]})
    assert sql(datos, "SELECT total_afectados FROM constancias.alerta_plantilla "
               "WHERE plantilla_id = %s", (pid,)) == [(2,)]  # fmt: skip
