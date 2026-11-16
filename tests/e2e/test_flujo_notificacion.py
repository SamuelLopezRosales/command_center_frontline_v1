"""T-218 (T-117): flujo completo de notificaciones por WhatsApp, de extremo a extremo, con el simulador
de Meta. Recorrido de design.md §0.5 con las piezas reales (ver ``ayudantes_e2e_notif.py``).

Qué es real: PostgreSQL 16 con RLS y roles de servicio, LocalStack (SQS, EventBridge, SNS, SES), los
servicios `campos`, `colaboradores`, `notificaciones` y `whatsapp` (chat de RH) como apps ASGI con el
cliente interno, el bot y el ``worker_entrada``, las Lambdas ``webhook_meta`` (firma válida),
``despachador``, ``enviador``, ``estados_entrega`` y ``respaldo_correo``, los relays del outbox y el
consumidor de ``ev-notificaciones``. Meta es el simulador (``services/whatsapp/tests/simulador_meta``).

Qué se simula: EventBridge Scheduler (``StubScheduler``: el cuerpo del schedule se entrega a mano a
``notif-despacho``, como lo haría Scheduler a la hora) y el tiempo de las piezas con horario (relojes
fijos); lo demás usa el reloj real y la base, que se mueve con SQL.

Comando: ``uv run pytest tests/e2e/test_flujo_notificacion.py -q``
"""

import os
import re

import pytest
from ayudantes_e2e import RAIZ, SIM
from ayudantes_e2e_notif import (
    BASE_CHAT,
    BASE_NOT,
    CELULARES,
    CORREOS,
    PROGRAMADA_PARA,
    mas_horas,
    wa_id,
)

pytestmark = pytest.mark.docker

RECORRIDO = RAIZ / "docs" / "recorrido_fase6.md"
CLAVES_SENSIBLES = (*CELULARES.values(), *CORREOS.values(), "Notif")


def wamid_de(w, nombre: str, tipo: str | None = "template") -> str:
    return w.meta_a(nombre, tipo)[-1]["wamid"]


async def estado_meta(w, nombre: str, estado: str, *, error: int | None = None, tipo="template"):
    await w.estado_meta(
        wamid_de(w, nombre, tipo), estado, destinatario=wa_id(CELULARES[nombre]), error=error
    )


async def programar(w, nid: int, emp=None):
    r = await w.confirmar(
        nid, emp, modo_envio="PROGRAMAR", programada_para="2026-11-17T14:00:00-06:00"
    )
    assert r.status_code == 202, r.text
    return r.json()


async def despachar_programada(w, nid: int):
    """Scheduler dispara a la hora: el despachador real y todo lo que sigue."""
    await w.disparar_schedule(f"cc-notif-{nid}", ahora=mas_horas(PROGRAMADA_PARA, 0.002))
    await w.bombear("Scheduler dispara el despacho")


async def lista_para_enviar(w, *, respaldo=True, nombre="aviso_cita"):
    pid = await w.plantilla_aprobada(nombre)
    nid = await w.crear_notificacion(pid, respaldo=respaldo)
    await w.revisar(nid)
    return pid, nid


def sin_datos_personales(texto: str) -> bool:
    return not any(c in texto for c in CLAVES_SENSIBLES) and not any(
        wa_id(c) in texto for c in CELULARES.values()
    )


# --------------------------------------------------------------------------- 1. camino feliz


