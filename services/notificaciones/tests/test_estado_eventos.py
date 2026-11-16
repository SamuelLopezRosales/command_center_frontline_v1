"""T-113: consumidores de eventos y máquina de estados (``estado_service``). Base real con RLS.

El mensaje de una notificación lleva ``origen_tipo = NOTIFICACION`` y ``origen_id`` = id del
destinatario; ``wa.mensaje_estado`` los trae tal cual.
"""

import asyncio
import hashlib
import itertools
import uuid

import psycopg
import pytest
from ayudantes_notificaciones import (
    VARIABLES,
    insertar_destinatarios,
    insertar_plantilla,
    sql,
)
from cc_notificaciones import consumidores

pytestmark = pytest.mark.docker

BASE = "/api/v1/notificaciones"
CRITERIOS = {"op": "Y", "items": [{"campo": "planta_id", "operador": "es", "valor": 3}]}
_SEC = itertools.count(1)


async def _notificacion(http, h, datos, destinatarios, estado="ENVIANDO", empresa=None):
    """Notificación en ``estado`` con un destinatario por cada estado de ``destinatarios``.
    Devuelve ``(notificacion_id, [destinatario_id])``."""
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
        ids += insertar_destinatarios(datos, nid, empresa=empresa, n=1, estado=e)
    sql(
        datos,
        "UPDATE notificaciones.notificacion SET estado = %s, "
        "programada_para = CASE WHEN %s = 'PROGRAMADA' THEN now() END WHERE id = %s",
        (estado, estado, nid),
    )
    return nid, ids


def _evento(datos, destinatario_id, estado, *, error=None, origen="NOTIFICACION", **extra):
    """Evento del enviador: ``origen_id`` es la notificación y ``colaborador_id`` el destinatario.
    ``destinatario_id`` (de la base) solo sirve para encontrar ambos; un valor que no existe deja
    ids que no corresponden a nadie."""
    fila = None
    if isinstance(destinatario_id, int):
        fila = sql(
            datos,
            "SELECT notificacion_id, colaborador_id FROM notificaciones.notificacion_destinatario "
            "WHERE id = %s",
            (destinatario_id,),
        )
    nid, col = fila[0] if fila else (destinatario_id, 99999)
    return {
        "evento_id": str(uuid.uuid4()),
        "tipo": "wa.mensaje_estado",
        "mensaje_uuid": str(uuid.uuid4()),
        "origen_tipo": origen,
        "origen_id": nid,
        "colaborador_id": col,
        "estado": estado,
        "error_codigo": error,
        "empresa_id": datos["a"],
        **{"colaborador_id": col, **extra},
    }


def _estado_n(datos, nid):
    return sql(datos, "SELECT estado FROM notificaciones.notificacion WHERE id = %s", (nid,))[0][0]


def _estados_d(datos, nid):
    return [
        f[0]
        for f in sql(
            datos,
            "SELECT estado_envio FROM notificaciones.notificacion_destinatario "
            "WHERE notificacion_id = %s ORDER BY id",
            (nid,),
        )
    ]


def _motor(http):
    return http._transport.app.state.motor


# ------------------------------------------------------------------ los estados solo avanzan


async def test_el_estado_del_destinatario_solo_avanza(http, h, datos):
    motor = _motor(http)
    nid, (d,) = await _notificacion(http, h, datos, ["PENDIENTE"])

    async def aplicar(estado, **kw):
        return await consumidores.manejar_evento(motor, _evento(datos, d, estado, **kw))

    def ahora():
        return _estados_d(datos, nid)[0]

    assert await aplicar("ENVIADO") is True and ahora() == "ENVIADO"
    assert await aplicar("ENVIADO") is False  # repetido con otro evento_id
    assert await aplicar("LEIDO") is True and ahora() == "LEIDO"  # salta ENTREGADO
    assert await aplicar("ENTREGADO") is False and ahora() == "LEIDO"  # fuera de orden
    assert await aplicar("ENVIADO") is False and ahora() == "LEIDO"
    assert await aplicar("FALLIDO", error="META_131026") is False and ahora() == "LEIDO"
    fila = sql(
        datos,
        "SELECT canal_usado, motivo_fallo FROM notificaciones.notificacion_destinatario "
        "WHERE id = %s",
        (d,),
    )[0]
    assert fila == ("WHATSAPP", None)


async def test_un_evento_repetido_se_procesa_una_sola_vez(http, h, datos):
    motor = _motor(http)
    _, (d,) = await _notificacion(http, h, datos, ["PENDIENTE"])
    ev = _evento(datos, d, "ENVIADO")
    assert await consumidores.manejar_evento(motor, ev) is True
    assert await consumidores.manejar_evento(motor, ev) is False
    assert sql(datos, "SELECT count(*) FROM notificaciones.evento_procesado")[0][0] == 1


