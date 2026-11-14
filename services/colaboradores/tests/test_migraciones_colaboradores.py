"""T-028: migraciones de campos y colaboradores."""

import hashlib

import psycopg
import pytest

from tests.fixtures.migrar import bajar, subir

pytestmark = pytest.mark.docker


def _crudo(bd) -> str:
    return bd.url_sync.replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture
def bd(base_datos):
    for servicio in ("dashboard", "campos", "colaboradores"):
        subir(servicio, base_datos.url_sync)
    return base_datos


@pytest.fixture
def ctx(bd):
    """Empresa, organización, planta y un campo de lista con una opción."""
    with psycopg.connect(_crudo(bd), autocommit=True) as c:
        emp = c.execute(
            "INSERT INTO identidad.empresa (razon_social) VALUES ('E') RETURNING id"
        ).fetchone()[0]
        org = c.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORG01', 'Org') RETURNING id",
            (emp,),
        ).fetchone()[0]
        pla = c.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Apodaca') "
            "RETURNING id",
            (emp,),
        ).fetchone()[0]
        campo = c.execute(
            "INSERT INTO campos.campo_colaborador (empresa_id, nombre_campo, clave, codigo_interno, tipo_dato, orden) "
            "VALUES (%s, 'Turno', 'turno', 'CAMP-0001', 'LISTA', 1) RETURNING id",
            (emp,),
        ).fetchone()[0]
        opcion = c.execute(
            "INSERT INTO campos.opcion_campo (empresa_id, campo_id, etiqueta, valor, descripcion) "
            "VALUES (%s, %s, 'Matutino', 'MATUTINO', '08:00 – 17:00') RETURNING id",
            (emp, campo),
        ).fetchone()[0]
    return {"emp": emp, "org": org, "pla": pla, "campo": campo, "opcion": opcion}


def _colaborador(c, ctx, numero="EMP-0001", celular="8112345678", **extra):
    columnas = {
        "empresa_id": ctx["emp"],
        "organizacion_id": ctx["org"],
        "planta_id": ctx["pla"],
        "numero_empleado": numero,
        "nombres": "María Fernanda",
        "apellido_paterno": "Ramírez",
        "apellido_materno": "Ortiz",
        "celular_cifrado": b"\x01cifrado",
        "celular_hash": hashlib.sha256(celular.encode()).digest(),
        "celular_ultimos4": celular[-4:],
        "fecha_ingreso": "2021-03-15",
        "puesto": "Operador",
        "tipo_empleado": "OPERATIVO",
    }
    columnas.update(extra)
    nombres = ", ".join(columnas)
    marcas = ", ".join(["%s"] * len(columnas))
    return c.execute(
        f"INSERT INTO colaboradores.colaborador ({nombres}) VALUES ({marcas}) RETURNING id",  # noqa: S608
        list(columnas.values()),
    ).fetchone()[0]


def test_tablas_creadas(bd):
    esperadas = {
        "campos": {
            "campo_colaborador",
            "contador_campo",
            "opcion_campo",
            "outbox",
            "evento_procesado",
            "alembic_version",
        },
        "colaboradores": {
            "organizacion",
            "planta",
            "colaborador",
            "valor_campo",
            "carga_colaboradores",
            "fila_carga",
            "clave_datos",
            "outbox",
            "evento_procesado",
            "alembic_version",
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


def test_unicidad_por_empresa(ctx, bd):
    with psycopg.connect(_crudo(bd), autocommit=True) as c:
        _colaborador(c, ctx)
        with pytest.raises(psycopg.errors.UniqueViolation) as e1:
            _colaborador(c, ctx, numero="EMP-0001", celular="8199999999")
        assert e1.value.diag.constraint_name == "colaborador_empresa_id_numero_empleado_key"
        with pytest.raises(psycopg.errors.UniqueViolation) as e2:
            _colaborador(c, ctx, numero="EMP-0002", celular="8112345678")
        assert e2.value.diag.constraint_name == "colaborador_empresa_id_celular_hash_key"
        # Otra empresa sí puede repetir número y celular.
        emp2 = c.execute(
            "INSERT INTO identidad.empresa (razon_social) VALUES ('E2') RETURNING id"
        ).fetchone()[0]
        org2 = c.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORG01', 'Org') RETURNING id",
            (emp2,),
        ).fetchone()[0]
        pla2 = c.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Apodaca') "
            "RETURNING id",
            (emp2,),
        ).fetchone()[0]
        _colaborador(c, {**ctx, "emp": emp2, "org": org2, "pla": pla2})


