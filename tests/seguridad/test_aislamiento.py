"""T-143 (CC-REQ-150, 153, CC-NFR-008): aislamiento por empresa y por token en TODA la API pública.

La lista de rutas sale de ``contracts/openapi/*.json`` (no se escribe a mano: una ruta nueva entra
sola a estas pruebas). Se usan los seis servicios reales como apps ASGI, PostgreSQL 16 con RLS y los
roles de servicio, y datos de la empresa A en todos los servicios (``ayudantes_seg.poblar``).

Qué se demuestra:

1. Con un token válido de la empresa B, toda ruta con id en el path responde 404 o 403 sobre datos
   de la empresa A, y no cambia ni un dato de la base.
2. Las listas de la empresa B no contienen nada de la A, aunque se envíe ``X-Empresa-Id`` o
   ``empresa_id`` de la A (la empresa sale solo del token).
3. Sin token, mal firmado, expirado, con ``client_id`` o ``token_use`` incorrectos, ``alg: none`` o un
   token interno: 401 en cada ruta de ``/api/v1``.
4. ``/internal/*`` rechaza tokens de usuario y tokens de servicios no autorizados (401).
"""

import re

import pytest
from ayudantes_e2e import SECRETO_INTERNO
from ayudantes_seg import (
    MARCAS_A,
    SERVICIOS,
    app_de,
    cliente_de,
    consulta_de,
    cuerpo_de,
    operaciones,
    poblar,
    tokens_internos_malos,
    tokens_malos,
)
from cc_common.auth import _aplanar  # recorrido de rutas incluso dentro de routers

pytestmark = pytest.mark.docker

PARAMETRO = re.compile(r"\{(\w+)\}")
# Rutas con token propio en la URL (enlaces de un solo uso y verificación pública): sin usuario.
PUBLICAS = ("/api/v1/publico/", "/d/")
# Rutas de ``/api/v1`` que no usan el token de Cognito de la forma normal; ninguna por ahora.
ESQUEMAS_EXENTOS: set[tuple[str, str]] = set()


def _publica(ruta: str) -> bool:
    return ruta.startswith(PUBLICAS)


def _con_ids(ruta: str, ids: dict) -> str:
    def sustituir(m: re.Match) -> str:
        nombre = m.group(1)
        assert nombre in ids, f"falta el id de prueba para {{{nombre}}} en {ruta}"
        return str(ids[nombre])

    return PARAMETRO.sub(sustituir, ruta)


def _con_unos(ruta: str) -> str:
    return PARAMETRO.sub("1", ruta)


def _rutas_api(con_ids: bool):
    for servicio in SERVICIOS:
        for metodo, ruta, op in operaciones(servicio):
            if ruta.startswith("/api/v1/") and not _publica(ruta):
                if con_ids == bool(PARAMETRO.search(ruta)):
                    yield servicio, metodo, ruta, op


def _volcado(w) -> list[str]:
    """Estado de los datos de negocio (sin outbox ni bitácora: las llamadas rechazadas pueden
    anotar un intento, pero no deben cambiar datos)."""
    lineas = w.volcado_de_la_base(
        esquemas=(
            "colaboradores",
            "campos",
            "constancias",
            "notificaciones",
            "whatsapp",
            "identidad",
        )
    ).splitlines()
    utiles = (ln for ln in lineas if ".outbox:" not in ln[:60] and "bitacora" not in ln[:60])
    # ``ultima_actividad`` del usuario que llama cambia con cada petición propia (no es de A)
    return sorted(
        re.sub(r'"ultima_actividad":"[^"]*"', '"ultima_actividad":null', ln) for ln in utiles
    )


