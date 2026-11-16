"""T-143 (CC-REQ-074, 084, 090, 159; design.md §7.2, §11.3): enumeración y fuerza bruta de códigos.

- Código de verificación del bot (6 dígitos): límite de intentos, bloqueo que ni el dato correcto
  levanta, respuesta idéntica sin importar qué mitad falló, y vencido igual a inexistente.
- Token del enlace de descarga (``/d/{token}``) y código de verificación pública del QR
  (``/api/v1/publico/verificar/{codigo}``): entropía suficiente y 404 idéntico para cualquier valor
  que no exista (sin pistas sobre el formato).

Sin pruebas de tiempos: no son estables. La limitación por IP de las rutas públicas la da AWS WAF
(design.md §11.4, 100 solicitudes por 5 minutos [POR CONFIRMAR]); se verifica en la capa de
infraestructura (T-225/T-226) y en ``test`` (T-229/T-230), no aquí.
"""

import re
import secrets

import pytest
from ayudantes_e2e import LLAVE_CODIGOS, NSS_A
from cc_whatsapp.bot import mensajes_es as M
from cc_whatsapp.bot.verificacion import generar_codigo, hmac_codigo

pytestmark = pytest.mark.docker


def _conversacion(w):
    return w.sql(
        "SELECT id, estado, verificada, intentos_verificacion FROM whatsapp.conversacion_whatsapp "
        "WHERE empresa_id = %s ORDER BY id DESC LIMIT 1",
        (w.a.id,),
    )[0]


async def test_el_codigo_no_se_adivina_tres_intentos_y_bloqueo_que_el_dato_correcto_no_levanta(
    mundo_seg,
):
    w = mundo_seg
    await w.decir("constancia")
    codigo = w.codigo_recibido()
    otro = f"{(int(codigo) + 1) % 10**6:06d}"
    # (1) código incorrecto con el dato correcto y (2) código correcto con el dato incorrecto:
    # el mismo mensaje, para que nadie sepa cuál de las dos mitades acertó.
    await w.decir(f"{otro} {NSS_A[-4:]}")
    primer_mensaje = w.textos()[-1]
    await w.decir(f"{codigo} 0000")
    segundo_mensaje = w.textos()[-1]
    assert primer_mensaje == segundo_mensaje == M.DATOS_NO_COINCIDEN
    assert _conversacion(w)[1:] == ("VERIFICANDO", False, 2)
    # (3) tercer fallo: bloqueo de la conversación
    await w.decir(f"{otro} 0000")
    assert w.textos()[-1] == M.BLOQUEADO and _conversacion(w)[1:] == ("BLOQUEADA", False, 3)
    # con la conversación bloqueada ni el código ni el dato correctos la verifican
    for _ in range(3):
        await w.decir(f"{codigo} {NSS_A[-4:]}")
        assert w.textos()[-1] == M.BLOQUEADO
    estado = _conversacion(w)
    assert estado[1:3] == ("BLOQUEADA", False) and estado[3] == 3  # no siguió contando
    assert w.estado_solicitud() == []  # y no se generó nada
    assert not any(NSS_A[-4:] in t for t in w.textos())  # el bot no eco-repite el dato


async def test_codigo_vencido_e_inexistente_son_indistinguibles_y_no_cuentan_intento(mundo_seg):
    w = mundo_seg
    await w.decir("constancia")
    viejo = w.codigo_recibido()
    w.sql("UPDATE whatsapp.codigo_verificacion SET fecha_expira = now() - interval '1 minute'")
    await w.decir(f"{viejo} {NSS_A[-4:]}")
    por_vencido = w.textos()[-1]
    nuevo = w.codigo_recibido()
    assert nuevo != viejo
    # sin ningún código vigente (se invalidan todos)
    w.sql("UPDATE whatsapp.codigo_verificacion SET usado = true")
    await w.decir(f"{nuevo} {NSS_A[-4:]}")
    por_inexistente = w.textos()[-1]
    # mismo aviso (el código nuevo cambia, el resto del texto es el mismo)
    assert re.sub(r"\d{6}", "<codigo>", por_vencido) == re.sub(
        r"\d{6}", "<codigo>", por_inexistente
    )
    assert _conversacion(w)[3] == 0  # ni uno ni otro cuentan como intento
    # el código viejo ya no sirve aunque llegue después con el dato correcto
    await w.decir(f"{viejo} {NSS_A[-4:]}")
    assert _conversacion(w)[1:3] == ("VERIFICANDO", False)


