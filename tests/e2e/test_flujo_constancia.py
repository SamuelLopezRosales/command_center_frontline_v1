"""T-214 (T-103, T-104): solicitud de constancia por WhatsApp, de extremo a extremo, con el
simulador de Meta. Cada pieza real, conectada con las demás (ver ``ayudantes_e2e.py``).

Qué es real: PostgreSQL 16 con RLS y roles de servicio, LocalStack (SQS, EventBridge, SNS y S3 con
Object Lock), los servicios ``campos``, ``colaboradores``, ``constancias`` y ``dashboard`` como apps
ASGI que se llaman con el cliente interno, el bot y el ``worker_entrada``, las Lambdas
``webhook_meta`` (firma HMAC válida), ``enviador`` y ``estados_entrega``, el ``worker_pdf``, los relays
del outbox y el consumidor de eventos de ``constancias``. Meta es el simulador de
``services/whatsapp/tests/simulador_meta``.

Qué NO es real en Windows: el renderizador de PDF. WeasyPrint necesita Pango, que Windows no tiene;
igual que ``test_worker_pdf.py``, se inyecta un renderizador (``FalsoPdf``) y el "PDF" es el HTML
de la constancia con una cabecera. Las aserciones que necesitan un PDF real
(``test_con_pdf_real_de_weasyprint``) llevan el marcador ``pdf``: se omiten donde WeasyPrint no
carga y corren donde sí (Linux o contenedor con Pango; además necesitan Docker para la base).

Comando: ``uv run pytest tests/e2e -q``
"""

import hashlib
import os
import re

import pytest
from ayudantes_e2e import (
    CELULAR_A,
    NSS_A,
    NSS_B,
    RAIZ,
    SIM,
    WA_ID_A,
    WA_ID_B,
    cerrar_mundo,
    construir_mundo,
    texto_de,
)
from cc_whatsapp.bot import mensajes_es as M
from cc_whatsapp.bot.contexto import Mensaje
from cc_whatsapp.bot.conversacion import procesar

pytestmark = pytest.mark.docker

FOLIO = re.compile(r"CG-\d{4}-0001")
RECORRIDO = RAIZ / "docs" / "recorrido_fase5.md"


# --------------------------------------------------------------------------- ayudantes del flujo


async def solicitar(w, *, nss: str = NSS_A, dato: str | None = None):
    """Palabra clave y respuesta con el código y el dato adicional (verificación correcta)."""
    await w.decir("constancia")
    await w.decir(f"{w.codigo_recibido()} {dato or nss[-4:]}")


async def entregada(w, estado: str = "delivered"):
    """Meta reporta el estado del mensaje con el enlace."""
    await w.estado_meta(w.wamid_del_enlace(), estado)


def conversacion(w, empresa_id=None):
    return w.sql(
        "SELECT estado, verificada, intentos_verificacion, solicitud_constancia_id, "
        "bloqueada_hasta FROM whatsapp.conversacion_whatsapp WHERE empresa_id = %s ORDER BY id "
        "DESC LIMIT 1",
        (empresa_id or w.a.id,),
    )[0]


def sin_datos_personales(texto: str, w) -> bool:
    return not any(
        s in texto for s in ("Ana", "Pérez", "Luna", CELULAR_A, WA_ID_A, NSS_A, "E-" + str(w.a.id))
    )


# --------------------------------------------------------------------------- 1. camino feliz