async def test_camino_feliz_de_la_notificacion_hasta_el_chat_y_el_respaldo(mundo_notif, caplog):
    w = mundo_notif
    # --- 1. plantilla de mensaje: BORRADOR -> EN_REVISION -> APROBADA (simulador de Meta)
    pid = await w.plantilla_aprobada("aviso_cita")
    w.paso("Plantilla `aviso_cita`", "BORRADOR -> EN_REVISION (API de Meta simulada) -> APROBADA "
           "(`wa.plantilla_estado` por webhook firmado)")  # fmt: skip
    assert w.sim.plantillas["aviso_cita"]["status"] == "APPROVED"

    # --- 2. borrador y revisión (embudo)
    nid = await w.crear_notificacion(pid, respaldo=True)
    assert (await w.notificacion(nid))["estado"] == "BORRADOR"
    rev = await w.revisar(nid)
    assert rev["embudo"] == {
        "seleccionados": 5, "con_consentimiento": 4, "activos": 3, "celular_valido": 3,
    }  # fmt: skip
    assert rev["excluidos_por_motivo"] == {
        "SIN_CONSENTIMIENTO": 1, "ESTATUS_BAJA": 1, "SIN_CELULAR_VALIDO": 0,
    }  # fmt: skip
    d = w.destinatarios(nid)
    assert d["dario"][:2] == ("EXCLUIDO", "SIN_CONSENTIMIENTO")
    assert d["elena"][:2] == ("EXCLUIDO", "ESTATUS_BAJA")
    assert {d[n][0] for n in ("ana", "beto", "carla")} == {"PENDIENTE"}
    w.paso("Revisión (embudo)", "5 seleccionados -> 4 con consentimiento -> 3 activos -> 3 con celular "
           "válido; excluidos: 1 SIN_CONSENTIMIENTO y 1 ESTATUS_BAJA")  # fmt: skip

    # --- 3. programación: schedule único hacia notif-despacho
    n = await programar(w, nid)
    assert n["estado"] == "PROGRAMADA"
    s = w.scheduler_not.schedules[f"cc-notif-{nid}"]
    assert s.cuerpo == {"notificacion_id": nid, "tipo": "INICIO", "empresa_id": w.a.id}
    assert s.expresion == "at(2026-11-17T14:00:00)" and s.zona == "America/Mexico_City"
    assert w.sim.enviados == []  # nada sale antes de la hora
    w.paso(
        "Programación", f"PROGRAMADA para las 14:00 de Ciudad de México; schedule `cc-notif-{nid}`"
    )

    # --- 4. despacho: despachador -> wa-salida.fifo -> enviador -> Meta
    await despachar_programada(w, nid)
    assert w.estado_notificacion(nid) == "COMPLETADA"
    for quien in ("ana", "beto", "carla"):
        [envio] = w.meta_a(quien)
        assert envio["type"] == "template" and envio["template"]["name"] == "aviso_cita"
        params = [p["text"] for c in envio["template"]["components"] for p in c["parameters"]]
        assert params == [f"{quien.capitalize()} Notif Luna", "20 de noviembre"]
    assert w.meta_a("dario") == [] and w.meta_a("elena") == []  # sin consentimiento y baja: nada
    msgs = w.mensajes("NOTIFICACION")
    assert [(m[1], m[2], m[3], m[4]) for m in msgs] == [("ENVIADO", None, "PLANTILLA", 1)] * 3
    d = w.destinatarios(nid)
    assert {d[n][0] for n in ("ana", "beto", "carla")} == {"ENVIADO"}
    assert {d[n][3] for n in ("ana", "beto", "carla")} == {"WHATSAPP"}
    assert d["dario"][0] == d["elena"][0] == "EXCLUIDO"
    assert w.sql("SELECT fecha_envio IS NOT NULL FROM notificaciones.notificacion WHERE id = %s",
                 (nid,)) == [(True,)]  # fmt: skip
    assert f"cc-notif-respaldo-{nid}" in w.sched_lam.schedules  # el respaldo a las 24 horas
    w.paso("Despacho", "el despachador publica 3 mensajes en `wa-salida.fifo`; el enviador los manda a "
           "Meta; la notificación queda COMPLETADA (Darío y Elena no reciben nada)")  # fmt: skip

    # --- 5. estados de Meta: sent / delivered / read (estados-entrega real)
    await estado_meta(w, "ana", "sent")  # ya estaba ENVIADO: sin cambio
    await estado_meta(w, "beto", "delivered")
    await estado_meta(w, "carla", "delivered")
    await estado_meta(w, "carla", "read")
    d = w.destinatarios(nid)
    assert (d["ana"][0], d["beto"][0], d["carla"][0]) == ("ENVIADO", "ENTREGADO", "LEIDO")
    assert w.estado_notificacion(nid) == "COMPLETADA"  # entregar o leer no cambia el estado
    w.paso("Estados de Meta", "Ana `sent`, Beto `delivered`, Carla `delivered` y `read` -> ENVIADO, "
           "ENTREGADO y LEIDO")  # fmt: skip

    # --- 6. respuesta de Carla: el bot emite wa.respuesta_recibida y la notificación marca RESPONDIO
    await w.decir("Gracias, ahí estaré", wa_id=wa_id(CELULARES["carla"]))
    d = w.destinatarios(nid)
    assert d["carla"][0] == "RESPONDIO" and d["beto"][0] == "ENTREGADO"
    assert w.estado_notificacion(nid) == "COMPLETADA"
    [(conv_id, estado_conv, verificada, origen)] = w.sql(
        "SELECT id, estado, verificada, origen FROM whatsapp.conversacion_whatsapp "
        "WHERE empresa_id = %s", (w.a.id,))  # fmt: skip
    assert (estado_conv, verificada, origen) == ("ACTIVA", False, "NOTIFICACION")
    assert w.sql("SELECT conversacion_id FROM notificaciones.notificacion_destinatario "
                 "WHERE notificacion_id = %s AND colaborador_id = %s",
                 (nid, w.colaboradores["carla"])) == [(conv_id,)]  # fmt: skip
    [(evento,)] = w.sql("SELECT payload FROM whatsapp.outbox WHERE tipo = 'wa.respuesta_recibida'")
    assert set(evento) == {"empresa_id", "colaborador_id", "conversacion_id", "recibido_en"}
    w.paso("Respuesta", "Carla responde; el bot abre su conversación y emite `wa.respuesta_recibida` "
           "(solo ids); el destinatario pasa a RESPONDIO y queda ligado a la conversación")  # fmt: skip

    # --- 7. chat de RH (WAP): lista, hilo cifrado y respuesta con la ventana abierta
    r = await w.http_wa.get(BASE_CHAT, params={"notificacion_id": nid}, headers=w.rh_a)
    assert r.status_code == 200, r.text
    [item] = r.json()["items"]
    assert item["id"] == conv_id and item["ventana_abierta"] is True
    assert (
        item["colaborador_nombre"] == "Carla Notif Luna" and item["ultima_notificacion_id"] == nid
    )
    hilo = (await w.http_wa.get(f"{BASE_CHAT}/{conv_id}/mensajes", headers=w.rh_a)).json()["items"]
    assert [(m["direccion"], m["origen_tipo"], m["contenido"]) for m in hilo] == [
        ("ENTRANTE", "BOT", "Gracias, ahí estaré"), ("SALIENTE", "NOTIFICACION", None),
    ]  # fmt: skip
    [(blob,)] = w.sql("SELECT contenido_cifrado FROM whatsapp.mensaje_whatsapp "
                      "WHERE direccion = 'ENTRANTE' AND conversacion_id = %s", (conv_id,))  # fmt: skip
    assert b"ahi estare" not in bytes(blob).lower() and "ahí".encode() not in bytes(blob)
    texto_rh = "Perfecto, te esperamos puntual."
    r = await w.http_wa.post(
        f"{BASE_CHAT}/{conv_id}/mensajes", json={"texto": texto_rh}, headers=w.rh_a
    )
    assert r.status_code == 202, r.text
    await w.bombear("RH responde por el chat")
    [envio] = w.meta_a("carla", "text")
    assert envio["text"]["body"] == texto_rh
    [(mid, est, origen_msg, usuario)] = w.sql(
        "SELECT id, estado, origen_tipo, enviado_por_usuario_id FROM whatsapp.mensaje_whatsapp "
        "WHERE origen_tipo = 'CHAT'")  # fmt: skip
    assert (est, origen_msg, usuario) == ("ENVIADO", "CHAT", w.a.usuario_id)
    await w.estado_meta(envio["wamid"], "delivered", destinatario=wa_id(CELULARES["carla"]))
    assert w.sql("SELECT estado FROM whatsapp.mensaje_whatsapp WHERE id = %s", (mid,)) == [
        ("ENTREGADO",)
    ]
    hilo = (await w.http_wa.get(f"{BASE_CHAT}/{conv_id}/mensajes", headers=w.rh_a)).json()["items"]
    assert hilo[0]["contenido"] == texto_rh and hilo[0]["estado"] == "ENTREGADO"
    w.paso("Chat de RH", "RH ve la conversación (ventana abierta), lee la respuesta descifrada y le "
           "contesta; Meta recibe el texto y reporta `delivered`")  # fmt: skip

    # --- 8. con la ventana cerrada: texto libre da 409; una plantilla aprobada sí sale
    w.cerrar_ventana(conv_id)
    r = await w.http_wa.post(
        f"{BASE_CHAT}/{conv_id}/mensajes", json={"texto": "¿Sigues ahí?"}, headers=w.rh_a
    )
    assert r.status_code == 409 and r.json()["codigo"] == "VENTANA_24H_CERRADA"
    assert (await w.http_wa.get(BASE_CHAT, headers=w.rh_a)).json()["items"][0][
        "ventana_abierta"
    ] is False
    r = await w.http_wa.post(
        f"{BASE_CHAT}/{conv_id}/mensajes/plantilla",
        json={"plantilla_mensaje_id": pid, "variables": ["Carla", "viernes"]}, headers=w.rh_a,
    )  # fmt: skip
    assert r.status_code == 202, r.text
    await w.bombear("RH envía una plantilla con la ventana cerrada")
    assert len(w.meta_a("carla", "template")) == 2 and len(w.meta_a("carla", "text")) == 1
    assert w.sql("SELECT estado, tipo FROM whatsapp.mensaje_whatsapp WHERE origen_tipo = 'CHAT' "
                 "ORDER BY id") == [("ENTREGADO", "TEXTO"), ("ENVIADO", "PLANTILLA")]  # fmt: skip
    w.paso("Ventana de 24 horas", "cerrada: texto libre -> 409 `VENTANA_24H_CERRADA`; plantilla aprobada "
           "-> 202 y Meta la recibe")  # fmt: skip

    # --- 9. respaldo por correo a las 24 horas: solo quien no recibió (Ana)
    assert w.correos_enviados() == []
    await w.disparar_respaldo(nid, ahora=mas_horas(PROGRAMADA_PARA, 25))
    await w.bombear("respaldo por correo a las 24 horas")
    [correo] = w.correos_enviados()
    assert correo["Destination"]["ToAddresses"] == [CORREOS["ana"]]
    cuerpo_correo = correo["Body"]["text_part"]
    assert "Hola Ana Notif Luna, tu cita es el 20 de noviembre." in cuerpo_correo
    d = w.destinatarios(nid)
    assert d["ana"][0] == "ENVIADO" and d["ana"][3] == "CORREO"  # el correo no es una entrega
    assert (d["beto"][3], d["carla"][3]) == ("WHATSAPP", "WHATSAPP")
    assert w.sql("SELECT respaldo_enviado_en IS NOT NULL FROM notificaciones.notificacion_destinatario "
                 "WHERE notificacion_id = %s AND colaborador_id = %s",
                 (nid, w.colaboradores["ana"])) == [(True,)]  # fmt: skip
    await w.disparar_respaldo(nid, ahora=mas_horas(PROGRAMADA_PARA, 26))  # repetir no reenvía
    await w.bombear("el mismo respaldo se repite")
    assert len(w.correos_enviados()) == 1
    w.paso("Respaldo por correo", "a las 24 horas solo Ana (ENVIADO) recibe el correo por SES; Beto "
           "(ENTREGADO) y Carla (RESPONDIO) no; repetir el mensaje no reenvía")  # fmt: skip

    # --- 10. ningún dato personal en los logs capturados
    assert sin_datos_personales(caplog.text), "datos personales en los logs"
    assert "Ahí estaré" not in caplog.text and texto_rh not in caplog.text

    # --- 11. recorrido grabado para el punto de control T-118
    if not os.environ.get("CC_E2E_SIN_RECORRIDO"):
        escribir_recorrido(w, nid=nid, conv_id=conv_id)


