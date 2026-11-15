"""T-204: plantilla de Excel, lector y validador de filas (sin base de datos)."""

from datetime import date, datetime
from io import BytesIO

import pytest
from ayudantes_carga import (
    FIJAS,
    definiciones_basicas,
    fila_valida,
    libro,
    plantilla_llena,
)
from cc_colaboradores.campos_cliente import DefinicionCampo
from cc_colaboradores.excel import generador, lector
from cc_colaboradores.excel.lector import FilaCruda
from cc_colaboradores.excel.modelo import MAX_BYTES, MAX_FILAS, ArchivoInvalido
from cc_colaboradores.excel.validador import MENSAJES, FilaValida, Referencias, ValidadorCarga
from openpyxl import load_workbook

REF = Referencias({"org1": 1, "org2": 2}, {"norte": 10, "sur": 11})


def _validador(defs=None, columnas=None, ref=REF):
    defs = definiciones_basicas() if defs is None else defs
    columnas = columnas or [*FIJAS, "CAMP-0001", "CAMP-0002", "CAMP-0003", "CAMP-0004", "CAMP-0005"]
    return ValidadorCarga(defs, ref, columnas)


def _fila(n=3, **valores) -> FilaCruda:
    base = fila_valida(1)
    base.update({k: v for k, v in valores.items() if v is not None})
    for k, v in valores.items():
        if v is None:
            base.pop(k, None)
    return FilaCruda(n, base)


def _codigos(r) -> list[str]:
    assert isinstance(r, list), "se esperaba una fila con errores"
    return [e.codigo for e in r]


# ------------------------------------------------------------------ plantilla (T-060)


def test_plantilla_trae_hojas_encabezados_y_validaciones():
    defs = definiciones_basicas() + [
        DefinicionCampo(106, "Turno", "turno", "CAMP-0006", "TEXTO", activo=False, orden=6)
    ]
    contenido = generador.generar(
        defs, [{"clave": "ORG1", "razon_social": "Org Uno", "activa": True}], ["Norte", "Sur"]
    )
    wb = load_workbook(BytesIO(contenido))
    assert wb.sheetnames == [
        "Instrucciones",
        "Colaboradores",
        "Organizaciones",
        "Catálogos",
        "Diccionario",
        "_meta",
    ]
    estados = {n: wb[n].sheet_state for n in wb.sheetnames}
    assert estados["Catálogos"] == "hidden" and estados["_meta"] == "hidden"
    assert estados["Colaboradores"] == "visible" and estados["Diccionario"] == "visible"

    ws = wb["Colaboradores"]
    encabezados = [c.value for c in ws[1]]
    claves = [c.value for c in ws[2]]
    # los once fijos y solo los campos activos, en su orden
    assert claves == [*FIJAS, "nss", "area", "sueldo", "periodicidad_sueldo", "antiguedad"]
    assert "turno" not in claves
    por_clave = dict(zip(claves, encabezados, strict=True))
    assert por_clave["apellido_materno"].endswith("*") and por_clave["tipo_empleado"].endswith("*")
    assert por_clave["estatus"].endswith("*") and not por_clave["nss"].endswith("*")

    tipos = {(str(dv.sqref), dv.type) for dv in ws.data_validations.dataValidation}
    letra = {k: chr(ord("A") + i) for i, k in enumerate(claves)}
    for clave, tipo in (
        ("tipo_empleado", "list"),
        ("estatus", "list"),
        ("planta", "list"),
        ("organizacion", "list"),
        ("celular_whatsapp", "textLength"),
        ("area", "list"),
        ("sueldo", "decimal"),
    ):
        assert (f"{letra[clave]}3:{letra[clave]}2002", tipo) in tipos, clave

    meta = [r for r in wb["_meta"].iter_rows(min_row=1, values_only=True)]
    assert meta[0][:2] == ("version", "CC-2.0")
    assert [r[1] for r in meta[2:]] == [
        *FIJAS,
        "CAMP-0001",
        "CAMP-0002",
        "CAMP-0003",
        "CAMP-0004",
        "CAMP-0005",
    ]
    assert wb["Organizaciones"]["A3"].value == "ORG1"
    assert wb["Catálogos"]["A2"].value == "Norte"