async def test_camino_feliz_de_la_constancia_hasta_entregada(mundo, caplog):
    w = mundo
    # --- 1. "constancia": aviso de privacidad primero y después el código con su desafío
    await w.decir("constancia")
    aviso, codigo_msg = w.textos()
    assert aviso == M.aviso_privacidad("https://cc.e2e.test/privacidad")
    assert "los últimos 4 dígitos de tu NSS" in codigo_msg
    codigo = w.codigo_recibido()
    assert conversacion(w)[:3] == ("VERIFICANDO", False, 0)
    [(hmac_guardado,)] = w.sql("SELECT codigo_hmac FROM whatsapp.codigo_verificacion")
    assert codigo.encode() not in bytes(hmac_guardado)

    # --- 2. código + dato adicional: verificado, plantilla única usada directo, PDF y enlace
    await w.decir(f"{codigo} {NSS_A[-4:]}")
    est, verificada, intentos, solicitud_abierta, _ = conversacion(w)
    assert (est, verificada, intentos, solicitud_abierta) == ("ACTIVA", True, 0, None)
    textos = w.textos()
    assert textos[2] == M.PREPARANDO
    enlace = w.enlace_recibido()
    assert re.search(r"Tu constancia CG-\d{4}-0001 está lista", textos[3])

    [(sid, estado_sol, motivo)] = w.estado_solicitud()
    [(cid, folio, entrega, _tiene_fecha, sid_c)] = w.estado_constancia()
    assert (estado_sol, motivo, entrega, sid_c) == ("GENERADA", None, "PENDIENTE", sid)
    assert FOLIO.fullmatch(folio)

    # worker-pdf: objeto en el bucket de constancias (Object Lock), hash y snapshot
    [(clave, huella, snapshot)] = w.sql(
        "SELECT pdf_s3_key, pdf_hash_sha256, datos_snapshot_json FROM constancias.constancia_generada"
    )
    objeto = w.aws.s3.get_object(Bucket=w.aws.bucket_constancias, Key=clave)
    cuerpo = objeto["Body"].read()
    assert hashlib.sha256(cuerpo).hexdigest() == huella
    assert objeto["ObjectLockMode"] == "GOVERNANCE"
    assert folio.encode() in cuerpo and "Ana Pérez Luna".encode() in cuerpo
    assert clave == f"constancias/{w.a.id}/{folio[3:7]}/{folio}.pdf"
    assert snapshot["valores"]["nombre_completo"] == "Ana Pérez Luna"
    assert NSS_A not in str(snapshot) and "cifrado" in snapshot["valores"]["nss"]  # sensible
    [(token_hash, generado_por)] = w.sql(
        "SELECT token_hash, generado_por FROM constancias.token_descarga"
    )
    token = enlace.rsplit("/", 1)[1]
    assert (bytes(token_hash), generado_por) == (hashlib.sha256(token.encode()).digest(), "BOT")

    # enviador: mensaje con el enlace, enviado por la API simulada y registrado
    [(_, est_msg, error, tipo_msg, intentos_msg, wamid)] = w.mensajes("CONSTANCIA")
    assert (est_msg, error, tipo_msg, intentos_msg) == ("ENVIADO", None, "TEXTO", 1)
    assert wamid == w.wamid_del_enlace()
    envio_meta = next(e for e in w.sim.enviados if e["wamid"] == wamid)
    assert envio_meta["to"] == "52" + CELULAR_A and envio_meta["text"]["preview_url"] is False

    # --- 3. Meta: delivered (y estados desordenados: sent tardío, read) -> estados-entrega -> ENTREGADA
    await w.estado_meta(wamid, "delivered")
    await w.estado_meta(wamid, "sent")  # tardío: no retrocede
    assert w.mensajes("CONSTANCIA")[0][1] == "ENTREGADO"
    assert w.estado_constancia()[0][2:4] == ("ENTREGADA", True)
    assert w.estado_solicitud()[0][1:] == ("ENTREGADA", None)
    await w.estado_meta(wamid, "read")
    assert w.mensajes("CONSTANCIA")[0][1] == "LEIDO"
    assert w.estado_constancia()[0][2] == "ENTREGADA"  # leído no cambia la entrega

    # --- 4. el enlace funciona UNA vez (consumirlo es el POST; abrir la página no lo gasta)
    pagina = await w.http_con.get(f"/d/{token}")
    assert pagina.status_code == 200 and "Descargar constancia" in pagina.text
    assert (await w.http_con.get(f"/d/{token}")).status_code == 200
    primera = await w.http_con.post(f"/d/{token}/descargar")
    assert primera.status_code == 302 and clave in primera.headers["location"]
    segunda = await w.http_con.post(f"/d/{token}/descargar")
    assert segunda.status_code == 410 and segunda.json()["codigo"] == "ENLACE_NO_VIGENTE"
    assert (await w.http_con.get(f"/d/{token}")).status_code == 410

    # --- 5. ningún secreto en los logs capturados
    log = caplog.text
    assert codigo not in log, "el código de verificación apareció en los logs"
    assert token not in log, "el token del enlace apareció en los logs"
    for secreto in (WA_ID_A, CELULAR_A, NSS_A, "Ana Pérez"):
        assert secreto not in log

    # --- 6. recorrido grabado para el punto de control T-104
    if not os.environ.get("CC_E2E_SIN_RECORRIDO"):
        escribir_recorrido(w, folio=folio, clave=clave, huella=huella, sid=sid, cid=cid)