def escribir_recorrido(w, *, nid: int, conv_id: int) -> None:
    """Transcripción legible del recorrido (sin celular completo, código, token ni contenido)."""
    L = [
        "# Recorrido grabado de la Fase 6: notificación por WhatsApp (T-218, punto de control T-118)",
        "",
        "Generado por `tests/e2e/test_flujo_notificacion.py::"
        "test_camino_feliz_de_la_notificacion_hasta_el_chat_y_el_respaldo`.",
        "Para regenerarlo: `uv run pytest tests/e2e/test_flujo_notificacion.py -q -k camino_feliz`.",
        "Los tiempos cambian en cada corrida.",
        "",
        "Piezas reales: PostgreSQL 16 (RLS y roles de servicio), LocalStack (SQS, EventBridge, SNS, SES),",
        "servicios `campos`, `colaboradores`, `notificaciones` y `whatsapp` (chat de RH) como apps ASGI con",
        "token interno, bot y `worker_entrada`, Lambdas `webhook-meta`, `despachador`, `enviador`,",
        "`estados-entrega` y `respaldo-correo`, relays del outbox y consumidor de `ev-notificaciones`.",
        "Meta: simulador (`services/whatsapp/tests/simulador_meta`). Simulado: EventBridge Scheduler",
        "(`StubScheduler`; el cuerpo del schedule se entrega a mano a `notif-despacho`) y los relojes de las",
        "piezas con horario. Los números se muestran como `…NNNN`, el nombre del colaborador en las",
        "plantillas como `<nombre>` (los de los pasos son ficticios) y no se incluye ningún correo, código ni token.",
        "",
        "## Pasos",
        "",
        "| # | Paso | Qué ocurrió |",
        "|---|---|---|",
    ]
    for i, (titulo, detalle) in enumerate(w.relato, 1):
        L.append(f"| {i} | {titulo} | {detalle.replace('|', '/')} |")
    L += [
        "",
        "## Conversación con el colaborador (lo que Meta entregó y lo que él escribió)",
        "",
        "| # | Quién | Mensaje |",
        "|---|---|---|",
    ]
    for i, (quien, texto) in enumerate(w.transcripcion, 1):
        L.append(f"| {i} | {quien} | {texto.replace('|', '/')} |")
    L += ["", "## Tiempos del bombeo", "", "| Paso | Tiempo (s) |", "|---|---|"]
    L += [f"| {et} | {t:.2f} |" for et, t in w.tiempos]
    acumulado: dict[str, int] = {}
    for nombre, n in w.pasos:
        acumulado[nombre] = acumulado.get(nombre, 0) + n
    L += ["", "Trabajo hecho por pieza en el bombeo (acumulado):", ""]
    L += [f"- {nombre}: {n}" for nombre, n in acumulado.items()]
    d = w.destinatarios(nid)
    L += [
        "",
        "## Estado final",
        "",
        f"- Notificación {nid}: `{w.estado_notificacion(nid)}`.",
        "- Destinatarios:",
    ]
    for nombre in ("ana", "beto", "carla", "dario", "elena"):
        estado, motivo_ex, motivo_fallo, canal = d[nombre]
        extra = f", motivo `{motivo_ex}`" if motivo_ex else ""
        extra += f", canal `{canal}`" if canal else ""
        L.append(f"  - {nombre.capitalize()}: `{estado}`{extra}.")
    L += [
        f"- Conversación {conv_id}: `ACTIVA`, no verificada, origen `NOTIFICACION`; ventana de 24 horas "
        "cerrada a propósito para probar el 409.",
        "- Mensajes del chat de RH (tabla `mensaje_whatsapp`, contenido cifrado en la base):",
    ]
    for _id, estado, error, tipo, intentos, _p in w.mensajes("CHAT"):
        L.append(f"  - {tipo}, estado `{estado}`, intentos {intentos}, error {error or 'ninguno'}.")
    L += [
        "- Correos de respaldo en SES (LocalStack): 1 (solo a quien no recibió el WhatsApp).",
        f"- Mensajes enviados por Meta: {len(w.sim.enviados)}.",
        "",
    ]
    RECORRIDO.write_text("\n".join(L), encoding="utf-8")