def test_plantilla_se_lee_de_vuelta_y_refleja_un_campo_nuevo():
    defs = definiciones_basicas()
    antes = lector.leer(plantilla_llena(defs, [fila_valida(1, area="Ventas")]))
    assert antes.version == "CC-2.0" and len(antes.filas) == 1
    assert antes.filas[0].numero_fila == 3 and antes.filas[0].valores["CAMP-0002"] == "Ventas"
    assert "CAMP-0006" not in antes.columnas
    defs.append(DefinicionCampo(106, "Turno", "turno", "CAMP-0006", "TEXTO", orden=6))
    despues = lector.leer(plantilla_llena(defs, [fila_valida(1)]))
    assert despues.columnas[-1] == "CAMP-0006"


def test_plantilla_se_abre_con_openpyxl_aunque_no_haya_organizaciones_ni_plantas():
    wb = load_workbook(BytesIO(generador.generar([], [], [])))
    assert wb["Colaboradores"].max_column == len(FIJAS)


# ------------------------------------------------------------------ lector (T-061)


def test_lector_mapea_por_clave_ignora_validacion_ejemplo_y_vacias():
    filas = [
        fila_valida(1, numero_empleado="EJEMPLO-001"),
        fila_valida(2, fecha_ingreso=datetime(2021, 3, 15)),
        {},
        fila_valida(3, fecha_ingreso="15/03/2021", celular_whatsapp=8112345678.0),
    ]
    contenido = libro(filas, claves=[*FIJAS, "_validacion"])
    # una fórmula en la columna de validación no se evalúa ni llega a las filas
    wb = load_workbook(BytesIO(contenido))
    wb["Colaboradores"].cell(row=4, column=len(FIJAS) + 1, value='=IF(A4="","","OK")')
    buf = BytesIO()
    wb.save(buf)
    a = lector.leer(buf.getvalue())
    assert a.version == "EXTERNA" and "_validacion" in a.columnas
    assert [f.numero_fila for f in a.filas] == [4, 6]  # sin el ejemplo ni la fila vacía
    assert all("_validacion" not in f.valores for f in a.filas)
    assert a.filas[0].valores["fecha_ingreso"] == datetime(2021, 3, 15)
    assert a.filas[1].valores["celular_whatsapp"] == 8112345678


def test_lector_con_meta_usa_el_codigo_no_el_encabezado():
    renombradas = [("numero" if k == "numero_empleado" else k) for k in FIJAS]
    contenido = libro(
        [fila_valida(1, numero=None) | {"numero": "E-1"}],
        claves=renombradas,
        meta=FIJAS,
    )
    a = lector.leer(contenido)
    assert a.version == "CC-2.0" and a.filas[0].valores["numero_empleado"] == "E-1"


def test_lector_una_formula_en_una_celda_de_datos_llega_como_texto():
    a = lector.leer(libro([fila_valida(1, puesto="=1+1")], claves=FIJAS))
    assert a.filas[0].valores["puesto"] == "=1+1"


def test_lector_acepta_2000_filas_y_rechaza_2001():
    ok = libro([fila_valida(i) for i in range(1, MAX_FILAS + 1)], claves=FIJAS)
    assert len(lector.leer(ok).filas) == MAX_FILAS
    with pytest.raises(ArchivoInvalido) as exc:
        lector.leer(libro([fila_valida(i) for i in range(1, MAX_FILAS + 2)], claves=FIJAS))
    assert exc.value.motivo == "DEMASIADAS_FILAS"


