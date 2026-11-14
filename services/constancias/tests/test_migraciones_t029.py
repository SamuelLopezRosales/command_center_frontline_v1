"""T-029: migraciones de whatsapp, constancias y notificaciones, vistas y funciones."""

import hashlib
import json
import uuid

import psycopg
import pytest

from tests.fixtures.migrar import ORDEN, bajar, subir_todo

pytestmark = pytest.mark.docker
H64 = "a" * 64


def _crudo(bd) -> str:
    return bd.url_sync.replace("postgresql+psycopg://", "postgresql://")


def _empresa(c, nombre="E"):
    emp = c.execute(
        "INSERT INTO identidad.empresa (razon_social) VALUES (%s) RETURNING id", (nombre,)
    ).fetchone()[0]
    usu = c.execute(
        "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
        "VALUES (%s, 'RH', %s, %s) RETURNING id",
        (emp, f"rh{emp}@x.com", f"s{emp}"),
    ).fetchone()[0]
    org = c.execute(
        "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
        "VALUES (%s, 'ORG01', 'Org') RETURNING id",
        (emp,),
    ).fetchone()[0]
    pla = c.execute(
        "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Apodaca') RETURNING id",
        (emp,),
    ).fetchone()[0]
    return {"emp": emp, "usu": usu, "org": org, "pla": pla}


def _colaborador(c, ctx, numero="EMP-0001", consentimiento=True):
    h = hashlib.sha256(f"{ctx['emp']}{numero}".encode()).digest()
    return c.execute(
        "INSERT INTO colaboradores.colaborador (empresa_id, organizacion_id, planta_id, numero_empleado, nombres, "
        "apellido_paterno, apellido_materno, celular_cifrado, celular_hash, celular_ultimos4, fecha_ingreso, "
        "puesto, tipo_empleado, consentimiento_whatsapp) VALUES (%s,%s,%s,%s,'Ana','López','Ruiz',%s,%s,'5678',"
        "'2021-03-15','Analista','ADMINISTRATIVO',%s) RETURNING id",
        (ctx["emp"], ctx["org"], ctx["pla"], numero, b"\x01x", h, consentimiento),
    ).fetchone()[0]


def _constancia(c, ctx, col, folio="CG-2026-0001", estado="PENDIENTE"):
    pla = c.execute(
        "INSERT INTO constancias.plantilla_constancia (empresa_id, nombre, activa) "
        "VALUES (%s, %s, true) RETURNING id",
        (ctx["emp"], f"Laboral {uuid.uuid4().hex[:8]}"),
    ).fetchone()[0]
    ver = c.execute(
        "INSERT INTO constancias.version_plantilla (empresa_id, plantilla_id, numero, contenido_s3_key, "
        "hash_sha256, creada_por_usuario_id) VALUES (%s,%s,1,'k',%s,%s) RETURNING id",
        (ctx["emp"], pla, H64, ctx["usu"]),
    ).fetchone()[0]
    sol = c.execute(
        "INSERT INTO constancias.solicitud_constancia (empresa_id, colaborador_id, version_plantilla_id, "
        "estado, colaborador_nombre) VALUES (%s,%s,%s,'GENERADA','Ana López Ruiz') RETURNING id",
        (ctx["emp"], col, ver),
    ).fetchone()[0]
    cid = c.execute(
        "INSERT INTO constancias.constancia_generada (empresa_id, solicitud_id, colaborador_id, version_plantilla_id, "
        "folio, pdf_s3_key, pdf_hash_sha256, datos_snapshot_json, colaborador_nombre, numero_empleado, "
        "codigo_verificacion, estado_entrega) VALUES (%s,%s,%s,%s,%s,'pdf',%s,%s,'Ana López Ruiz','EMP-0001',%s,%s) "
        "RETURNING id",
        (
            ctx["emp"],
            sol,
            col,
            ver,
            folio,
            H64,
            json.dumps({"puesto": "Analista"}),
            uuid.uuid4().hex,
            estado,
        ),
    ).fetchone()[0]
    return {"plantilla": pla, "version": ver, "solicitud": sol, "constancia": cid}


@pytest.fixture
def bd(base_datos):
    subir_todo(base_datos.url_sync)
    return base_datos