# --------------------------------------------------------------------------- 2. fallas y reintento


async def test_con_fallas_el_reintento_envia_solo_al_fallido_y_no_repite_al_que_ya_recibio(
    mundo_notif,
):
    w = mundo_notif
    w.fallo_envio = lambda c: SIM.ERROR_SERVIDOR if c["to"] == "52" + CELULARES["carla"] else None
    pid, nid = await lista_para_enviar(w, respaldo=False)
    r = await w.confirmar(nid, modo_envio="AHORA")  # NOT-19: escribe el mensaje de despacho
    assert r.status_code == 202 and r.json()["estado"] == "ENVIANDO", r.text
    await w.bombear("despacho inmediato con un envío que falla")

    # Carla: Meta responde 503 tres veces (3 recepciones) y queda FALLIDA; el resto salió
    assert w.estado_notificacion(nid) == "CON_FALLAS"
    d = w.destinatarios(nid)
    assert (d["ana"][0], d["beto"][0], d["carla"][0]) == ("ENVIADO", "ENVIADO", "FALLIDO")
    assert d["carla"][2] == "INTENTOS_AGOTADOS"
    assert w.meta_a("carla") == [] and len(w.reintentos_pedidos) == 2  # esperas de SQS pedidas
    await estado_meta(w, "ana", "delivered")
    await estado_meta(w, "beto", "delivered")
    assert w.estado_notificacion(nid) == "CON_FALLAS"

    # NOT-22: Meta ya responde; solo se reintenta a Carla (un mensaje nuevo, otra "ronda")
    w.fallo_envio = None
    r = await w.http_not.post(f"{BASE_NOT}/{nid}/reintentar", json={}, headers=w.rh_a)
    assert r.status_code == 202 and r.json()["estado"] == "ENVIANDO", r.text
    await w.bombear("reintento de los fallidos")
    assert w.estado_notificacion(nid) == "COMPLETADA"
    d = w.destinatarios(nid)
    assert (d["ana"][0], d["beto"][0], d["carla"][0]) == ("ENTREGADO", "ENTREGADO", "ENVIADO")
    assert len(w.meta_a("ana")) == 1 and len(w.meta_a("beto")) == 1  # NO reciben otra vez
    assert len(w.meta_a("carla")) == 1
    filas = w.sql(
        "SELECT estado, error_codigo FROM whatsapp.mensaje_whatsapp WHERE colaborador_id = %s "
        "AND origen_tipo = 'NOTIFICACION' ORDER BY id", (w.colaboradores["carla"],))  # fmt: skip
    assert filas == [("FALLIDO", "INTENTOS_AGOTADOS"), ("ENVIADO", None)]
    # ya no hay nada que reintentar
    r = await w.http_not.post(f"{BASE_NOT}/{nid}/reintentar", json={}, headers=w.rh_a)
    assert r.status_code == 409 and r.json()["codigo"] == "ESTADO_INVALIDO"


