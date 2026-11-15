"""T-207 (T-078): catálogo de variables y resolutor (sin base de datos)."""

from datetime import UTC, datetime

from cc_constancias.clientes import DefinicionCampo, OpcionCampo, StubColaboradores
from cc_constancias.render.catalogo_variables import Catalogo
from cc_constancias.render.resolutor_variables import resolver

AHORA = datetime(2026, 11, 15, 3, 0, tzinfo=UTC)  # en México todavía es 14 de noviembre


def _defs() -> list[DefinicionCampo]:
    return [
        DefinicionCampo(1, "Área", "area", "CAMP-0001", "LISTA", orden=1),
        DefinicionCampo(2, "NSS", "nss", "CAMP-0002", "TEXTO", es_sensible=True, orden=2),
        DefinicionCampo(3, "RFC", "rfc", "CAMP-0003", "TEXTO", es_sensible=True, orden=3),
        DefinicionCampo(4, "Sueldo", "sueldo", "CAMP-0004", "NUMERO", es_sensible=True, orden=4),
        DefinicionCampo(
            5,
            "Periodicidad",
            "periodicidad_sueldo",
            "CAMP-0005",
            "LISTA",
            orden=5,
            opciones=(OpcionCampo(1, "Quincenal", "QUINCENAL"),),
        ),
        DefinicionCampo(6, "Antigüedad", "antiguedad", "CAMP-0006", "FECHA", orden=6),
        DefinicionCampo(7, "Ruta", "ruta_transporte", "CAMP-0007", "TEXTO", activo=False, orden=7),
    ]


# ------------------------------------------------------------------ catálogo


def test_el_catalogo_agrupa_colaborador_organizacion_sensibles_y_sistema():
    activas = Catalogo(_defs()).activas()
    por_grupo: dict[str, list[str]] = {}
    for v in activas:
        por_grupo.setdefault(v.grupo, []).append(v.nombre)
    assert list(por_grupo) == ["COLABORADOR", "ORGANIZACION", "SENSIBLES", "SISTEMA"]
    assert por_grupo["COLABORADOR"] == [
        "nombre_completo",
        "puesto",
        "fecha_ingreso",
        "planta",
        "horario",
        "area",
        "periodicidad_sueldo",
        "antiguedad",
    ]
    assert por_grupo["ORGANIZACION"] == [
        "organizacion.razon_social",
        "organizacion.rfc",
        "organizacion.domicilio_fiscal",
        "organizacion.nombre_firmante",
        "organizacion.cargo_firmante",
        "organizacion.correo_firmante",
        "lugar",
        "registro_patronal",
    ]
    # los campos sensibles y después las derivadas, como en el editor
    assert por_grupo["SENSIBLES"] == ["nss", "rfc", "sueldo", "sueldo_mensual", "sueldo_letra"]
    assert por_grupo["SISTEMA"] == ["folio", "fecha_emision", "qr_verificacion"]
    assert all(v.sensible for v in activas if v.grupo == "SENSIBLES")
    assert not any(v.sensible for v in activas if v.grupo != "SENSIBLES")


def test_un_campo_inactivo_no_se_ofrece_pero_se_distingue_de_uno_inexistente():
    c = Catalogo(_defs())
    assert "ruta_transporte" not in [v.nombre for v in c.activas()]
    assert c.estado("ruta_transporte") == "INACTIVA"
    assert c.estado("eliminado") == "INEXISTENTE"
    assert c.estado("area") == "ACTIVA" and c.estado("sueldo_mensual") == "ACTIVA"
    assert c.estado("empresa") == "INEXISTENTE"  # {{empresa}} sigue pendiente (PQ-17)


def test_registro_patronal_siempre_existe_aunque_el_campo_no_este():
    sin_campos = Catalogo([])
    assert sin_campos.estado("registro_patronal") == "ACTIVA"
    assert sin_campos.estado("nss") == "INEXISTENTE"  # sin campo, sin variable
    con_campo_inactivo = Catalogo(
        [DefinicionCampo(9, "Reg", "registro_patronal", "CAMP-0009", "TEXTO", activo=False)]
    )
    assert (
        con_campo_inactivo.estado("registro_patronal") == "ACTIVA"
    )  # el respaldo es el de la org.


