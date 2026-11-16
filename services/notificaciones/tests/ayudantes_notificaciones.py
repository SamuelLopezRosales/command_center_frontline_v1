"""Ayudantes de prueba del servicio notificaciones: tokens firmados y construcción de la app."""

import importlib
import importlib.util
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

EMISOR = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_PRUEBA"
CLIENTE = "cliente-spa"
LLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SECRETO_INTERNO = "secreto-interno-de-prueba-0123456789-abcdef"  # pragma: allowlist secret


def emitir(sub: str, empresa_id: int, usuario_id: int | None, rol: str = "RH") -> str:
    ahora = int(time.time())
    claims = {
        "sub": sub,
        "iss": EMISOR,
        "client_id": CLIENTE,
        "token_use": "access",
        "iat": ahora,
        "exp": ahora + 900,
        "jti": uuid.uuid4().hex,
        "empresa_id": str(empresa_id),
        "rol": rol,
    }
    if usuario_id is not None:
        claims["usuario_id"] = str(usuario_id)
    return jwt.encode(claims, LLAVE, algorithm="RS256")


def cab(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


RAIZ = Path(__file__).resolve().parents[3]


def simulador_meta():
    """El simulador de Meta de `whatsapp` (``services/whatsapp/tests/simulador_meta``): se carga por
    ruta para no depender de que el directorio de pruebas de ese servicio esté en ``sys.path``."""
    try:
        return importlib.import_module("simulador_meta")
    except ImportError:
        ruta = RAIZ / "services" / "whatsapp" / "tests" / "simulador_meta" / "__init__.py"
        espec = importlib.util.spec_from_file_location(
            "simulador_meta", ruta, submodule_search_locations=[str(ruta.parent)]
        )
        modulo = importlib.util.module_from_spec(espec)
        sys.modules["simulador_meta"] = modulo
        espec.loader.exec_module(modulo)
        return modulo


class Reloj:
    """Reloj controlable: ``ahora`` en UTC. Por defecto, martes 17/11/2026 12:00 en Ciudad de
    México (18:00 UTC), dentro de horario."""

    def __init__(self, ahora: datetime | None = None) -> None:
        self.ahora = ahora or datetime(2026, 11, 17, 18, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.ahora


def construir_app(
    motor, campos=None, colaboradores=None, *, meta=None, scheduler=None, reloj=None, **cfg
):
    from cc_common.auth import VerificadorToken
    from cc_notificaciones.clientes import StubCampos, StubColaboradores
    from cc_notificaciones.config import ConfigNotificaciones
    from cc_notificaciones.main import crear_app

    return crear_app(
        ConfigNotificaciones(cognito_emisor=EMISOR, cognito_client_id=CLIENTE, **cfg),
        motor=motor,
        verificador=VerificadorToken(EMISOR, CLIENTE, resolver_llave=lambda _t: LLAVE.public_key()),
        campos=campos or StubCampos(),
        colaboradores=colaboradores or StubColaboradores(),
        meta=meta,
        scheduler=scheduler,
        reloj=reloj,
        secreto_interno=lambda: SECRETO_INTERNO,
    )


def sql(datos, consulta, params=()):
    """Consulta con el rol administrador (sin RLS) para comprobar el estado de la base."""
    import psycopg

    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        cur = c.execute(consulta, params)
        return cur.fetchall() if cur.description else []


def app_colaboradores(motor, campos, secreto: str = SECRETO_INTERNO):
    """La aplicación real de `colaboradores` (solo se usa su INT-COL-06; sin cifrador ni S3)."""
    from cc_colaboradores.config import ConfigColaboradores
    from cc_colaboradores.main import crear_app

    return crear_app(
        ConfigColaboradores(),
        motor=motor,
        verificador=object(),
        cifrador=object(),
        campos=campos,
        secreto_interno=lambda: secreto,
    )


def insertar_plantilla(
    datos,
    *,
    empresa=None,
    usuario=None,
    nombre="aviso_uniformes_v1",
    texto="Hola {{1}}, te esperamos el {{2}}.",
    estado="APROBADA",
):
    """Plantilla directa en la base (sin pasar por Meta)."""
    import json

    import psycopg

    empresa = empresa or datos["a"]
    usuario = usuario or (datos["ua"] if empresa == datos["a"] else datos["ub"])
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        return c.execute(
            "INSERT INTO notificaciones.plantilla_mensaje (empresa_id, creada_por_usuario_id, "
            "nombre, categoria, texto_con_variables, estado_meta, id_plantilla_meta, ejemplos_json) "
            "VALUES (%s, %s, %s, 'UTILITY', %s, %s, %s, %s::jsonb) RETURNING id",
            (
                empresa,
                usuario,
                nombre,
                texto,
                estado,
                None if estado == "BORRADOR" else f"TPL-{nombre}",
                json.dumps(["Ana", "13 nov"]),
            ),
        ).fetchone()[0]


VARIABLES = {
    "1": {"origen": "COLABORADOR", "campo": "nombre_completo"},
    "2": {"origen": "FIJO", "valor": "13 nov 2026"},
}


def insertar_destinatarios(datos, notificacion_id, *, empresa=None, n=3, estado="PENDIENTE"):
    """``n`` renglones (colaborador_id desde 1000), todos en ``estado``; devuelve sus ids."""
    import psycopg

    empresa = empresa or datos["a"]
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        existentes = c.execute(
            "SELECT count(*) FROM notificaciones.notificacion_destinatario "
            "WHERE notificacion_id = %s",
            (notificacion_id,),
        ).fetchone()[0]
        ids = []
        for i in range(existentes, existentes + n):
            ids.append(
                c.execute(
                    "INSERT INTO notificaciones.notificacion_destinatario (empresa_id, "
                    "notificacion_id, colaborador_id, estado_envio, motivo_exclusion, "
                    "colaborador_nombre, planta_nombre, celular_ultimos4) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 'Apodaca', %s) RETURNING id",
                    (
                        empresa,
                        notificacion_id,
                        1000 + i,
                        estado,
                        "SIN_CONSENTIMIENTO" if estado == "EXCLUIDO" else None,
                        f"Colaborador {1000 + i}",
                        f"{(i * 1111) % 10000:04d}",
                    ),
                ).fetchone()[0]
            )
        return ids
