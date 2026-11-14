"""Verificación del entorno local (T-022)."""

import uuid

import pytest

pytestmark = pytest.mark.docker


def test_postgres_16_con_extensiones(base_datos):
    import psycopg

    url = base_datos.url_sync.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as c:
        version = c.execute("SHOW server_version").fetchone()[0]
        extensiones = {r[0] for r in c.execute("SELECT extname FROM pg_extension").fetchall()}
        assert c.execute("SELECT unaccent('María')").fetchone()[0] == "Maria"
        assert c.execute("SELECT similarity('Ramírez', 'Ramirez') > 0").fetchone()[0] is True
    assert version.startswith("16")
    assert {"pg_trgm", "unaccent", "pgcrypto"} <= extensiones


def test_cada_prueba_tiene_su_base(base_datos, postgres_servidor):
    import psycopg

    host = postgres_servidor.get_container_host_ip()
    puerto = postgres_servidor.get_exposed_port(5432)
    with psycopg.connect(f"postgresql://cc:cc@{host}:{puerto}/cc") as c:
        bases = {r[0] for r in c.execute("SELECT datname FROM pg_database").fetchall()}
    assert base_datos.nombre in bases


def test_localstack_servicios(localstack):
    import boto3

    kw = {
        "endpoint_url": localstack,
        "region_name": "us-east-1",
        "aws_access_key_id": "test",
        "aws_secret_access_key": "test",
    }  # noqa: S106
    nombre = f"prueba-{uuid.uuid4().hex[:8]}"
    s3 = boto3.client("s3", **kw)
    s3.create_bucket(Bucket=nombre)
    assert nombre in {b["Name"] for b in s3.list_buckets()["Buckets"]}
    sqs = boto3.client("sqs", **kw)
    url = sqs.create_queue(QueueName=nombre)["QueueUrl"]
    sqs.send_message(QueueUrl=url, MessageBody="hola")
    assert sqs.receive_message(QueueUrl=url)["Messages"][0]["Body"] == "hola"
    for servicio in ("events", "sns", "ses"):
        boto3.client(servicio, **kw)
