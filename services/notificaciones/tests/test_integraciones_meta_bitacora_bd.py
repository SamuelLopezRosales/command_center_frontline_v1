"""Conexión con Meta contra PostgreSQL real: la bitácora y el candado como ``svc_notificaciones``.

Comprueba lo que el doble de motor no puede: que la acción nueva se inserta con el rol del
servicio (sin ``RETURNING``), que la restricción ``detalle_permitido`` acepta ``campos`` y
``estado_nuevo`` y que el candado de asesoría es ejecutable por ese rol.
"""

import asyncio

import httpx
import pytest
from ayudantes_integraciones_meta import COMPLETO, ClienteSecretosFalso, sin_secretos
from ayudantes_notificaciones import cab, construir_app, emitir, sql
from cc_notificaciones.integracion_meta import AlmacenSecretsManager

pytestmark = pytest.mark.docker

URL = "/api/v1/integraciones/meta"


@pytest.fixture
async def cliente_bd(motor):
    secretos = ClienteSecretosFalso()
    app = construir_app(
        motor, almacen_meta=AlmacenSecretsManager("cc/test/meta", "us-east-1", cliente=secretos)
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, secretos


def _registros(datos, accion):
    return sql(
        datos,
        "SELECT empresa_id, usuario_id, entidad, origen, detalle::text FROM auditoria.bitacora "
        "WHERE accion = %s ORDER BY id",
        (accion,),
    )


async def test_guardar_y_probar_registran_bitacora_real_sin_valores(cliente_bd, datos, h):
    c, secretos = cliente_bd
    r = await c.put(URL, json=COMPLETO, headers=h)
    assert r.status_code == 200, r.text
    ((empresa, usuario, entidad, origen, detalle),) = _registros(datos, "META_CONFIGURADA")
    assert (empresa, usuario, entidad, origen) == (
        datos["a"],
        datos["ua"],
        "integracion_meta",
        "USUARIO",
    )
    assert (
        sin_secretos(detalle) and "access_token" in detalle and COMPLETO["waba_id"] not in detalle
    )

    # Sin credenciales guardadas, probar es 422 y no registra nada (no hubo prueba).
    secretos.valor = "{}"
    r = await c.post(f"{URL}/probar", headers=h)
    assert r.status_code == 422
    assert _registros(datos, "META_PROBADA") == []


async def test_dos_guardados_simultaneos_no_se_pisan(cliente_bd, datos, h):
    c, secretos = cliente_bd
    await asyncio.gather(
        c.put(URL, json={"waba_id": COMPLETO["waba_id"]}, headers=h),
        c.put(URL, json={"phone_number_id": COMPLETO["phone_number_id"]}, headers=h),
        c.put(URL, json={"api_version": "v22.0"}, headers=h),
    )
    assert secretos.json["waba_id"] == COMPLETO["waba_id"]
    assert secretos.json["phone_number_id"] == COMPLETO["phone_number_id"]
    assert secretos.json["api_version"] == "v22.0"
    assert len(_registros(datos, "META_CONFIGURADA")) == 3


async def test_otra_empresa_sin_permiso_no_cambia_nada(cliente_bd, datos):
    c, secretos = cliente_bd
    sin_permiso = cab(emitir("sub-b", datos["b"], datos["ub"], rol="OTRO"))
    r = await c.put(URL, json=COMPLETO, headers=sin_permiso)
    assert r.status_code == 403 and secretos.escrituras == []
    assert _registros(datos, "META_CONFIGURADA") == []
