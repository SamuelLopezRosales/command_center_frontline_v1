"""T-112: Lambda ``conciliador`` con PostgreSQL real (RLS) y un doble de SQS."""

from datetime import timedelta

import pytest
from conciliador.handler import manejar
from notif_comun.config import ConfigNotifLambdas
from notif_comun.metricas import CONTADORES
from notif_comun.pruebas import AHORA, NOCHE, ColaSqsFalsa

pytestmark = pytest.mark.docker

DESPACHO = "notif-despacho"
RESPALDO = "notif-respaldo"
EVENTO = {"source": "aws.events", "detail-type": "Scheduled Event"}


class Ctx:
    def __init__(self, mundo, ahora=AHORA):
        self.mundo = mundo
        self.sqs = ColaSqsFalsa()
        self.ahora = ahora
        self.cfg = ConfigNotifLambdas(
            cola_despacho_url=DESPACHO, cola_respaldo_url=RESPALDO, ambiente="test"
        )

    def ciclo(self):
        return manejar(
            EVENTO, abrir=self.mundo.abrir, cfg=self.cfg, sqs=self.sqs, reloj=lambda: self.ahora
        )

    def cola(self, nombre):
        return self.sqs.cuerpos(nombre)

    def total(self):
        return sum(len(v) for v in self.sqs.mensajes.values())


def programada(mundo, minutos_atraso, empresa=None, **kw):
    return mundo.notificacion(
        empresa,
        estado="PROGRAMADA",
        modo_envio="PROGRAMAR",
        programada_para=AHORA - timedelta(minutes=minutos_atraso),
        **kw,
    )


# --- PROGRAMADA atrasada -------------------------------------------------------------------


def test_reencola_una_programada_con_mas_de_10_minutos_de_atraso(mundo):
    tarde = programada(mundo, 11)
    a_tiempo = programada(mundo, 9)
    c = Ctx(mundo)
    r = c.ciclo()
    assert r["programadas_reencoladas"] == 1 and r["errores"] == 0
    [m] = c.cola(DESPACHO)
    assert m["tipo"] == "INICIO" and m["notificacion_id"] == tarde and m["empresa_id"] == mundo.a
    assert m["evento_id"]
    assert a_tiempo not in [x["notificacion_id"] for x in c.cola(DESPACHO)]
    assert CONTADORES["programadas_atrasadas"] == 1


def test_no_reencola_en_dos_ciclos_seguidos(mundo):
    programada(mundo, 20)
    c = Ctx(mundo)
    c.ciclo()
    assert len(c.cola(DESPACHO)) == 1
    c.ahora = AHORA + timedelta(minutes=5)  # el siguiente ciclo, 5 minutos después
    r = c.ciclo()
    assert r["programadas_reencoladas"] == 0 and len(c.cola(DESPACHO)) == 1
    # si a los 30 minutos sigue PROGRAMADA (el despachador no la tomó), se reintenta
    c.ahora = AHORA + timedelta(minutes=31)
    assert c.ciclo()["programadas_reencoladas"] == 1 and len(c.cola(DESPACHO)) == 2


@pytest.mark.parametrize("estado", ["BORRADOR", "ENVIANDO", "CANCELADA", "COMPLETADA"])
def test_solo_reencola_programadas(mundo, estado):
    mundo.notificacion(estado=estado, programada_para=AHORA - timedelta(hours=2), destinatarios=0)
    c = Ctx(mundo)
    c.ciclo()
    assert c.cola(DESPACHO) == []


# --- destinatarios encolados sin avance --------------------------------------------------------


def test_libera_destinatarios_encolados_hace_mas_de_30_minutos(mundo):
    nid = mundo.notificacion(
        estado="ENVIANDO", destinatarios=3, encolado_en=AHORA - timedelta(minutes=45)
    )
    ids = [r[0] for r in mundo.destinatarios(nid, "id")]
    # uno reciente y uno que ya avanzó no se tocan
    mundo.sql("UPDATE notificaciones.notificacion_destinatario SET encolado_en = %s WHERE id = %s",
              (AHORA - timedelta(minutes=5), ids[0]))  # fmt: skip
    mundo.sql(
        "UPDATE notificaciones.notificacion_destinatario SET estado_envio = 'ENVIADO' WHERE id = %s",
        (ids[1],),
    )
    c = Ctx(mundo)
    r = c.ciclo()
    assert r["destinatarios_liberados"] == 1  # solo ids[2]: PENDIENTE y encolado hace 45 min
    filas = dict(mundo.destinatarios(nid, "id, encolado_en IS NULL"))
    assert filas == {ids[0]: False, ids[1]: False, ids[2]: True}
    [m] = c.cola(DESPACHO)
    assert m["tipo"] == "CONTINUAR" and m["notificacion_id"] == nid and m["empresa_id"] == mundo.a
    assert CONTADORES["destinatarios_liberados"] == 1


