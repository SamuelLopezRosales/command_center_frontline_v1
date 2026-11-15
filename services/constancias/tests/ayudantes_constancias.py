"""Ayudantes de prueba del servicio constancias: tokens firmados, datos y constancias emitidas."""

import json
import time
import uuid

import jwt
from cc_constancias import contenido as esquema
from cc_constancias.almacenamiento import clave_version
from cryptography.hazmat.primitives.asymmetric import rsa

EMISOR = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_PRUEBA"
CLIENTE = "cliente-spa"
LLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SECRETO_INTERNO = "secreto-interno-de-prueba-0123456789-abcdef"

CONTENIDO = {
    "esquema": 1,
    "bloques": [
        {"tipo": "logotipo"},
        {
            "tipo": "parrafo",
            "contenido": [{"texto": "hace constar que "}, {"var": "nombre_completo"}],
        },
    ],
}


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


def construir_app(motor, almacen=None, campos=None, colaboradores=None, **cfg):
    from cc_common.auth import VerificadorToken
    from cc_constancias.clientes import StubCampos, StubColaboradores
    from cc_constancias.config import ConfigConstancias
    from cc_constancias.main import crear_app

    return crear_app(
        ConfigConstancias(cognito_emisor=EMISOR, cognito_client_id=CLIENTE, **cfg),
        motor=motor,
        verificador=VerificadorToken(EMISOR, CLIENTE, resolver_llave=lambda _t: LLAVE.public_key()),
        almacen=almacen,
        campos=campos or StubCampos(),
        colaboradores=colaboradores or StubColaboradores(),
        secreto_interno=lambda: SECRETO_INTERNO,
    )


def sql(datos, consulta, params=()):
    """Consulta con el rol administrador (sin RLS) para comprobar el estado de la base."""
    import psycopg

    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        cur = c.execute(consulta, params)
        return cur.fetchall() if cur.description else []


def canonico(contenido: dict | None = None) -> tuple[bytes, str]:
    cuerpo = esquema.serializar(esquema.leer(contenido or CONTENIDO))
    return cuerpo, esquema.hash_de(cuerpo)


def publicar_version(datos, almacen, plantilla_id: int, numero: int = 1, contenido=None) -> str:
    """Inserta una versión publicada (lo que hará CON-10 en T-208) con su objeto en S3."""
    cuerpo, hash_ = canonico(contenido)
    clave = clave_version(datos["a"], plantilla_id, numero)
    almacen._s3.put_object(Bucket=almacen._bucket, Key=clave, Body=cuerpo)
    sql(
        datos,
        "INSERT INTO constancias.version_plantilla (empresa_id, plantilla_id, numero, "
        "contenido_s3_key, hash_sha256, creada_por_usuario_id) VALUES (%s, %s, %s, %s, %s, %s)",
        (datos["a"], plantilla_id, numero, clave, hash_, datos["ua"]),
    )
    return clave


def crear_colaborador(datos) -> int:
    """Inserta un colaborador de la empresa A (con su organización y planta). Devuelve su id."""
    e = datos["a"]
    org = sql(
        datos,
        "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
        "VALUES (%s, %s, 'Org') ON CONFLICT (empresa_id, clave) DO UPDATE SET razon_social = 'Org' "
        "RETURNING id",
        (e, "ORG1"),
    )[0][0]
    planta = sql(
        datos,
        "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Norte') "
        "ON CONFLICT (empresa_id, lower(nombre)) DO UPDATE SET nombre = 'Norte' RETURNING id",
        (e,),
    )[0][0]
    return sql(
        datos,
        "INSERT INTO colaboradores.colaborador (empresa_id, organizacion_id, planta_id, "
        "numero_empleado, nombres, apellido_paterno, apellido_materno, celular_cifrado, "
        "celular_hash, celular_ultimos4, fecha_ingreso, puesto, tipo_empleado) "
        "VALUES (%s, %s, %s, %s, 'Ana', 'Pérez', 'Ruiz', '\\x00', "
        "decode(md5(%s) || md5(%s), 'hex'), '0000', '2020-01-01', 'Op', 'OPERATIVO') RETURNING id",
        (e, org, planta, f"E-{uuid.uuid4().hex[:8]}".upper(), uuid.uuid4().hex, uuid.uuid4().hex),
    )[0][0]


def emitir_constancia(datos, plantilla_id: int, numero_version: int = 1, n: int = 1) -> int:
    """Inserta una constancia ya emitida con la versión indicada. Devuelve su id."""
    e = datos["a"]
    colaborador = crear_colaborador(datos)
    version = sql(
        datos,
        "SELECT id FROM constancias.version_plantilla WHERE plantilla_id = %s AND numero = %s",
        (plantilla_id, numero_version),
    )[0][0]
    solicitud = sql(
        datos,
        "INSERT INTO constancias.solicitud_constancia (empresa_id, colaborador_id, "
        "version_plantilla_id, estado, colaborador_nombre) "
        "VALUES (%s, %s, %s, 'GENERADA', 'Ana Pérez Ruiz') RETURNING id",
        (e, colaborador, version),
    )[0][0]
    return sql(
        datos,
        "INSERT INTO constancias.constancia_generada (empresa_id, solicitud_id, colaborador_id, "
        "version_plantilla_id, folio, pdf_s3_key, pdf_hash_sha256, datos_snapshot_json, "
        "colaborador_nombre, numero_empleado, codigo_verificacion) "
        "VALUES (%s, %s, %s, %s, %s, 'constancias/x.pdf', %s, '{}'::jsonb, 'Ana Pérez Ruiz', "
        "'E-1', %s) RETURNING id",
        (e, solicitud, colaborador, version, f"CG-2026-{n:04d}", "0" * 64, uuid.uuid4().hex),
    )[0][0]


def volcado(contenido) -> str:
    return json.dumps(contenido, ensure_ascii=False)