async def test_un_failed_tardio_de_meta_reabre_la_notificacion_como_con_fallas(mundo_notif):
    w = mundo_notif
    _pid, nid = await lista_para_enviar(w, respaldo=False)
    assert (await w.confirmar(nid, modo_envio="AHORA")).status_code == 202
    await w.bombear("despacho inmediato")
    assert w.estado_notificacion(nid) == "COMPLETADA"
    await estado_meta(w, "beto", "failed", error=131026)  # Meta acepta y rechaza después
    d = w.destinatarios(nid)
    assert d["beto"][0] == "FALLIDO" and d["beto"][2] == "NUMERO_INVALIDO"
    assert w.estado_notificacion(nid) == "CON_FALLAS"
    estados = {m[1] for m in w.mensajes("NOTIFICACION")}
    assert estados == {"ENVIADO", "FALLIDO"}


async def test_baja_y_revocacion_despues_de_revisar_no_reciben_y_no_se_reintentan(mundo_notif):
    w = mundo_notif
    _pid, nid = await lista_para_enviar(w, respaldo=False)
    assert (await w.confirmar(nid, modo_envio="AHORA")).status_code == 202
    # cambian las condiciones entre la revisión y el despacho
    r = await w.http_col.post(
        f"/api/v1/colaboradores/{w.colaboradores['ana']}/baja",
        json={"fecha_baja": "2026-11-16"}, headers=w.rh_a,
    )  # fmt: skip
    assert r.status_code == 200, r.text
    r = await w.http_col.put(
        f"/api/v1/colaboradores/{w.colaboradores['beto']}/consentimiento",
        json={"otorgado": False}, headers=w.rh_a,
    )  # fmt: skip
    assert r.status_code == 200, r.text
    await w.bombear("despacho tras la baja y la revocación")
    assert w.meta_a("ana") == [] and w.meta_a("beto") == []  # el enviador no les manda nada
    assert len(w.meta_a("carla")) == 1
    d = w.destinatarios(nid)
    # el motivo de INT-COL-05 es "BAJA" (el de la revisión, EXCLUIDO, es "ESTATUS_BAJA"): ver informe
    assert (d["ana"][0], d["ana"][2]) == ("FALLIDO", "BAJA")
    assert (d["beto"][0], d["beto"][2]) == ("FALLIDO", "SIN_CONSENTIMIENTO")
    assert d["carla"][0] == "ENVIADO"
    assert w.estado_notificacion(nid) == "CON_FALLAS"
    # ninguno de los dos es elegible hoy: NOT-22 no los reintenta
    r = await w.http_not.post(f"{BASE_NOT}/{nid}/reintentar", json={}, headers=w.rh_a)
    assert r.status_code == 422 and r.json()["codigo"] == "SIN_FALLIDOS_REINTENTABLES", r.text
    assert w.meta_a("ana") == [] and w.meta_a("beto") == []


