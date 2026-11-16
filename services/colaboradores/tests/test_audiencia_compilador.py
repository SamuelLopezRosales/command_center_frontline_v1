"""T-106: compilador de criterios de audiencia (unitarias y de seguridad; sin base de datos)."""

import re
from datetime import date
from decimal import Decimal

import pytest
from cc_colaboradores.campos_cliente import DefinicionCampo, OpcionCampo
from cc_colaboradores.servicios.audiencia_query_service import FRAGMENTOS, _escapar_like, compilar
from cc_common.criterios_audiencia import MAX_CRITERIOS, OPERADORES_POR_TIPO, validar
from cc_common.errores import ErrorValidacion


def _d(id_, codigo, tipo, sensible=False, activo=True, opciones=()):
    return DefinicionCampo(
        id=id_,
        nombre_campo=codigo,
        clave=codigo.lower(),
        codigo_interno=codigo,
        tipo_dato=tipo,
        es_sensible=sensible,
        activo=activo,
        opciones=tuple(opciones),
    )


DEFS = [
    _d(1, "CAMP-0001", "TEXTO"),
    _d(2, "CAMP-0002", "LISTA", opciones=[OpcionCampo(10, "Ventas", "VENTAS")]),
    _d(3, "CAMP-0003", "NUMERO"),
    _d(4, "CAMP-0004", "FECHA"),
    _d(5, "CAMP-0005", "SI_NO"),
    _d(6, "CAMP-0006", "TEXTO", sensible=True),
    _d(7, "CAMP-0007", "TEXTO", activo=False),
]


def _c(*items, op="Y"):
    return {"op": op, "items": list(items)}


def _h(campo, operador, valor):
    return {"campo": campo, "operador": operador, "valor": valor}


def _compilar(*items, op="Y"):
    return compilar(validar(_c(*items, op=op), DEFS))


def _errores(criterios):
    with pytest.raises(ErrorValidacion) as e:
        validar(criterios, DEFS)
    return {(x.campo, x.codigo) for x in e.value.errores}


# ------------------------------------------------------------------ por operador y por tipo


def test_fijos_es_no_es_en():
    c = _compilar(_h("planta_id", "es", 3), _h("tipo_empleado", "no_es", "OPERATIVO"))
    assert c.sql == "(c.planta_id = :p1 AND c.tipo_empleado <> :p2)"
    assert c.params == {"p1": 3, "p2": "OPERATIVO"}
    c = _compilar(_h("organizacion_id", "en", [1, 2]))
    assert c.sql == "(c.organizacion_id = ANY(:p1))" and c.params == {"p1": [1, 2]}
    c = _compilar(_h("estatus", "es", "ACTIVO"))
    assert c.sql == "(c.estatus = :p1)"


def test_colaborador_id_es_el_criterio_estable_del_modo_individual():
    """T-216: una notificación individual se evalúa como un criterio más sobre ``c.id``."""
    c = _compilar(_h("colaborador_id", "es", 77))
    assert "c.id = :p1" in c.sql and c.params == {"p1": 77}
    assert _errores(_c(_h("colaborador_id", "es", "77"))) == {
        ("criterios.items.0.valor", "VALOR_INVALIDO")
    }


def test_texto_es_contiene_y_no_es():
    c = _compilar(_h("CAMP-0001", "es", "Norte"))
    assert "EXISTS (SELECT 1 FROM colaboradores.valor_campo v" in c.sql
    assert "lower(v.valor_texto) = lower(:p1)" in c.sql and c.sql.count("NOT EXISTS") == 0
    assert c.params == {"p1": "Norte", "p1_campo": 1}
    c = _compilar(_h("CAMP-0001", "contiene", "50%_a\\b"))
    assert "LIKE lower(:p1) ESCAPE" in c.sql
    assert c.params["p1"] == "%50\\%\\_a\\\\b%"  # comodines escapados: se busca el texto literal
    c = _compilar(_h("CAMP-0001", "no_es", "Norte"))
    assert c.sql.startswith("(NOT EXISTS (SELECT 1 FROM colaboradores.valor_campo v")


def test_lista_resuelve_la_opcion_a_su_id_y_no_es_incluye_a_quien_no_tiene_valor():
    c = _compilar(_h("CAMP-0002", "es", "VENTAS"))
    assert "v.valor_opcion_id = :p1" in c.sql and c.params["p1"] == 10
    c = _compilar(_h("CAMP-0002", "en", ["VENTAS"]))
    assert "v.valor_opcion_id = ANY(:p1)" in c.sql and c.params["p1"] == [10]
    c = _compilar(_h("CAMP-0002", "no_es", "VENTAS"))
    assert "NOT EXISTS" in c.sql and c.params["p1"] == 10


