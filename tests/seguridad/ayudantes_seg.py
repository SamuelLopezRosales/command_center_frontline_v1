"""Ayudantes de las pruebas de seguridad (T-143).

- ``contrato(servicio)``: el OpenAPI de ``contracts/openapi/<servicio>.json`` (fuente de la lista de rutas).
- ``generar_cuerpo``: cuerpo mínimo válido de una operación a partir de su esquema.
- ``poblar``: crea datos de la empresa A en los seis servicios (con marcas únicas) y devuelve sus ids.
- ``tokens_malos``: la colección de tokens de usuario que ninguna ruta pública debe aceptar.
"""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

import jwt
from ayudantes_e2e import CLIENTE, CONTENIDO_PLANTILLA, EMISOR, LLAVE_JWT, NSS_A, SECRETO_INTERNO
from ayudantes_e2e_notif import CELULARES, wa_id
from cryptography.hazmat.primitives.asymmetric import rsa

RAIZ = Path(__file__).resolve().parents[2]
SERVICIOS = ("campos", "colaboradores", "constancias", "dashboard", "notificaciones", "whatsapp")
METODOS = ("get", "post", "put", "patch", "delete")

# Marcas que solo existen en la empresa A: ninguna respuesta a la empresa B debe contenerlas.
MARCAS_A = {
    "plantilla_constancia": "PLANTILLA-SOLO-A",
    "audiencia": "AUDIENCIA-SOLO-A",
    "notificacion": "AVISO-SOLO-A",
    "plantilla_mensaje": "marca_solo_a",
    "campo": "marca_a_secreta",
}


def contrato(servicio: str) -> dict:
    return json.loads((RAIZ / "contracts" / "openapi" / f"{servicio}.json").read_text("utf-8"))


def operaciones(servicio: str):
    """``(metodo, ruta, operacion)`` de cada operación del contrato."""
    for ruta, item in contrato(servicio)["paths"].items():
        for metodo in METODOS:
            if metodo in item:
                yield metodo.upper(), ruta, item[metodo]


# --------------------------------------------------------------------------- cuerpos de ejemplo


def _resolver(esquema: dict, comp: dict) -> dict:
    while "$ref" in esquema:
        esquema = comp[esquema["$ref"].rsplit("/", 1)[1]]
    return esquema


def ejemplo(esquema: dict, comp: dict, nivel: int = 0) -> Any:
    esquema = _resolver(esquema, comp)
    for clave in ("anyOf", "oneOf"):
        if clave in esquema:
            opciones = [o for o in esquema[clave] if _resolver(o, comp).get("type") != "null"]
            return ejemplo(opciones[0], comp, nivel + 1)
    if "enum" in esquema:
        return esquema["enum"][0]
    if "const" in esquema:
        return esquema["const"]
    tipo = esquema.get("type")
    if tipo == "object" or "properties" in esquema:
        props = esquema.get("properties", {})
        return {
            k: ejemplo(props[k], comp, nivel + 1)
            for k in esquema.get("required", [])
            if k in props and nivel < 6
        }
    if tipo == "array":
        return []
    if tipo == "integer":
        return max(1, int(esquema.get("minimum", 1)))
    if tipo == "number":
        return 1
    if tipo == "boolean":
        return True
    formato = esquema.get("format")
    if formato == "date":
        return "2026-01-15"
    if formato == "date-time":
        return "2026-11-17T20:00:00+00:00"
    return "x" * max(1, int(esquema.get("minLength", 1)))


def cuerpo_de(servicio: str, operacion: dict) -> Any | None:
    cuerpo = operacion.get("requestBody")
    if not cuerpo:
        return None
    contenido = cuerpo["content"].get("application/json")
    if contenido is None:
        return None
    return ejemplo(contenido["schema"], contrato(servicio)["components"]["schemas"])


def consulta_de(servicio: str, operacion: dict) -> dict[str, Any]:
    """Parámetros de consulta obligatorios con un valor cualquiera."""
    comp = contrato(servicio)["components"]["schemas"]
    salida = {}
    for p in operacion.get("parameters", []):
        if p["in"] == "query" and p.get("required"):
            salida[p["name"]] = ejemplo(p["schema"], comp)
    return salida


# --------------------------------------------------------------------------- tokens


