"""T-110: confirmación, horario y programación (NOT-19). Base real con RLS; Scheduler en memoria
(el cliente real contra LocalStack está en ``test_scheduler_localstack.py``).
"""

import asyncio
import itertools
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest
from ayudantes_notificaciones import (
    VARIABLES,
    insertar_destinatarios,
    insertar_plantilla,
    sql,
)
from cc_common.outbox import publicador_aws, publicar_pendientes

pytestmark = pytest.mark.docker

BASE = "/api/v1/notificaciones"
CRITERIOS = {"op": "Y", "items": [{"campo": "planta_id", "operador": "es", "valor": 3}]}
MX = ZoneInfo("America/Mexico_City")
_SEC = itertools.count(1)


def _mx(dia, h, m=0, s=0):
    return datetime(2026, 11, dia, h, m, s, tzinfo=MX)


async def _borrador(http, h, datos, *, validos=3, excluidos=1, revisada=True, **extra):
    p = insertar_plantilla(datos, nombre=f"plantilla_{next(_SEC)}")
    cuerpo = {
        "titulo": "Entrega de uniformes",
        "modo": "CRITERIOS",
        "criterios": CRITERIOS,
        "plantilla_mensaje_id": p,
        "variables": VARIABLES,
        **extra,
    }
    r = await http.post(BASE, json=cuerpo, headers=h)
    assert r.status_code == 201, r.text
    nid = r.json()["id"]
    if validos:
        insertar_destinatarios(datos, nid, n=validos, estado="PENDIENTE")
    if excluidos:
        insertar_destinatarios(datos, nid, n=excluidos, estado="EXCLUIDO")
    if revisada:
        with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
            c.execute(
                "UPDATE notificaciones.notificacion SET revisada_en = now(), "
                "total_seleccionados = %s, total_excluidos = %s WHERE id = %s",
                (validos + excluidos, excluidos, nid),
            )
    return nid


async def _confirmar(http, h, nid, **cuerpo):
    return await http.post(f"{BASE}/{nid}/confirmar", json=cuerpo, headers=h)


def _n(datos, nid):
    return sql(
        datos,
        "SELECT estado, modo_envio, programada_para, schedule_nombre, respaldo_correo, "
        "confirmada_fuera_horario, confirmada_por_usuario_id, confirmada_en "
        "FROM notificaciones.notificacion WHERE id = %s",
        (nid,),
    )[0]


def _outbox(datos):
    return sql(
        datos,
        "SELECT destino_tipo, destino, tipo, payload, empresa_id, publicado_en "
        "FROM notificaciones.outbox ORDER BY id",
    )


def _bitacora(datos):
    return sql(
        datos,
        "SELECT accion, usuario_id, entidad, entidad_id, origen, detalle "
        "FROM auditoria.bitacora WHERE accion = 'NOTIFICACION_ENVIO' ORDER BY id",
    )


def _codigos(r):
    return {(e["campo"], e["codigo"]) for e in r.json()["errores"]}


# ------------------------------------------------------------------ programar: horario


@pytest.mark.parametrize(
    ("hora", "valida"),
    [
        (_mx(18, 7, 59, 59), False),
        (_mx(18, 8, 0, 0), True),  # inicio inclusivo
        (_mx(18, 14, 30), True),
        (_mx(18, 20, 0, 0), True),  # fin inclusivo
        (_mx(18, 20, 0, 1), False),
        (_mx(18, 23, 30), False),
        (_mx(18, 3, 0), False),
    ],
)
async def test_programar_respeta_el_horario_inclusive(http, h, datos, scheduler, hora, valida):
    nid = await _borrador(http, h, datos)
    r = await _confirmar(http, h, nid, modo_envio="PROGRAMAR", programada_para=hora.isoformat())
    if valida:
        assert r.status_code == 202, r.text
        assert r.json()["estado"] == "PROGRAMADA"
        assert len(scheduler.schedules) == 1
    else:
        assert r.status_code == 422, r.text
        assert ("programada_para", "FUERA_DE_HORARIO") in _codigos(r)
        assert _n(datos, nid)[0] == "BORRADOR" and not scheduler.schedules
        assert _outbox(datos) == [] and _bitacora(datos) == []