def test_numero_todos_los_operadores():
    esperado = {
        "=": "v.valor_numero = :p1",
        "<": "v.valor_numero < :p1",
        "<=": "v.valor_numero <= :p1",
        ">": "v.valor_numero > :p1",
        ">=": "v.valor_numero >= :p1",
    }
    for op, frag in esperado.items():
        c = _compilar(_h("CAMP-0003", op, 12.5))
        assert frag in c.sql and c.params["p1"] == Decimal("12.5")
    c = _compilar(_h("CAMP-0003", "entre", [1, 10]))
    assert "v.valor_numero BETWEEN :p1a AND :p1b" in c.sql
    assert (c.params["p1a"], c.params["p1b"]) == (Decimal(1), Decimal(10))


def test_fecha_antes_despues_entre():
    c = _compilar(_h("CAMP-0004", "antes", "2024-01-31"))
    assert "v.valor_fecha < :p1" in c.sql and c.params["p1"] == date(2024, 1, 31)
    c = _compilar(_h("CAMP-0004", "despues", "2024-01-31"))
    assert "v.valor_fecha > :p1" in c.sql
    c = _compilar(_h("CAMP-0004", "entre", ["2024-01-01", "2024-12-31"]))
    assert "BETWEEN :p1a AND :p1b" in c.sql and c.params["p1b"] == date(2024, 12, 31)


def test_si_no_se_guarda_como_si_o_no():
    assert _compilar(_h("CAMP-0005", "es", True)).params["p1"] == "SI"
    assert _compilar(_h("CAMP-0005", "es", False)).params["p1"] == "NO"


def test_antiguedad_usa_make_interval_con_parametros_y_la_zona():
    c = _compilar(_h("antiguedad_anios", ">=", 5))
    assert "make_interval(years => :p1)" in c.sql and ":zona" in c.sql
    assert c.sql.startswith("(c.fecha_ingreso <=") and c.params == {"p1": 5}
    # a > 5  <=>  a >= 6 ; a < 5  <=>  ingreso posterior a hoy - 5 años ; a <= 5  <=>  a < 6
    assert _compilar(_h("antiguedad_anios", ">", 5)).params == {"p1": 6}
    lt = _compilar(_h("antiguedad_anios", "<", 5))
    assert "c.fecha_ingreso > " in lt.sql and lt.params == {"p1": 5}
    assert _compilar(_h("antiguedad_anios", "<=", 5)).params == {"p1": 6}
    eq = _compilar(_h("antiguedad_anios", "=", 5))
    assert eq.params == {"p1": 5, "p2": 6} and "AND c.fecha_ingreso >" in eq.sql
    entre = _compilar(_h("antiguedad_anios", "entre", [2, 4]))
    assert entre.params == {"p1": 2, "p2": 5}


def test_grupos_y_combinadores():
    c = _compilar(
        _h("planta_id", "es", 1),
        _c(_h("estatus", "es", "ACTIVO"), _h("antiguedad_anios", ">=", 1), op="O"),
    )
    assert c.sql.startswith("(c.planta_id = :p1 AND (c.estatus = :p2 OR c.fecha_ingreso <=")


def test_cada_operador_de_la_lista_cerrada_tiene_fragmento():
    for tipo, ops in OPERADORES_POR_TIPO.items():
        for op in ops:
            assert (tipo, op) in FRAGMENTOS, (tipo, op)


# ------------------------------------------------------------------ seguridad


@pytest.mark.parametrize(
    "malo",
    [
        "x'; DROP TABLE colaboradores.colaborador; --",
        "O'Brien",
        "a;b",
        '"; SELECT 1 --',
        "%' OR '1'='1",
    ],
)
def test_un_valor_con_comillas_o_punto_y_coma_no_altera_la_consulta(malo):
    base = _compilar(_h("CAMP-0001", "es", "Norte"))
    for operador in ("es", "contiene", "no_es"):
        c = _compilar(_h("CAMP-0001", operador, malo))
        # el texto del SQL no incluye el valor: solo nombres de parámetro y fragmentos fijos
        for trozo in (malo, malo.strip()):
            assert trozo not in c.sql
        assert ";" not in c.sql and "'" not in re.sub(r"ESCAPE '\\'", "", c.sql)
        esperado = f"%{_escapar_like(malo)}%" if operador == "contiene" else malo
        assert esperado in c.params.values()
    # misma estructura que con un valor inocuo
    assert _compilar(_h("CAMP-0001", "es", malo)).sql == base.sql


def test_el_sql_solo_contiene_fragmentos_y_nombres_de_parametro():
    c = _compilar(
        _h("CAMP-0001", "contiene", "'; --"),
        _h("CAMP-0002", "en", ["VENTAS"]),
        _h("CAMP-0003", "entre", [1, 2]),
        _h("CAMP-0004", "despues", "2020-02-02"),
        _h("planta_id", "en", [1, 2, 3]),
        _h("antiguedad_anios", "entre", [1, 3]),
    )
    sin_parametros = re.sub(r":p\d+(?:_campo|a|b)?|:zona", "", c.sql)
    assert not re.search(r"[0-9]{4}-|VENTAS|--", sin_parametros)
    assert ":" not in sin_parametros.replace("::", "")