# --------------------------------------------------------------------------- 3. respaldo


async def test_respaldo_sin_correo_marca_fallido_y_avisa_a_rh_sin_datos_personales(mundo_notif):
    from ayudantes_e2e_notif import _alta

    w = mundo_notif
    # Fabio recibe el WhatsApp pero no tiene correo registrado
    w.colaboradores["fabio"] = await _alta(
        w, w.a, "fabio", "8111110006", planta=w.planta_notif, correo=None
    )
    _pid, nid = await lista_para_enviar(w, respaldo=True)
    assert (await w.confirmar(nid, modo_envio="AHORA")).status_code == 202
    await w.bombear("despacho inmediato")
    await w.disparar_respaldo(nid, ahora=mas_horas(w.reloj_lam.ahora, 25))
    await w.bombear("respaldo a las 24 horas")
    assert sorted(m["Destination"]["ToAddresses"][0] for m in w.correos_enviados()) == sorted(
        CORREOS.values()
    )
    d = w.destinatarios(nid)
    assert d["fabio"][0] == "FALLIDO" and d["fabio"][2] == "SIN_CORREO"
    alertas = await w.alertas_rh(esperar=1, tipo="RESPALDO_SIN_CORREO")
    assert alertas[0]["notificacion_id"] == nid and alertas[0]["motivos"] == {"SIN_CORREO": 1}
    assert "8111110006" not in str(alertas) and "Fabio" not in str(alertas)