async def test_el_horario_se_evalua_en_la_zona_de_la_notificacion(http, h, datos, scheduler):
    # 13:30 UTC del 18: 07:30 en México (fuera) pero 08:30 en Nueva York (dentro)
    instante = datetime(2026, 11, 18, 13, 30, tzinfo=UTC).isoformat()
    mx = await _borrador(http, h, datos)
    ny = await _borrador(http, h, datos, zona_horaria="America/New_York")
    r = await _confirmar(http, h, mx, modo_envio="PROGRAMAR", programada_para=instante)
    assert r.status_code == 422 and ("programada_para", "FUERA_DE_HORARIO") in _codigos(r)
    r = await _confirmar(http, h, ny, modo_envio="PROGRAMAR", programada_para=instante)
    assert r.status_code == 202
    s = scheduler.schedules[f"cc-notif-{ny}"]
    assert s.zona == "America/New_York" and s.expresion == "at(2026-11-18T08:30:00)"


async def test_programar_exige_fecha_con_zona_y_futura(http, h, datos, scheduler, reloj):
    nid = await _borrador(http, h, datos)
    r = await _confirmar(http, h, nid, modo_envio="PROGRAMAR")
    assert r.status_code == 422 and ("programada_para", "REQUERIDO") in _codigos(r)
    r = await _confirmar(
        http, h, nid, modo_envio="PROGRAMAR", programada_para="2026-11-18T09:00:00"
    )
    assert r.status_code == 422 and ("programada_para", "FECHA_INVALIDA") in _codigos(r)
    r = await _confirmar(http, h, nid, modo_envio="PROGRAMAR", programada_para="no-es-fecha")
    assert r.status_code == 422
    # pasado (hoy 10:00, cuando ya son las 12:00) y el instante exacto de "ahora"
    for pasado in (_mx(17, 10), reloj.ahora):
        r = await _confirmar(
            http, h, nid, modo_envio="PROGRAMAR", programada_para=pasado.isoformat()
        )
        assert r.status_code == 422 and ("programada_para", "PROGRAMACION_PASADA") in _codigos(r)
    assert _n(datos, nid)[0] == "BORRADOR" and not scheduler.schedules


async def test_programar_fuera_de_horario_no_admite_confirmacion_de_excepcion(http, h, datos):
    nid = await _borrador(http, h, datos)
    r = await _confirmar(
        http,
        h,
        nid,
        modo_envio="PROGRAMAR",
        programada_para=_mx(18, 22).isoformat(),
        confirmar_fuera_horario=True,
    )
    assert r.status_code == 422 and ("programada_para", "FUERA_DE_HORARIO") in _codigos(r)


# ------------------------------------------------------------------ programar: schedule único


async def test_programar_crea_un_schedule_unico_con_el_nombre_guardado(http, h, datos, scheduler):
    nid = await _borrador(http, h, datos)
    cuando = _mx(18, 9, 0)
    r = await _confirmar(
        http,
        h,
        nid,
        modo_envio="PROGRAMAR",
        programada_para=cuando.isoformat(),
        respaldo_correo=True,
    )
    assert r.status_code == 202, r.text
    d = r.json()
    assert d["estado"] == "PROGRAMADA" and d["modo_envio"] == "PROGRAMAR"
    assert datetime.fromisoformat(d["programada_para"]) == cuando
    assert d["respaldo_correo"] is True and d["confirmada_fuera_horario"] is False
    assert d["confirmada_por_usuario_id"] == datos["ua"] and d["confirmada_en"]

    nombre = f"cc-notif-{nid}"
    fila = _n(datos, nid)
    assert fila[0] == "PROGRAMADA" and fila[3] == nombre and fila[4] is True
    assert list(scheduler.schedules) == [nombre]
    s = scheduler.schedules[nombre]
    assert s.expresion == "at(2026-11-18T09:00:00)" and s.zona == "America/Mexico_City"
    assert s.cuerpo == {"notificacion_id": nid, "tipo": "INICIO", "empresa_id": datos["a"]}
    assert _outbox(datos) == []  # programar no escribe mensaje: lo dispara Scheduler