def _firmar(claims: dict, llave=LLAVE_JWT, alg="RS256", cabeceras=None) -> str:
    return jwt.encode(claims, llave, algorithm=alg, headers=cabeceras)


def claims_validos(emp: int = 1, usr: int = 1, **cambios) -> dict:
    ahora = int(time.time())
    base = {
        "sub": "sub-prueba",
        "iss": EMISOR,
        "client_id": CLIENTE,
        "token_use": "access",
        "iat": ahora,
        "exp": ahora + 900,
        "jti": uuid.uuid4().hex,
        "empresa_id": str(emp),
        "rol": "RH",
        "usuario_id": str(usr),
    }
    base.update(cambios)
    return {k: v for k, v in base.items() if v is not None}


def _sin_firma(claims: dict) -> str:
    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims)}."


def tokens_malos(empresa_id: int, usuario_id: int) -> dict[str, str | None]:
    """Nombre -> valor del encabezado ``Authorization`` (``None``: sin encabezado)."""
    otra_llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ahora = int(time.time())
    v = claims_validos(empresa_id, usuario_id)
    return {
        "sin_encabezado": None,
        "esquema_basic": "Basic dXN1YXJpbzpjbGF2ZQ==",
        "bearer_vacio": "Bearer ",
        "basura": "Bearer esto-no-es-un-jwt",
        "firmado_con_otra_llave": "Bearer " + _firmar(v, otra_llave),
        "expirado": "Bearer "
        + _firmar(claims_validos(empresa_id, usuario_id, iat=ahora - 4000, exp=ahora - 3000)),
        "client_id_incorrecto": "Bearer "
        + _firmar(claims_validos(empresa_id, usuario_id, client_id="otro-cliente")),
        "sin_client_id": "Bearer "
        + _firmar(claims_validos(empresa_id, usuario_id, client_id=None)),
        "token_use_id": "Bearer " + _firmar(claims_validos(empresa_id, usuario_id, token_use="id")),
        "emisor_incorrecto": "Bearer "
        + _firmar(
            claims_validos(
                empresa_id,
                usuario_id,
                iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_OTRO",
            )
        ),
        "sin_empresa_id": "Bearer "
        + _firmar(claims_validos(empresa_id, usuario_id, empresa_id=None)),
        "empresa_id_no_numerico": "Bearer "
        + _firmar(claims_validos(empresa_id, usuario_id, empresa_id="1 OR 1=1")),
        "alg_none": "Bearer " + _sin_firma(v),
        "hs256_con_el_secreto_interno": "Bearer " + _firmar(v, SECRETO_INTERNO, "HS256"),
        "token_interno_de_servicio": "Bearer " + _token_interno("colaboradores"),
    }


def _token_interno(servicio: str, **cambios) -> str:
    from cc_common.internal_client import AUDIENCIA

    ahora = int(time.time())
    claims = {"iss": servicio, "aud": AUDIENCIA, "iat": ahora, "exp": ahora + 60,
              "jti": uuid.uuid4().hex}  # fmt: skip
    claims.update(cambios)
    return _firmar(claims, SECRETO_INTERNO, "HS256")


def tokens_internos_malos(permitidos: frozenset[str], empresa_id: int, usuario_id: int):
    """Encabezados ``Authorization`` que ``/internal/*`` debe rechazar con 401."""
    ahora = int(time.time())
    ajeno = next(s for s in ("whatsapp", "constancias", "dashboard", "campos", "colaboradores",
                             "notificaciones") if s not in permitidos)  # fmt: skip
    return {
        "sin_encabezado": None,
        "token_de_usuario_rh": "Bearer " + _firmar(claims_validos(empresa_id, usuario_id)),
        "basura": "Bearer abc",
        "servicio_no_autorizado": "Bearer " + _token_interno(ajeno),
        "servicio_inexistente": "Bearer " + _token_interno("intruso"),
        "sin_servicio": "Bearer " + _token_interno("", iss=""),
        "secreto_incorrecto": "Bearer "
        + _firmar(
            {"iss": sorted(permitidos)[0], "aud": "cc-interno", "iat": ahora, "exp": ahora + 60},
            "otro-secreto-de-prueba-0123456789-abcdefghi",
            "HS256",
        ),
        "audiencia_incorrecta": "Bearer " + _token_interno(sorted(permitidos)[0], aud="otra"),
        "expirado": "Bearer "
        + _token_interno(sorted(permitidos)[0], iat=ahora - 4000, exp=ahora - 3000),
        "alg_none": "Bearer "
        + _sin_firma(
            {"iss": sorted(permitidos)[0], "aud": "cc-interno", "iat": ahora, "exp": ahora + 60}
        ),
        "rs256_con_la_llave_de_usuarios": "Bearer "
        + _firmar(
            {"iss": sorted(permitidos)[0], "aud": "cc-interno", "iat": ahora, "exp": ahora + 60}
        ),
    }


