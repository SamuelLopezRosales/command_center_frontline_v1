"""T-115: reintentar fallidos (NOT-22) y cancelar (NOT-20). Base real con RLS; Scheduler y
`colaboradores` en memoria (la elegibilidad vigente la dicta ``colaboradores.no_elegibles``).
"""

import asyncio
import itertools
import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from ayudantes_notificaciones import (
    VARIABLES,
    insertar_destinatarios,
    insertar_plantilla,
    sql,
)
from cc_notificaciones import consumidores
from cc_notificaciones.servicios.reintentar_cancelar import evento_reintento

pytestmark = pytest.mark.docker

BASE = "/api/v1/notificaciones"
CRITERIOS = {"op": "Y", "items": [{"campo": "planta_id", "operador": "es", "valor": 3}]}
_SEC = itertools.count(1)
NOCHE = datetime(2026, 11, 18, 4, 30, tzinfo=UTC)  # 22:30 del 17 en Ciudad de México


async def _notificacion(http, h, datos, destinatarios, estado="CON_FALLAS"):
    """Notificación en ``estado`` con un destinatario por estado de ``destinatarios`` (los
    colaboradores son 1000, 1001...). Devuelve ``(notificacion_id, [destinatario_id])``."""
    p = insertar_plantilla(datos, nombre=f"plantilla_{next(_SEC)}")
    r = await http.post(
        BASE,
        json={
            "titulo": "Aviso",
            "modo": "CRITERIOS",
            "criterios": CRITERIOS,
            "plantilla_mensaje_id": p,
            "variables": VARIABLES,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    nid = r.json()["id"]
    ids = []
    for e in destinatarios:
        ids += insertar_destinatarios(datos, nid, n=1, estado=e)
    sql(
        datos,
        "UPDATE notificaciones.notificacion SET estado = %s, revisada_en = now(), "
        "total_seleccionados = %s, total_excluidos = 0, "
        "programada_para = CASE WHEN %s = 'PROGRAMADA' THEN now() END WHERE id = %s",
        (estado, len(ids), estado, nid),
    )
    return nid, ids


async def _reintentar(http, h, nid, **cuerpo):
    return await http.post(f"{BASE}/{nid}/reintentar", json=cuerpo, headers=h)


def _destinatarios(datos, nid):
    return sql(
        datos,
        "SELECT colaborador_id, estado_envio, intentos, encolado_en, motivo_fallo "
        "FROM notificaciones.notificacion_destinatario WHERE notificacion_id = %s ORDER BY id",
        (nid,),
    )


def _outbox(datos):
    return sql(
        datos,
        "SELECT evento_id, destino, tipo, payload, empresa_id FROM notificaciones.outbox "
        "ORDER BY id",
    )


def _estado(datos, nid):
    return sql(datos, "SELECT estado FROM notificaciones.notificacion WHERE id = %s", (nid,))[0][0]


def _bitacora(datos, accion):
    return sql(
        datos,
        "SELECT usuario_id, entidad_id, origen, detalle FROM auditoria.bitacora "
        "WHERE accion = %s ORDER BY id",
        (accion,),
    )


# ------------------------------------------------------------------ reintentar (NOT-22)


async def test_reintentar_solo_toca_fallidos_elegibles_y_deja_la_notificacion_enviando(
    http, h, datos, colaboradores
):
    colaboradores.no_elegibles = {1002: "CELULAR_INVALIDO"}
    nid, _ = await _notificacion(
        http, h, datos, ["ENTREGADO", "FALLIDO", "FALLIDO", "LEIDO", "EXCLUIDO"]
    )
    sql(
        datos,
        "UPDATE notificaciones.notificacion_destinatario SET motivo_fallo = 'META_131026' "
        "WHERE notificacion_id = %s AND estado_envio = 'FALLIDO'",
        (nid,),
    )
    r = await _reintentar(http, h, nid)
    assert r.status_code == 202, r.text
    assert r.json()["estado"] == "ENVIANDO"

    assert _destinatarios(datos, nid) == [
        (1000, "ENTREGADO", 0, None, None),  # ya recibió: intacto
        (1001, "PENDIENTE", 1, None, None),  # reintentable: nuevo ciclo
        (1002, "FALLIDO", 0, None, "META_131026"),  # celular inválido: no se incluye
        (1003, "LEIDO", 0, None, None),
        (1004, "EXCLUIDO", 0, None, None),
    ]
    assert _estado(datos, nid) == "ENVIANDO"
    # a `colaboradores` solo se le pregunta por los fallidos (nunca por quien ya recibió)
    assert colaboradores.consultas_elegibilidad == [[1001, 1002]]


async def test_reintentar_escribe_un_mensaje_de_reintento_con_evento_determinista(http, h, datos):
    nid, _ = await _notificacion(http, h, datos, ["FALLIDO", "ENTREGADO"])
    await _reintentar(http, h, nid)
    ((eid, destino, tipo, payload, empresa),) = _outbox(datos)
    assert eid == evento_reintento(nid, 1)
    assert destino == "notif-despacho" and tipo == "notificacion.confirmada"
    assert payload == {"notificacion_id": nid, "tipo": "REINTENTO", "empresa_id": datos["a"]}
    assert empresa == datos["a"]


async def test_reintentar_deja_bitacora_sin_datos_personales(http, h, datos, colaboradores):
    colaboradores.no_elegibles = {1001: "CELULAR_INVALIDO"}
    nid, _ = await _notificacion(http, h, datos, ["FALLIDO", "FALLIDO", "FALLIDO"])
    await _reintentar(http, h, nid)
    ((usuario, entidad_id, origen, detalle),) = _bitacora(datos, "NOTIFICACION_ENVIO")
    assert (usuario, entidad_id, origen) == (datos["ua"], nid, "USUARIO")
    assert detalle == {
        "notificacion_id": nid,
        "motivo": "REINTENTO",
        "estado_anterior": "CON_FALLAS",
        "estado_nuevo": "ENVIANDO",
        "totales": {"reintentados": 2, "omitidos": 1},
        "confirmada_fuera_horario": False,
    }


async def test_nunca_reenvia_a_quien_ya_recibio(http, h, datos, colaboradores):
    """Todos los estados de recepción quedan igual, aunque `colaboradores` los diera por
    elegibles: solo los ``FALLIDO`` pasan a ``PENDIENTE``."""
    recibieron = ["ENVIADO", "ENTREGADO", "LEIDO", "RESPONDIO"]
    nid, _ = await _notificacion(http, h, datos, [*recibieron, "FALLIDO"])
    r = await _reintentar(http, h, nid)
    assert r.status_code == 202
    assert [f[1] for f in _destinatarios(datos, nid)] == [*recibieron, "PENDIENTE"]
    assert [f[2] for f in _destinatarios(datos, nid)] == [0, 0, 0, 0, 1]


async def test_un_entregado_tardio_entre_la_consulta_y_el_cambio_no_se_reenvia(
    http, h, datos, colaboradores, motor
):
    """El ``UPDATE`` exige ``FALLIDO`` al momento de cambiar: quien recibió mientras tanto queda."""
    nid, (d1, d2) = await _notificacion(http, h, datos, ["FALLIDO", "FALLIDO"])

    async def entrega_tardia(empresa_id, colaboradores_ids):
        sql(
            datos,
            "UPDATE notificaciones.notificacion_destinatario SET estado_envio = 'ENTREGADO' "
            "WHERE id = %s",
            (d1,),
        )
        return {c: None for c in colaboradores_ids}

    colaboradores.elegibilidad = entrega_tardia
    r = await _reintentar(http, h, nid)
    assert r.status_code == 202
    assert [f[1] for f in _destinatarios(datos, nid)] == ["ENTREGADO", "PENDIENTE"]


@pytest.mark.parametrize(
    "estado", ["BORRADOR", "PROGRAMADA", "ENVIANDO", "COMPLETADA", "CANCELADA"]
)
async def test_reintentar_solo_desde_con_fallas(http, h, datos, estado):
    nid, _ = await _notificacion(http, h, datos, ["FALLIDO"], estado=estado)
    r = await _reintentar(http, h, nid)
    assert r.status_code == 409 and r.json()["codigo"] == "ESTADO_INVALIDO"
    assert _estado(datos, nid) == estado and _outbox(datos) == []
    assert _destinatarios(datos, nid)[0][1] == "FALLIDO"


async def test_reintentar_otra_empresa_o_inexistente_da_404(http, h, hb, datos):
    nid, _ = await _notificacion(http, h, datos, ["FALLIDO"])
    assert (await _reintentar(http, hb, nid)).status_code == 404
    assert (await _reintentar(http, h, 99999)).status_code == 404
    assert _estado(datos, nid) == "CON_FALLAS"


async def test_sin_fallidos_elegibles_da_422_y_no_cambia_nada(http, h, datos, colaboradores):
    colaboradores.no_elegibles = {1000: "CELULAR_INVALIDO", 1001: "BAJA"}
    nid, _ = await _notificacion(http, h, datos, ["FALLIDO", "FALLIDO", "ENTREGADO"])
    r = await _reintentar(http, h, nid)
    assert r.status_code == 422
    assert {e["codigo"] for e in r.json()["errores"]} == {"SIN_FALLIDOS_REINTENTABLES"}
    assert _estado(datos, nid) == "CON_FALLAS" and _outbox(datos) == []
    assert [f[1] for f in _destinatarios(datos, nid)] == ["FALLIDO", "FALLIDO", "ENTREGADO"]
    assert _bitacora(datos, "NOTIFICACION_ENVIO") == []


async def test_pedir_el_reintento_dos_veces_no_duplica(http, h, datos):
    nid, _ = await _notificacion(http, h, datos, ["FALLIDO", "ENTREGADO"])
    r1 = await _reintentar(http, h, nid)
    r2 = await _reintentar(http, h, nid)
    assert r1.status_code == r2.status_code == 202
    assert r2.json()["estado"] == "ENVIANDO"
    assert len(_outbox(datos)) == 1
    assert [f[1:3] for f in _destinatarios(datos, nid)] == [("PENDIENTE", 1), ("ENTREGADO", 0)]
    assert len(_bitacora(datos, "NOTIFICACION_ENVIO")) == 1


async def test_reintentos_simultaneos_publican_un_solo_mensaje(http, h, datos):
    nid, _ = await _notificacion(http, h, datos, ["FALLIDO", "FALLIDO", "FALLIDO"])
    rs = await asyncio.gather(*[_reintentar(http, h, nid) for _ in range(6)])
    assert [r.status_code for r in rs] == [202] * 6
    assert len(_outbox(datos)) == 1
    assert [f[2] for f in _destinatarios(datos, nid)] == [1, 1, 1]


async def test_un_segundo_ciclo_de_reintento_es_otro_mensaje(http, h, datos):
    motor = http._transport.app.state.motor
    nid, _ = await _notificacion(http, h, datos, ["FALLIDO"])
    assert (await _reintentar(http, h, nid)).status_code == 202
    # vuelve a fallar: la notificación cierra con fallas y se puede reintentar de nuevo
    ev = {
        "evento_id": str(uuid.uuid4()),
        "tipo": "wa.mensaje_estado",
        "origen_tipo": "NOTIFICACION",
        "origen_id": nid,
        "colaborador_id": 1000,
        "estado": "FALLIDO",
        "error_codigo": "INTENTOS_AGOTADOS",
        "empresa_id": datos["a"],
    }
    assert await consumidores.manejar_evento(motor, ev) is True
    assert _estado(datos, nid) == "CON_FALLAS"
    assert (await _reintentar(http, h, nid)).status_code == 202
    assert [o[0] for o in _outbox(datos)] == [evento_reintento(nid, 1), evento_reintento(nid, 2)]
    assert _destinatarios(datos, nid)[0][:3] == (1000, "PENDIENTE", 2)


async def test_reintentar_fuera_de_horario_pide_confirmacion(http, h, datos, reloj):
    reloj.ahora = NOCHE
    nid, _ = await _notificacion(http, h, datos, ["FALLIDO"])
    r = await _reintentar(http, h, nid)
    assert r.status_code == 409
    assert r.json()["codigo"] == "FUERA_DE_HORARIO_REQUIERE_CONFIRMACION"
    assert _estado(datos, nid) == "CON_FALLAS" and _outbox(datos) == []
    assert _destinatarios(datos, nid)[0][1] == "FALLIDO"
    r = await _reintentar(http, h, nid, confirmar_fuera_horario=False)
    assert r.status_code == 409

    r = await _reintentar(http, h, nid, confirmar_fuera_horario=True)
    assert r.status_code == 202, r.text
    d = r.json()
    assert d["estado"] == "ENVIANDO" and d["confirmada_fuera_horario"] is True
    assert d["confirmada_por_usuario_id"] == datos["ua"]
    ((_, _, _, detalle),) = _bitacora(datos, "NOTIFICACION_ENVIO")
    assert detalle["confirmada_fuera_horario"] is True
    assert len(_outbox(datos)) == 1


async def test_reintentar_dentro_de_horario_no_marca_fuera_de_horario(http, h, datos):
    nid, _ = await _notificacion(http, h, datos, ["FALLIDO"])
    r = await _reintentar(http, h, nid, confirmar_fuera_horario=True)  # innecesaria: no cuenta
    assert r.status_code == 202 and r.json()["confirmada_fuera_horario"] is False


# ------------------------------------------------------------------ cancelar (NOT-20)


async def _programada(http, h, datos, scheduler):
    nid, _ = await _notificacion(http, h, datos, ["PENDIENTE", "PENDIENTE"], estado="BORRADOR")
    r = await http.post(
        f"{BASE}/{nid}/confirmar",
        json={"modo_envio": "PROGRAMAR", "programada_para": "2026-11-18T09:00:00-06:00"},
        headers=h,
    )
    assert r.status_code == 202, r.text
    assert list(scheduler.schedules) == [f"cc-notif-{nid}"]
    return nid


async def _cancelar(http, h, nid, **cuerpo):
    return await http.post(f"{BASE}/{nid}/cancelar", json=cuerpo or None, headers=h)


async def test_cancelar_un_borrador(http, h, datos, scheduler):
    nid, _ = await _notificacion(http, h, datos, ["PENDIENTE"], estado="BORRADOR")
    r = await _cancelar(http, h, nid, motivo="Se envió por otro medio")
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "CANCELADA"
    assert r.json()["motivo_cancelacion"] == "Se envió por otro medio"
    assert scheduler.eliminados == []  # un borrador no tiene schedule
    ((usuario, entidad_id, origen, detalle),) = _bitacora(datos, "NOTIFICACION_CANCELADA")
    assert (usuario, entidad_id, origen) == (datos["ua"], nid, "USUARIO")
    assert detalle == {
        "notificacion_id": nid,
        "estado_anterior": "BORRADOR",
        "estado_nuevo": "CANCELADA",
    }  # el motivo libre no va a la bitácora
    assert _outbox(datos) == []


async def test_cancelar_una_programada_elimina_el_schedule(http, h, datos, scheduler):
    nid = await _programada(http, h, datos, scheduler)
    r = await _cancelar(http, h, nid)  # sin cuerpo
    assert r.status_code == 200 and r.json()["estado"] == "CANCELADA"
    assert r.json()["motivo_cancelacion"] is None
    assert scheduler.eliminados == [f"cc-notif-{nid}"] and scheduler.schedules == {}
    ((_, _, _, detalle),) = _bitacora(datos, "NOTIFICACION_CANCELADA")
    assert detalle["estado_anterior"] == "PROGRAMADA"


async def test_cancelar_dos_veces_es_idempotente(http, h, datos, scheduler):
    nid = await _programada(http, h, datos, scheduler)
    assert (await _cancelar(http, h, nid)).status_code == 200
    r = await _cancelar(http, h, nid)
    assert r.status_code == 200 and r.json()["estado"] == "CANCELADA"
    assert scheduler.eliminados == [f"cc-notif-{nid}"]
    assert len(_bitacora(datos, "NOTIFICACION_CANCELADA")) == 1


@pytest.mark.parametrize("estado", ["ENVIANDO", "COMPLETADA", "CON_FALLAS"])
async def test_cancelar_una_ya_enviada_da_409(http, h, datos, scheduler, estado):
    nid, _ = await _notificacion(http, h, datos, ["ENVIADO"], estado=estado)
    r = await _cancelar(http, h, nid)
    assert r.status_code == 409 and r.json()["codigo"] == "ESTADO_INVALIDO"
    assert _estado(datos, nid) == estado
    assert scheduler.eliminados == [] and _bitacora(datos, "NOTIFICACION_CANCELADA") == []


async def test_si_falla_scheduler_al_cancelar_da_502_y_nada_cambia(http, h, datos, scheduler):
    nid = await _programada(http, h, datos, scheduler)
    scheduler.error = RuntimeError("sin red")
    r = await _cancelar(http, h, nid)
    assert r.status_code == 502 and r.json()["codigo"] == "ERROR_PROVEEDOR_PROGRAMADOR"
    assert "sin red" not in r.text
    assert _estado(datos, nid) == "PROGRAMADA"
    assert _bitacora(datos, "NOTIFICACION_CANCELADA") == []
    scheduler.error = None  # se puede repetir
    assert (await _cancelar(http, h, nid)).status_code == 200
    assert _estado(datos, nid) == "CANCELADA"


async def test_una_cancelada_ya_no_se_confirma_ni_se_reintenta(http, h, datos, scheduler):
    nid = await _programada(http, h, datos, scheduler)
    await _cancelar(http, h, nid)
    r = await http.post(f"{BASE}/{nid}/confirmar", json={"modo_envio": "AHORA"}, headers=h)
    assert r.status_code == 409
    assert (await _reintentar(http, h, nid)).status_code == 409
    assert _outbox(datos) == []


async def test_cancelar_valida_el_motivo_y_la_empresa(http, h, hb, datos):
    nid, _ = await _notificacion(http, h, datos, ["PENDIENTE"], estado="BORRADOR")
    assert (await _cancelar(http, h, nid, motivo="x" * 201)).status_code == 422
    assert (await _cancelar(http, h, nid, texto="otro")).status_code == 422
    assert (await _cancelar(http, hb, nid)).status_code == 404
    assert (await _cancelar(http, h, 99999)).status_code == 404
    assert _estado(datos, nid) == "BORRADOR"


async def test_cancelaciones_simultaneas_borran_el_schedule_una_vez(http, h, datos, scheduler):
    nid = await _programada(http, h, datos, scheduler)
    rs = await asyncio.gather(*[_cancelar(http, h, nid) for _ in range(5)])
    assert [r.status_code for r in rs] == [200] * 5
    assert scheduler.eliminados == [f"cc-notif-{nid}"]
    assert len(_bitacora(datos, "NOTIFICACION_CANCELADA")) == 1


def test_la_accion_de_bitacora_existe_en_el_catalogo_y_en_la_base(datos):
    from cc_common.bitacora import ACCIONES

    assert "NOTIFICACION_CANCELADA" in ACCIONES
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        # la base no restringe la acción: la restricción vigente es la lista de claves de `detalle`
        c.execute(
            "INSERT INTO auditoria.bitacora (empresa_id, accion, entidad, origen, detalle) "
            "VALUES (%s, 'NOTIFICACION_CANCELADA', 'notificacion', 'SISTEMA', "
            '\'{"notificacion_id": 1, "estado_anterior": "BORRADOR"}\')',
            (datos["a"],),
        )


async def test_el_reintento_libera_encolado_y_respaldo_y_suma_intentos(http, h, datos):
    nid, (d,) = await _notificacion(http, h, datos, ["FALLIDO"])
    sql(
        datos,
        "UPDATE notificaciones.notificacion_destinatario SET encolado_en = now(), "
        "respaldo_enviado_en = now(), intentos = 2, motivo_fallo = 'INTENTOS_AGOTADOS' "
        "WHERE id = %s",
        (d,),
    )
    assert (await _reintentar(http, h, nid)).status_code == 202
    fila = sql(
        datos,
        "SELECT estado_envio, encolado_en, respaldo_enviado_en, intentos, motivo_fallo "
        "FROM notificaciones.notificacion_destinatario WHERE id = %s",
        (d,),
    )[0]
    assert fila == ("PENDIENTE", None, None, 3, None)


async def test_el_mensaje_de_reintento_llega_a_notif_despacho_con_el_cuerpo_esperado(
    http, h, datos
):
    import json

    from cc_common.outbox import publicador_aws, publicar_pendientes

    class Cola:
        def __init__(self):
            self.enviados = []

        def send_message(self, **kw):
            self.enviados.append(kw)

    nid, _ = await _notificacion(http, h, datos, ["FALLIDO"])
    await _reintentar(http, h, nid)
    cola = Cola()
    motor = http._transport.app.state.motor
    assert (
        await publicar_pendientes(
            motor, "notificaciones", publicador_aws(cola, None, fuente="cc.notificaciones")
        )
        == 1
    )
    (m,) = cola.enviados
    assert m["QueueUrl"] == "notif-despacho"
    assert json.loads(m["MessageBody"]) == {
        "evento_id": str(evento_reintento(nid, 1)),
        "tipo": "REINTENTO",
        "notificacion_id": nid,
        "empresa_id": datos["a"],
    }


async def test_el_reintento_cambia_el_mensaje_uuid_del_despachador(http, h, datos):
    """``mensaje_uuid = uuid5(notificación, destinatario, ronda = intentos)``: sin sumar
    ``intentos`` el reenvío repetiría el uuid del primer intento y el enviador lo ignoraría."""
    nid, (d,) = await _notificacion(http, h, datos, ["FALLIDO"])
    antes = sql(
        datos, "SELECT intentos FROM notificaciones.notificacion_destinatario WHERE id = %s", (d,)
    )[0][0]
    await _reintentar(http, h, nid)
    despues = sql(
        datos, "SELECT intentos FROM notificaciones.notificacion_destinatario WHERE id = %s", (d,)
    )[0][0]
    uuid_ = lambda ronda: uuid.uuid5(uuid.NAMESPACE_URL, f"{nid}:{d}:{ronda}")  # noqa: E731
    assert despues == antes + 1 and uuid_(antes) != uuid_(despues)
