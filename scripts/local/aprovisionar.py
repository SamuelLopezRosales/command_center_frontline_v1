"""Prepara LocalStack y PostgreSQL para el stack local. Todo es idempotente.

- LocalStack: buckets (``cargas``, ``plantillas`` y ``constancias`` con Object Lock), colas SQS,
  bus de EventBridge con las reglas de ``infra/stacks/messaging.py``, llave KMS con su alias y
  los secretos que leen los servicios.
- La llave KMS se crea con material fijo guardado en ``.local/secretos.json``: si LocalStack se
  recrea, las llaves de datos ya cifradas en la base siguen siendo legibles.
- PostgreSQL: contraseñas de los roles de servicio (generadas una vez en ``.local/``).
"""

from __future__ import annotations

import base64
import json
import secrets
import sys
import uuid
from typing import Any

from scripts.local import constantes as c

CORS_BUCKETS = {
    "CORSRules": [
        {
            "AllowedOrigins": ["http://localhost:5173", "http://127.0.0.1:5173"],
            "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
            "AllowedHeaders": ["*"],
            "ExposeHeaders": ["ETag"],
        }
    ]
}


def cargar_secretos() -> dict[str, Any]:
    """Secretos de desarrollo del stack: se generan una vez y se reutilizan."""
    c.LOCAL.mkdir(parents=True, exist_ok=True)
    datos: dict[str, Any] = {}
    if c.ARCHIVO_SECRETOS.exists():
        datos = json.loads(c.ARCHIVO_SECRETOS.read_text(encoding="utf-8"))
    cambio = False

    def fijar(clave: str, fabrica) -> None:
        nonlocal cambio
        if clave not in datos:
            datos[clave] = fabrica()
            cambio = True

    fijar("internal_auth", lambda: secrets.token_urlsafe(48))
    fijar("hmac_celular", lambda: secrets.token_urlsafe(48))
    fijar("whatsapp_hmac", lambda: secrets.token_urlsafe(48))
    fijar("kms_id", lambda: str(uuid.uuid4()))
    fijar("kms_material", lambda: base64.b64encode(secrets.token_bytes(32)).decode())
    datos.setdefault("roles", {})
    for rol in c.ROLES_SERVICIO:
        if rol not in datos["roles"]:
            datos["roles"][rol] = secrets.token_urlsafe(24)
            cambio = True
    if cambio:
        c.ARCHIVO_SECRETOS.write_text(json.dumps(datos, indent=2), encoding="utf-8")
    return datos


def url_cola(nombre: str, base: str = c.LOCALSTACK) -> str:
    return f"{base}/{c.CUENTA}/{nombre}"


def _cliente(servicio: str):
    import boto3

    return boto3.client(
        servicio,
        endpoint_url=c.LOCALSTACK,
        region_name=c.REGION,
        aws_access_key_id="test",  # noqa: S106 - credenciales ficticias de LocalStack
        aws_secret_access_key="test",  # noqa: S106  # pragma: allowlist secret
    )


def preparar_localstack(secretos: dict[str, Any], salida=print) -> None:
    from botocore.exceptions import ClientError

    s3, sqs, events = _cliente("s3"), _cliente("sqs"), _cliente("events")
    kms, sm = _cliente("kms"), _cliente("secretsmanager")

    for bucket in c.BUCKETS:
        try:
            s3.head_bucket(Bucket=bucket)
        except ClientError:
            extra = (
                {"ObjectLockEnabledForBucket": True} if bucket == c.BUCKET_CON_OBJECT_LOCK else {}
            )
            s3.create_bucket(Bucket=bucket, **extra)
            salida(f"bucket creado: {bucket}")
        if bucket != c.BUCKET_CON_OBJECT_LOCK:
            s3.put_bucket_cors(Bucket=bucket, CORSConfiguration=CORS_BUCKETS)

    for nombre, visibilidad in c.COLAS.items():
        atributos = {"VisibilityTimeout": str(visibilidad)}
        if nombre.endswith(".fifo"):
            atributos.update(FifoQueue="true", ContentBasedDeduplication="false")
        sqs.create_queue(
            QueueName=nombre, Attributes=atributos
        )  # idempotente con iguales atributos

    if _falta_bus(events):
        events.create_event_bus(Name=c.BUS)
    for evento, colas in c.RUTAS_EVENTOS.items():
        regla = "cc-local-" + evento.replace(".", "-").replace("_", "-")
        events.put_rule(
            Name=regla, EventBusName=c.BUS, EventPattern=json.dumps({"detail-type": [evento]})
        )
        events.put_targets(
            Rule=regla,
            EventBusName=c.BUS,
            Targets=[
                {
                    "Id": cola,
                    "Arn": f"arn:aws:sqs:{c.REGION}:{c.CUENTA}:{cola}",
                }
                for cola in colas
            ],
        )

    alias = kms.list_aliases().get("Aliases", [])
    if not any(a["AliasName"] == c.LLAVE_ALIAS for a in alias):
        llave = kms.create_key(
            Description="Llave de datos del stack local",
            Tags=[
                {"TagKey": "_custom_id_", "TagValue": secretos["kms_id"]},
                {"TagKey": "_custom_key_material_", "TagValue": secretos["kms_material"]},
            ],
        )["KeyMetadata"]["KeyId"]
        kms.create_alias(AliasName=c.LLAVE_ALIAS, TargetKeyId=llave)
        salida(f"llave KMS creada: {c.LLAVE_ALIAS}")

    for clave, nombre in c.SECRETOS_AWS.items():
        try:
            sm.create_secret(Name=nombre, SecretString=secretos[clave])
            salida(f"secreto creado: {nombre}")
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ResourceExistsException":
                raise
            sm.put_secret_value(SecretId=nombre, SecretString=secretos[clave])

    crear_secreto_meta(sm, salida)


def crear_secreto_meta(sm, salida=print) -> bool:
    """Crea ``cc/local/meta`` vacío (``{}``: "no configurada"); si ya existe no lo toca."""
    from botocore.exceptions import ClientError

    try:
        sm.create_secret(Name=c.SECRETO_META, SecretString="{}")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceExistsException":
            raise
        return False
    salida(f"secreto creado: {c.SECRETO_META} (vacío: se llena en Integraciones)")
    return True


def _falta_bus(events) -> bool:
    return not any(b["Name"] == c.BUS for b in events.list_event_buses().get("EventBuses", []))


def url_admin(base: str | None = None, *, driver: str = "postgresql") -> str:
    nombre = base or c.DB_NOMBRE
    return (
        f"{driver}://{c.DB_ADMIN_USUARIO}:{c.DB_ADMIN_CONTRASENA}"
        f"@{c.DB_HOST}:{c.DB_PUERTO}/{nombre}"
    )


def asignar_contrasenas(secretos: dict[str, Any]) -> list[str]:
    """Fija la contraseña de cada rol de base (reutiliza ``scripts/asignar_contrasenas.py``)."""
    from scripts.asignar_contrasenas import asignar

    return asignar(url_admin(), secretos["roles"])


def migrar() -> None:
    from scripts.migrar_todo import migrar as migrar_todo

    migrar_todo(url_admin(driver="postgresql+psycopg"), salida=lambda m: print(f"  {m}"))


if __name__ == "__main__":  # pragma: no cover
    sys.exit("Use scripts/local.ps1 up")
