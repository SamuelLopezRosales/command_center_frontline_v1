"""T-213 (T-100): confirmación de entrega de la constancia desde ``wa.mensaje_estado``."""

import json
import uuid

import pytest
from ayudantes_constancias import crear_colaborador, sql
from ayudantes_emision import plantilla_activa, salidas, solicitud, version_id
from cc_constancias.config import ConfigConstancias
from cc_constancias.consumidores import manejar_evento

pytestmark = pytest.mark.docker

HASH = "b" * 64


@pytest.fixture
def mundo(datos, s3_plantillas):
    colaborador = crear_colaborador(datos)
    pid = plantilla_activa(datos, s3_plantillas[0])
    return {"colaborador": colaborador, "plantilla": pid, "almacen": s3_plantillas[0]}


def _constancia(datos, mundo, estado_entrega="PENDIENTE", folio="CG-2026-0001") -> tuple[int, int]:
    """Solicitud ``GENERADA`` con su constancia. Devuelve ``(solicitud_id, constancia_id)``."""
    sid = solicitud(datos, mundo["colaborador"], mundo["plantilla"], estado="GENERADA")
    cid = sql(
        datos,
        "INSERT INTO constancias.constancia_generada (empresa_id, solicitud_id, colaborador_id, "
        "version_plantilla_id, folio, pdf_s3_key, pdf_hash_sha256, datos_snapshot_json, "
        "colaborador_nombre, numero_empleado, codigo_verificacion, estado_entrega) "
        "VALUES (%s,%s,%s,%s,%s,'pdf',%s,%s,'Ana Pérez Ruiz','EMP-0001',%s,%s) RETURNING id",
        (
            datos["a"],
            sid,
            mundo["colaborador"],
            version_id(datos, mundo["plantilla"]),
            folio,
            HASH,
            json.dumps({"p": 1}),
            uuid.uuid4().hex,
            estado_entrega,
        ),
    )[0][0]
    return sid, cid


def _evento(datos, constancia_id, estado, origen="CONSTANCIA"):
    return {
        "tipo": "wa.mensaje_estado",
        "empresa_id": datos["a"],
        "origen_tipo": origen,
        "origen_id": constancia_id,
        "estado": estado,
        "mensaje_uuid": str(uuid.uuid4()),
    }


async def _aplicar(motor, datos, evento):
    return await manejar_evento(motor, None, None, None, evento, ConfigConstancias())


def _estados(datos, sid, cid):
    return (
        sql(datos, "SELECT estado, motivo_fallo FROM constancias.solicitud_constancia WHERE id = %s", (sid,))[0],
        sql(datos, "SELECT estado_entrega, fecha_entrega IS NOT NULL FROM constancias.constancia_generada WHERE id = %s", (cid,))[0],
    )  # fmt: skip


@pytest.mark.parametrize("estado", ["ENTREGADO", "LEIDO"])
async def test_entregado_o_leido_pasan_constancia_y_solicitud_a_entregada(
    motor, datos, mundo, estado
):
    sid, cid = _constancia(datos, mundo)
    assert await _aplicar(motor, datos, _evento(datos, cid, estado)) is True
    assert _estados(datos, sid, cid) == (("ENTREGADA", None), ("ENTREGADA", True))
    assert salidas(datos, "constancia.fallida") == []


async def test_repetir_el_evento_o_recibirlo_en_otro_orden_no_cambia_nada(motor, datos, mundo):
    sid, cid = _constancia(datos, mundo)
    await _aplicar(motor, datos, _evento(datos, cid, "ENTREGADO"))
    assert await _aplicar(motor, datos, _evento(datos, cid, "LEIDO")) is False
    # Un fallo que llega tarde no hace retroceder una constancia ya entregada.
    assert await _aplicar(motor, datos, _evento(datos, cid, "FALLIDO")) is False
    assert _estados(datos, sid, cid) == (("ENTREGADA", None), ("ENTREGADA", True))
    assert salidas(datos, "constancia.fallida") == []


async def test_fallo_definitivo_deja_fallida_y_avisa_sin_datos_personales(motor, datos, mundo):
    sid, cid = _constancia(datos, mundo)
    assert await _aplicar(motor, datos, _evento(datos, cid, "FALLIDO")) is True
    assert _estados(datos, sid, cid) == (("FALLIDA", "ENTREGA_FALLIDA"), ("FALLIDA", False))
    [aviso] = salidas(datos, "constancia.fallida")
    assert aviso["solicitud_id"] == sid and aviso["motivo"] == "ENTREGA_FALLIDA"
    assert "Ana" not in json.dumps(aviso) and "Pérez" not in json.dumps(aviso)
    # Repetir el fallo no duplica el aviso.
    assert await _aplicar(motor, datos, _evento(datos, cid, "FALLIDO")) is False
    assert len(salidas(datos, "constancia.fallida")) == 1


async def test_entrega_posterior_a_un_fallo_corrige_el_estado(motor, datos, mundo):
    sid, cid = _constancia(datos, mundo)
    await _aplicar(motor, datos, _evento(datos, cid, "FALLIDO"))
    assert await _aplicar(motor, datos, _evento(datos, cid, "ENTREGADO")) is True
    assert _estados(datos, sid, cid) == (("ENTREGADA", None), ("ENTREGADA", True))


@pytest.mark.parametrize("estado", ["ENVIADO", "ENCOLADO"])
async def test_estados_intermedios_no_cambian_la_constancia(motor, datos, mundo, estado):
    sid, cid = _constancia(datos, mundo)
    assert await _aplicar(motor, datos, _evento(datos, cid, estado)) is False
    assert _estados(datos, sid, cid) == (("GENERADA", None), ("PENDIENTE", False))


async def test_mensajes_de_otro_origen_se_ignoran(motor, datos, mundo):
    sid, cid = _constancia(datos, mundo)
    for origen in ("BOT", "NOTIFICACION"):
        assert await _aplicar(motor, datos, _evento(datos, cid, "ENTREGADO", origen)) is False
    assert _estados(datos, sid, cid) == (("GENERADA", None), ("PENDIENTE", False))


async def test_un_evento_de_otra_empresa_no_toca_la_constancia(motor, datos, mundo):
    sid, cid = _constancia(datos, mundo)
    ajeno = _evento(datos, cid, "ENTREGADO") | {"empresa_id": datos["b"]}
    assert await _aplicar(motor, datos, ajeno) is False  # RLS: la fila no es visible
    assert _estados(datos, sid, cid) == (("GENERADA", None), ("PENDIENTE", False))
