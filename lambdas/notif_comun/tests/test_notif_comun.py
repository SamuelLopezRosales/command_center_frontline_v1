"""Piezas compartidas de las Lambdas de notificaciones: horario, variables, Scheduler y colaboradores."""

import json
from datetime import UTC, datetime, time

import httpx
import pytest
from notif_comun import horario, plantilla
from notif_comun.contactos import ContactosHttp, ContactosNoDisponible, StubContactos
from notif_comun.scheduler import (
    DESPACHO,
    RESPALDO,
    SchedulerBoto,
    ScheduleUnico,
    cuerpo_despacho,
    nombre_respaldo,
    siguiente_nombre,
)

MX = "America/Mexico_City"
SECRETO = "secreto-de-prueba-0123456789-abcdef-ghij"  # pragma: allowlist secret


def utc(*a):
    return datetime(*a, tzinfo=UTC)


@pytest.mark.parametrize(
    ("momento", "esperado"),
    [
        (utc(2026, 11, 17, 14, 0), True),  # 08:00:00 local
        (utc(2026, 11, 17, 13, 59, 59), False),
        (utc(2026, 11, 18, 2, 0), True),  # 20:00:00 local, inclusivo
        (utc(2026, 11, 18, 2, 0, 1), False),
    ],
)
def test_horario_inclusivo(momento, esperado):
    assert horario.dentro_de_horario(momento, MX) is esperado


def test_siguiente_inicio_y_expresion():
    noche = horario.siguiente_inicio(utc(2026, 11, 18, 4, 0), MX)  # 22:00 local
    assert noche.isoformat() == "2026-11-18T08:00:00-06:00"
    madrugada = horario.siguiente_inicio(utc(2026, 11, 17, 10, 0), MX)  # 04:00 local
    assert madrugada.isoformat() == "2026-11-17T08:00:00-06:00"
    en_horario = utc(2026, 11, 17, 18, 0)
    assert horario.siguiente_inicio(en_horario, MX) == en_horario
    assert horario.expresion_at(noche, MX) == "at(2026-11-18T08:00:00)"
    assert horario.dentro_de_horario(utc(2026, 11, 17, 18), MX, time(9), time(10)) is False
    with pytest.raises(ValueError):
        horario.dentro_de_horario(datetime(2026, 11, 17, 12), MX)


def test_variables_de_la_plantilla():
    vj = {
        "2": {"origen": "FIJO", "valor": "20 nov"},
        "1": {"origen": "COLABORADOR", "campo": "nombre_completo"},
        "3": {"origen": "COLABORADOR", "campo": "nombre_completo"},
        "10": {"origen": "COLABORADOR", "campo": "puesto"},
    }
    assert plantilla.campos_colaborador(vj) == ["nombre_completo", "puesto"]
    assert plantilla.armar_variables(vj, {"nombre_completo": "Ana", "puesto": "Jefa"}) == [
        "Ana",
        "20 nov",
        "Ana",
        "Jefa",
    ]
    assert plantilla.armar_variables(vj, {}) == ["", "20 nov", "", ""]
    assert plantilla.armar_variables(None) == []
    texto = plantilla.renderizar("Hola {{1}}, el {{2}} {{9}}", ["Ana", "20 nov"])
    assert texto == "Hola Ana, el 20 nov "


def test_variables_con_nombre_salen_en_el_orden_del_texto_con_su_lista_de_nombres():
    texto = "Te esperamos en {{lugar}}, {{guest_name}}. {{guest_name}}, ¡hasta pronto!"
    vj = {
        "guest_name": {"origen": "COLABORADOR", "campo": "nombre_completo"},
        "lugar": {"origen": "FIJO", "valor": "Recepción"},
    }
    assert plantilla.nombres_variables(texto) == ["lugar", "guest_name"]
    assert plantilla.campos_colaborador(vj) == ["nombre_completo"]
    variables = plantilla.armar_variables(vj, {"nombre_completo": "Ana"}, texto)
    assert variables == ["Recepción", "Ana"]
    assert plantilla.renderizar(texto, variables) == (
        "Te esperamos en Recepción, Ana. Ana, ¡hasta pronto!"
    )
    # un dato faltante del colaborador queda vacío (el enviador lo rechaza antes de llamar a Meta)
    assert plantilla.armar_variables(vj, {}, texto) == ["Recepción", ""]
    # una variable del texto sin entrada en variables_json también queda vacía
    assert plantilla.armar_variables({"lugar": vj["lugar"]}, {}, texto) == ["Recepción", ""]


def test_las_posicionales_no_cambian_con_el_texto_ni_sin_el():
    vj = {
        "2": {"origen": "FIJO", "valor": "20 nov"},
        "1": {"origen": "COLABORADOR", "campo": "nombre_completo"},
    }
    texto = "Hola {{1}}, el {{2}}"
    assert plantilla.nombres_variables(texto) is None and plantilla.nombres_variables(None) is None
    assert plantilla.armar_variables(vj, {"nombre_completo": "Ana"}) == ["Ana", "20 nov"]
    assert plantilla.armar_variables(vj, {"nombre_completo": "Ana"}, texto) == ["Ana", "20 nov"]
    assert plantilla.renderizar("sin variables", []) == "sin variables"