async def test_un_fallido_guarda_el_motivo_y_avanza_desde_enviado(http, h, datos):
    motor = _motor(http)
    _, (d1, d2) = await _notificacion(http, h, datos, ["PENDIENTE", "ENVIADO"])
    assert (
        await consumidores.manejar_evento(motor, _evento(datos, d1, "FALLIDO", error="X")) is True
    )
    assert await consumidores.manejar_evento(
        motor, _evento(datos, d2, "FALLIDO", error="META_131026")
    )
    filas = sql(
        datos,
        "SELECT estado_envio, motivo_fallo FROM notificaciones.notificacion_destinatario "
        "WHERE id IN (%s, %s) ORDER BY id",
        (d1, d2),
    )
    assert filas == [("FALLIDO", "X"), ("FALLIDO", "META_131026")]
    # un FALLIDO sin código también deja motivo
    _, (d3,) = await _notificacion(http, h, datos, ["PENDIENTE"])
    await consumidores.manejar_evento(motor, _evento(datos, d3, "FALLIDO"))
    assert sql(
        datos,
        "SELECT motivo_fallo FROM notificaciones.notificacion_destinatario WHERE id = %s",
        (d3,),
    ) == [("ERROR_DE_ENTREGA",)]


async def test_un_excluido_no_cambia(http, h, datos):
    motor = _motor(http)
    nid, (pend, exc) = await _notificacion(http, h, datos, ["PENDIENTE", "EXCLUIDO"])
    assert await consumidores.manejar_evento(motor, _evento(datos, exc, "ENVIADO")) is False
    assert _estados_d(datos, nid) == ["PENDIENTE", "EXCLUIDO"]


# ------------------------------------------------------------------ cierre de la notificación


async def test_completada_cuando_no_quedan_pendientes_ni_fallidos(http, h, datos):
    motor = _motor(http)
    nid, (a, b) = await _notificacion(http, h, datos, ["PENDIENTE", "PENDIENTE"])
    await consumidores.manejar_evento(motor, _evento(datos, a, "ENVIADO"))
    assert _estado_n(datos, nid) == "ENVIANDO"  # queda un pendiente
    await consumidores.manejar_evento(motor, _evento(datos, b, "ENTREGADO"))
    assert _estado_n(datos, nid) == "COMPLETADA"
    # los avances posteriores solo cambian contadores
    await consumidores.manejar_evento(motor, _evento(datos, a, "LEIDO"))
    assert _estado_n(datos, nid) == "COMPLETADA"


async def test_con_fallas_cuando_no_quedan_pendientes_y_hay_fallidos(http, h, datos):
    motor = _motor(http)
    nid, (a, b, c) = await _notificacion(http, h, datos, ["PENDIENTE"] * 3)
    await consumidores.manejar_evento(motor, _evento(datos, a, "FALLIDO", error="X"))
    assert _estado_n(datos, nid) == "ENVIANDO"  # hay fallido pero quedan pendientes
    await consumidores.manejar_evento(motor, _evento(datos, b, "ENVIADO"))
    assert _estado_n(datos, nid) == "ENVIANDO"
    await consumidores.manejar_evento(motor, _evento(datos, c, "ENTREGADO"))
    assert _estado_n(datos, nid) == "CON_FALLAS"
    # un ENTREGADO posterior de otro no cambia el estado de la notificación
    await consumidores.manejar_evento(motor, _evento(datos, b, "ENTREGADO"))
    assert _estado_n(datos, nid) == "CON_FALLAS"


async def test_los_excluidos_no_impiden_cerrar(http, h, datos):
    motor = _motor(http)
    nid, (a, _) = await _notificacion(http, h, datos, ["PENDIENTE", "EXCLUIDO"])
    await consumidores.manejar_evento(motor, _evento(datos, a, "ENVIADO"))
    assert _estado_n(datos, nid) == "COMPLETADA"


async def test_un_fallido_tardio_reabre_una_completada_como_con_fallas(http, h, datos):
    motor = _motor(http)
    nid, (a, b) = await _notificacion(http, h, datos, ["PENDIENTE", "PENDIENTE"])
    await consumidores.manejar_evento(motor, _evento(datos, a, "ENVIADO"))
    await consumidores.manejar_evento(motor, _evento(datos, b, "ENVIADO"))
    assert _estado_n(datos, nid) == "COMPLETADA"
    await consumidores.manejar_evento(motor, _evento(datos, b, "FALLIDO", error="META_131026"))
    assert _estados_d(datos, nid) == ["ENVIADO", "FALLIDO"]
    assert _estado_n(datos, nid) == "CON_FALLAS"