def test_lector_rechaza_archivos_ajenos_sin_procesar_filas():
    casos = {
        "ARCHIVO_DEMASIADO_GRANDE": b"PK" + b"0" * MAX_BYTES,
        "NO_ES_XLSX": b"%PDF-1.7 no es excel",
    }
    for motivo, contenido in casos.items():
        with pytest.raises(ArchivoInvalido) as exc:
            lector.leer(contenido)
        assert exc.value.motivo == motivo
    with pytest.raises(ArchivoInvalido) as exc:  # ZIP sin estructura de libro
        lector.leer(b"PK\x03\x04" + b"\x00" * 40)
    assert exc.value.motivo == "NO_ES_XLSX"

    from openpyxl import Workbook

    otra = Workbook()
    otra.active.title = "Hoja1"
    buf = BytesIO()
    otra.save(buf)
    with pytest.raises(ArchivoInvalido) as exc:
        lector.leer(buf.getvalue())
    assert exc.value.motivo == "SIN_HOJA_COLABORADORES"
    with pytest.raises(ArchivoInvalido) as exc:  # faltan columnas fijas
        lector.leer(libro([fila_valida(1)], claves=["numero_empleado", "nombres"]))
    assert exc.value.motivo == "ESTRUCTURA_AJENA"
    with pytest.raises(ArchivoInvalido) as exc:  # claves repetidas
        lector.leer(libro([fila_valida(1)], claves=[*FIJAS, "puesto"]))
    assert exc.value.motivo == "COLUMNAS_REPETIDAS"


# ------------------------------------------------------------------ validador (T-061, §10.3)


def test_fila_valida_se_normaliza():
    r = _validador().validar(
        _fila(
            numero_empleado=" e-0001 ",
            celular_whatsapp=" 81-1234 5678",
            tipo_empleado="OPERATIVO",
            estatus="activo",
            fecha_ingreso=datetime(2021, 3, 15),
            organizacion="org1",
            planta="NORTE",
            **{"CAMP-0002": "producción", "CAMP-0001": "12345678901", "CAMP-0003": 9500.5},
            **{"CAMP-0004": "QUINCENAL"},
        )
    )
    assert isinstance(r, FilaValida)
    d = r.datos
    assert d.numero_empleado == "E-0001" and d.celular == "8112345678"
    assert (d.organizacion_id, d.planta_id, d.tipo_empleado) == (1, 10, "OPERATIVO")
    assert d.fecha_ingreso == date(2021, 3, 15) and r.estatus == "ACTIVO"
    por_codigo = {v.codigo_interno: v.valor for v in r.valores}
    assert por_codigo["CAMP-0002"] == 201  # id de la opción PRODUCCION, por etiqueta sin acento
    assert por_codigo["CAMP-0004"] == 212 and str(por_codigo["CAMP-0003"]) == "9500.5000"


def test_una_celda_vacia_de_un_campo_opcional_no_genera_borrado():
    r = _validador().validar(_fila())  # ningún campo dinámico capturado
    assert isinstance(r, FilaValida) and r.valores == []


