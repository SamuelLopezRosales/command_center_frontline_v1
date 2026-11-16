"""T-110: el schedule único en EventBridge Scheduler (LocalStack) a través de la API.

Necesita LocalStack con ``scheduler`` en ``SERVICES`` (``docker-compose.yml``; si el contenedor
es anterior a T-216, recréelo con ``docker compose up -d --force-recreate localstack``); si el
servicio no está disponible, las pruebas se omiten con ese aviso.
"""

import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3
import httpx
import pytest
from ayudantes_notificaciones import (
    VARIABLES,
    construir_app,
    insertar_destinatarios,
    insertar_plantilla,
)
from cc_notificaciones.scheduler import SchedulerBoto, ScheduleUnico, cuerpo_despacho

pytestmark = pytest.mark.docker

BASE = "/api/v1/notificaciones"
MX = ZoneInfo("America/Mexico_City")
ROL = "arn:aws:iam::000000000000:role/cc-scheduler-prueba"


@pytest.fixture
def aws(localstack):
    kw = {
        "region_name": "us-east-1",
        "endpoint_url": localstack,
        "aws_access_key_id": "test",
        "aws_secret_access_key": "test",  # pragma: allowlist secret
    }
    sch = boto3.client("scheduler", **kw)
    try:
        sch.list_schedules()
    except Exception:
        pytest.skip(
            "LocalStack sin el servicio scheduler: agréguelo a SERVICES y recree el contenedor"
        )
    sqs = boto3.client("sqs", **kw)
    cola = f"notif-despacho-prueba-{uuid.uuid4().hex[:8]}"
    url = sqs.create_queue(QueueName=cola)["QueueUrl"]
    arn = f"arn:aws:sqs:us-east-1:000000000000:{cola}"
    yield {"scheduler": sch, "sqs": sqs, "cola_url": url, "cola_arn": arn, "kw": kw}
    for s in sch.list_schedules().get("Schedules", []):
        if s["Name"].startswith("cc-notif-"):
            sch.delete_schedule(Name=s["Name"], GroupName=s.get("GroupName", "default"))
    sqs.delete_queue(QueueUrl=url)


@pytest.fixture
def cliente(aws):
    return SchedulerBoto(
        destino_arn=aws["cola_arn"], rol_arn=ROL, cliente=aws["scheduler"], grupo="default"
    )


def _schedules(aws):
    return [
        s
        for s in aws["scheduler"].list_schedules()["Schedules"]
        if s["Name"].startswith("cc-notif-")
    ]


async def test_crear_actualizar_y_eliminar_un_schedule_unico(aws, cliente):
    s = ScheduleUnico(
        nombre=f"cc-notif-{uuid.uuid4().int % 10**9}",
        expresion="at(2030-11-18T09:00:00)",
        zona="America/Mexico_City",
        cuerpo=cuerpo_despacho(5, 1),
    )
    await cliente.crear_unico(s)
    await cliente.crear_unico(s)  # idempotente: ya existe, no falla ni duplica
    assert [x["Name"] for x in _schedules(aws)] == [s.nombre]
    d = aws["scheduler"].get_schedule(Name=s.nombre)
    assert d["ScheduleExpression"] == "at(2030-11-18T09:00:00)"
    assert d["ScheduleExpressionTimezone"] == "America/Mexico_City"
    assert d["FlexibleTimeWindow"]["Mode"] == "OFF" and d["ActionAfterCompletion"] == "DELETE"
    assert d["Target"]["Arn"] == aws["cola_arn"] and d["Target"]["RoleArn"] == ROL
    assert json.loads(d["Target"]["Input"]) == {
        "notificacion_id": 5,
        "tipo": "INICIO",
        "empresa_id": 1,
    }
    await cliente.eliminar(s.nombre)
    await cliente.eliminar(s.nombre)  # cancelar dos veces es seguro
    assert _schedules(aws) == []


async def test_confirmar_programada_crea_el_schedule_con_el_nombre_guardado(
    aws, cliente, motor, datos, campos, colaboradores, reloj, h
):
    app = construir_app(motor, campos, colaboradores, scheduler=cliente, reloj=reloj)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as http:
        p = insertar_plantilla(datos)
        crit = {"op": "Y", "items": [{"campo": "planta_id", "operador": "es", "valor": 3}]}
        r = await http.post(
            BASE,
            json={
                "titulo": "Aviso",
                "modo": "CRITERIOS",
                "criterios": crit,
                "plantilla_mensaje_id": p,
                "variables": VARIABLES,
            },
            headers=h,
        )
        nid = r.json()["id"]
        insertar_destinatarios(datos, nid, n=2)
        from ayudantes_notificaciones import sql

        sql(
            datos,
            "UPDATE notificaciones.notificacion SET revisada_en = now() WHERE id = %s",
            (nid,),
        )
        cuando = datetime(2026, 11, 18, 9, 0, tzinfo=MX).isoformat()
        cuerpo = {"modo_envio": "PROGRAMAR", "programada_para": cuando}
        r1 = await http.post(f"{BASE}/{nid}/confirmar", json=cuerpo, headers=h)
        r2 = await http.post(f"{BASE}/{nid}/confirmar", json=cuerpo, headers=h)
    assert r1.status_code == r2.status_code == 202, r1.text
    nombre = sql(
        datos, "SELECT schedule_nombre FROM notificaciones.notificacion WHERE id = %s", (nid,)
    )[0][0]
    assert nombre == f"cc-notif-{nid}"
    assert [x["Name"] for x in _schedules(aws)] == [nombre]  # uno solo
    d = aws["scheduler"].get_schedule(Name=nombre)
    assert d["ScheduleExpression"] == "at(2026-11-18T09:00:00)"
    assert d["ScheduleExpressionTimezone"] == "America/Mexico_City"
    assert json.loads(d["Target"]["Input"]) == {
        "notificacion_id": nid,
        "tipo": "INICIO",
        "empresa_id": datos["a"],
    }