async def test_confirmar_dos_veces_no_crea_dos_schedules(http, h, datos, scheduler):
    nid = await _borrador(http, h, datos)
    cuerpo = {"modo_envio": "PROGRAMAR", "programada_para": _mx(18, 9).isoformat()}
    r1 = await _confirmar(http, h, nid, **cuerpo)
    r2 = await _confirmar(http, h, nid, **cuerpo)
    assert r1.status_code == r2.status_code == 202
    assert r1.json()["confirmada_en"] == r2.json()["confirmada_en"]
    assert scheduler.llamadas_crear == 1 and len(scheduler.schedules) == 1
    assert len(_bitacora(datos)) == 1
    # la misma hora expresada en UTC es la misma programación
    r3 = await _confirmar(
        http,
        h,
        nid,
        modo_envio="PROGRAMAR",
        programada_para=_mx(18, 9).astimezone(UTC).isoformat(),
    )
    assert r3.status_code == 202 and scheduler.llamadas_crear == 1
    # otra hora o enviar ahora: es otra decisión sobre una ya confirmada
    r4 = await _confirmar(
        http, h, nid, modo_envio="PROGRAMAR", programada_para=_mx(18, 10).isoformat()
    )
    assert r4.status_code == 409 and r4.json()["codigo"] == "ESTADO_INVALIDO"
    r5 = await _confirmar(http, h, nid, modo_envio="AHORA")
    assert r5.status_code == 409
    assert scheduler.llamadas_crear == 1 and _outbox(datos) == []


async def test_confirmaciones_simultaneas_crean_un_solo_schedule(http, h, datos, scheduler):
    nid = await _borrador(http, h, datos)
    cuerpo = {"modo_envio": "PROGRAMAR", "programada_para": _mx(18, 9).isoformat()}
    rs = await asyncio.gather(*[_confirmar(http, h, nid, **cuerpo) for _ in range(5)])
    assert [r.status_code for r in rs] == [202] * 5
    assert scheduler.llamadas_crear == 1 and len(scheduler.schedules) == 1
    assert len(_bitacora(datos)) == 1


async def test_si_falla_scheduler_da_502_y_nada_cambia(http, h, datos, scheduler):
    nid = await _borrador(http, h, datos)
    scheduler.error = RuntimeError("sin red")
    r = await _confirmar(
        http, h, nid, modo_envio="PROGRAMAR", programada_para=_mx(18, 9).isoformat()
    )
    assert r.status_code == 502 and r.json()["codigo"] == "ERROR_PROVEEDOR_PROGRAMADOR"
    assert "sin red" not in r.text
    assert _n(datos, nid)[0] == "BORRADOR" and _bitacora(datos) == []
    scheduler.error = None  # se puede reintentar
    r = await _confirmar(
        http, h, nid, modo_envio="PROGRAMAR", programada_para=_mx(18, 9).isoformat()
    )
    assert r.status_code == 202


# ------------------------------------------------------------------ enviar ahora y horario


async def test_enviar_ahora_dentro_de_horario_no_pide_confirmacion(http, h, datos, scheduler):
    nid = await _borrador(http, h, datos)
    r = await _confirmar(http, h, nid, modo_envio="AHORA")
    assert r.status_code == 202, r.text
    assert r.json()["estado"] == "ENVIANDO" and r.json()["confirmada_fuera_horario"] is False
    fila = _n(datos, nid)
    assert fila[:2] == ("ENVIANDO", "AHORA") and fila[2] is None and fila[3] is None
    assert not scheduler.schedules
    (msg,) = _outbox(datos)
    assert msg[0] == "SQS" and msg[1] == "notif-despacho" and msg[2] == "notificacion.confirmada"
    assert msg[3] == {"notificacion_id": nid, "tipo": "INICIO", "empresa_id": datos["a"]}
    assert msg[4] == datos["a"] and msg[5] is None


async def test_enviar_ahora_fuera_de_horario_da_409_hasta_confirmar(http, h, datos, reloj):
    reloj.ahora = _mx(17, 22, 30)
    nid = await _borrador(http, h, datos)
    r = await _confirmar(http, h, nid, modo_envio="AHORA")
    assert r.status_code == 409, r.text
    assert r.json()["codigo"] == "FUERA_DE_HORARIO_REQUIERE_CONFIRMACION"
    r = await _confirmar(http, h, nid, modo_envio="AHORA", confirmar_fuera_horario=False)
    assert r.status_code == 409
    assert _n(datos, nid)[0] == "BORRADOR" and _outbox(datos) == [] and _bitacora(datos) == []

    r = await _confirmar(http, h, nid, modo_envio="AHORA", confirmar_fuera_horario=True)
    assert r.status_code == 202, r.text
    assert r.json()["estado"] == "ENVIANDO" and r.json()["confirmada_fuera_horario"] is True
    fila = _n(datos, nid)
    # quién confirmó y cuándo
    assert fila[5] is True and fila[6] == datos["ua"] and fila[7] is not None
    assert len(_outbox(datos)) == 1
    (b,) = _bitacora(datos)
    assert b[1] == datos["ua"] and b[2] == "notificacion" and b[3] == nid and b[4] == "USUARIO"
    assert b[5]["confirmada_fuera_horario"] is True