def _cuerpos_a_medida(w) -> dict[tuple[str, str], dict]:
    """Cuerpos que el esquema por sí solo no deja válidos (reglas cruzadas del servicio)."""
    from cc_colaboradores.servicios.catalogos import _prefijo

    return {
        ("POST", "/api/v1/organizaciones/{organizacion_id}/logotipo"): {
            "content_type": "image/png", "tamano": 1000,
        },
        ("POST", "/api/v1/organizaciones/{organizacion_id}/logotipo/confirmar"): {
            "s3_key": _prefijo(w.b.id, w.a.organizacion_id) + "x.png",  # clave de B, id de A
        },
        ("POST", "/api/v1/plantillas/{plantilla_id}/vista-previa"): {
            "colaborador_id": w.a.colaborador_id, "version": 1,
        },
    }  # fmt: skip


async def _llamar(w, servicio, metodo, ruta, op, headers, cuerpo=None, **extra):
    cuerpo = cuerpo if cuerpo is not None else cuerpo_de(servicio, op)
    args = {"headers": headers, "params": consulta_de(servicio, op) | extra.get("params", {})}
    if cuerpo is not None and metodo in ("POST", "PUT", "PATCH"):
        args["json"] = cuerpo
    return await cliente_de(w, servicio).request(metodo, ruta, **args)


# --------------------------------------------------------------------------- 1 y 2: por empresa


async def test_la_empresa_b_no_alcanza_datos_de_la_empresa_a_en_ninguna_ruta(mundo_seg):
    w = mundo_seg
    ids = await poblar(w)
    antes = _volcado(w)
    cabeceras_b = w.b.rh | {"If-Match": '"1"'}
    a_medida = _cuerpos_a_medida(w)
    problemas: list[str] = []
    consultadas = 0

    # (1) toda ruta con id en el path, con el id de un dato de A
    for servicio, metodo, ruta, op in _rutas_api(con_ids=True):
        url = _con_ids(ruta, ids[servicio])
        r = await _llamar(
            w, servicio, metodo, url, op, cabeceras_b, cuerpo=a_medida.get((metodo, ruta))
        )
        consultadas += 1
        if r.status_code not in (403, 404):
            problemas.append(f"{servicio} {metodo} {url} -> {r.status_code} {r.text[:120]}")
        elif r.status_code == 404 and "codigo" not in r.text:
            # el 404 genérico del enrutador significaría que la ruta no existe, no que se aisló
            problemas.append(
                f"{servicio} {metodo} {url} -> 404 sin código de dominio: {r.text[:80]}"
            )
        elif any(m in r.text for m in MARCAS_A.values()):
            problemas.append(f"{servicio} {metodo} {url} filtra datos de A en el error")

    # (2) las listas de B no traen nada de A, aun pidiendo la empresa de A por encabezado y consulta
    marcas = [*MARCAS_A.values(), f"E-{w.a.id}", f"N-{w.a.id}-", "RH EmpresaA", "rh@empresaa.test"]
    engañosos = {"X-Empresa-Id": str(w.a.id), "X-Empresa": str(w.a.id)}
    for servicio, metodo, ruta, op in _rutas_api(con_ids=False):
        if metodo != "GET" or ruta.endswith("/plantilla"):
            continue
        r = await _llamar(
            w, servicio, metodo, ruta, op, cabeceras_b | engañosos,
            params={"empresa_id": w.a.id},
        )  # fmt: skip
        consultadas += 1
        if r.status_code >= 500:
            problemas.append(f"{servicio} GET {ruta} -> {r.status_code}")
        propias = [m for m in marcas if m in r.text]
        if propias:
            problemas.append(f"{servicio} GET {ruta} devuelve datos de A: {propias}")

    assert consultadas >= 60, f"se esperaban decenas de rutas del contrato, hubo {consultadas}"
    assert not problemas, "\n".join(problemas)

    # ninguna llamada de B cambió un dato de A
    assert _volcado(w) == antes

    # sanidad: con el token de A las mismas rutas GET sí encuentran los datos (los ids eran reales)
    sin_datos = []
    for servicio, metodo, ruta, op in _rutas_api(con_ids=True):
        if metodo != "GET":
            continue
        url = _con_ids(ruta, ids[servicio])
        r = await _llamar(w, servicio, metodo, url, op, w.a.rh)
        if r.status_code != 200:
            sin_datos.append(f"{servicio} GET {url} -> {r.status_code}")
    assert not sin_datos, "los datos de prueba de A no existen:\n" + "\n".join(sin_datos)