@pytest.mark.parametrize(
    ("cambios", "esperado"),
    [
        ({"nombres": None}, "FALTA_OBLIGATORIO"),
        ({"apellido_materno": None}, "FALTA_OBLIGATORIO"),
        ({"tipo_empleado": None}, "FALTA_OBLIGATORIO"),
        ({"numero_empleado": None}, "NUMERO_EMPLEADO_VACIO"),
        ({"celular_whatsapp": "8112"}, "CELULAR_INVALIDO"),
        ({"celular_whatsapp": "+52 81 1234 5678"}, "CELULAR_INVALIDO"),
        ({"celular_whatsapp": "81-tel-5678"}, "CELULAR_INVALIDO"),
        ({"organizacion": "NOEXISTE"}, "ORGANIZACION_NO_EXISTE"),
        ({"planta": "Poniente"}, "PLANTA_NO_EXISTE"),
        ({"estatus": "SUSPENDIDO"}, "ESTATUS_INVALIDO"),
        ({"tipo_empleado": "Directivo"}, "TIPO_EMPLEADO_INVALIDO"),
        ({"fecha_ingreso": "31/02/2021"}, "FECHA_INVALIDA"),
        ({"fecha_ingreso": 44000.5}, "FECHA_INVALIDA"),
        ({"CAMP-0001": "123"}, "FORMATO_INVALIDO"),
        ({"CAMP-0003": 9500}, "SUELDO_SIN_PERIODICIDAD"),
        ({"CAMP-0004": "Quincenal"}, "SUELDO_SIN_PERIODICIDAD"),
        ({"CAMP-0002": "Marketing"}, "VALOR_LISTA_INVALIDO"),
        ({"CAMP-0002": "Vieja"}, "VALOR_LISTA_INVALIDO"),
        ({"CAMP-0005": "ayer"}, "FECHA_INVALIDA"),
    ],
)
def test_un_codigo_por_cada_error_de_fila(cambios, esperado):
    r = _validador().validar(_fila(**cambios))
    assert esperado in _codigos(r)
    for e in r:
        assert e.codigo in MENSAJES or e.codigo == "ESTATUS_INVALIDO"
        # los mensajes no repiten valores de la fila
        for valor in (
            "8112",
            "NOEXISTE",
            "Poniente",
            "SUSPENDIDO",
            "Directivo",
            "Marketing",
            "ayer",
        ):
            assert valor not in e.mensaje


def test_la_fila_se_valida_entera_y_lista_todos_sus_errores():
    r = _validador().validar(
        _fila(nombres=None, apellido_materno=None, celular_whatsapp="1", planta="X", estatus="Z")
    )
    assert _codigos(r) == [
        "FALTA_OBLIGATORIO",
        "CELULAR_INVALIDO",
        "PLANTA_NO_EXISTE",
        "ESTATUS_INVALIDO",
    ]
    assert r[0].mensaje == "Falta: nombre(s), apellido materno."


def test_repetidos_dentro_del_archivo():
    v = _validador()
    assert isinstance(
        v.validar(_fila(3, numero_empleado="E-1", celular_whatsapp="8111111111")), FilaValida
    )
    r = v.validar(_fila(4, numero_empleado=" e-1", celular_whatsapp="8122222222"))
    assert _codigos(r) == ["NUMERO_REPETIDO_EN_ARCHIVO"]
    assert r[0].mensaje == "Número de empleado repetido en el archivo (fila 3)."
    r = v.validar(_fila(5, numero_empleado="E-2", celular_whatsapp="8111111111"))
    assert _codigos(r) == ["CELULAR_REPETIDO"]


def test_organizacion_o_planta_inactiva_no_existe():
    # las inactivas no están en las referencias (el worker solo carga las activas)
    ref = Referencias({"org1": 1}, {"norte": 10})
    r = _validador(ref=ref).validar(_fila(organizacion="ORG2", planta="Sur"))
    assert _codigos(r) == ["ORGANIZACION_NO_EXISTE", "PLANTA_NO_EXISTE"]


def test_campo_obligatorio_dinamico_vacio_es_falta():
    defs = definiciones_basicas()
    defs[0] = DefinicionCampo(
        101, "NSS", "nss", "CAMP-0001", "TEXTO", obligatorio=True, formato_validacion=r"\d{11}"
    )
    r = _validador(defs).validar(_fila())
    assert _codigos(r) == ["FALTA_OBLIGATORIO"] and r[0].mensaje == "Falta: NSS."


def test_columna_de_un_campo_inexistente_se_ignora():
    v = _validador(columnas=[*FIJAS, "CAMP-0099", "desconocida"])
    assert isinstance(v.validar(_fila(**{"CAMP-0099": "x", "desconocida": "y"})), FilaValida)