@pytest.mark.parametrize("estado", ["BORRADOR", "CANCELADA", "PROGRAMADA", "CON_FALLAS"])
async def test_solo_una_enviando_se_cierra(http, h, datos, estado):
    motor = _motor(http)
    nid, (a,) = await _notificacion(http, h, datos, ["PENDIENTE"], estado=estado)
    await consumidores.manejar_evento(motor, _evento(datos, a, "ENVIADO"))
    assert _estado_n(datos, nid) == estado  # el destinatario avanza; la notificación no


async def test_dos_ultimos_eventos_a_la_vez_cierran_la_notificacion(http, h, datos):
    """Sin bloquear la notificación, cada transacción vería a la otra como pendiente y la
    notificación se quedaría en ENVIANDO."""
    motor = _motor(http)
    for _ in range(5):
        nid, ids = await _notificacion(http, h, datos, ["PENDIENTE"] * 6)
        resultados = await asyncio.gather(
            *[consumidores.manejar_evento(motor, _evento(datos, d, "ENVIADO")) for d in ids]
        )
        assert all(resultados)
        assert _estado_n(datos, nid) == "COMPLETADA"


async def test_los_ultimos_eventos_con_un_fallido_cierran_con_fallas_en_paralelo(http, h, datos):
    motor = _motor(http)
    nid, ids = await _notificacion(http, h, datos, ["PENDIENTE"] * 4)
    await asyncio.gather(
        *[
            consumidores.manejar_evento(
                motor, _evento(datos, d, "FALLIDO" if i == 0 else "ENTREGADO", error="X")
            )
            for i, d in enumerate(ids)
        ]
    )
    assert _estado_n(datos, nid) == "CON_FALLAS"


# ------------------------------------------------------------------ eventos que no son de aquí


@pytest.mark.parametrize("origen", ["CONSTANCIA", "BOT", "CHAT", "RECHAZO_BOT"])
async def test_los_mensajes_de_otro_origen_se_ignoran(http, h, datos, origen):
    motor = _motor(http)
    nid, (d,) = await _notificacion(http, h, datos, ["PENDIENTE"])
    assert (
        await consumidores.manejar_evento(motor, _evento(datos, d, "ENVIADO", origen=origen))
        is False
    )
    assert _estados_d(datos, nid) == ["PENDIENTE"]
    assert sql(datos, "SELECT count(*) FROM notificaciones.evento_procesado")[0][0] == 0


async def test_eventos_incompletos_o_de_un_destinatario_desconocido_no_hacen_nada(http, h, datos):
    motor = _motor(http)
    nid, (d,) = await _notificacion(http, h, datos, ["PENDIENTE"])
    malos = [
        _evento(datos, None, "ENVIADO"),
        _evento(datos, d, "ENVIADO", empresa_id=None),
        _evento(datos, d, "RECIBIDO"),
        _evento(datos, d, "ENCOLADO"),
        _evento(datos, "x", "ENVIADO"),
        _evento(datos, 99999999, "ENVIADO"),
        _evento(datos, d, "ENVIADO", colaborador_id=424242),  # nadie con ese colaborador
        _evento(datos, d, "ENVIADO", origen_id=nid + 1000),  # otra notificación
    ]
    for ev in malos:
        assert await consumidores.manejar_evento(motor, ev) is False
    assert _estados_d(datos, nid) == ["PENDIENTE"]


async def test_un_evento_de_otra_empresa_no_toca_los_destinatarios_ajenos(http, h, datos):
    motor = _motor(http)
    nid, (d,) = await _notificacion(http, h, datos, ["PENDIENTE"])
    ev = _evento(datos, d, "ENVIADO", empresa_id=datos["b"])
    assert await consumidores.manejar_evento(motor, ev) is False  # la RLS lo oculta
    assert _estados_d(datos, nid) == ["PENDIENTE"] and _estado_n(datos, nid) == "ENVIANDO"
    ev = _evento(datos, d, "ENVIADO")  # el de su empresa sí
    assert await consumidores.manejar_evento(motor, ev) is True


async def test_los_tipos_desconocidos_siguen_lanzando(http):
    for tipo in ("wa.otra_cosa", "wa.numero_invalido", "campo.actualizado", None):
        with pytest.raises(consumidores.EventoNoManejado):
            await consumidores.manejar_evento(_motor(http), {"tipo": tipo})


# ------------------------------------------------------------------ wa.respuesta_recibida


def _conversacion(datos, empresa=None, semilla="a"):
    huella = hashlib.sha256(semilla.encode()).digest()
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        return c.execute(
            "INSERT INTO whatsapp.conversacion_whatsapp (empresa_id, estado, celular_hash, origen) "
            "VALUES (%s, 'ACTIVA', %s, 'NOTIFICACION') RETURNING id",
            (empresa or datos["a"], huella),
        ).fetchone()[0]