def test_liberar_no_repite_trabajo_en_el_ciclo_siguiente(mundo):
    mundo.notificacion(estado="ENVIANDO", destinatarios=5, encolado_en=AHORA - timedelta(hours=1))
    c = Ctx(mundo)
    assert c.ciclo()["destinatarios_liberados"] == 5
    c.ahora = AHORA + timedelta(minutes=5)
    assert c.ciclo()["destinatarios_liberados"] == 0
    assert len(c.cola(DESPACHO)) == 1  # un solo CONTINUAR


# --- respaldos por correo ------------------------------------------------------------------------


def respaldo(mundo, **kw):
    kw.setdefault("estado", "COMPLETADA")
    kw.setdefault("destinatarios", 2)
    kw.setdefault("encolado_en", AHORA - timedelta(hours=25))
    kw.setdefault("estado_envio", "ENVIADO")
    return mundo.notificacion(respaldo=True, **kw)


def test_programa_el_respaldo_pendiente_una_sola_vez(mundo):
    nid = respaldo(mundo)
    c = Ctx(mundo)
    r = c.ciclo()
    assert r["respaldos_encolados"] == 1
    assert c.cola(RESPALDO) == [{"notificacion_id": nid, "empresa_id": mundo.a}]
    c.ahora = AHORA + timedelta(minutes=5)
    assert c.ciclo()["respaldos_encolados"] == 0 and len(c.cola(RESPALDO)) == 1
    assert CONTADORES["respaldos_programados"] == 1


def test_respaldo_incluye_fallidos_y_excluye_entregados_y_ya_atendidos(mundo):
    nid = respaldo(mundo, destinatarios=0)  # sin renglones: nada que respaldar
    c = Ctx(mundo)
    assert c.ciclo()["respaldos_encolados"] == 0
    for n, (estado, atendido) in enumerate(
        (("ENTREGADO", False), ("LEIDO", False), ("ENVIADO", True)), 1
    ):
        mundo.sql(
            "INSERT INTO notificaciones.notificacion_destinatario (empresa_id, notificacion_id, "
            "colaborador_id, estado_envio, colaborador_nombre, encolado_en, respaldo_enviado_en) "
            "VALUES (%s, %s, %s, %s, 'N', %s, %s)",
            (mundo.a, nid, 9000 + n, estado, AHORA - timedelta(hours=30),
             AHORA if atendido else None),
        )  # fmt: skip
    assert c.ciclo()["respaldos_encolados"] == 0 and c.cola(RESPALDO) == []
    mundo.sql(
        "INSERT INTO notificaciones.notificacion_destinatario (empresa_id, notificacion_id, "
        "colaborador_id, estado_envio, colaborador_nombre, encolado_en) "
        "VALUES (%s, %s, 99999, 'FALLIDO', 'N', %s)",
        (mundo.a, nid, AHORA - timedelta(hours=30)),
    )
    assert c.ciclo()["respaldos_encolados"] == 1


def test_respaldo_no_antes_de_24_horas_ni_sin_la_opcion(mundo):
    respaldo(mundo, encolado_en=AHORA - timedelta(hours=20))
    mundo.notificacion(estado="COMPLETADA", destinatarios=2, estado_envio="ENVIADO",
                       encolado_en=AHORA - timedelta(hours=40), respaldo=False)  # fmt: skip
    c = Ctx(mundo)
    assert c.ciclo()["respaldos_encolados"] == 0 and c.cola(RESPALDO) == []


def test_respaldo_fuera_de_horario_espera(mundo):
    respaldo(mundo)
    c = Ctx(mundo, ahora=NOCHE)  # 22:00 en Ciudad de México
    assert c.ciclo()["respaldos_encolados"] == 0 and c.cola(RESPALDO) == []
    assert CONTADORES["respaldos_fuera_de_horario"] == 1
    c.ahora = NOCHE + timedelta(hours=10)  # 08:00 del día siguiente
    assert c.ciclo()["respaldos_encolados"] == 1


# --- cierre de la notificación -----------------------------------------------------------------