def escribir_recorrido(w, *, folio, clave, huella, sid, cid) -> None:
    """Transcripción legible del recorrido (sin celular completo, código, token ni valores)."""
    L = [
        "# Recorrido grabado de la Fase 5: constancia por WhatsApp (T-214, punto de control T-104)",
        "",
        "Generado por `tests/e2e/test_flujo_constancia.py::test_camino_feliz_de_la_constancia_hasta_entregada`.",
        "Para regenerarlo: `uv run pytest tests/e2e -q -k camino_feliz`. Los tiempos cambian en cada corrida.",
        "",
        "Piezas reales: PostgreSQL 16 (RLS y roles de servicio), LocalStack (SQS, EventBridge, SNS, S3 con",
        "Object Lock), servicios `campos`, `colaboradores`, `constancias` y `dashboard` (ASGI con token interno),",
        "bot y `worker_entrada`, Lambdas `webhook-meta`, `enviador` y `estados-entrega`, `worker-pdf`, relays",
        "del outbox y consumidor de eventos. Meta: simulador (`services/whatsapp/tests/simulador_meta`).",
        "Limitación: en Windows el renderizador de PDF se inyecta (WeasyPrint no carga sin Pango); el PDF",
        "real se prueba con el marcador `pdf`. Los secretos se muestran como `***` y los números como `…NNNN`.",
        "",
        "## Conversación (colaborador y bot)",
        "",
        "| # | Quién | Mensaje |",
        "|---|---|---|",
    ]
    for i, (quien, texto) in enumerate(w.transcripcion, 1):
        L.append(f"| {i} | {quien} | {texto.replace('|', '/')} |")
    L += ["", "## Pasos y tiempos", "", "| Paso | Tiempo (s) |", "|---|---|"]
    L += [f"| {et} | {t:.2f} |" for et, t in w.tiempos]
    L += ["", "Trabajo hecho por pieza en el bombeo (acumulado):", ""]
    acumulado: dict[str, int] = {}
    for nombre, n in w.pasos:
        acumulado[nombre] = acumulado.get(nombre, 0) + n
    L += [f"- {nombre}: {n}" for nombre, n in acumulado.items()]
    solicitud = w.estado_solicitud()[0]
    constancia = w.estado_constancia()[0]
    L += [
        "",
        "## Estado final",
        "",
        f"- Solicitud {sid}: `{solicitud[1]}` (motivo: {solicitud[2] or 'ninguno'}).",
        f"- Constancia {cid}: folio `{folio}`, entrega `{constancia[2]}`.",
        f"- Objeto en S3 (bucket de constancias con Object Lock, modo GOVERNANCE): `{clave}`.",
        f"- Huella SHA-256 del PDF: `{huella[:16]}…`.",
        "- Enlace de un solo uso: la primera descarga redirige (302) y la segunda responde 410 `ENLACE_NO_VIGENTE`.",
        "- Mensajes de la constancia (tabla `mensaje_whatsapp`):",
    ]
    for _id, estado, error, tipo, intentos, _wamid in w.mensajes("CONSTANCIA"):
        L.append(f"  - {tipo}, estado `{estado}`, intentos {intentos}, error {error or 'ninguno'}.")
    conv = conversacion(w)
    L += [
        f"- Conversación: estado `{conv[0]}`, verificada: {conv[1]}, intentos de verificación: {conv[2]}.",
        f"- Mensajes enviados por Meta al colaborador: {len(w.recibidos())}.",
        "",
    ]
    RECORRIDO.write_text("\n".join(L), encoding="utf-8")


async def test_con_varias_plantillas_se_ofrece_la_lista_y_se_usa_la_elegida(
    mundo_varias_plantillas,
):
    w = mundo_varias_plantillas
    await solicitar(w)
    lista = [e for e in w.recibidos() if e["type"] == "interactive"]
    assert len(lista) == 1
    filas = lista[0]["interactive"]["action"]["sections"][0]["rows"]
    ids = {f["id"] for f in filas}
    assert ids == {f"plantilla:{p}" for p in w.a.plantillas.values()}
    assert w.estado_solicitud()[0][1] == "RECIBIDA"  # abierta, aún sin plantilla
    assert conversacion(w)[3] is not None

    elegida = w.a.plantillas["Constancia 2"]
    await w.elegir(f"plantilla:{elegida}")
    assert w.estado_solicitud()[0][1] == "GENERADA"
    [(plantilla_usada,)] = w.sql(
        "SELECT v.plantilla_id FROM constancias.solicitud_constancia s "
        "JOIN constancias.version_plantilla v ON v.id = s.version_plantilla_id"
    )
    assert plantilla_usada == elegida
    assert M.PREPARANDO in w.textos() and FOLIO.search(w.textos()[-1])