# --------------------------------------------------------------------------- 4. respuestas


async def test_numero_no_registrado_y_mensaje_repetido_no_ensucian_las_respuestas(mundo_notif):
    w = mundo_notif
    _pid, nid = await lista_para_enviar(w, respaldo=False)
    assert (await w.confirmar(nid, modo_envio="AHORA")).status_code == 202
    await w.bombear("despacho inmediato")
    # un número que no es de ningún colaborador: el bot lo ignora y no emite el evento
    await w.decir("hola", wa_id="5219999999999")
    assert w.publicados.get("EVENTBRIDGE:wa.respuesta_recibida") is None
    assert w.sql("SELECT count(*) FROM whatsapp.outbox WHERE tipo = 'wa.respuesta_recibida'") == [
        (0,)
    ]
    # el mismo wamid dos veces (SQS entrega al menos una vez): un solo evento y un solo RESPONDIO
    wa = wa_id(CELULARES["beto"])
    for _ in range(2):
        w.webhook(w.sim.mensaje_entrante(wa, "Enterado", wamid="wamid.REPETIDO1"))
        await w.bombear("el colaborador responde (repetido)")
    assert w.sql("SELECT count(*) FROM whatsapp.outbox WHERE tipo = 'wa.respuesta_recibida'") == [
        (1,)
    ]
    assert w.destinatarios(nid)["beto"][0] == "RESPONDIO"
    assert w.sql("SELECT count(*) FROM whatsapp.conversacion_whatsapp") == [(1,)]
    # quien no recibió ninguna notificación (Darío, excluido) y escribe: sin conversación ni RESPONDIO
    await w.decir("hola", wa_id=wa_id(CELULARES["dario"]))
    assert w.destinatarios(nid)["dario"][0] == "EXCLUIDO"
    assert w.sql("SELECT count(*) FROM whatsapp.conversacion_whatsapp") == [(1,)]


# --------------------------------------------------------------------------- 5. aislamiento


async def test_el_flujo_de_una_empresa_no_toca_los_datos_de_la_otra(mundo_notif):
    w = mundo_notif
    _pid, nid = await lista_para_enviar(w, respaldo=False)
    assert (await w.confirmar(nid, modo_envio="AHORA")).status_code == 202
    await w.bombear("despacho de la empresa A")
    await w.decir("Gracias", wa_id=wa_id(CELULARES["ana"]))
    [(conv_a,)] = w.sql("SELECT id FROM whatsapp.conversacion_whatsapp WHERE empresa_id = %s",
                        (w.a.id,))  # fmt: skip

    # la empresa B hace su propio flujo completo con su propia colaboradora
    pid_b = await w.plantilla_aprobada("aviso_cita_b", w.b)
    nid_b = await w.crear_notificacion(pid_b, emp=w.b, planta=w.planta_notif_b, respaldo=False)
    rev_b = await w.revisar(nid_b, w.b)
    assert rev_b["embudo"]["seleccionados"] == 1
    assert (await w.confirmar(nid_b, w.b, modo_envio="AHORA")).status_code == 202
    await w.bombear("despacho de la empresa B")
    assert w.estado_notificacion(nid_b) == "COMPLETADA"
    destino_b = "52" + "8199990001"
    assert [e["to"] for e in w.sim.enviados if e["to"] == destino_b] == [destino_b]
    assert w.sql("SELECT empresa_id, count(*) FROM whatsapp.mensaje_whatsapp WHERE origen_tipo = "
                 "'NOTIFICACION' GROUP BY empresa_id ORDER BY empresa_id") == [(w.a.id, 3), (w.b.id, 1)]  # fmt: skip

    # B no ve ni toca lo de A: notificaciones, destinatarios, plantillas, conversaciones y chat
    for ruta in (f"{BASE_NOT}/{nid}", f"{BASE_NOT}/{nid}/destinatarios"):
        assert (await w.http_not.get(ruta, headers=w.rh_b)).status_code == 404, ruta
    assert (await w.http_not.post(f"{BASE_NOT}/{nid}/revisar", headers=w.rh_b)).status_code == 404
    assert (await w.http_wa.get(BASE_CHAT, headers=w.rh_b)).json()["items"] == []
    assert (
        await w.http_wa.get(f"{BASE_CHAT}/{conv_a}/mensajes", headers=w.rh_b)
    ).status_code == 404
    r = await w.http_wa.post(
        f"{BASE_CHAT}/{conv_a}/mensajes", json={"texto": "hola"}, headers=w.rh_b
    )
    assert r.status_code == 404
    r = await w.http_wa.put(
        f"{BASE_CHAT}/{conv_a}/asignacion", json={"usuario_id": w.b.usuario_id}, headers=w.rh_b
    )
    assert r.status_code == 404
    # una plantilla de A no sirve a B en el chat (INT-NOT-01 la busca en la empresa del token)
    # y una asignación a un usuario de otra empresa se rechaza
    r = await w.http_wa.put(
        f"{BASE_CHAT}/{conv_a}/asignacion", json={"usuario_id": w.b.usuario_id}, headers=w.rh_a
    )
    assert r.status_code == 422 and r.json()["codigo"] == "USUARIO_NO_ENCONTRADO"
    r = await w.http_wa.put(
        f"{BASE_CHAT}/{conv_a}/asignacion", json={"usuario_id": w.a.usuario_id}, headers=w.rh_a
    )
    assert r.status_code == 200 and r.json()["asignada_a_usuario_id"] == w.a.usuario_id
    # el estado de A no cambió por lo de B
    assert w.estado_notificacion(nid) == "COMPLETADA"
    assert len(w.meta_a("ana")) == 1