def test_cierra_completada_o_con_fallas_y_no_toca_las_que_tienen_pendientes(mundo):
    ok = mundo.notificacion(estado="ENVIANDO", destinatarios=2, estado_envio="ENTREGADO")
    mal = mundo.notificacion(estado="ENVIANDO", destinatarios=2, estado_envio="ENVIADO")
    mundo.sql("UPDATE notificaciones.notificacion_destinatario SET estado_envio = 'FALLIDO' "
              "WHERE id = (SELECT min(id) FROM notificaciones.notificacion_destinatario "
              "WHERE notificacion_id = %s)", (mal,))  # fmt: skip
    pendiente = mundo.notificacion(estado="ENVIANDO", destinatarios=2, estado_envio="PENDIENTE")
    c = Ctx(mundo)
    assert c.ciclo()["notificaciones_cerradas"] == 2
    assert (mundo.estado(ok), mundo.estado(mal), mundo.estado(pendiente)) == (
        "COMPLETADA", "CON_FALLAS", "ENVIANDO",
    )  # fmt: skip
    assert mundo.sql(
        "SELECT fecha_envio IS NOT NULL FROM notificaciones.notificacion WHERE id = %s", (ok,)
    )[0][0]
    assert c.ciclo()["notificaciones_cerradas"] == 0  # idempotente


# --- idempotencia general, errores y aislamiento ---------------------------------------------------


def escenario_completo(mundo):
    programada(mundo, 15)
    mundo.notificacion(estado="ENVIANDO", destinatarios=4, encolado_en=AHORA - timedelta(hours=1))
    respaldo(mundo)
    mundo.notificacion(estado="ENVIANDO", destinatarios=1, estado_envio="ENTREGADO")


def test_dos_ciclos_seguidos_no_generan_trabajo_duplicado(mundo):
    escenario_completo(mundo)
    c = Ctx(mundo)
    primero = c.ciclo()
    assert primero == {
        "programadas_reencoladas": 1, "destinatarios_liberados": 4, "respaldos_encolados": 1,
        "notificaciones_cerradas": 1, "errores": 0,
    }  # fmt: skip
    mensajes = c.total()
    estados = mundo.sql("SELECT id, estado FROM notificaciones.notificacion ORDER BY id")
    c.ahora = AHORA + timedelta(minutes=5)
    segundo = c.ciclo()
    assert segundo == {k: 0 for k in primero}
    assert c.total() == mensajes == 3
    assert mundo.sql("SELECT id, estado FROM notificaciones.notificacion ORDER BY id") == estados


def test_un_paso_con_error_no_bloquea_a_los_demas_y_se_reintenta(mundo):
    prog = programada(mundo, 15)
    ok = mundo.notificacion(estado="ENVIANDO", destinatarios=1, estado_envio="ENTREGADO")
    c = Ctx(mundo)
    c.sqs.fallar_envio = True
    r = c.ciclo()
    assert r["errores"] == 1
    assert mundo.estado(ok) == "COMPLETADA"  # el cierre sí corrió
    assert (
        mundo.sql("SELECT reencolada_en FROM notificaciones.notificacion WHERE id = %s", (prog,))[
            0
        ][0]
        is None
    )
    c.sqs.fallar_envio = False
    assert c.ciclo()["programadas_reencoladas"] == 1


def test_aislamiento_por_empresa(mundo):
    pa = programada(mundo, 15, mundo.a)
    pb = programada(mundo, 15, mundo.b)
    la = mundo.notificacion(
        mundo.a, estado="ENVIANDO", destinatarios=1, encolado_en=AHORA - timedelta(hours=1)
    )
    lb = mundo.notificacion(
        mundo.b, estado="ENVIANDO", destinatarios=2, encolado_en=AHORA - timedelta(hours=1)
    )
    c = Ctx(mundo)
    c.ciclo()
    por_notif = {m["notificacion_id"]: m["empresa_id"] for m in c.cola(DESPACHO)}
    assert por_notif == {pa: mundo.a, pb: mundo.b, la: mundo.a, lb: mundo.b}
    assert (
        mundo.contar(la, "encolado_en IS NULL") == 1
        and mundo.contar(lb, "encolado_en IS NULL") == 2
    )


def test_sin_trabajo_no_hace_nada(mundo):
    c = Ctx(mundo)
    assert c.ciclo() == {
        "programadas_reencoladas": 0, "destinatarios_liberados": 0, "respaldos_encolados": 0,
        "notificaciones_cerradas": 0, "errores": 0,
    }  # fmt: skip
    assert c.total() == 0


def test_la_conexion_de_la_lambda_no_ve_otras_tablas_sin_empresa(mundo):
    """Sin ``app.empresa_id`` la RLS no devuelve filas: las funciones de conciliación son la única
    puerta entre empresas y solo entregan ids."""
    mundo.notificacion(estado="ENVIANDO", destinatarios=2, estado_envio="ENTREGADO")
    with mundo.abrir() as conn:
        assert conn.execute("SELECT count(*) FROM notificaciones.notificacion").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT count(*) FROM notificaciones.conciliar_cierres_pendientes()"
            ).fetchone()[0]
            == 1
        )
