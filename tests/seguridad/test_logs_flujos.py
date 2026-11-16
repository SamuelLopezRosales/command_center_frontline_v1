"""T-143 (CC-REQ-162, CC-NFR-010; design.md §11.5, §15.1): revisión de los logs de los flujos completos.

Se recorren con las piezas reales (el mismo mundo de ``tests/e2e``) los flujos de la constancia y de la
notificación, más los caminos de error (datos incorrectos, bloqueo, número desconocido, fallo de envío)
y las consultas de RH, y se captura TODO lo que se registra:

- los registros de ``logging`` (``caplog``), con INFO para todo y DEBUG para los registradores del
  producto (``cc.*`` y las Lambdas), que es más estricto que producción;
- la salida estándar y de error (las métricas EMF y cualquier ``print``).

Y se afirma que NO aparece: celular (10 dígitos, con 52 o 521), nombres de los colaboradores, RFC,
CURP, NSS, textos de mensajes (los que vio el colaborador y los que escribió), tokens de enlace,
códigos de verificación (del bot y del QR), URLs firmadas ni el JWT. Los valores buscados son los de
los datos de prueba (ficticios) y además se buscan por patrón, para que valga con datos que no se
conocían de antemano.
"""

import logging

import pytest
from ayudantes_e2e import (
    CELULAR_A,
    CELULAR_B,
    NSS_A,
    NSS_B,
    SECRETO_INTERNO,
    WA_ID_A,
    WA_ID_B,
    texto_de,
)
from ayudantes_e2e_notif import CELULARES, CORREOS, wa_id
from ayudantes_seg import PATRONES_PROHIBIDOS, poblar, violaciones

pytestmark = pytest.mark.docker

ROSA = {
    "celular": "8155550001", "nss": "55544433322", "rfc": "ROPM900101AB1",
    "curp": "ROPM900101MNLSXX09", "nombres": "Rosalinda", "paterno": "Ximénez", "materno": "Quiroga",
}  # fmt: skip
NOMBRES = ["Ana", "Beto", "Carla", "Dario", "Darío", "Elena", "Notif", "Pérez", "Perez", "Luna",
           ROSA["nombres"], ROSA["paterno"], ROSA["materno"]]  # fmt: skip
REGISTRADORES = ("cc", "webhook_meta", "enviador", "estados_entrega", "despachador",
                 "respaldo_correo", "conciliador")  # fmt: skip


class Recolector(logging.Handler):
    """Guarda TODO lo registrado: mensaje, argumentos, campos extra y traza (``caplog`` solo guarda
    la fase de la prueba en curso y con el nivel que pytest fija; aquí no se pierde nada)."""

    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.registros: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.registros.append(record)

    def texto(self) -> str:
        formato = logging.Formatter("%(name)s %(levelname)s %(message)s")
        estandar = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}
        lineas = []
        for r in self.registros:
            extras = {k: v for k, v in r.__dict__.items() if k not in estandar}  # ``extra=...``
            lineas.append(f"{formato.format(r)} || args={r.args!r} extras={extras!r}")
        return chr(10).join(lineas)


def test_el_revisor_detecta_lo_que_debe_detectar():
    """Control negativo: sin esta prueba, un revisor roto aprobaría cualquier log."""
    malo = (
        "envío a 8112345678 y 5218112345678 (+52 81) NSS 12345678901 CURP ROPM900101MNLSXX09 "
        "RFC ROPM900101AB1 correo ana@ejemplo.test /d/" + "A" * 43 + " "
        "https://x.cloudfront.net/c.pdf?Expires=1&Signature=abc&Key-Pair-Id=K "
        "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.firma-larga-1234"  # pragma: allowlist secret
    )
    hallado = " | ".join(violaciones(malo, {"nombre": "Ana"}))
    for esperado in ("celular", "NSS", "CURP", "RFC", "correo", "token de enlace", "ruta de descarga",
                     "URL firmada", "JWT", "Bearer", "nombre"):  # fmt: skip
        assert esperado in hallado, esperado
    limpio = (
        "constancia 17 solicitud 3 colaborador_id=4 empresa_id=1 folio CG-2026-0001 estado ENVIADO"
    )
    assert violaciones(limpio, {"nombre": "Ana"}) == []
    assert len(PATRONES_PROHIBIDOS) >= 10


