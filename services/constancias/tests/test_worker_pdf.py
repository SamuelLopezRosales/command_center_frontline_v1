"""T-209 (T-085): worker-pdf con base real y S3 en LocalStack (el PDF real se prueba en test_pdf)."""

import base64
import hashlib

import pytest
from ayudantes_constancias import CLIENTE, EMISOR, crear_colaborador, sql
from ayudantes_emision import plantilla_activa, salidas, solicitud
from cc_common.db import transaccion
from cc_common.errores import ErrorInterno
from cc_constancias.clientes import DefinicionCampo
from cc_constancias.config import ConfigConstancias
from cc_constancias.workers.worker_pdf import atender, procesar_solicitud

pytestmark = pytest.mark.docker

NSS = DefinicionCampo(1, "NSS", "nss", "CAMP-0002", "TEXTO", es_sensible=True)
NSS_CLARO = "12345678901"


class FalsoPdf:
    def __init__(self, fallos: int = 0):
        self.fallos = fallos
        self.htmls: list[str] = []

    def __call__(self, html: str) -> bytes:
        if self.fallos:
            self.fallos -= 1
            raise RuntimeError("falla inyectada")
        self.htmls.append(html)
        return b"%PDF-1.7 falso " + html.encode()


@pytest.fixture
def cfg():
    return ConfigConstancias(
        cognito_emisor=EMISOR, cognito_client_id=CLIENTE, dominio="cc.prueba.test",
        max_intentos_pdf=3, retencion_constancias_dias=1,
    )  # fmt: skip


@pytest.fixture
def mundo(datos, campos, colaboradores, s3_plantillas, s3_constancias, cifrador, motor, cfg):
    campos.por_empresa[datos["a"]] = [NSS]
    colaborador = crear_colaborador(datos)
    colaboradores.valores[colaborador] = {"nombre_completo": "Ana Pérez", "nss": NSS_CLARO}
    colaboradores.resumenes[colaborador] = {"numero_empleado": "E-77", "organizacion": {"id": 0}}
    pid = plantilla_activa(datos, s3_plantillas[0])
    sid = solicitud(datos, colaborador, pid)
    pdf = FalsoPdf()

    async def correr(**extra):
        return await procesar_solicitud(
            motor, cfg,
            almacen=s3_plantillas[0], almacen_constancias=s3_constancias[0], cifrador=cifrador,
            campos=campos, colaboradores=colaboradores, cargador_logotipo=None,
            empresa_id=datos["a"], solicitud_id=sid, generar_pdf=extra.pop("generar_pdf", pdf),
            **extra,
        )  # fmt: skip

    return {"sid": sid, "pid": pid, "col": colaborador, "pdf": pdf, "correr": correr, "cfg": cfg}


def constancia(datos, sid):
    return sql(
        datos,
        "SELECT id, folio, pdf_s3_key, pdf_hash_sha256, datos_snapshot_json, numero_empleado, "
        "codigo_verificacion FROM constancias.constancia_generada WHERE solicitud_id = %s",
        (sid,),
    )


async def test_genera_la_constancia_con_pdf_inmutable_y_snapshot_cifrado(
    datos, mundo, s3_constancias, cifrador, motor
):
    assert await mundo["correr"]() == "GENERADA"
    [(cid, folio, clave, huella, snap, numero, codigo)] = constancia(datos, mundo["sid"])
    assert folio.startswith("CG-") and folio.endswith("-0001") and numero == "E-77"
    assert len(codigo) >= 22 and clave == f"constancias/{datos['a']}/{folio[3:7]}/{folio}.pdf"

    _, s3, bucket = s3_constancias
    obj = s3.get_object(Bucket=bucket, Key=clave, ChecksumMode="ENABLED")
    cuerpo = obj["Body"].read()
    assert hashlib.sha256(cuerpo).hexdigest() == huella
    assert obj["ChecksumSHA256"] == base64.b64encode(bytes.fromhex(huella)).decode()
    assert obj["ObjectLockMode"] == "GOVERNANCE"
    assert f"/v/{codigo}".encode() in cuerpo or codigo.encode() in cuerpo  # el QR apunta al código
    assert b"Ana P" in cuerpo and NSS_CLARO.encode() in cuerpo  # el PDF sí lleva el dato

    # snapshot: sensibles cifrados uno a uno; el resto en claro
    assert NSS_CLARO not in str(snap) and snap["valores"]["nombre_completo"] == "Ana Pérez"
    blob = base64.b64decode(snap["valores"]["nss"]["cifrado"])
    async with transaccion(motor, datos["a"]) as conn, cifrador.transaccion(conn, datos["a"]):
        claro = cifrador.descifrar(blob, empresa_id=datos["a"], registro=f"{mundo['sid']}:nss")
        assert claro == NSS_CLARO
        with pytest.raises(Exception, match=".*"):  # ligado a su solicitud y variable
            cifrador.descifrar(blob, empresa_id=datos["a"], registro=f"{mundo['sid']}:otro")

    # entrega: token guardado solo como hash, mensaje a wa-salida y bitácora del sistema
    [msg] = salidas(datos, "CONSTANCIA_ENLACE")
    token = msg["enlace"].rsplit("/", 1)[1]
    assert msg["enlace"].startswith("https://cc.prueba.test/d/") and len(token) == 43
    hashes = sql(datos, "SELECT token_hash, generado_por FROM constancias.token_descarga "
                 "WHERE constancia_id = %s", (cid,))  # fmt: skip
    assert [(bytes(h), g) for h, g in hashes] == [(hashlib.sha256(token.encode()).digest(), "BOT")]
    assert sql(datos, "SELECT estado FROM constancias.solicitud_constancia WHERE id = %s",
               (mundo["sid"],)) == [("GENERADA",)]  # fmt: skip
    bit = sql(datos, "SELECT origen, usuario_id, detalle FROM auditoria.bitacora "
              "WHERE accion = 'CONSTANCIA_GENERADA'")  # fmt: skip
    assert bit[0][:2] == ("SISTEMA", None) and bit[0][2]["folio"] == folio