def _respuesta(datos, colaborador_id, **extra):
    return {
        "evento_id": str(uuid.uuid4()),
        "tipo": "wa.respuesta_recibida",
        "colaborador_id": colaborador_id,
        "empresa_id": datos["a"],
        **extra,
    }


def _conversacion_de(datos, destinatario_id):
    return sql(
        datos,
        "SELECT conversacion_id FROM notificaciones.notificacion_destinatario WHERE id = %s",
        (destinatario_id,),
    )[0][0]


@pytest.mark.parametrize("previo", ["ENVIADO", "ENTREGADO", "LEIDO"])
async def test_la_respuesta_marca_respondio_y_vincula_la_conversacion(http, h, datos, previo):
    motor = _motor(http)
    nid, (d,) = await _notificacion(http, h, datos, [previo], estado="COMPLETADA")
    conv = _conversacion(datos)
    ev = _respuesta(datos, 1000, conversacion_id=conv)
    assert await consumidores.manejar_evento(motor, ev) is True
    assert _estados_d(datos, nid) == ["RESPONDIO"] and _conversacion_de(datos, d) == conv
    assert _estado_n(datos, nid) == "COMPLETADA"  # solo cambian los contadores
    assert await consumidores.manejar_evento(motor, ev) is False  # repetido
    assert await consumidores.manejar_evento(motor, _respuesta(datos, 1000)) is False
    # un LEIDO tardío no retrocede a quien ya respondió
    await consumidores.manejar_evento(motor, _evento(datos, d, "LEIDO"))
    assert _estados_d(datos, nid) == ["RESPONDIO"]
    r = await http.get(f"{BASE}/{nid}", headers=h)
    assert r.json()["contadores"]["respondieron"] == 1


async def test_la_respuesta_va_al_envio_mas_reciente_del_colaborador(http, h, datos):
    motor = _motor(http)
    viejo, (dv,) = await _notificacion(http, h, datos, ["ENTREGADO"], estado="COMPLETADA")
    reciente, (dr,) = await _notificacion(http, h, datos, ["ENTREGADO"], estado="COMPLETADA")
    sql(
        datos,
        "UPDATE notificaciones.notificacion_destinatario "
        "SET fecha_estado = now() - interval '2 hours' WHERE id = %s",
        (dv,),
    )
    assert await consumidores.manejar_evento(motor, _respuesta(datos, 1000)) is True
    assert _estados_d(datos, viejo) == ["ENTREGADO"]
    assert _estados_d(datos, reciente) == ["RESPONDIO"]


async def test_la_respuesta_puede_indicar_el_destinatario(http, h, datos):
    motor = _motor(http)
    nid, (d1, d2) = await _notificacion(http, h, datos, ["ENTREGADO", "ENTREGADO"])
    ev = _respuesta(datos, 1001, notificacion_destinatario_id=d1)
    # el destinatario indicado manda sobre el colaborador (aquí no coinciden, pero lo indicado gana)
    assert await consumidores.manejar_evento(motor, ev) is True
    assert _estados_d(datos, nid) == ["RESPONDIO", "ENTREGADO"]


@pytest.mark.parametrize("estado", ["PENDIENTE", "FALLIDO", "EXCLUIDO"])
async def test_sin_envio_reciente_la_respuesta_no_marca_nada(http, h, datos, estado):
    motor = _motor(http)
    nid, _ = await _notificacion(http, h, datos, [estado])
    assert await consumidores.manejar_evento(motor, _respuesta(datos, 1000)) is False
    assert _estados_d(datos, nid) == [estado]


async def test_una_respuesta_fuera_de_la_ventana_de_24_horas_no_marca(http, h, datos):
    motor = _motor(http)
    nid, (d,) = await _notificacion(http, h, datos, ["ENTREGADO"], estado="COMPLETADA")
    sql(
        datos,
        "UPDATE notificaciones.notificacion_destinatario "
        "SET fecha_estado = now() - interval '25 hours' WHERE id = %s",
        (d,),
    )
    assert await consumidores.manejar_evento(motor, _respuesta(datos, 1000)) is False
    assert _estados_d(datos, nid) == ["ENTREGADO"]


async def test_la_respuesta_de_otra_empresa_no_toca_los_destinatarios_ajenos(http, h, datos):
    motor = _motor(http)
    nid, _ = await _notificacion(http, h, datos, ["ENTREGADO"])
    ev = _respuesta(datos, 1000, empresa_id=datos["b"])
    assert await consumidores.manejar_evento(motor, ev) is False
    assert _estados_d(datos, nid) == ["ENTREGADO"]
    assert await consumidores.manejar_evento(motor, _respuesta(datos, None)) is False
    assert await consumidores.manejar_evento(motor, _respuesta(datos, "x")) is False