async def test_la_empresa_a_no_alcanza_los_datos_de_la_empresa_b_en_una_muestra(mundo_seg):
    """Simetría: el aislamiento no depende de qué empresa se creó primero."""
    w = mundo_seg
    b = w.b
    r = await w.http_col.get(f"/api/v1/colaboradores/{b.colaborador_id}", headers=w.a.rh)
    assert r.status_code == 404
    r = await w.http_con.get(
        f"/api/v1/plantillas/{next(iter(b.plantillas.values()))}", headers=w.a.rh
    )
    assert r.status_code == 404
    r = await w.http_col.get(f"/api/v1/organizaciones/{b.organizacion_id}", headers=w.a.rh)
    assert r.status_code in (404, 405)
    r = await w.http_col.get("/api/v1/colaboradores", headers=w.a.rh)
    assert all(i["id"] != b.colaborador_id for i in r.json()["items"])


# --------------------------------------------------------------------------- 3: tokens de usuario


async def test_ninguna_ruta_de_la_api_acepta_un_token_malo(mundo_seg):
    w = mundo_seg
    malos = tokens_malos(w.a.id, w.a.usuario_id)
    problemas: list[str] = []
    llamadas = 0
    for servicio in SERVICIOS:
        for metodo, ruta, op in operaciones(servicio):
            if not ruta.startswith("/api/v1/") or _publica(ruta):
                continue
            if (servicio, ruta) in ESQUEMAS_EXENTOS:
                continue
            for nombre, valor in malos.items():
                cabeceras = {} if valor is None else {"Authorization": valor}
                r = await _llamar(w, servicio, metodo, _con_unos(ruta), op, cabeceras)
                llamadas += 1
                if r.status_code != 401:
                    problemas.append(f"{servicio} {metodo} {ruta} [{nombre}] -> {r.status_code}")
    assert llamadas >= 14 * 60
    assert not problemas, "\n".join(problemas)


async def test_los_tokens_del_cuerpo_o_de_la_consulta_no_sustituyen_al_encabezado(mundo_seg):
    """Un token válido en la URL o en una cookie no autentica."""
    w = mundo_seg
    token = w.a.rh["Authorization"].split(" ", 1)[1]
    for extra in ({"params": {"access_token": token}}, {"cookies": {"Authorization": token}}):
        r = await w.http_col.get("/api/v1/colaboradores", **extra)
        assert r.status_code == 401


async def test_un_token_de_usuario_valido_sin_el_claim_de_empresa_o_con_rol_ajeno_no_pasa(
    mundo_seg,
):
    from ayudantes_seg import _firmar, claims_validos

    w = mundo_seg
    sin_empresa = "Bearer " + _firmar(claims_validos(w.a.id, w.a.usuario_id, empresa_id=None))
    r = await w.http_col.get("/api/v1/colaboradores", headers={"Authorization": sin_empresa})
    assert r.status_code == 401
    rol_ajeno = "Bearer " + _firmar(claims_validos(w.a.id, w.a.usuario_id, rol="ADMIN_GLOBAL"))
    r = await w.http_col.get("/api/v1/colaboradores", headers={"Authorization": rol_ajeno})
    assert r.status_code in (401, 403)


# --------------------------------------------------------------------------- 4: /internal/*


def _rutas_internas(w):
    """``(servicio, metodo, ruta, servicios_permitidos)`` leído de las apps (dependencia declarada)."""
    salida = []
    for servicio in SERVICIOS:
        for camino, ruta in _aplanar(app_de(w, servicio).routes):
            if not camino.startswith("/internal"):
                continue
            permiso = next(
                (
                    dep.call._permiso
                    for dep in ruta.dependant.dependencies
                    if str(getattr(dep.call, "_permiso", "")).startswith("interno:")
                ),
                None,
            )
            for metodo in sorted(ruta.methods or []):
                salida.append((servicio, metodo, camino, permiso))
    return salida