def test_clasificar_inexistentes_inactivas_y_sensibles_sin_repetir():
    r = Catalogo(_defs()).clasificar(
        ["area", "nss", "nss", "ruta_transporte", "fantasma", "sueldo_letra", "folio", "fantasma"]
    )
    assert r == {
        "inexistentes": ["fantasma"],
        "inactivas": ["ruta_transporte"],
        "sensibles": ["nss", "sueldo_letra"],
    }


def test_las_variables_de_fecha_se_conocen():
    assert Catalogo(_defs()).fechas() == {"fecha_ingreso", "fecha_emision", "antiguedad"}


def test_una_clave_reservada_no_pisa_a_una_variable_del_sistema():
    c = Catalogo([DefinicionCampo(1, "Folio", "folio", "CAMP-0001", "TEXTO", es_sensible=True)])
    assert c.obtener("folio").grupo == "SISTEMA" and not c.es_sensible("folio")


# ------------------------------------------------------------------ resolutor

COLABORADOR = {
    "nombre_completo": "María Fernanda Ramírez Ortiz",
    "puesto": "Operadora",
    "fecha_ingreso": "2021-03-15",
    "planta": "Apodaca",
    "horario": "6:00 a 14:00",
    "area": "Producción",
    "nss": "12345678901",
    "sueldo": "9500",
    "periodicidad_sueldo": "QUINCENAL",
    "registro_patronal": "A0000000000",
    "organizacion.razon_social": "Empresa Ejemplo SA de CV",
    "lugar": "Monterrey",
    "antiguedad": "2020-01-01",
}


async def _resolver(variables, colaborador=None, **kw):
    stub = StubColaboradores({7: COLABORADOR if colaborador is None else colaborador})
    r = await resolver(
        stub,
        empresa_id=1,
        colaborador_id=7,
        variables=variables,
        definiciones=_defs(),
        ahora=AHORA,
        **kw,
    )
    return r, stub


async def test_resuelve_fijas_organizacion_campos_derivadas_y_sistema():
    r, _ = await _resolver(
        [
            "nombre_completo",
            "fecha_ingreso",
            "horario",
            "area",
            "registro_patronal",
            "organizacion.razon_social",
            "lugar",
            "sueldo_mensual",
            "sueldo_letra",
            "antiguedad",
            "folio",
            "fecha_emision",
        ],
        sistema={"folio": "CG-2026-0001"},
    )
    assert r.faltantes == [] and r.desconocidas == []
    assert r.valores == {
        "nombre_completo": "María Fernanda Ramírez Ortiz",
        "fecha_ingreso": "15 de marzo de 2021",  # en texto largo
        "horario": "6:00 a 14:00",  # de la descripción de la opción del turno
        "area": "Producción",
        "registro_patronal": "A0000000000",
        "organizacion.razon_social": "Empresa Ejemplo SA de CV",
        "lugar": "Monterrey",
        "sueldo_mensual": "$19,000.00",  # 9,500 quincenal × 2
        "sueldo_letra": "DIECINUEVE MIL PESOS 00/100 MN",
        "antiguedad": "1 de enero de 2020",  # un campo de fecha también va en texto
        "folio": "CG-2026-0001",
        "fecha_emision": "14 de noviembre de 2026",  # fecha de México, no UTC
    }
    assert r.factores_version == "1"
    assert r.sensibles_usadas == ["sueldo_mensual", "sueldo_letra"]


async def test_a_colaboradores_solo_van_las_que_el_resuelve_mas_los_insumos_del_sueldo():
    _, stub = await _resolver(
        ["nombre_completo", "folio", "sueldo_letra", "fantasma", "fecha_emision"],
        sistema={"folio": "CG-1"},
    )
    (_, colaborador_id, enviadas) = stub.llamadas[0]
    assert colaborador_id == 7
    assert enviadas == ["nombre_completo", "sueldo", "periodicidad_sueldo"]