@pytest.mark.parametrize(
    ("ahora", "fuera"),
    [
        (_mx(17, 7, 59, 59), True),
        (_mx(17, 8, 0, 0), False),
        (_mx(17, 20, 0, 0), False),
        (_mx(17, 20, 0, 1), True),
        (_mx(18, 0, 0), True),
    ],
)
async def test_enviar_ahora_en_los_bordes_del_horario(http, h, datos, reloj, ahora, fuera):
    reloj.ahora = ahora
    nid = await _borrador(http, h, datos)
    r = await _confirmar(http, h, nid, modo_envio="AHORA")
    assert (r.status_code == 409) is fuera


async def test_confirmar_fuera_de_horario_sin_necesitarlo_no_deja_marca(http, h, datos):
    nid = await _borrador(http, h, datos)  # 12:00, dentro de horario
    r = await _confirmar(http, h, nid, modo_envio="AHORA", confirmar_fuera_horario=True)
    assert r.status_code == 202 and r.json()["confirmada_fuera_horario"] is False
    assert _bitacora(datos)[0][5]["confirmada_fuera_horario"] is False


async def test_enviar_ahora_dos_veces_o_a_la_vez_publica_un_solo_mensaje(http, h, datos):
    nid = await _borrador(http, h, datos)
    rs = await asyncio.gather(*[_confirmar(http, h, nid, modo_envio="AHORA") for _ in range(4)])
    assert [r.status_code for r in rs] == [202] * 4
    assert (await _confirmar(http, h, nid, modo_envio="AHORA")).status_code == 202
    assert len(_outbox(datos)) == 1 and len(_bitacora(datos)) == 1


async def test_el_mensaje_del_outbox_llega_a_la_cola_con_la_forma_del_despachador(
    http, h, datos, motor
):
    nid = await _borrador(http, h, datos)
    await _confirmar(http, h, nid, modo_envio="AHORA")

    class Cola:
        def __init__(self):
            self.enviados = []

        def send_message(self, **kw):
            self.enviados.append(kw)

    cola = Cola()
    publicados = await publicar_pendientes(
        motor, "notificaciones", publicador_aws(cola, None, fuente="cc.notificaciones")
    )
    assert publicados == 1
    (m,) = cola.enviados
    assert m["QueueUrl"] == "notif-despacho"
    cuerpo = json.loads(m["MessageBody"])
    assert cuerpo["tipo"] == "INICIO" and cuerpo["notificacion_id"] == nid
    assert cuerpo["empresa_id"] == datos["a"] and cuerpo["evento_id"]
    assert _outbox(datos)[0][5] is not None  # marcado publicado


# ------------------------------------------------------------------ requisitos previos


async def test_sin_destinatarios_validos_da_422(http, h, datos, scheduler):
    solo_excluidos = await _borrador(http, h, datos, validos=0, excluidos=3)
    for cuerpo in (
        {"modo_envio": "AHORA"},
        {"modo_envio": "PROGRAMAR", "programada_para": _mx(18, 9).isoformat()},
    ):
        r = await _confirmar(http, h, solo_excluidos, **cuerpo)
        assert r.status_code == 422
        assert ("notificacion", "SIN_DESTINATARIOS_VALIDOS") in _codigos(r)
    assert _n(datos, solo_excluidos)[0] == "BORRADOR" and not scheduler.schedules
    assert _outbox(datos) == []


async def test_sin_revisar_da_422(http, h, datos):
    nid = await _borrador(http, h, datos, validos=0, excluidos=0, revisada=False)
    r = await _confirmar(http, h, nid, modo_envio="AHORA")
    assert r.status_code == 422 and ("notificacion", "REVISION_PENDIENTE") in _codigos(r)