def test_nombres_de_schedule():
    assert siguiente_nombre(7, "cc-notif-7") == "cc-notif-7-1"
    assert siguiente_nombre(7, "cc-notif-7-1") == "cc-notif-7-2"
    assert siguiente_nombre(7, None) == "cc-notif-7-1"
    assert siguiente_nombre(7, "otro") == "cc-notif-7-1"
    assert nombre_respaldo(7) == "cc-notif-respaldo-7"
    assert nombre_respaldo(7, "d20261118") == "cc-notif-respaldo-7-d20261118"
    assert cuerpo_despacho(7, 3) == {"notificacion_id": 7, "tipo": "INICIO", "empresa_id": 3}


class ClienteBotoFalso:
    class exceptions:  # noqa: N801
        class ConflictException(Exception):  # noqa: N818
            pass

    def __init__(self, existe=False):
        self.existe = existe
        self.llamadas = []

    def create_schedule(self, **kw):
        self.llamadas.append(("create", kw))
        if self.existe:
            raise self.exceptions.ConflictException

    def update_schedule(self, **kw):
        self.llamadas.append(("update", kw))


def test_scheduler_boto_crea_un_schedule_unico_y_actualiza_si_existe():
    destinos = {
        DESPACHO: "arn:aws:sqs:us-east-1:1:notif-despacho",
        RESPALDO: "arn:aws:sqs:us-east-1:1:notif-respaldo",
    }
    s = ScheduleUnico(
        "cc-notif-7-1", "at(2026-11-18T08:00:00)", MX, cuerpo_despacho(7, 3), RESPALDO
    )
    nuevo = ClienteBotoFalso()
    SchedulerBoto(destinos=destinos, rol_arn="arn:rol", cliente=nuevo).crear_unico(s)
    [(op, p)] = nuevo.llamadas
    assert op == "create" and p["Name"] == "cc-notif-7-1"
    assert p["ActionAfterCompletion"] == "DELETE"
    assert p["FlexibleTimeWindow"] == {"Mode": "OFF"} and p["ScheduleExpressionTimezone"] == MX
    assert p["Target"]["Arn"] == destinos[RESPALDO] and p["Target"]["RoleArn"] == "arn:rol"
    assert p["Target"]["Input"] == '{"notificacion_id":7,"tipo":"INICIO","empresa_id":3}'
    viejo = ClienteBotoFalso(existe=True)
    SchedulerBoto(destinos=destinos, rol_arn="arn:rol", cliente=viejo).crear_unico(s)
    assert [op for op, _ in viejo.llamadas] == ["create", "update"]


def _http(responder):
    return httpx.Client(transport=httpx.MockTransport(responder))


def test_contactos_http_lleva_empresa_token_y_completa_los_ausentes():
    vistas = []

    def responder(req: httpx.Request) -> httpx.Response:
        vistas.append(req)
        ids = json.loads(req.content)["ids"]
        items = [{"id": i, "elegible": True, "valores": {"x": "1"}} for i in ids if i != 3]
        return httpx.Response(200, json={"items": items})

    c = ContactosHttp("http://col", lambda: SECRETO, cliente=_http(responder))
    r = c.resolver(9, list(range(1, 1202)), "NOTIFICACION", ["x"])
    assert len(vistas) == 3  # lotes de 500
    assert vistas[0].headers["x-empresa-id"] == "9"
    assert vistas[0].headers["authorization"].startswith("Bearer ")
    assert str(vistas[0].url) == "http://col/internal/colaboradores/contactos:resolver"
    assert json.loads(vistas[0].content)["variables"] == ["x"]
    assert r[1]["elegible"] and r[3] == {"id": 3, "elegible": False, "motivo": "NO_ENCONTRADO"}


@pytest.mark.parametrize("estado", [500, 422])
def test_contactos_http_error_es_no_disponible(estado):
    c = ContactosHttp(
        "http://col", lambda: SECRETO, cliente=_http(lambda r: httpx.Response(estado))
    )
    with pytest.raises(ContactosNoDisponible):
        c.resolver(1, [1], "CORREO")


def test_contactos_http_error_de_red():
    def fallar(_r):
        raise httpx.ConnectError("sin red")

    c = ContactosHttp("http://col", lambda: SECRETO, cliente=_http(fallar))
    with pytest.raises(ContactosNoDisponible):
        c.resolver(1, [1], "CORREO")


def test_stub_contactos_solo_entrega_las_variables_pedidas():
    s = StubContactos({1: {"elegible": True, "valores": {"a": "1", "b": "2"}}})
    assert s.resolver(5, [1, 2], "NOTIFICACION", ["a"]) == {
        1: {"id": 1, "elegible": True, "valores": {"a": "1"}},
        2: {"id": 2, "elegible": False, "motivo": "NO_ENCONTRADO", "valores": {}},
    }