def test_campo_fuera_de_la_lista_cerrada_se_rechaza():
    assert ("criterios.items.0.campo", "CAMPO_DESCONOCIDO") in _errores(
        _c(_h("colaborador.nss; DROP", "es", "x"))
    )
    assert ("criterios.items.0.campo", "CAMPO_DESCONOCIDO") in _errores(
        _c(_h("celular_hash", "es", "x"))
    )
    # inactivo, sensible y de otra empresa (no está en las definiciones)
    assert ("criterios.items.0.campo", "CAMPO_DESCONOCIDO") in _errores(
        _c(_h("CAMP-0007", "es", "x"))
    )
    assert ("criterios.items.0.campo", "CAMPO_SENSIBLE_NO_FILTRABLE") in _errores(
        _c(_h("CAMP-0006", "es", "x"))
    )
    assert ("criterios.items.0.campo", "CAMPO_DESCONOCIDO") in _errores(
        _c(_h("CAMP-9999", "es", "x"))
    )


def test_operadores_y_valores_invalidos():
    assert ("criterios.items.0.operador", "OPERADOR_NO_PERMITIDO") in _errores(
        _c(_h("CAMP-0001", ">", "x"))
    )
    assert ("criterios.items.0.operador", "OPERADOR_NO_PERMITIDO") in _errores(
        _c(_h("CAMP-0003", "contiene", 1))
    )
    assert ("criterios.items.0.operador", "OPERADOR_NO_PERMITIDO") in _errores(
        _c(_h("CAMP-0005", "no_es", True))
    )
    assert ("criterios.items.0.operador", "OPERADOR_NO_PERMITIDO") in _errores(
        _c(_h("planta_id", ">", 1))
    )
    malos = [
        ("CAMP-0003", "=", "5"),
        ("CAMP-0003", "=", True),
        ("CAMP-0003", "entre", [5, 1]),
        ("CAMP-0004", "antes", "31/01/2024"),
        ("CAMP-0005", "es", "SI"),
        ("planta_id", "es", "3; DROP"),
        ("planta_id", "es", True),
        ("tipo_empleado", "es", "GERENTE"),
        ("estatus", "es", "INACTIVO"),
        ("antiguedad_anios", ">=", -1),
        ("antiguedad_anios", ">=", 1.5),
        ("antiguedad_anios", ">=", 500),
        ("CAMP-0001", "es", ""),
        ("CAMP-0001", "es", "x" * 201),
        ("CAMP-0001", "en", ["a"]),
    ]
    for campo, op, valor in malos:
        codigos = {c for _, c in _errores(_c(_h(campo, op, valor)))}
        assert codigos & {"VALOR_INVALIDO", "OPERADOR_NO_PERMITIDO"}, (campo, op, valor)
    assert ("criterios.items.0.valor", "OPCION_DESCONOCIDA") in _errores(
        _c(_h("CAMP-0002", "es", "NO-EXISTE"))
    )


def test_el_error_no_repite_el_valor_recibido():
    with pytest.raises(ErrorValidacion) as e:
        validar(
            _c(_h("CAMP-0003", "=", "secreto-123"), _h("zzz-campo", "es", "otro-secreto")), DEFS
        )
    texto = repr([x.__dict__ for x in e.value.errores])
    assert "secreto" not in texto


def test_estructura_limites_y_profundidad():
    assert ("criterios", "SIN_CRITERIOS") not in _errores({"op": "Y", "items": []})
    assert ("criterios.items", "ESTRUCTURA_INVALIDA") in _errores({"op": "Y", "items": []})
    assert ("criterios.op", "COMBINADOR_INVALIDO") in _errores(
        {"op": "XOR", "items": [_h("planta_id", "es", 1)]}
    )
    assert ("criterios", "ESTRUCTURA_INVALIDA") in _errores({"campo": "planta_id"})
    assert ("criterios.items.0", "ESTRUCTURA_INVALIDA") in _errores(
        _c({"campo": "planta_id", "operador": "es", "valor": 1, "extra": 1})
    )
    profundo = _c(_c(_c(_h("planta_id", "es", 1))))
    assert ("criterios.items.0.items.0", "PROFUNDIDAD_EXCEDIDA") in _errores(profundo)
    veinte = _c(*[_h("planta_id", "es", i + 1) for i in range(MAX_CRITERIOS)])
    validar(veinte, DEFS)  # 20 criterios: permitido
    veintiuno = _c(*[_h("planta_id", "es", i + 1) for i in range(MAX_CRITERIOS + 1)])
    assert ("criterios", "DEMASIADOS_CRITERIOS") in _errores(veintiuno)
    # el límite cuenta también los criterios dentro de subgrupos
    mixto = _c(
        _c(*[_h("planta_id", "es", i + 1) for i in range(15)], op="O"),
        *[_h("planta_id", "es", i + 1) for i in range(6)],
    )
    assert ("criterios", "DEMASIADOS_CRITERIOS") in _errores(mixto)


def test_las_definiciones_de_otra_empresa_no_se_ven_y_el_arbol_vacio_exige_un_criterio():
    with pytest.raises(ErrorValidacion):
        validar(_c(_h("CAMP-0001", "es", "x")), [])