@pytest.mark.parametrize(
    "extra",
    [
        {"tipo_empleado": "HONORARIOS"},
        {"estatus": "SUSPENDIDO"},
        {"numero_empleado": "emp-0009"},
        {"fecha_baja": "2026-01-01"},
        {"celular_ultimos4": "12ab"},
    ],
)
def test_checks_de_colaborador(ctx, bd, extra):
    with (
        psycopg.connect(_crudo(bd), autocommit=True) as c,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        _colaborador(
            c,
            ctx,
            numero=extra.get("numero_empleado", "EMP-0100"),
            **{k: v for k, v in extra.items() if k != "numero_empleado"},
        )


def test_valor_campo_un_solo_valor(ctx, bd):
    with psycopg.connect(_crudo(bd), autocommit=True) as c:
        col = _colaborador(c, ctx)
        c.execute(
            "INSERT INTO colaboradores.valor_campo (empresa_id, colaborador_id, campo_id, valor_opcion_id) "
            "VALUES (%s, %s, %s, %s)",
            (ctx["emp"], col, ctx["campo"], ctx["opcion"]),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(
                "INSERT INTO colaboradores.valor_campo (empresa_id, colaborador_id, campo_id, valor_texto) "
                "VALUES (%s, %s, %s, 'x')",
                (ctx["emp"], col, ctx["campo"]),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "UPDATE colaboradores.valor_campo SET valor_texto = 'x' WHERE colaborador_id = %s",
                (col,),
            )


def test_campos_restricciones(ctx, bd):
    with psycopg.connect(_crudo(bd), autocommit=True) as c:
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO campos.campo_colaborador (empresa_id, nombre_campo, clave, codigo_interno, tipo_dato, orden) "
                "VALUES (%s, 'X', 'Clave Mala', 'CAMP-0002', 'TEXTO', 2)",
                (ctx["emp"],),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO campos.campo_colaborador (empresa_id, nombre_campo, clave, codigo_interno, tipo_dato, orden) "
                "VALUES (%s, 'X', 'x2', 'CAMP-0003', 'JSON', 2)",
                (ctx["emp"],),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "UPDATE campos.campo_colaborador SET codigo_interno = 'CAMP-0099' WHERE id = %s",
                (ctx["campo"],),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "UPDATE campos.opcion_campo SET valor = 'OTRO' WHERE id = %s", (ctx["opcion"],)
            )
        c.execute(
            "UPDATE campos.opcion_campo SET etiqueta = 'Matutino (L-V)', activo = false WHERE id = %s",
            (ctx["opcion"],),
        )
        c.execute(
            "UPDATE campos.campo_colaborador SET es_sugerido = true WHERE id = %s", (ctx["campo"],)
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "UPDATE campos.campo_colaborador SET eliminado = true, activo = false WHERE id = %s",
                (ctx["campo"],),
            )


def test_planta_unica_sin_mayusculas_y_carga(ctx, bd):
    with psycopg.connect(_crudo(bd), autocommit=True) as c:
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(
                "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'APODACA')",
                (ctx["emp"],),
            )
        usu = c.execute(
            "INSERT INTO identidad.usuario (empresa_id, nombre, correo, cognito_sub) "
            "VALUES (%s, 'RH', 'rh@x.com', 's') RETURNING id",
            (ctx["emp"],),
        ).fetchone()[0]
        carga = c.execute(
            "INSERT INTO colaboradores.carga_colaboradores (empresa_id, usuario_id, nombre_archivo, "
            "version_plantilla) VALUES (%s, %s, 'a.xlsx', '1.3') RETURNING id",
            (ctx["emp"], usu),
        ).fetchone()[0]
        c.execute(
            "INSERT INTO colaboradores.fila_carga (empresa_id, carga_id, numero_fila, resultado) "
            "VALUES (%s, %s, 3, 'ERROR')",
            (ctx["emp"], carga),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(
                "INSERT INTO colaboradores.fila_carga (empresa_id, carga_id, numero_fila, resultado) "
                "VALUES (%s, %s, 3, 'NUEVO')",
                (ctx["emp"], carga),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "UPDATE colaboradores.carga_colaboradores SET total_filas = 2001 WHERE id = %s",
                (carga,),
            )


def test_busqueda_trigrama_usa_indice(ctx, bd):
    with psycopg.connect(_crudo(bd), autocommit=True) as c:
        for i in range(300):
            _colaborador(c, ctx, numero=f"EMP-{i:04d}", celular=f"81{i:08d}")
        c.execute("ANALYZE colaboradores.colaborador")
        c.execute("SET enable_seqscan = off")
        plan = "\n".join(
            r[0]
            for r in c.execute(
                "EXPLAIN SELECT id FROM colaboradores.colaborador WHERE "
                "colaboradores.f_unaccent(lower(nombres || ' ' || apellido_paterno || ' ' || apellido_materno)) "
                "LIKE '%' || colaboradores.f_unaccent(lower('ramirez')) || '%'"
            )
        )
        assert "colaborador_nombre_trgm" in plan
        n = c.execute(
            "SELECT count(*) FROM colaboradores.colaborador WHERE "
            "colaboradores.f_unaccent(lower(nombres || ' ' || apellido_paterno)) LIKE '%ramirez%'"
        ).fetchone()[0]
        assert n == 300


def test_sube_y_baja(base_datos):
    for s in ("dashboard", "campos", "colaboradores"):
        subir(s, base_datos.url_sync)
    bajar("colaboradores", base_datos.url_sync)
    bajar("campos", base_datos.url_sync)
    with psycopg.connect(_crudo(base_datos)) as c:
        n = c.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema IN "
            "('campos', 'colaboradores') AND table_name <> 'alembic_version'"
        ).fetchone()[0]
    assert n == 0