async def test_una_variable_inexistente_se_marca_y_no_se_envia_a_nadie():
    r, stub = await _resolver(["area", "fantasma", "empresa"])
    assert r.desconocidas == ["fantasma", "empresa"]
    assert r.valores == {"area": "Producción"} and r.faltantes == []
    assert stub.llamadas[0][2] == ["area"]


async def test_una_variable_inactiva_sigue_resolviendo_sus_valores_conservados():
    r, _ = await _resolver(["ruta_transporte"], colaborador={"ruta_transporte": "Ruta 7"})
    assert r.valores == {"ruta_transporte": "Ruta 7"} and r.desconocidas == []


async def test_sin_valor_es_faltante_y_el_orden_se_conserva():
    r, _ = await _resolver(
        ["puesto", "nss", "rfc", "area"], colaborador={"puesto": "Op", "area": "A"}
    )
    assert r.valores == {"puesto": "Op", "area": "A"}
    assert r.faltantes == ["nss", "rfc"]
    assert r.sensibles_usadas == ["nss", "rfc"]


async def test_texto_en_blanco_cuenta_como_faltante():
    r, _ = await _resolver(["puesto"], colaborador={"puesto": "   "})
    assert r.faltantes == ["puesto"] and r.valores == {}


async def test_las_derivadas_faltan_si_falta_algun_insumo_o_no_se_pueden_calcular():
    sin_periodicidad = {k: v for k, v in COLABORADOR.items() if k != "periodicidad_sueldo"}
    r, _ = await _resolver(
        ["sueldo_mensual", "sueldo_letra", "puesto"], colaborador=sin_periodicidad
    )
    assert r.faltantes == ["sueldo_mensual", "sueldo_letra"] and r.valores == {
        "puesto": "Operadora"
    }
    for malo in ({"sueldo": "abc"}, {"sueldo": "0"}, {"periodicidad_sueldo": "ANUAL"}):
        r, _ = await _resolver(["sueldo_mensual"], colaborador={**COLABORADOR, **malo})
        assert r.faltantes == ["sueldo_mensual"], malo


async def test_solo_se_calcula_lo_que_la_plantilla_usa():
    r, _ = await _resolver(["sueldo_letra"])
    assert list(r.valores) == ["sueldo_letra"] and "sueldo_mensual" not in r.valores


async def test_sueldos_semanales_y_catorcenales():
    r, _ = await _resolver(
        ["sueldo_mensual"], colaborador={"sueldo": "1000", "periodicidad_sueldo": "SEMANAL"}
    )
    assert r.valores["sueldo_mensual"] == "$4,333.33"
    r, _ = await _resolver(
        ["sueldo_mensual", "sueldo_letra"],
        colaborador={"sueldo": "5000", "periodicidad_sueldo": "CATORCENAL"},
    )
    assert r.valores["sueldo_letra"] == "DIEZ MIL OCHOCIENTOS TREINTA Y TRES PESOS 33/100 MN"


async def test_el_sistema_que_no_se_entrega_es_faltante_salvo_la_fecha_que_se_calcula():
    r, _ = await _resolver(["folio", "qr_verificacion", "fecha_emision"])
    assert r.faltantes == ["folio", "qr_verificacion"]
    assert r.valores == {"fecha_emision": "14 de noviembre de 2026"}


async def test_la_fecha_de_emision_entregada_manda():
    r, _ = await _resolver(["fecha_emision"], sistema={"fecha_emision": "1 de enero de 2030"})
    assert r.valores == {"fecha_emision": "1 de enero de 2030"}


async def test_sin_variables_no_llama_a_colaboradores_con_datos():
    r, stub = await _resolver([])
    assert r.valores == {} and r.faltantes == [] and stub.llamadas[0][2] == []