# --------------------------------------------------------------------------- 2. casos de §7.4


async def test_numero_no_registrado_recibe_sin_acceso_y_queda_solo_el_hash(mundo):
    w = mundo
    desconocido = "5219999999999"
    await w.decir("constancia", wa_id=desconocido)
    assert w.textos(desconocido) == [M.SIN_ACCESO]
    bitacora = w.sql(
        "SELECT origen, detalle FROM auditoria.bitacora WHERE accion = 'INTENTO_WHATSAPP'"
    )
    assert bitacora[0][0] == "SISTEMA" and bitacora[0][1]["motivo"] == "NO_REGISTRADO"
    assert desconocido not in str(bitacora) and "9999999999" not in str(bitacora)
    assert w.sql("SELECT count(*) FROM whatsapp.conversacion_whatsapp") == [(0,)]
    assert w.estado_solicitud() == []


@pytest.mark.parametrize("motivo", ["BAJA", "SIN_CONSENTIMIENTO"])
async def test_baja_y_sin_consentimiento_reciben_servicio_no_disponible_y_se_avisa_a_rh(
    mundo, motivo
):
    w = mundo
    if motivo == "BAJA":
        r = await w.http_col.post(
            f"/api/v1/colaboradores/{w.a.colaborador_id}/baja",
            json={"fecha_baja": "2026-11-01"},
            headers=w.a.rh,
        )
    else:
        r = await w.http_col.put(
            f"/api/v1/colaboradores/{w.a.colaborador_id}/consentimiento",
            json={"otorgado": False},
            headers=w.a.rh,
        )
    assert r.status_code == 200, r.text
    await w.decir("constancia")
    assert w.textos() == [M.NO_DISPONIBLE]
    [aviso] = await w.alertas_rh(esperar=1, tipo="SERVICIO_NO_DISPONIBLE")
    assert aviso["colaborador_id"] == w.a.colaborador_id and aviso["motivo"] == motivo
    assert sin_datos_personales(str(aviso), w) and aviso["empresa_id"] == w.a.id
    assert w.sql("SELECT count(*) FROM whatsapp.conversacion_whatsapp") == [(0,)]


async def test_datos_incorrectos_uno_y_dos_intentos_y_bloqueo_al_tercero(mundo):
    w = mundo
    await w.decir("constancia")
    for n in (1, 2):
        await w.decir(f"{w.codigo_recibido()} 0000")
        assert w.textos()[-1] == M.DATOS_NO_COINCIDEN
        assert conversacion(w)[:3] == ("VERIFICANDO", False, n)
    assert await w.alertas_rh() == []
    await w.decir(f"{w.codigo_recibido()} 0000")
    assert w.textos()[-1] == M.BLOQUEADO
    estado, verificada, _, _, hasta = conversacion(w)
    assert (estado, verificada) == ("BLOQUEADA", False)
    horas = w.sql(
        "SELECT extract(epoch FROM bloqueada_hasta - now()) / 3600 FROM whatsapp.conversacion_whatsapp"
    )[0][0]
    assert 23.9 < float(horas) <= 24
    [aviso] = await w.alertas_rh(esperar=1, tipo="ACCESO_BLOQUEADO")
    assert aviso["colaborador_id"] == w.a.colaborador_id and sin_datos_personales(str(aviso), w)
    # bloqueada: ni el dato correcto la desbloquea, y no se genera nada
    await w.decir(f"{w.codigo_recibido()} {NSS_A[-4:]}")
    assert w.textos()[-1] == M.BLOQUEADO and conversacion(w)[0] == "BLOQUEADA"
    assert w.estado_solicitud() == []


async def test_codigo_vencido_envia_otro_sin_contar_intento_y_se_puede_verificar(mundo):
    w = mundo
    await w.decir("constancia")
    viejo = w.codigo_recibido()
    w.sql("UPDATE whatsapp.codigo_verificacion SET fecha_expira = now() - interval '1 minute'")
    await w.decir(f"{viejo} {NSS_A[-4:]}")
    assert w.textos()[-1].startswith(M.CODIGO_VENCIDO)
    assert conversacion(w)[:3] == ("VERIFICANDO", False, 0)  # sin intento contado
    nuevo = w.codigo_recibido()
    await w.decir(f"{nuevo} {NSS_A[-4:]}")
    assert conversacion(w)[0] == "ACTIVA" and w.estado_solicitud()[0][1] == "GENERADA"