def test_el_codigo_depende_de_la_conversacion_y_tiene_forma_fija():
    codigo = generar_codigo()
    assert re.fullmatch(r"\d{6}", codigo)
    h1 = hmac_codigo(LLAVE_CODIGOS, 1, codigo)
    assert h1 != hmac_codigo(LLAVE_CODIGOS, 2, codigo)  # un código de otra conversación no vale
    assert h1 != hmac_codigo(b"otra-llave-de-prueba-0123456789-abcdef", 1, codigo)
    assert codigo not in h1.hex()
    # son 10^6 combinaciones y 3 intentos: 3 en un millón por conversación, sin reintentos infinitos
    distintos = {generar_codigo() for _ in range(2000)}
    assert len(distintos) > 1900  # no es constante ni se repite de forma evidente


async def test_los_codigos_y_tokens_publicos_no_se_enumeran(mundo_seg):
    w = mundo_seg
    # una constancia real con enlace y código de verificación
    await w.decir("constancia")
    await w.decir(f"{w.codigo_recibido()} {NSS_A[-4:]}")
    token = w.enlace_recibido().rsplit("/", 1)[1]
    [(codigo_qr,)] = w.sql(
        "SELECT codigo_verificacion FROM constancias.constancia_generada WHERE empresa_id = %s",
        (w.a.id,),
    )
    assert len(token) == 43 and len(codigo_qr) >= 22  # 256 y 128 bits de azar

    # lo real sí responde (contraprueba) y solo con los datos mínimos del diseño
    r = await w.http_con.get(f"/api/v1/publico/verificar/{codigo_qr}")
    assert r.status_code == 200
    assert set(r.json()) == {"nombre", "folio", "fecha_emision", "estado"}
    assert NSS_A not in r.text and "8112345678" not in r.text

    def normal(r):  # el cuerpo sin el id de correlación, que cambia en cada respuesta
        return re.sub(r'"correlacion_id":"[^"]*"', "", r.text), r.status_code

    # todo lo que no existe responde exactamente igual, sea cual sea su forma
    inexistentes = [secrets.token_urlsafe(16) for _ in range(40)]  # forma válida
    mal_formados = ["a", "A" * 21, "A" * 65, "x y", "%00", "..%2F..", "' OR '1'='1", "ñ" * 22]
    esperado = normal(await w.http_con.get(f"/api/v1/publico/verificar/{inexistentes[0]}"))
    assert esperado[1] == 404
    for c in (
        inexistentes[1:] + mal_formados + [codigo_qr[:-1] + ("A" if codigo_qr[-1] != "A" else "B")]
    ):
        r = await w.http_con.get(f"/api/v1/publico/verificar/{c}")
        assert normal(r) == esperado, c
    # un token de descarga no sirve como código de verificación ni al revés
    assert (await w.http_con.get(f"/api/v1/publico/verificar/{token}")).status_code == 404

    ajenos = [secrets.token_urlsafe(32) for _ in range(40)]
    pagina = normal(await w.http_con.get(f"/d/{ajenos[0]}"))
    assert pagina[1] == 404
    consumo = normal(await w.http_con.post(f"/d/{ajenos[0]}/descargar"))
    assert consumo[1] == 404
    for t in ajenos[1:] + mal_formados + [token[:-1] + ("A" if token[-1] != "A" else "B")]:
        assert normal(await w.http_con.get(f"/d/{t}")) == pagina, t
        assert normal(await w.http_con.post(f"/d/{t}/descargar")) == consumo, t
    # el código de verificación (QR) no es un token de descarga
    assert (await w.http_con.get(f"/d/{codigo_qr}")).status_code == 404
    # y con el token real, intentar sin consumir no lo gasta
    assert (await w.http_con.get(f"/d/{token}")).status_code == 200
    # nada de lo anterior marcó la constancia como entregada ni cambió datos
    assert w.estado_solicitud()[0][1] == "GENERADA"