async def test_internal_rechaza_tokens_de_usuario_y_de_servicios_no_autorizados(mundo_seg):
    w = mundo_seg
    rutas = _rutas_internas(w)
    en_contrato = [
        (s_, m, r) for s_ in SERVICIOS for m, r, _ in operaciones(s_) if r.startswith("/internal")
    ]
    assert len(rutas) == len(en_contrato) >= 15, (len(rutas), len(en_contrato))
    sin_dependencia = [f"{s} {m} {p}" for s, m, p, perm in rutas if perm is None]
    assert not sin_dependencia, f"rutas /internal sin requiere_servicio: {sin_dependencia}"

    # el contrato y las apps declaran las mismas rutas internas
    declaradas = {(s, m, p) for s, m, p, _ in rutas}
    for servicio in SERVICIOS:
        for metodo, ruta, _op in operaciones(servicio):
            if ruta.startswith("/internal"):
                assert (servicio, metodo, ruta) in declaradas, f"{servicio} {metodo} {ruta}"

    problemas: list[str] = []
    for servicio, metodo, camino, permiso in rutas:
        permitidos = frozenset(permiso.removeprefix("interno:").split(","))
        op = next(
            (o for m, p, o in operaciones(servicio) if m == metodo and p == camino),
            {"parameters": []},
        )
        for nombre, valor in tokens_internos_malos(permitidos, w.a.id, w.a.usuario_id).items():
            cabeceras = {"X-Empresa-Id": str(w.a.id)}
            if valor is not None:
                cabeceras["Authorization"] = valor
            r = await _llamar(w, servicio, metodo, _con_unos(camino), op, cabeceras)
            if r.status_code != 401:
                problemas.append(f"{servicio} {metodo} {camino} [{nombre}] -> {r.status_code}")
    assert not problemas, "\n".join(problemas)


async def test_el_token_interno_de_un_servicio_autorizado_si_pasa_pero_exige_la_empresa(mundo_seg):
    """Contraprueba: el rechazo anterior se debe al token y no a otra causa (la ruta existe)."""
    from cc_common.internal_client import emitir_token_interno

    w = mundo_seg
    token = emitir_token_interno(SECRETO_INTERNO, "whatsapp")
    cab = {"Authorization": f"Bearer {token}"}
    sin_empresa = await w.http_col.post(
        "/internal/colaboradores/buscar-por-celular", json={"celular": "8112345678"}, headers=cab
    )
    assert sin_empresa.status_code == 422 and "EMPRESA_REQUERIDA" in sin_empresa.text
    con_empresa = await w.http_col.post(
        "/internal/colaboradores/buscar-por-celular",
        json={"celular": "8112345678"},
        headers=cab | {"X-Empresa-Id": str(w.a.id)},
    )
    assert con_empresa.status_code == 200, con_empresa.text


async def test_el_token_interno_no_sirve_en_las_rutas_publicas_y_el_de_usuario_tampoco_en_internas(
    mundo_seg,
):
    from cc_common.internal_client import emitir_token_interno

    w = mundo_seg
    interno = {"Authorization": "Bearer " + emitir_token_interno(SECRETO_INTERNO, "whatsapp")}
    assert (await w.http_col.get("/api/v1/colaboradores", headers=interno)).status_code == 401
    usuario = w.a.rh | {"X-Empresa-Id": str(w.a.id)}
    r = await w.http_col.post(
        "/internal/colaboradores/buscar-por-celular", json={}, headers=usuario
    )
    assert r.status_code == 401


def test_el_contrato_publico_no_expone_rutas_internas_sin_el_prefijo_internal():
    """Todo lo que no es ``/api/v1``, ``/d`` o ``/internal`` en los contratos es una excepción
    explícita (hoy ninguna)."""
    ajenas = []
    for servicio in SERVICIOS:
        for metodo, ruta, _ in operaciones(servicio):
            if not ruta.startswith(("/api/v1/", "/d/", "/internal/")):
                ajenas.append(f"{servicio} {metodo} {ruta}")
    assert not ajenas, ajenas