async def test_campo_obligatorio_vacio_responde_falta_informacion_y_avisa_a_rh_con_los_campos(
    mundo,
):
    w = mundo
    # el colaborador no tiene NSS: el desafío pasa a la fecha de ingreso y la plantilla pide NSS
    w.sql("DELETE FROM colaboradores.valor_campo WHERE colaborador_id = %s", (w.a.colaborador_id,))
    await w.decir("constancia")
    assert "15/03" in w.textos()[-1]  # el ejemplo del desafío por fecha de ingreso
    await w.decir(f"{w.codigo_recibido()} 15/03")
    assert w.textos()[-1] == M.FALTA_INFORMACION
    [(_, estado, motivo)] = w.estado_solicitud()
    assert (estado, motivo) == ("FALLIDA", "CAMPOS_FALTANTES")
    assert w.estado_constancia() == []
    [aviso] = await w.alertas_rh(esperar=1, tipo="constancia.fallida")
    assert aviso["motivo"] == "CAMPOS_FALTANTES" and aviso["campos"] == ["nss"]
    assert sin_datos_personales(str(aviso), w) and aviso["origen"] == "EVENTBRIDGE"
    assert w.pdf.llamadas == 0


async def test_palabra_no_reconocida_con_conversacion_verificada_recibe_ayuda(mundo):
    w = mundo
    await solicitar(w)
    antes = len(w.textos())
    await w.decir("¿qué onda?")
    assert w.textos()[antes:] == [M.AYUDA]
    assert len(w.estado_solicitud()) == 1  # no abrió otra solicitud


# --------------------------------------------------------------------------- 3. fallas inyectadas


async def test_falla_persistente_del_pdf_deja_la_solicitud_fallida_y_avisa_a_rh(mundo_pdf_falla):
    w = mundo_pdf_falla
    await solicitar(w)
    assert w.pdf.llamadas == 3  # max_intentos_pdf recepciones
    [(_, estado, motivo)] = w.estado_solicitud()
    assert (estado, motivo) == ("FALLIDA", "ERROR_RENDER")
    assert w.estado_constancia() == [] and w.mensajes("CONSTANCIA") == []
    assert M.PREPARANDO in w.textos() and not any("/d/" in t for t in w.textos())
    [aviso] = await w.alertas_rh(esperar=1, tipo="constancia.fallida")
    assert aviso["motivo"] == "ERROR_RENDER" and aviso["empresa_id"] == w.a.id
    assert sin_datos_personales(str(aviso), w)
    # el mensaje salió de la cola de PDF (no queda reintentándose)
    assert w.aws.recibir(w.aws.pdf) == []


async def test_envio_con_error_permanente_deja_mensaje_constancia_y_solicitud_fallidos(mundo):
    w = mundo
    w.fallo_envio = lambda c: SIM.ERROR_NUMERO_INVALIDO if "/d/" in str(c) else None
    await solicitar(w)
    [(_, estado_msg, error, _, intentos, wamid)] = w.mensajes("CONSTANCIA")
    assert (estado_msg, error, intentos, wamid) == ("FALLIDO", "NUMERO_INVALIDO", 1, None)
    assert w.estado_constancia()[0][2] == "FALLIDA"
    assert w.estado_solicitud()[0][1:] == ("FALLIDA", "ENTREGA_FALLIDA")
    [aviso] = await w.alertas_rh(esperar=1, tipo="constancia.fallida")
    assert aviso["motivo"] == "ENTREGA_FALLIDA" and sin_datos_personales(str(aviso), w)
    assert w.reintentos_pedidos == []  # permanente: no se reintenta


async def test_envio_con_error_transitorio_agota_reintentos_y_queda_fallido(mundo):
    w = mundo
    w.fallo_envio = lambda c: SIM.ERROR_SERVIDOR if "/d/" in str(c) else None
    await solicitar(w)
    [(_, estado_msg, error, _, intentos, _)] = w.mensajes("CONSTANCIA")
    assert (estado_msg, error, intentos) == ("FALLIDO", "INTENTOS_AGOTADOS", 2)
    assert w.reintentos_pedidos == [30]  # una espera de 30 s tras la 1.ª recepción
    assert w.estado_constancia()[0][2] == "FALLIDA"
    assert w.estado_solicitud()[0][1:] == ("FALLIDA", "ENTREGA_FALLIDA")
    [aviso] = await w.alertas_rh(esperar=1, tipo="constancia.fallida")
    assert aviso["motivo"] == "ENTREGA_FALLIDA" and sin_datos_personales(str(aviso), w)
    assert not any("/d/" in t for t in w.textos())


