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
async def http(motor, s3_plantillas, campos):
    app = construir_app(motor, almacen=s3_plantillas[0], campos=campos)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture
def h(datos):
    """Encabezados de la usuaria de la empresa A."""
    return cab(emitir("sub-a", datos["a"], datos["ua"]))


@pytest.fixture
def hb(datos):
    return cab(emitir("sub-b", datos["b"], datos["ub"]))