# --------------------------------------------------------------------------- datos de la empresa A


def sql(w, consulta: str, params=()):
    return w.sql(consulta, params)


async def poblar(w) -> dict[str, dict[str, Any]]:
    """Datos de la empresa A en los seis servicios. Devuelve, por servicio, el valor de cada
    parámetro de ruta (``colaborador_id``, ``carga_id``...)."""
    A = w.a
    ids: dict[str, dict[str, Any]] = {s: {} for s in SERVICIOS}

    # campos: un campo LISTA con una opción (marca única de A)
    # SQL y no la API: el contador de códigos internos de `campos` choca con los campos sembrados
    # por el mundo de prueba (CAMP-0001 y CAMP-0002).
    campo = sql(
        w,
        "INSERT INTO campos.campo_colaborador (empresa_id, nombre_campo, clave, codigo_interno, "
        "tipo_dato, orden, es_sensible) VALUES (%s, 'Marca A', %s, 'CAMP-0090', 'LISTA', 9, false) "
        "RETURNING id",
        (A.id, MARCAS_A["campo"]),
    )[0][0]
    opcion = sql(
        w,
        "INSERT INTO campos.opcion_campo (empresa_id, campo_id, etiqueta, valor) "
        "VALUES (%s, %s, 'Opcion A', 'OPCION_A') RETURNING id",
        (A.id, campo),
    )[0][0]
    ids["campos"] = {"campo_id": campo, "opcion_id": opcion}
    w.app_col.state.campos.invalidar()

    # colaboradores: organización, planta, colaborador y una carga con un error
    carga = sql(
        w,
        "INSERT INTO colaboradores.carga_colaboradores (empresa_id, usuario_id, nombre_archivo, "
        "version_plantilla, total_filas, filas_error, estado) VALUES (%s, %s, 'a.xlsx', '1.3', 1, 1, "
        "'TERMINADA') RETURNING id",
        (A.id, A.usuario_id),
    )[0][0]
    sql(
        w,
        "INSERT INTO colaboradores.fila_carga (empresa_id, carga_id, numero_fila, resultado, mensaje) "
        "VALUES (%s, %s, 3, 'ERROR', 'E_CODIGO: mensaje')",
        (A.id, carga),
    )
    ids["colaboradores"] = {
        "colaborador_id": A.colaborador_id,
        "organizacion_id": A.organizacion_id,
        "planta_id": A.planta_id,
        "carga_id": carga,
    }

    # constancias: la plantilla activa se renombra con la marca y se hace un flujo completo
    plantilla = A.plantillas["Constancia laboral"]
    r = await w.http_con.patch(
        f"/api/v1/plantillas/{plantilla}",
        json={"nombre": MARCAS_A["plantilla_constancia"]},
        headers=A.rh,
    )
    assert r.status_code == 200, r.text
    r = await w.http_con.put(
        f"/api/v1/plantillas/{plantilla}/borrador", json=CONTENIDO_PLANTILLA, headers=A.rh
    )
    assert r.status_code == 200, r.text  # un borrador sobre la versión activa
    await w.decir("constancia")
    await w.decir(f"{w.codigo_recibido()} {NSS_A[-4:]}")
    await w.estado_meta(w.wamid_del_enlace(), "delivered")
    constancia = sql(
        w, "SELECT id FROM constancias.constancia_generada WHERE empresa_id = %s", (A.id,)
    )[0][0]
    ids["constancias"] = {"plantilla_id": plantilla, "numero": 1, "constancia_id": constancia}

    # notificaciones: plantilla de mensaje aprobada, audiencia, notificación enviada y respuesta
    pid = await w.plantilla_aprobada(MARCAS_A["plantilla_mensaje"])
    r = await w.http_not.post(
        "/api/v1/audiencias",
        json={"nombre": MARCAS_A["audiencia"],
              "criterios": {"op": "Y", "items": [{"campo": "planta_id", "operador": "es",
                                                  "valor": w.planta_notif}]}},
        headers=A.rh,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    audiencia = r.json()["id"]
    nid = await w.crear_notificacion(pid, titulo=MARCAS_A["notificacion"])
    await w.revisar(nid)
    r = await w.confirmar(nid, modo_envio="AHORA")
    assert r.status_code == 202, r.text
    await w.bombear("poblar: envío de la notificación")
    await w.decir("Gracias, ahí estaré", wa_id=wa_id(CELULARES["carla"]))
    conversacion = sql(
        w, "SELECT id FROM whatsapp.conversacion_whatsapp WHERE empresa_id = %s", (A.id,)
    )
    ids["notificaciones"] = {"plantilla_id": pid, "audiencia_id": audiencia, "notificacion_id": nid}
    ids["whatsapp"] = {"conversacion_id": max(c[0] for c in conversacion)}
    ids["dashboard"] = {"usuario_id": A.usuario_id}
    return ids


def cliente_de(w, servicio: str):
    return {
        "campos": w.http_campos,
        "colaboradores": w.http_col,
        "constancias": w.http_con,
        "dashboard": w.http_dash,
        "notificaciones": w.http_not,
        "whatsapp": w.http_wa,
    }[servicio]


def app_de(w, servicio: str):
    return {
        "campos": w.app_campos,
        "colaboradores": w.app_col,
        "constancias": w.app_con,
        "dashboard": w.http_dash._transport.app,
        "notificaciones": w.app_not,
        "whatsapp": w.app_wa,
    }[servicio]


# --------------------------------------------------------------------------- revisión de logs

# Patrones genéricos de datos personales y secretos (design.md §11.5, §15.1): valen aunque no se
# conozca de antemano el valor concreto.
PATRONES_PROHIBIDOS: dict[str, re.Pattern[str]] = {
    "celular (10 dígitos, con 52 o 521)": re.compile(r"(?<!\d)(?:521?)?\d{10}(?!\d)"),
    "NSS (11 dígitos)": re.compile(r"(?<!\d)\d{11}(?!\d)"),
    "CURP": re.compile(r"\b[A-Z]{4}\d{6}[HMX][A-Z]{5}[A-Z0-9]\d\b", re.I),
    "RFC": re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b", re.I),
    "correo": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "token de enlace (43 caracteres base64url)": re.compile(
        r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])"
    ),
    "ruta de descarga /d/<token>": re.compile(r"/d/[A-Za-z0-9_-]{20,}"),
    "JWT": re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."),
    "encabezado Authorization/Bearer": re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{10,}", re.I),
    "URL firmada (S3 o CloudFront)": re.compile(
        r"X-Amz-(?:Signature|Credential|Security-Token)|[?&]Signature=|Key-Pair-Id", re.I
    ),
    "llave de AWS": re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"),
}


def violaciones(texto: str, conocidos: dict[str, str]) -> list[str]:
    """Qué dato prohibido aparece en ``texto``. ``conocidos``: etiqueta -> valor exacto (celular,
    nombre, código...). Los nombres se buscan como palabra completa y sin importar mayúsculas."""
    halladas = []
    for etiqueta, valor in conocidos.items():
        if not valor:
            continue
        if re.fullmatch(r"[\wÁÉÍÓÚÜÑáéíóúüñ ]+", valor) and not valor.isdigit():
            patron = re.compile(rf"(?<!\w){re.escape(valor)}(?!\w)", re.I)
        else:
            patron = re.compile(rf"(?<![\w-]){re.escape(valor)}(?![\w-])" if valor.isdigit()
                                else re.escape(valor))  # fmt: skip
        if patron.search(texto):
            halladas.append(f"{etiqueta}: {valor!r}")
    for etiqueta, patron in PATRONES_PROHIBIDOS.items():
        m = patron.search(texto)
        if m:
            halladas.append(f"patrón {etiqueta}: ...{m.group(0)[:6]}...")
    return halladas
