"""Datos de ejemplo del stack local, para que el dashboard no salga vacío.

- ``sembrar_base``: empresa, campos sugeridos y usuarios de desarrollo (SQL con el usuario
  administrador de la base). Escribe ``.local/usuarios.json``, que lee la pasarela.
- ``sembrar_demo``: organizaciones, plantas, colaboradores (con y sin consentimiento) y una
  plantilla publicada. Va POR LA API a través de la pasarela, así que ejercita el cifrado, la
  validación y la bitácora reales. Es idempotente: no repite lo que ya existe.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from scripts.local import constantes as c
from scripts.local.aprovisionar import url_admin

ORGANIZACIONES = (
    {
        "clave": "MATRIZ",
        "razon_social": "Industrias Demo SA de CV",
        "rfc": "IDE210101AB1",
        "nombre_firmante": "Marta Solís Rivera",
        "cargo_firmante": "Gerente de Recursos Humanos",
        "ciudad": "Monterrey",
    },
    {"clave": "SERVICIOS", "razon_social": "Servicios Demo SA de CV", "rfc": "SDE220202CD2"},
)
PLANTAS = ("Planta Monterrey", "Planta Saltillo")

# (número, nombres, paterno, materno, celular, tipo, puesto, ingreso, org., planta, consent.)
COLABORADORES = (
    (
        "E-1001",
        "Carlos",
        "Hernández",
        "López",
        "5512345601",
        "OPERATIVO",
        "Operador",
        "2021-03-15",
        0,
        0,
        True,
    ),
    (
        "E-1002",
        "María",
        "García",
        "Torres",
        "5512345602",
        "ADMINISTRATIVO",
        "Analista de nómina",
        "2020-07-01",
        0,
        0,
        True,
    ),
    (
        "E-1003",
        "José",
        "Martínez",
        "Ruiz",
        "5512345603",
        "OPERATIVO",
        "Soldador",
        "2022-01-10",
        0,
        1,
        True,
    ),
    (
        "E-1004",
        "Laura",
        "Sánchez",
        "Pérez",
        "5512345604",
        "ADMINISTRATIVO",
        "Coordinadora de calidad",
        "2019-11-20",
        1,
        0,
        False,
    ),
    (
        "E-1005",
        "Miguel",
        "Ramírez",
        "Díaz",
        "5512345605",
        "OPERATIVO",
        "Montacarguista",
        "2023-05-08",
        0,
        1,
        False,
    ),
    (
        "E-1006",
        "Patricia",
        "Flores",
        "Vega",
        "5512345606",
        "ADMINISTRATIVO",
        "Contadora",
        "2018-02-26",
        1,
        0,
        True,
    ),
    (
        "E-1007",
        "Roberto",
        "Morales",
        "Castro",
        "5512345607",
        "OPERATIVO",
        "Almacenista",
        "2024-01-15",
        0,
        0,
        False,
    ),
    (
        "E-1008",
        "Fernanda",
        "Ortega",
        "Núñez",
        "5512345608",
        "ADMINISTRATIVO",
        "Reclutadora",
        "2022-09-05",
        1,
        1,
        True,
    ),
)

CONTENIDO_PLANTILLA = {
    "esquema": 1,
    "bloques": [
        {"tipo": "logotipo", "alineacion": "centro"},
        {
            "tipo": "parrafo",
            "alineacion": "centro",
            "contenido": [{"texto": "CONSTANCIA LABORAL"}],
        },
        {
            "tipo": "parrafo",
            "alineacion": "justificado",
            "contenido": [
                {"texto": "Por medio de la presente se hace constar que "},
                {"var": "nombre_completo"},
                {"texto": " labora en esta empresa con el puesto de "},
                {"var": "puesto"},
                {"texto": "."},
            ],
        },
    ],
}


def sembrar_base(salida=print) -> dict[str, Any]:
    import psycopg

    from scripts.bootstrap_admin import sembrar_campos

    with psycopg.connect(url_admin()) as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('cc_local_sembrado'))")
        fila = conn.execute(
            "SELECT id FROM identidad.empresa WHERE lower(razon_social) = lower(%s) ORDER BY id",
            (c.EMPRESA_DEMO,),
        ).fetchone()
        if fila is None:
            fila = conn.execute(
                "INSERT INTO identidad.empresa (razon_social, rfc) VALUES (%s, %s) RETURNING id",
                (c.EMPRESA_DEMO, "EDE200101XY9"),
            ).fetchone()
            salida(f"empresa creada: {c.EMPRESA_DEMO}")
        empresa_id = fila[0]
        creados = sembrar_campos(conn, empresa_id)
        if creados:
            salida(f"campos sugeridos sembrados: {creados}")
        usuarios = []
        for u in c.USUARIOS_DEV:
            uid = conn.execute(
                "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (cognito_sub) DO UPDATE "
                "SET nombre = EXCLUDED.nombre, activo = true RETURNING id",
                (empresa_id, u["nombre"], u["correo"], u["sub"]),
            ).fetchone()[0]
            usuarios.append({**u, "empresa_id": empresa_id, "usuario_id": uid, "rol": "RH"})
    c.ARCHIVO_USUARIOS.write_text(json.dumps(usuarios, indent=2), encoding="utf-8")
    return {"empresa_id": empresa_id, "usuarios": usuarios}


class _Api:
    """Cliente mínimo de la pasarela con el token de un usuario de desarrollo."""

    def __init__(self, base: str, correo: str) -> None:
        self.http = httpx.Client(base_url=base, timeout=30.0)
        s = self.http.post(
            "/api/dev/auth/iniciar", json={"correo": correo, "contrasena": c.CONTRASENA_DEV}
        ).raise_for_status()
        t = self.http.post(
            "/api/dev/auth/totp", json={"sesion": s.json()["sesion"], "codigo": "000000"}
        ).raise_for_status()
        self.http.headers["Authorization"] = f"Bearer {t.json()['access_token']}"

    def pedir(self, metodo: str, ruta: str, **kw: Any) -> httpx.Response:
        r = self.http.request(metodo, ruta, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{metodo} {ruta} -> {r.status_code}: {r.text[:400]}")
        return r


def _items(r: httpx.Response) -> list[dict]:
    cuerpo = r.json()
    if isinstance(cuerpo, list):
        return cuerpo
    for clave in ("items", "datos", "organizaciones", "plantas", "plantillas", "resultados"):
        if isinstance(cuerpo.get(clave), list):
            return cuerpo[clave]
    raise RuntimeError(f"Forma de respuesta inesperada: {list(cuerpo)[:6]}")


def sembrar_demo(base: str, secreto_interno: str, salida=print) -> None:
    api = _Api(base, c.USUARIOS_DEV[0]["correo"])

    orgs = _items(api.pedir("GET", "/api/v1/organizaciones"))
    por_clave = {o["clave"]: o["id"] for o in orgs}
    for o in ORGANIZACIONES:
        if o["clave"] not in por_clave:
            por_clave[o["clave"]] = api.pedir("POST", "/api/v1/organizaciones", json=o).json()["id"]
            salida(f"organización creada: {o['razon_social']}")
    ids_org = [por_clave[o["clave"]] for o in ORGANIZACIONES]

    plantas = {p["nombre"]: p["id"] for p in _items(api.pedir("GET", "/api/v1/plantas"))}
    for nombre in PLANTAS:
        if nombre not in plantas:
            plantas[nombre] = api.pedir("POST", "/api/v1/plantas", json={"nombre": nombre}).json()[
                "id"
            ]
            salida(f"planta creada: {nombre}")
    ids_planta = [plantas[n] for n in PLANTAS]

    existentes = {
        x["numero_empleado"]
        for x in _items(api.pedir("GET", "/api/v1/colaboradores", params={"limite": 100}))
    }
    for num, nom, pat, mat, cel, tipo, puesto, ingreso, o, p, consiente in COLABORADORES:
        if num in existentes:
            continue
        api.pedir(
            "POST",
            "/api/v1/colaboradores",
            json={
                "numero_empleado": num,
                "nombres": nom,
                "apellido_paterno": pat,
                "apellido_materno": mat,
                "celular": cel,
                "organizacion_id": ids_org[o],
                "planta_id": ids_planta[p],
                "fecha_ingreso": ingreso,
                "puesto": puesto,
                "tipo_empleado": tipo,
                "consentimiento": consiente,
            },
        )
        salida(f"colaborador creado: {num} {nom} {pat} ({'con' if consiente else 'sin'} consent.)")

    if not _items(api.pedir("GET", "/api/v1/plantillas")):
        p = api.pedir(
            "POST",
            "/api/v1/plantillas",
            json={
                "nombre": "Constancia laboral",
                "descripcion": "Plantilla de ejemplo del stack local.",
            },
        ).json()
        api.pedir("PUT", f"/api/v1/plantillas/{p['id']}/borrador", json=CONTENIDO_PLANTILLA)
        api.pedir("POST", f"/api/v1/plantillas/{p['id']}/publicar", json={})
        salida("plantilla publicada: Constancia laboral")

    if not api.pedir("GET", "/api/v1/constancias/historial").json()["items"]:
        _generar_constancias(api, secreto_interno, salida)


def _generar_constancias(api: _Api, secreto_interno: str, salida=print) -> None:
    """Pide tres constancias como lo hace el bot (INT-CON-02 a 04); las genera el worker de PDF."""
    from cc_common.internal_client import emitir_token_interno

    usuario = json.loads(c.ARCHIVO_USUARIOS.read_text(encoding="utf-8"))[0]
    empresa_id = usuario["empresa_id"]
    interno = httpx.Client(
        base_url=f"http://127.0.0.1:{c.PUERTOS_SERVICIOS['constancias']}/internal",
        headers={
            "Authorization": f"Bearer {emitir_token_interno(secreto_interno, 'whatsapp')}",
            "X-Empresa-Id": str(empresa_id),
        },
        timeout=30.0,
    )
    plantilla = interno.get("/plantillas/activas").raise_for_status().json()["plantillas"][0]
    cols = {
        x["numero_empleado"]: x
        for x in _items(api.pedir("GET", "/api/v1/colaboradores", params={"limite": 100}))
    }
    for numero in ("E-1001", "E-1002", "E-1006"):
        col = cols[numero]
        nombre = col["nombre_completo"]
        sid = (
            interno.post(
                "/solicitudes", json={"colaborador_id": col["id"], "colaborador_nombre": nombre}
            )
            .raise_for_status()
            .json()["id"]
        )
        interno.post(
            f"/solicitudes/{sid}/plantilla", json={"plantilla_id": plantilla["id"]}
        ).raise_for_status()
        interno.post(f"/solicitudes/{sid}/generar").raise_for_status()
        salida(f"constancia solicitada para {nombre} (la genera el worker de PDF)")


def esperar_http(url: str, segundos: float = 60.0) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        try:
            if httpx.get(url, timeout=2.0).status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1.0)
    return False