# --------------------------------------------------------------------------- 6. datos sensibles


async def test_la_base_no_guarda_texto_de_rh_ni_de_respuestas_en_claro(mundo_notif):
    w = mundo_notif
    _pid, nid = await lista_para_enviar(w, respaldo=False)
    assert (await w.confirmar(nid, modo_envio="AHORA")).status_code == 202
    await w.bombear("despacho inmediato")
    respuesta = "Confirmo mi asistencia a la cita"
    await w.decir(respuesta, wa_id=wa_id(CELULARES["carla"]))
    [(conv_id,)] = w.sql("SELECT id FROM whatsapp.conversacion_whatsapp")
    texto_rh = "Te esperamos con tu identificación"
    r = await w.http_wa.post(
        f"{BASE_CHAT}/{conv_id}/mensajes", json={"texto": texto_rh}, headers=w.rh_a
    )
    assert r.status_code == 202
    await w.bombear("RH responde")
    # nada de lo que se guarda en las tablas de negocio, la bitácora o los eventos lleva el texto;
    # el ``outbox`` de salida conserva el mensaje tal cual (defecto conocido, ver el xfail siguiente)
    volcado = "\n".join(
        linea for linea in w.volcado_de_la_base(("whatsapp", "notificaciones", "auditoria",
                                                 "colaboradores")).splitlines()
        if ".outbox:" not in linea[:40]
    )  # fmt: skip
    assert respuesta not in volcado and texto_rh not in volcado
    assert re.search(r"CHAT", volcado)  # el registro del mensaje sí existe


@pytest.mark.xfail(
    strict=True,
    reason="Defecto conocido (mismo que el código y el token): el texto que RH escribe en el chat viaja "
    "en claro en whatsapp.outbox.payload (el `enviador` no descifra) y la fila se conserva tras "
    "publicarse; en la tabla mensaje_whatsapp sí va cifrado. Falta vaciar el texto al publicar.",
)
async def test_el_texto_del_chat_no_queda_en_claro_en_el_outbox(mundo_notif):
    w = mundo_notif
    _pid, nid = await lista_para_enviar(w, respaldo=False)
    assert (await w.confirmar(nid, modo_envio="AHORA")).status_code == 202
    await w.bombear("despacho inmediato")
    await w.decir("Gracias", wa_id=wa_id(CELULARES["carla"]))
    [(conv_id,)] = w.sql("SELECT id FROM whatsapp.conversacion_whatsapp")
    texto_rh = "Te esperamos con tu identificación"
    await w.http_wa.post(
        f"{BASE_CHAT}/{conv_id}/mensajes", json={"texto": texto_rh}, headers=w.rh_a
    )
    await w.bombear("RH responde")
    assert texto_rh not in str(w.sql("SELECT payload FROM whatsapp.outbox"))