def test_todas_las_tablas(bd):
    esperadas = {
        "whatsapp": {
            "conversacion_whatsapp",
            "mensaje_whatsapp",
            "codigo_verificacion",
            "clave_datos",
            "outbox",
        },
        "constancias": {
            "plantilla_constancia",
            "version_plantilla",
            "borrador_plantilla",
            "solicitud_constancia",
            "constancia_generada",
            "contador_folio",
            "token_descarga",
            "alerta_plantilla",
            "clave_datos",
            "outbox",
        },
        "notificaciones": {
            "audiencia",
            "plantilla_mensaje",
            "notificacion",
            "notificacion_destinatario",
            "outbox",
        },
    }
    with psycopg.connect(_crudo(bd)) as c:
        for esquema, tablas in esperadas.items():
            reales = {
                r[0]
                for r in c.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
                    (esquema,),
                )
            }
            assert tablas <= reales, esquema
        vistas = {
            f"{r[0]}.{r[1]}"
            for r in c.execute(
                "SELECT table_schema, table_name FROM information_schema.views "
                "WHERE table_schema IN ('constancias', 'colaboradores')"
            )
        }
    assert vistas == {
        "constancias.v_historial",
        "constancias.v_solicitudes_recientes",
        "constancias.v_resumen",
        "constancias.v_alertas",
        "colaboradores.v_resumen",
        "colaboradores.v_alertas",
    }


