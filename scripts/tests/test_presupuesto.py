import json

from infra.config import esquema
from scripts import crear_presupuesto as cp


def test_presupuesto_desde_la_configuracion():
    amb = esquema.obtener_ambiente("test")
    presupuesto, notificaciones = cp.construir(amb)
    assert presupuesto["BudgetName"] == "command-center-test-mensual"
    assert presupuesto["BudgetLimit"] == {"Amount": "50.00", "Unit": "USD"}
    assert presupuesto["TimeUnit"] == "MONTHLY" and presupuesto["BudgetType"] == "COST"
    resumen = [
        (n["Notification"]["NotificationType"], n["Notification"]["Threshold"])
        for n in notificaciones
    ]
    assert resumen == [("ACTUAL", 80.0), ("ACTUAL", 100.0), ("FORECASTED", 100.0)]
    for n in notificaciones:
        assert n["Subscribers"] == [
            {"SubscriptionType": "EMAIL", "Address": "samuel.lopez@honne.com"}
        ]


def test_comandos_usan_solo_el_perfil_cc_test():
    amb = esquema.obtener_ambiente("test")
    for cmd in cp.comandos(amb, "034362033822").values():
        assert cmd[cmd.index("--profile") + 1] == "cc-test"
        texto = " ".join(cmd)
        assert "AKIA" not in texto and "secret" not in texto.lower()


def test_modo_que_pasaria_no_llama_a_aws(monkeypatch, capsys):
    def prohibido(*_a, **_k):
        raise AssertionError("no debe llamar a AWS en modo -WhatIf")

    monkeypatch.setattr(cp, "_correr", prohibido)
    monkeypatch.setattr(cp, "verificar", prohibido)
    assert cp.main(["--que-pasaria"]) == 0
    salida = capsys.readouterr().out
    assert "no se llama a AWS" in salida
    datos = json.loads(salida[salida.index("{") : salida.rindex("}") + 1])
    assert datos["presupuesto"]["BudgetLimit"]["Amount"] == "50.00"


def test_sin_sesion_valida_no_crea(monkeypatch, capsys):
    from scripts.aws_guard import ResultadoGuardia

    monkeypatch.setattr(
        cp, "verificar", lambda *_a, **_k: ResultadoGuardia(False, "SESION_VENCIDA", "login")
    )
    monkeypatch.setattr(cp, "_correr", lambda *_a: (_ for _ in ()).throw(AssertionError("no")))
    assert cp.main([]) == 1
    assert "SESION_VENCIDA" in capsys.readouterr().out


def test_idempotente_si_ya_existe(monkeypatch):
    from scripts.aws_guard import ResultadoGuardia

    llamadas = []
    monkeypatch.setattr(
        cp, "verificar", lambda *_a, **_k: ResultadoGuardia(True, "OK", "", cuenta="034362033822")
    )

    def correr(cmd):
        llamadas.append(cmd[5])
        return 0, "{}", ""

    monkeypatch.setattr(cp, "_correr", correr)
    assert cp.main([]) == 0
    assert "create-budget" not in llamadas