async def _alta_rosa(w) -> int:
    """Colaboradora con RFC, CURP y NSS (campos sensibles) para que sus valores pasen por el flujo."""
    for codigo, clave, nombre in (("CAMP-0003", "rfc", "RFC"), ("CAMP-0004", "curp", "CURP")):
        w.sql(
            "INSERT INTO campos.campo_colaborador (empresa_id, nombre_campo, clave, codigo_interno, "
            "tipo_dato, orden, es_sensible) VALUES (%s, %s, %s, %s, 'TEXTO', 5, true)",
            (w.a.id, nombre, clave, codigo),
        )
    w.app_col.state.campos.invalidar()
    r = await w.http_col.post(
        "/api/v1/colaboradores",
        json={
            "numero_empleado": "ROSA-1", "nombres": ROSA["nombres"],
            "apellido_paterno": ROSA["paterno"], "apellido_materno": ROSA["materno"],
            "celular": ROSA["celular"], "organizacion_id": w.a.organizacion_id,
            "planta_id": w.a.planta_id, "fecha_ingreso": "2019-06-01", "puesto": "Analista",
            "tipo_empleado": "ADMINISTRATIVO", "consentimiento": True,
            "campos": {"CAMP-0001": ROSA["nss"], "CAMP-0003": ROSA["rfc"], "CAMP-0004": ROSA["curp"]},
        },
        headers=w.a.rh,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _recorrer(w) -> dict[str, set[str]]:
    """Recorre los flujos y devuelve los secretos que fueron apareciendo (códigos, tokens...)."""
    secretos: dict[str, set[str]] = {"codigos": set(), "tokens": set(), "qr": set(), "urls": set()}
    await poblar(w)  # constancia de Ana, notificación a Ana/Beto/Carla, chat y datos de A
    secretos["codigos"].add(w.codigo_recibido())
    secretos["tokens"].add(w.enlace_recibido().rsplit("/", 1)[1])

    # --- la colaboradora con RFC, CURP y NSS pide su constancia (código, dato, PDF, enlace)
    rosa_id = await _alta_rosa(w)
    wa_rosa = "521" + ROSA["celular"]
    await w.decir("constancia", wa_id=wa_rosa)
    codigo = w.codigo_recibido(wa_rosa)
    secretos["codigos"].add(codigo)
    await w.decir(f"{codigo} {ROSA['nss'][-4:]}", wa_id=wa_rosa)
    enlace = w.enlace_recibido()
    secretos["tokens"].add(enlace.rsplit("/", 1)[1])
    await w.estado_meta(w.wamid_del_enlace(), "delivered", destinatario=wa_rosa)
    await w.estado_meta(w.wamid_del_enlace(), "read", destinatario=wa_rosa)
    token = enlace.rsplit("/", 1)[1]
    secretos["qr"] |= {
        f[0] for f in w.sql("SELECT codigo_verificacion FROM constancias.constancia_generada")
    }

    # --- el colaborador abre y consume el enlace; verificación pública del QR
    assert (await w.http_con.get(f"/d/{token}")).status_code == 200
    r = await w.http_con.post(f"/d/{token}/descargar")
    assert r.status_code == 302
    secretos["urls"].add(r.headers["location"])
    assert (await w.http_con.post(f"/d/{token}/descargar")).status_code == 410
    for qr in secretos["qr"]:
        assert (await w.http_con.get(f"/api/v1/publico/verificar/{qr}")).status_code == 200
    assert (await w.http_con.get("/api/v1/publico/verificar/" + "Z" * 22)).status_code == 404

    # --- consultas de RH (todas pasan por el registro de la aplicación y por la bitácora)
    r = await w.http_col.get(f"/api/v1/colaboradores/{rosa_id}", params={"incluir_sensibles": True},
                             headers=w.a.rh)  # fmt: skip
    assert r.status_code == 200 and ROSA["rfc"] in r.text  # la API sí los devuelve a RH
    await w.http_col.get("/api/v1/colaboradores", params={"q": ROSA["nombres"]}, headers=w.a.rh)
    await w.http_col.get("/api/v1/colaboradores", params={"q": "ROSA-1"}, headers=w.a.rh)
    constancias = (await w.http_dash.get("/api/v1/constancias/historial", headers=w.a.rh)).json()
    for item in constancias["items"]:
        r = await w.http_con.post(f"/api/v1/constancias/{item['id']}/descarga", headers=w.a.rh)
        if r.status_code == 200:
            secretos["urls"].add(r.text)
    for ruta in ("/api/v1/dashboard/resumen", "/api/v1/dashboard/alertas", "/api/v1/bitacora"):
        assert (await w.http_dash.get(ruta, headers=w.a.rh)).status_code == 200
    plantilla = next(iter(w.a.plantillas.values()))
    r = await w.http_con.post(
        f"/api/v1/plantillas/{plantilla}/vista-previa",
        json={"colaborador_id": rosa_id, "version": 1}, headers=w.a.rh,
    )  # fmt: skip
    assert r.status_code == 200

    # --- caminos de error: datos incorrectos hasta el bloqueo, número desconocido, empresa B
    await w.decir("constancia", wa_id=w.a.wa_id)
    secretos["codigos"].add(w.codigo_recibido())
    for _ in range(3):
        await w.decir(f"{w.codigo_recibido()} 0000", wa_id=w.a.wa_id)
    await w.decir("constancia", wa_id="5219999999999")
    await w.decir("hola", wa_id=wa_id(CELULARES["beto"]))
    return secretos


def _conocidos(w, secretos) -> dict[str, str]:
    conocidos = {
        "celular A": CELULAR_A, "wa_id A": WA_ID_A, "celular B": CELULAR_B, "wa_id B": WA_ID_B,
        "NSS A": NSS_A, "NSS B": NSS_B, "NSS Rosa": ROSA["nss"], "RFC Rosa": ROSA["rfc"],
        "CURP Rosa": ROSA["curp"], "celular Rosa": ROSA["celular"], "wa_id Rosa": "521" + ROSA["celular"],
        "número desconocido": "5219999999999", "secreto interno": SECRETO_INTERNO,
        "secreto de la app de Meta": w.sim.app_secret, "token de Meta": w.sim.access_token,
        "token de verificación de Meta": w.sim.verify_token,
    }  # fmt: skip
    conocidos |= {f"celular {n}": c for n, c in CELULARES.items()}
    conocidos |= {f"wa_id {n}": wa_id(c) for n, c in CELULARES.items()}
    conocidos |= {f"correo {n}": c for n, c in CORREOS.items()}
    conocidos |= {f"nombre {n}": n for n in NOMBRES}
    conocidos |= {f"código de verificación {c}": c for c in secretos["codigos"]}
    conocidos |= {f"token {t[:6]}...": t for t in secretos["tokens"]}
    conocidos |= {f"código QR {q[:6]}...": q for q in secretos["qr"]}
    conocidos |= {f"URL firmada {u[:30]}...": u for u in secretos["urls"] if u}
    # textos de mensajes: todo lo que Meta entregó a un colaborador (bot, plantillas, chat de RH)
    textos = {texto_de(e) for e in w.sim.enviados}
    conocidos |= {f"texto enviado {t[:25]}...": t for t in textos if len(t) >= 12}
    # y lo que escribieron los colaboradores y RH
    conocidos |= {
        "texto del colaborador": "Gracias, ahí estaré",
        "texto de RH": "Perfecto, te esperamos puntual.",
    }
    return conocidos


async def test_los_logs_de_los_flujos_completos_no_contienen_datos_personales_ni_secretos(
    mundo_seg, caplog, capfd
):
    w = mundo_seg
    recolector = Recolector()
    raiz = logging.getLogger()
    nivel_raiz = raiz.level
    raiz.addHandler(recolector)
    raiz.setLevel(logging.INFO)
    for nombre in ("httpx", "httpcore", "botocore", "urllib3", "asyncio"):
        logging.getLogger(nombre).setLevel(logging.WARNING)  # ruido de las propias herramientas
    niveles = {n: logging.getLogger(n).level for n in REGISTRADORES}
    for nombre in REGISTRADORES:
        logging.getLogger(nombre).setLevel(logging.DEBUG)  # más estricto que producción (INFO)
    try:
        secretos = await _recorrer(w)
        conv = w.sql(
            "SELECT max(id) FROM whatsapp.conversacion_whatsapp WHERE empresa_id = %s", (w.a.id,)
        )
        r = await w.http_wa.post(
            f"/api/v1/conversaciones/{conv[0][0]}/mensajes",
            json={"texto": "Perfecto, te esperamos puntual."}, headers=w.rh_a,
        )  # fmt: skip
        assert r.status_code in (202, 409)
        await w.bombear("RH responde")
    finally:
        raiz.removeHandler(recolector)
        raiz.setLevel(nivel_raiz)
        for nombre, nivel in niveles.items():
            logging.getLogger(nombre).setLevel(nivel)

    salida = capfd.readouterr()
    visto = chr(10).join([recolector.texto(), caplog.text, salida.out, salida.err])

    # controles positivos: se capturó de verdad (si no, esta prueba no demostraría nada)
    assert len(recolector.registros) >= 5, "casi no se registró nada: ¿se capturaron los logs?"
    assert "envios_ok" in salida.out and "webhook_mensajes_encolados" in salida.out
    assert {r_.name.split(".")[0] for r_ in recolector.registros} >= {"cc"}

    conocidos = _conocidos(w, secretos)
    assert len([c for c in conocidos if c.startswith("texto enviado")]) >= 5
    problemas = violaciones(visto, conocidos)
    assert not problemas, "datos personales o secretos en los logs:\n" + "\n".join(problemas)