def test_version_y_constancia_inmutables(bd):
    with psycopg.connect(_crudo(bd), autocommit=True) as c:
        ctx = _empresa(c)
        k = _constancia(c, ctx, _colaborador(c, ctx))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(
                "UPDATE constancias.version_plantilla SET contenido_s3_key = 'otra' WHERE id = %s",
                (k["version"],),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("DELETE FROM constancias.version_plantilla WHERE id = %s", (k["version"],))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(
                "UPDATE constancias.constancia_generada SET datos_snapshot_json = '{}' WHERE id = %s",
                (k["constancia"],),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(
                "DELETE FROM constancias.constancia_generada WHERE id = %s", (k["constancia"],)
            )
        # Lo permitido: entrega y vigencia.
        c.execute(
            "UPDATE constancias.constancia_generada SET estado_entrega = 'ENTREGADA', fecha_entrega = now(), "
            "estado_vigencia = 'CANCELADA', fecha_cancelacion = now(), motivo_cancelacion = 'x' WHERE id = %s",
            (k["constancia"],),
        )


def test_unicidades_de_constancias(bd):
    with psycopg.connect(_crudo(bd), autocommit=True) as c:
        ctx = _empresa(c)
        col = _colaborador(c, ctx)
        _constancia(c, ctx, col, folio="CG-2026-0001")
        with pytest.raises(psycopg.errors.UniqueViolation) as e:
            _constancia(c, ctx, col, folio="CG-2026-0001")
        assert e.value.diag.constraint_name == "constancia_empresa_id_folio_key"
        with pytest.raises(psycopg.errors.CheckViolation):
            _constancia(c, ctx, col, folio="FOLIO-1")
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO constancias.token_descarga (empresa_id, constancia_id, token_hash, fecha_expira, "
                "generado_por) SELECT %s, id, sha256('t'), now() + interval '25 hours', 'BOT' "
                "FROM constancias.constancia_generada LIMIT 1",
                (ctx["emp"],),
            )


def test_conversacion_unica_por_numero_y_verificacion(bd):
    with psycopg.connect(_crudo(bd), autocommit=True) as c:
        ctx = _empresa(c)
        col = _colaborador(c, ctx)
        h = hashlib.sha256(b"num").digest()
        c.execute(
            "INSERT INTO whatsapp.conversacion_whatsapp (empresa_id, colaborador_id, celular_hash, origen) "
            "VALUES (%s, %s, %s, 'CONSTANCIA')",
            (ctx["emp"], col, h),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(
                "INSERT INTO whatsapp.conversacion_whatsapp (empresa_id, celular_hash, origen, estado) "
                "VALUES (%s, %s, 'NOTIFICACION', 'ACTIVA')",
                (ctx["emp"], h),
            )
        c.execute("UPDATE whatsapp.conversacion_whatsapp SET estado = 'CERRADA'")
        c.execute(
            "INSERT INTO whatsapp.conversacion_whatsapp (empresa_id, celular_hash, origen, estado) "
            "VALUES (%s, %s, 'NOTIFICACION', 'ACTIVA')",
            (ctx["emp"], h),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute("UPDATE whatsapp.conversacion_whatsapp SET intentos_verificacion = 4")
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "UPDATE whatsapp.conversacion_whatsapp SET estado = 'BLOQUEADA' WHERE estado = 'ACTIVA'"
            )


def test_rango_de_estados(bd):
    with psycopg.connect(_crudo(bd)) as c:
        r = c.execute(
            "SELECT notificaciones.rango_estado_envio(e) FROM unnest(ARRAY['PENDIENTE','ENVIADO','ENTREGADO',"
            "'LEIDO','RESPONDIO']) e"
        ).fetchall()
        valores = [x[0] for x in r]
        assert valores == sorted(valores)
        assert c.execute(
            "SELECT whatsapp.rango_estado_mensaje('ENTREGADO') > "
            "whatsapp.rango_estado_mensaje('ENVIADO')"
        ).fetchone()[0]


def test_destinatario_excluido_exige_motivo(bd):
    with psycopg.connect(_crudo(bd), autocommit=True) as c:
        ctx = _empresa(c)
        n = c.execute(
            "INSERT INTO notificaciones.notificacion (empresa_id, usuario_id, zona_horaria, titulo, modo) "
            "VALUES (%s, %s, 'America/Mexico_City', 'Aviso', 'CRITERIOS') RETURNING id",
            (ctx["emp"], ctx["usu"]),
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO notificaciones.notificacion_destinatario (empresa_id, notificacion_id, colaborador_id, "
                "estado_envio, colaborador_nombre) VALUES (%s, %s, 1, 'EXCLUIDO', 'X')",
                (ctx["emp"], n),
            )
        c.execute(
            "INSERT INTO notificaciones.notificacion_destinatario (empresa_id, notificacion_id, colaborador_id, "
            "estado_envio, motivo_exclusion, colaborador_nombre) VALUES (%s, %s, 1, 'EXCLUIDO', "
            "'ESTATUS_BAJA', 'X')",
            (ctx["emp"], n),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "UPDATE notificaciones.notificacion SET estado = 'PROGRAMADA' WHERE id = %s", (n,)
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO notificaciones.plantilla_mensaje (empresa_id, creada_por_usuario_id, nombre, "
                "categoria, texto_con_variables) VALUES (%s, %s, 'Aviso Nómina', 'UTILITY', 'x')",
                (ctx["emp"], ctx["usu"]),
            )


def test_vistas_filtran_por_empresa(bd):
    with psycopg.connect(_crudo(bd), autocommit=True) as c:
        a, b = _empresa(c, "A"), _empresa(c, "B")
        _constancia(c, a, _colaborador(c, a), estado="FALLIDA")
        _colaborador(c, a, numero="EMP-0002", consentimiento=False)
        _constancia(c, b, _colaborador(c, b), folio="CG-2026-0001")
        c.execute("SELECT set_config('app.empresa_id', %s, false)", (str(a["emp"]),))
        assert c.execute("SELECT count(*) FROM constancias.v_historial").fetchone()[0] == 1
        resumen = c.execute(
            "SELECT constancias_mes, solicitudes_en_proceso, plantillas_activas "
            "FROM constancias.v_resumen"
        ).fetchone()
        assert resumen == (1, 1, 1)
        assert (
            c.execute("SELECT colaboradores_activos FROM colaboradores.v_resumen").fetchone()[0]
            == 2
        )
        tipos = {
            r[0]
            for r in c.execute(
                "SELECT tipo FROM constancias.v_alertas UNION ALL "
                "SELECT tipo FROM colaboradores.v_alertas"
            )
        }
        assert tipos == {"CONSTANCIA_FALLIDA", "SIN_CONSENTIMIENTO"}
        c.execute("SELECT set_config('app.empresa_id', '', false)")
        assert c.execute("SELECT count(*) FROM constancias.v_historial").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM constancias.v_resumen").fetchone()[0] == 0


def test_baja_completa(base_datos):
    subir_todo(base_datos.url_sync)
    for servicio in reversed(ORDEN):
        bajar(servicio, base_datos.url_sync)
    with psycopg.connect(_crudo(base_datos)) as c:
        n = c.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema IN "
            "('identidad','auditoria','campos','colaboradores','whatsapp','constancias','notificaciones') "
            "AND table_name <> 'alembic_version'"
        ).fetchone()[0]
    assert n == 0