@pytest.mark.xfail(
    strict=True,
    reason="Defecto: design.md §7.4 pide avisar al colaborador 'No pudimos enviar tu constancia. "
    "RH fue notificado.' cuando la entrega falla; ningún componente lo envía (T-213 solo avisa a RH).",
)
async def test_entrega_fallida_avisa_tambien_al_colaborador(mundo):
    w = mundo
    w.fallo_envio = lambda c: SIM.ERROR_SERVIDOR if "/d/" in str(c) else None
    await solicitar(w)
    assert "No pudimos enviar tu constancia. RH fue notificado." in w.textos()


# --------------------------------------------------------------------------- 4. reenvío por RH


async def test_rh_reenvia_una_constancia_fallida_y_al_llegar_delivered_queda_entregada(
    mundo_dos_empresas,
):
    w = mundo_dos_empresas
    w.fallo_envio = lambda c: SIM.ERROR_SERVIDOR if "/d/" in str(c) else None
    await solicitar(w)
    cid = w.estado_constancia()[0][0]
    assert w.estado_constancia()[0][2] == "FALLIDA"
    primeros = w.sql("SELECT token_hash FROM constancias.token_descarga")

    # otra empresa no puede reenviarla (RLS: para ella no existe), y una pendiente no se reenvía
    r = await w.http_con.post(f"/api/v1/constancias/{cid}/reenviar", headers=w.b.rh)
    assert r.status_code == 404
    assert w.estado_constancia()[0][2] == "FALLIDA"

    # el reenvío sale fuera de la ventana de 24 h: la plantilla aprobada "constancia lista"
    w.sql(
        "UPDATE whatsapp.conversacion_whatsapp SET ultimo_mensaje_entrante_at = now() - interval '30 hours'"
    )
    w.fallo_envio = None
    r = await w.http_con.post(f"/api/v1/constancias/{cid}/reenviar", headers=w.a.rh)
    assert r.status_code == 202
    assert w.estado_constancia()[0][2] == "PENDIENTE"
    again = await w.http_con.post(f"/api/v1/constancias/{cid}/reenviar", headers=w.a.rh)
    assert again.status_code == 409  # ya volvió a PENDIENTE
    await w.bombear("reenvío de RH")

    tokens = w.sql(
        "SELECT generado_por, usuario_id, token_hash FROM constancias.token_descarga ORDER BY id"
    )
    assert [t[0] for t in tokens] == ["BOT", "RH_REENVIO"] and tokens[1][1] == w.a.usuario_id
    assert tokens[1][2] != primeros[0][0]  # token nuevo
    plantilla = [e for e in w.recibidos() if e["type"] == "template"]
    assert len(plantilla) == 1 and plantilla[0]["template"]["name"] == "constancia_lista"
    folio = w.estado_constancia()[0][1]
    assert folio in texto_de(plantilla[0]) and "/d/" in texto_de(plantilla[0])
    nuevos = w.mensajes("CONSTANCIA")
    assert [m[1] for m in nuevos] == ["FALLIDO", "ENVIADO"] and nuevos[1][3] == "PLANTILLA"
    assert w.sql(
        "SELECT usuario_id FROM auditoria.bitacora WHERE accion = 'CONSTANCIA_REENVIADA'"
    ) == [(w.a.usuario_id,)]

    await entregada(w)
    assert w.estado_constancia()[0][2:4] == ("ENTREGADA", True)
    assert w.estado_solicitud()[0][1:] == ("ENTREGADA", None)
    assert w.mensajes("CONSTANCIA")[1][1] == "ENTREGADO"


# --------------------------------------------------------------------------- 5. aislamiento


