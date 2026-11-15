"""T-211 (T-095): Lambda ``estados-entrega`` con base real y RLS."""

import pytest
from ayudantes_whatsapp import crear_mensaje, eventos, mensaje, registro_sqs
from cc_whatsapp.metricas import CONTADORES
from estados_entrega.handler import manejar

pytestmark = pytest.mark.docker


def correr(datos, cfg, *cuerpos):
    registros = [registro_sqs(c, n) for n, c in enumerate(cuerpos, 1)]
    return manejar({"Records": registros}, abrir=datos["abrir"], cfg=cfg)


def estado(wamid, e, error=None):
    return {"clase": "mensaje", "id": wamid, "estado": e, "error_codigo": error}


def test_los_estados_solo_avanzan_aunque_lleguen_repetidos_o_desordenados(datos, cfg):
    clave = crear_mensaje(datos, datos["colaborador"], proveedor="wamid.A", estado="ENVIADO")
    r = correr(
        datos, cfg,
        estado("wamid.A", "read"), estado("wamid.A", "delivered"),  # fuera de orden
        estado("wamid.A", "read"), estado("wamid.A", "sent"),  # repetido y atrasado
    )  # fmt: skip
    assert r == {"batchItemFailures": []}
    assert mensaje(datos, clave)[0] == "LEIDO"
    publicados = eventos(datos, "wa.mensaje_estado")
    assert [e["estado"] for e in publicados] == ["LEIDO"]  # solo el avance real
    assert publicados[0]["origen_tipo"] == "CONSTANCIA" and publicados[0]["origen_id"] == 7
    assert (
        publicados[0]["mensaje_uuid"] == clave and publicados[0]["empresa_id"] == datos["empresa"]
    )


def test_entregado_publica_su_evento_y_failed_guarda_el_motivo(datos, cfg):
    a = crear_mensaje(datos, datos["colaborador"], proveedor="wamid.B", estado="ENVIADO")
    b = crear_mensaje(datos, datos["colaborador"], proveedor="wamid.C", estado="ENVIADO")
    correr(datos, cfg, estado("wamid.B", "delivered"), estado("wamid.C", "failed", "131047"))
    assert mensaje(datos, a)[0] == "ENTREGADO"
    assert mensaje(datos, b)[:2] == ("FALLIDO", "VENTANA_CERRADA")
    assert eventos(datos, "wa.numero_invalido") == []


def test_numero_invalido_publica_el_evento_para_colaboradores(datos, cfg):
    crear_mensaje(datos, datos["colaborador"], proveedor="wamid.D", estado="ENVIADO")
    correr(datos, cfg, estado("wamid.D", "failed", "131026"))
    assert eventos(datos, "wa.numero_invalido") == [
        {"colaborador_id": datos["colaborador"], "empresa_id": datos["empresa"]}
    ]


def test_estado_desconocido_o_de_un_mensaje_desconocido_no_cambia_nada(datos, cfg):
    clave = crear_mensaje(datos, datos["colaborador"], proveedor="wamid.E", estado="ENVIADO")
    r = correr(datos, cfg, estado("wamid.E", "deleted"), estado("wamid.NO-EXISTE", "read"))
    assert r == {"batchItemFailures": []}
    assert mensaje(datos, clave)[0] == "ENVIADO" and eventos(datos, "wa.mensaje_estado") == []
    assert CONTADORES["estados_desconocidos"] == 2


def test_el_estado_de_una_plantilla_se_publica(datos, cfg):
    correr(
        datos, cfg, {"clase": "plantilla", "nombre": "aviso", "evento": "REJECTED", "motivo": "X"}
    )
    assert eventos(datos, "wa.plantilla_estado") == [
        {"nombre": "aviso", "estado_meta": "REJECTED", "motivo_rechazo": "X"}
    ]


def test_un_lote_con_una_falla_parcial_devuelve_solo_esa(datos, cfg):
    crear_mensaje(datos, datos["colaborador"], proveedor="wamid.F", estado="ENVIADO")
    registros = [
        registro_sqs(estado("wamid.F", "delivered"), 1),
        {"messageId": "malo", "receiptHandle": "x", "body": "no es json"},
        registro_sqs(estado("wamid.F", "read"), 3),
    ]
    r = manejar({"Records": registros}, abrir=datos["abrir"], cfg=cfg)
    assert r == {"batchItemFailures": [{"itemIdentifier": "malo"}]}
    assert [e["estado"] for e in eventos(datos, "wa.mensaje_estado")] == ["ENTREGADO", "LEIDO"]
