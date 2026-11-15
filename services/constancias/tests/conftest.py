"""Fixtures del servicio constancias: base real con el rol ``svc_constancias`` y S3 en LocalStack."""

import uuid

import httpx
import psycopg
import pytest
from ayudantes_constancias import cab, construir_app, emitir
from cc_common.db import crear_motor


@pytest.fixture
def datos(bd_migrada):
    """Empresas A y B con un usuario RH cada una."""
    with psycopg.connect(bd_migrada.url_admin, autocommit=True) as c:

        def uno(sql, params=()):
            return c.execute(sql, params).fetchone()[0]

        a = uno("INSERT INTO identidad.empresa (razon_social) VALUES ('A') RETURNING id")
        b = uno("INSERT INTO identidad.empresa (razon_social) VALUES ('B') RETURNING id")
        ua = uno(
            "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
            "VALUES (%s, 'Ana RH', 'ana@a.com', 'sub-a') RETURNING id",
            (a,),
        )
        ub = uno(
            "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
            "VALUES (%s, 'Beto RH', 'beto@b.com', 'sub-b') RETURNING id",
            (b,),
        )
    return {"a": a, "b": b, "ua": ua, "ub": ub, "bd": bd_migrada}


@pytest.fixture
async def motor(datos):
    m = crear_motor(datos["bd"].url_rol("svc_constancias"))
    yield m
    await m.dispose()


@pytest.fixture
def s3_plantillas(localstack):
    """Bucket ``plantillas`` de la prueba en LocalStack: ``(AlmacenS3, cliente boto3, bucket)``."""
    import boto3
    from botocore.config import Config
    from cc_constancias.almacenamiento import AlmacenS3

    cliente = boto3.client(
        "s3",
        endpoint_url=localstack,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    bucket = f"cc-plantillas-{uuid.uuid4().hex[:10]}"
    cliente.create_bucket(Bucket=bucket)
    return AlmacenS3(bucket, cliente), cliente, bucket


@pytest.fixture
def campos():
    from cc_constancias.clientes import StubCampos

    return StubCampos()


@pytest.fixture
def colaboradores():
    from cc_constancias.clientes import StubColaboradores

    return StubColaboradores()


@pytest.fixture
async def http(motor, s3_plantillas, campos, colaboradores):
    app = construir_app(motor, almacen=s3_plantillas[0], campos=campos, colaboradores=colaboradores)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture
def h(datos):
    """Encabezados de la usuaria de la empresa A."""
    return cab(emitir("sub-a", datos["a"], datos["ua"]))


@pytest.fixture
def hb(datos):
    return cab(emitir("sub-b", datos["b"], datos["ub"]))


# ------------------------------------------------------------------ T-209: emisión


@pytest.fixture
def s3_constancias(localstack, s3_plantillas):
    """Bucket ``constancias`` con Object Lock: ``(AlmacenConstancias, cliente, bucket)``."""
    from cc_constancias.almacenamiento import AlmacenConstancias

    cliente = s3_plantillas[1]
    bucket = f"cc-constancias-{uuid.uuid4().hex[:10]}"
    cliente.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
    return AlmacenConstancias(bucket, cliente, retencion_dias=1), cliente, bucket


@pytest.fixture
def cifrador():
    from ayudantes_emision import KmsFalso
    from cc_constancias.cifrado import Cifrador

    return Cifrador(KmsFalso(), "llave-de-prueba")


@pytest.fixture(scope="session")
def llave_cloudfront():
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def firmador(llave_cloudfront):
    from cc_constancias.servicios.firma_cloudfront import FirmadorCloudFront
    from cryptography.hazmat.primitives import serialization

    pem = llave_cloudfront.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return FirmadorCloudFront("cdn.prueba.test", "KPAR1", pem)


@pytest.fixture
async def http_e(motor, s3_plantillas, s3_constancias, campos, colaboradores, firmador):
    """Cliente HTTP con el firmador y el almacén de constancias inyectados."""
    app = construir_app(
        motor,
        almacen=s3_plantillas[0],
        campos=campos,
        colaboradores=colaboradores,
        dominio="cc.prueba.test",
    )
    app.state.firmador = firmador
    app.state.almacen_constancias = s3_constancias[0]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