async def test_el_flujo_de_una_empresa_no_toca_los_datos_de_la_otra(mundo_dos_empresas):
    w = mundo_dos_empresas
    tablas = (
        "whatsapp.conversacion_whatsapp",
        "whatsapp.mensaje_whatsapp",
        "whatsapp.codigo_verificacion",
        "whatsapp.outbox",
        "constancias.solicitud_constancia",
        "constancias.constancia_generada",
        "constancias.token_descarga",
        "constancias.outbox",
    )

    def cuentas(empresa):
        return {
            t: w.sql(f"SELECT count(*) FROM {t} WHERE empresa_id = %s", (empresa,))[0][0]
            for t in tablas
        }  # noqa: S608

    antes_b = cuentas(w.b.id)
    await solicitar(w)
    await entregada(w)
    assert w.estado_solicitud()[0][1] == "ENTREGADA"
    assert cuentas(w.b.id) == antes_b  # ni una fila nueva para B
    # el bot de A no ve el número de B
    busqueda = await w.ctx_a.colaboradores.buscar_por_celular(w.a.id, WA_ID_B)
    assert busqueda.encontrado is False

    # el flujo de B (su propio bot): mismo folio por empresa y nada cruzado
    async def decir_b(texto):
        await procesar(w.ctx_b, Mensaje(w._wamid(), WA_ID_B, texto))
        await w.bombear("empresa B")

    await decir_b("constancia")
    await decir_b(f"{w.codigo_recibido(WA_ID_B)} {NSS_B[-4:]}")
    assert FOLIO.fullmatch(w.estado_constancia(w.b.id)[0][1])
    assert FOLIO.fullmatch(w.estado_constancia(w.a.id)[0][1])  # cada empresa su -0001
    assert w.estado_constancia(w.a.id)[0][0] != w.estado_constancia(w.b.id)[0][0]
    assert w.estado_solicitud(w.b.id)[0][1] == "GENERADA"
    await w.estado_meta(w.wamid_del_enlace(), "delivered", destinatario=WA_ID_B)
    assert w.estado_constancia(w.b.id)[0][2] == "ENTREGADA"
    # A no cambió, y los mensajes de cada uno fueron solo a su número
    assert w.estado_constancia(w.a.id)[0][2] == "ENTREGADA"
    assert all(NSS_B not in t and NSS_A not in t for t in w.textos() + w.textos(WA_ID_B))
    enlace_a, enlace_b = (next(t for t in w.textos(x) if "/d/" in t) for x in (WA_ID_A, WA_ID_B))
    assert enlace_a != enlace_b
    # el token de RH de una empresa no ve la constancia de la otra
    cid_a, cid_b = w.estado_constancia(w.a.id)[0][0], w.estado_constancia(w.b.id)[0][0]
    assert (await w.http_con.get(f"/api/v1/constancias/{cid_b}", headers=w.a.rh)).status_code == 404
    assert (await w.http_con.get(f"/api/v1/constancias/{cid_a}", headers=w.b.rh)).status_code == 404
    assert (await w.http_con.get(f"/api/v1/constancias/{cid_a}", headers=w.a.rh)).status_code == 200


# --------------------------------------------------------------------------- 6. dashboard


async def test_el_dashboard_refleja_la_constancia_entregada(mundo_dos_empresas):
    w = mundo_dos_empresas
    antes = (await w.http_dash.get("/api/v1/dashboard/resumen", headers=w.a.rh)).json()
    assert antes["constancias_mes"] == 0
    await solicitar(w)
    # generada pero aún no entregada: aparece como PENDIENTE
    recientes = (
        await w.http_dash.get("/api/v1/dashboard/constancias-recientes", headers=w.a.rh)
    ).json()
    assert [(c["estado_entrega"]) for c in recientes] == ["PENDIENTE"]
    await entregada(w)

    resumen = (await w.http_dash.get("/api/v1/dashboard/resumen", headers=w.a.rh)).json()
    assert resumen["constancias_mes"] == 1 and resumen["colaboradores_activos"] == 1
    assert resumen["solicitudes_en_proceso"] == 0 and resumen["plantillas_activas"] == 1
    [reciente] = (
        await w.http_dash.get("/api/v1/dashboard/constancias-recientes", headers=w.a.rh)
    ).json()
    assert FOLIO.fullmatch(reciente["folio"]) and reciente["estado_entrega"] == "ENTREGADA"
    assert reciente["colaborador_nombre"] == "Ana Pérez Luna"
    assert reciente["plantilla_nombre"] == "Constancia laboral"
    historial = (
        await w.http_dash.get(
            "/api/v1/constancias/historial", params={"estado": "ENTREGADA"}, headers=w.a.rh
        )
    ).json()
    assert [i["folio"] for i in historial["items"]] == [reciente["folio"]]
    assert historial["items"][0]["canal"] and historial["siguiente"] is None
    pendientes = (
        await w.http_dash.get(
            "/api/v1/constancias/historial", params={"estado": "PENDIENTE"}, headers=w.a.rh
        )
    ).json()
    assert pendientes["items"] == []
    # la otra empresa no ve nada
    otra = (await w.http_dash.get("/api/v1/dashboard/resumen", headers=w.b.rh)).json()
    assert otra["constancias_mes"] == 0
    assert (await w.http_dash.get("/api/v1/constancias/historial", headers=w.b.rh)).json()[
        "items"
    ] == []