async def test_la_plantilla_debe_seguir_aprobada(http, h, datos):
    nid = await _borrador(http, h, datos)
    sql(datos, "UPDATE notificaciones.plantilla_mensaje SET estado_meta = 'RECHAZADA'")
    r = await _confirmar(http, h, nid, modo_envio="AHORA")
    assert r.status_code == 422 and r.json()["codigo"] == "PLANTILLA_META_NO_APROBADA"


@pytest.mark.parametrize("estado", ["CANCELADA", "COMPLETADA", "CON_FALLAS"])
async def test_solo_se_confirma_desde_borrador(http, h, datos, estado):
    nid = await _borrador(http, h, datos)
    sql(datos, "UPDATE notificaciones.notificacion SET estado = %s WHERE id = %s", (estado, nid))
    r = await _confirmar(http, h, nid, modo_envio="AHORA")
    assert r.status_code == 409 and r.json()["codigo"] == "ESTADO_INVALIDO"
    assert _outbox(datos) == []


async def test_otra_empresa_no_confirma_ni_ve_la_notificacion(http, h, hb, datos, scheduler):
    nid = await _borrador(http, h, datos)
    r = await _confirmar(http, hb, nid, modo_envio="AHORA")
    assert r.status_code == 404
    assert (await _confirmar(http, h, 999_999, modo_envio="AHORA")).status_code == 404
    assert _n(datos, nid)[0] == "BORRADOR"


async def test_el_contrato_de_confirmar_es_cerrado(http, h, datos):
    nid = await _borrador(http, h, datos)
    for malo in (
        {"modo_envio": "YA"},
        {"modo_envio": "AHORA", "mensaje": "hola"},
        {},
    ):
        assert (await _confirmar(http, h, nid, **malo)).status_code == 422


# ------------------------------------------------------------------ bitácora


async def test_la_bitacora_lleva_criterios_y_totales_sin_datos_personales(
    http, h, datos, scheduler
):
    nid = await _borrador(http, h, datos, validos=4, excluidos=2)
    r = await _confirmar(
        http, h, nid, modo_envio="PROGRAMAR", programada_para=_mx(18, 9).isoformat()
    )
    assert r.status_code == 202
    (b,) = _bitacora(datos)
    accion, usuario, entidad, entidad_id, origen, detalle = b
    assert (accion, usuario, entidad, entidad_id, origen) == (
        "NOTIFICACION_ENVIO",
        datos["ua"],
        "notificacion",
        nid,
        "USUARIO",
    )
    assert detalle["criterios"] == CRITERIOS
    assert detalle["totales"] == {"seleccionados": 6, "excluidos": 2, "validos": 4}
    assert detalle["notificacion_id"] == nid and detalle["estado_nuevo"] == "PROGRAMADA"
    assert detalle["confirmada_fuera_horario"] is False and detalle["plantilla_id"]
    # nombres, celulares y variables nunca van a la bitácora
    texto = json.dumps(detalle)
    for prohibido in ("Colaborador", "1111", "nombre_completo", "13 nov", "Entrega de uniformes"):
        assert prohibido not in texto
    assert set(detalle) <= {
        "notificacion_id",
        "plantilla_id",
        "criterios",
        "totales",
        "estado_nuevo",
        "confirmada_fuera_horario",
    }


async def test_el_log_no_trae_datos_personales(http, h, datos, scheduler, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    nid = await _borrador(http, h, datos)
    await _confirmar(http, h, nid, modo_envio="AHORA")
    registrado = " ".join(r.getMessage() for r in caplog.records)
    for prohibido in ("Colaborador", "Entrega de uniformes", "Hola"):
        assert prohibido not in registrado


async def test_una_programacion_cercana_al_cambio_de_dia_usa_la_hora_local(
    http, h, datos, scheduler, reloj
):
    reloj.ahora = _mx(17, 23, 0)
    nid = await _borrador(http, h, datos)
    manana = reloj.ahora + timedelta(hours=9)  # 08:00 del 18
    r = await _confirmar(http, h, nid, modo_envio="PROGRAMAR", programada_para=manana.isoformat())
    assert r.status_code == 202
    assert scheduler.schedules[f"cc-notif-{nid}"].expresion == "at(2026-11-18T08:00:00)"