async def test_repetir_el_mensaje_no_crea_otra_constancia_y_los_cambios_no_la_alteran(
    datos, mundo, colaboradores
):
    await mundo["correr"]()
    antes = constancia(datos, mundo["sid"])
    colaboradores.valores[mundo["col"]]["nombre_completo"] = "Otro Nombre"
    assert await mundo["correr"]() == "IGNORADA"
    assert constancia(datos, mundo["sid"]) == antes
    assert len(salidas(datos, "CONSTANCIA_ENLACE")) == 1


async def test_falla_reintenta_reutiliza_folio_y_al_agotar_intentos_queda_fallida(
    datos, mundo, motor, cfg, s3_plantillas, s3_constancias, cifrador, campos, colaboradores
):
    recursos = {
        "almacen": s3_plantillas[0], "almacen_constancias": s3_constancias[0],
        "cifrador": cifrador, "campos": campos, "colaboradores": colaboradores,
        "cargador_logotipo": None, "generar_pdf": FalsoPdf(fallos=9),
    }  # fmt: skip

    async def intento(n):
        return await atender(
            motor, cfg, recepciones=n, empresa_id=datos["a"], solicitud_id=mundo["sid"], **recursos
        )

    for n in (1, 2):
        with pytest.raises(RuntimeError):
            await intento(n)  # SQS reentrega
    folio_reservado = sql(datos, "SELECT folio_reservado FROM constancias.solicitud_constancia "
                          "WHERE id = %s", (mundo["sid"],))[0][0]  # fmt: skip
    assert folio_reservado is not None
    assert await intento(3) == "FALLIDA"
    assert sql(datos, "SELECT estado, motivo_fallo FROM constancias.solicitud_constancia "
               "WHERE id = %s", (mundo["sid"],)) == [("FALLIDA", "ERROR_RENDER")]  # fmt: skip
    assert constancia(datos, mundo["sid"]) == []
    [aviso] = salidas(datos, "constancia.fallida")
    assert aviso["motivo"] == "ERROR_RENDER" and aviso["solicitud_id"] == mundo["sid"]
    ultimo = sql(datos, "SELECT ultimo FROM constancias.contador_folio")
    assert ultimo == [(1,)]  # los tres intentos consumieron un solo folio


async def test_plantilla_alterada_en_s3_se_rechaza(datos, mundo, s3_plantillas):
    almacen = s3_plantillas[0]
    clave = sql(datos, "SELECT contenido_s3_key FROM constancias.version_plantilla "
                "WHERE plantilla_id = %s", (mundo["pid"],))[0][0]  # fmt: skip
    almacen._s3.put_object(Bucket=almacen._bucket, Key=clave, Body=b'{"esquema":1,"bloques":[]}')
    with pytest.raises(ErrorInterno):
        await mundo["correr"]()
    assert constancia(datos, mundo["sid"]) == []


async def test_datos_que_faltan_en_el_worker_dejan_la_solicitud_fallida(
    datos, mundo, colaboradores
):
    colaboradores.valores[mundo["col"]].pop("nss")
    assert await mundo["correr"]() == "FALLIDA"
    assert sql(datos, "SELECT motivo_fallo FROM constancias.solicitud_constancia WHERE id = %s",
               (mundo["sid"],)) == [("CAMPOS_FALTANTES",)]  # fmt: skip