async def test_el_dashboard_muestra_la_falla_de_entrega_como_alerta(mundo):
    w = mundo
    w.fallo_envio = lambda c: SIM.ERROR_SERVIDOR if "/d/" in str(c) else None
    await solicitar(w)
    alertas = (await w.http_dash.get("/api/v1/dashboard/alertas", headers=w.a.rh)).json()
    assert any(a["tipo"] == "CONSTANCIA_FALLIDA" for a in alertas)
    [fila] = (
        await w.http_dash.get("/api/v1/dashboard/constancias-recientes", headers=w.a.rh)
    ).json()
    assert fila["estado_entrega"] == "FALLIDA"


# --------------------------------------------------------------------------- secretos


async def test_el_codigo_solo_se_guarda_como_hmac_y_nunca_el_numero_ni_el_token(mundo):
    w = mundo
    await solicitar(w)
    codigo = w.codigo_recibido()
    token = w.enlace_recibido().rsplit("/", 1)[1]
    # las filas del outbox llevan el mensaje saliente tal cual: se revisan aparte (xfail)
    volcado = "\n".join(
        linea for linea in w.volcado_de_la_base().splitlines() if ".outbox:" not in linea[:40]
    )
    # token del enlace: solo su hash; número: solo hash/cifrado/últimos 4
    assert token not in volcado
    assert WA_ID_A not in volcado and CELULAR_A not in volcado
    assert NSS_A not in volcado  # el NSS va cifrado
    # el código no queda en ninguna tabla de negocio
    en = [
        linea.split(":", 1)[0]
        for linea in volcado.splitlines()
        if re.search(rf"(?<![\d.:+-]){codigo}(?![\d])", linea.split(":", 1)[1])
    ]
    assert en == []


@pytest.mark.xfail(
    strict=True,
    reason="Defecto: el bot escribe el texto con el código de verificación en claro en "
    "whatsapp.outbox.payload y la fila se conserva tras publicarse (design.md §7.2: en la base "
    "solo se guarda el HMAC). Falta purgar o vaciar el texto al publicar.",
)
async def test_el_codigo_no_queda_en_claro_en_el_outbox(mundo):
    w = mundo
    await w.decir("constancia")
    codigo = w.codigo_recibido()
    filas = w.sql("SELECT payload::text FROM whatsapp.outbox")
    assert not any(f"verificación es {codigo}" in f[0] for f in filas)


@pytest.mark.xfail(
    strict=True,
    reason="Defecto: el mensaje con el enlace (token en claro) queda en constancias.outbox.payload "
    "después de publicarse; design.md §5.6 dice que solo se guarda el SHA-256 del token.",
)
async def test_el_token_del_enlace_no_queda_en_claro_en_el_outbox(mundo):
    w = mundo
    await solicitar(w)
    token = w.enlace_recibido().rsplit("/", 1)[1]
    filas = w.sql("SELECT payload::text FROM constancias.outbox")
    assert not any(token in f[0] for f in filas)


# --------------------------------------------------------------------------- PDF real (marcador)

try:
    from cc_constancias.render.pdf import disponible, html_a_pdf

    _hay_pdf = disponible()
except Exception:  # noqa: BLE001
    _hay_pdf = False


@pytest.mark.pdf
@pytest.mark.skipif(
    not _hay_pdf, reason="WeasyPrint no carga: corre en Linux o contenedor con Pango"
)
async def test_con_pdf_real_de_weasyprint(bd_migrada, localstack):
    """Mismo recorrido, con el renderizador real: el PDF del bucket es un PDF y trae el folio."""
    import io

    from pypdf import PdfReader

    w = await construir_mundo(bd_migrada, localstack, pdf=html_a_pdf)
    try:
        await solicitar(w)
        clave = w.sql("SELECT pdf_s3_key FROM constancias.constancia_generada")[0][0]
        cuerpo = w.aws.s3.get_object(Bucket=w.aws.bucket_constancias, Key=clave)["Body"].read()
        assert cuerpo.startswith(b"%PDF")
        texto = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(cuerpo)).pages)
        assert w.estado_constancia()[0][1] in texto and "Ana Pérez Luna" in texto
    finally:
        await cerrar_mundo(w)
