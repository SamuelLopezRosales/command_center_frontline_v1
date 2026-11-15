"""T-207 (T-078): catálogo de variables (CON-15) y su integración con `campos` real.

La primera parte usa un sustituto de INT-CAM-01; la segunda conecta el servicio `campos` de
verdad (sembrado incluido) por su cliente HTTP interno.
"""

import httpx
import pytest
from ayudantes_constancias import (
    CLIENTE,
    EMISOR,
    LLAVE,
    SECRETO_INTERNO,
    construir_app,
)
from cc_common.auth import VerificadorToken
from cc_common.db import crear_motor
from cc_common.internal_client import ClienteInterno
from cc_constancias.clientes import CamposHttp, DefinicionCampo

pytestmark = pytest.mark.docker


async def _variables(http, h):
    r = await http.get("/api/v1/constancias/variables", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["items"]


async def test_sin_campos_ofrece_las_fijas_de_organizacion_derivadas_y_sistema(http, h):
    items = await _variables(http, h)
    por_grupo = {}
    for v in items:
        por_grupo.setdefault(v["grupo"], []).append((v["nombre"], v["sensible"]))
    assert [g for g in por_grupo] == ["COLABORADOR", "ORGANIZACION", "SENSIBLES", "SISTEMA"]
    assert [n for n, _ in por_grupo["COLABORADOR"]] == [
        "nombre_completo",
        "puesto",
        "fecha_ingreso",
        "planta",
        "horario",
    ]
    assert "organizacion.razon_social" in [n for n, _ in por_grupo["ORGANIZACION"]]
    assert "registro_patronal" in [n for n, _ in por_grupo["ORGANIZACION"]]
    assert por_grupo["SENSIBLES"] == [("sueldo_mensual", True), ("sueldo_letra", True)]
    assert [n for n, _ in por_grupo["SISTEMA"]] == ["folio", "fecha_emision", "qr_verificacion"]
    assert "empresa" not in [v["nombre"] for v in items]  # pendiente (PQ-17)


async def test_los_campos_activos_se_agregan_por_grupo_y_los_inactivos_no(http, h, campos, datos):
    campos.por_empresa[datos["a"]] = [
        DefinicionCampo(1, "Área", "area", "CAMP-0001", "LISTA", orden=1),
        DefinicionCampo(2, "NSS", "nss", "CAMP-0002", "TEXTO", es_sensible=True, orden=2),
        DefinicionCampo(3, "Ruta", "ruta_transporte", "CAMP-0003", "TEXTO", activo=False, orden=3),
    ]
    items = await _variables(http, h)
    nombres = {v["nombre"]: v for v in items}
    assert nombres["area"]["grupo"] == "COLABORADOR" and nombres["area"]["sensible"] is False
    assert nombres["area"]["etiqueta"] == "Área"
    assert nombres["nss"]["grupo"] == "SENSIBLES" and nombres["nss"]["sensible"] is True
    assert "ruta_transporte" not in nombres
    sensibles = [v["nombre"] for v in items if v["grupo"] == "SENSIBLES"]
    assert sensibles == ["nss", "sueldo_mensual", "sueldo_letra"]  # derivadas al final


async def test_el_catalogo_es_por_empresa_y_pide_sesion(http, h, hb, campos, datos):
    campos.por_empresa[datos["a"]] = [DefinicionCampo(1, "Área", "area", "CAMP-0001", "LISTA")]
    assert "area" in [v["nombre"] for v in await _variables(http, h)]
    assert "area" not in [v["nombre"] for v in await _variables(http, hb)]
    assert (await http.get("/api/v1/constancias/variables")).status_code == 401


async def test_si_campos_no_responde_el_catalogo_falla_con_502(http, h, campos):
    from cc_common.errores import ErrorProveedor

    async def cae(_empresa):
        raise ErrorProveedor()

    campos.definiciones = cae
    r = await http.get("/api/v1/constancias/variables", headers=h)
    assert r.status_code == 502


# ------------------------------------------------------------------ con `campos` de verdad


async def test_el_catalogo_refleja_el_servicio_campos_real(datos, motor, s3_plantillas):
    """Siembra, alta de un campo personalizado y desactivación de uno sugerido, vistos por CON-15."""
    from ayudantes_constancias import cab, emitir
    from cc_campos.config import ConfigCampos
    from cc_campos.main import crear_app as crear_app_campos

    motor_campos = crear_motor(datos["bd"].url_rol("svc_campos"))
    try:
        app_campos = crear_app_campos(
            ConfigCampos(cognito_emisor=EMISOR, cognito_client_id=CLIENTE),
            motor=motor_campos,
            verificador=VerificadorToken(
                EMISOR, CLIENTE, resolver_llave=lambda _t: LLAVE.public_key()
            ),
            secreto_interno=lambda: SECRETO_INTERNO,
        )
        interno = ClienteInterno(
            "http://campos",
            servicio="constancias",
            secreto=lambda: SECRETO_INTERNO,
            transporte=httpx.ASGITransport(app=app_campos),
            reintentos=0,
        )
        app = construir_app(motor, almacen=s3_plantillas[0], campos=CamposHttp(interno))
        h = cab(emitir("sub-a", datos["a"], datos["ua"]))
        from cc_common.internal_client import emitir_token_interno

        token_dashboard = emitir_token_interno(SECRETO_INTERNO, "dashboard")
        async with (
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app_campos), base_url="http://c"
            ) as c,
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://k") as k,
        ):
            r = await c.post(
                f"/internal/empresas/{datos['a']}/campos-sugeridos",
                headers={
                    "Authorization": f"Bearer {token_dashboard}",
                    "X-Empresa-Id": str(datos["a"]),
                },
            )
            assert r.json()["creados"] == 11
            r = await c.post(
                "/api/v1/campos",
                json={
                    "nombre_campo": "Bono",
                    "clave": "bono",
                    "tipo_dato": "NUMERO",
                    "es_sensible": True,
                },
                headers=h,
            )
            assert r.status_code == 201
            turno = [
                x
                for x in (await c.get("/api/v1/campos", headers=h)).json()["dinamicos"]
                if x["clave"] == "turno"
            ][0]
            await c.patch(f"/api/v1/campos/{turno['id']}", json={"activo": False}, headers=h)

            items = (await k.get("/api/v1/constancias/variables", headers=h)).json()["items"]
            por = {v["nombre"]: v["grupo"] for v in items}
            assert por["area"] == "COLABORADOR" and por["departamento"] == "COLABORADOR"
            assert por["periodicidad_sueldo"] == "COLABORADOR"
            assert (
                por["sueldo"]
                == por["nss"]
                == por["rfc"]
                == por["curp"]
                == por["bono"]
                == "SENSIBLES"
            )
            assert por["correo"] == "COLABORADOR" and por["registro_patronal"] == "ORGANIZACION"
            assert "turno" not in por and "ruta_transporte" not in por  # inactivos
            assert por["sueldo_mensual"] == por["sueldo_letra"] == "SENSIBLES"
    finally:
        await motor_campos.dispose()
