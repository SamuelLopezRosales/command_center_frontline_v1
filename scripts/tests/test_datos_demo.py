"""Los datos de demostración pasan por el lector y el validador REALES de la carga masiva.

No necesita Docker: usa las mismas clases que ``worker_cargas`` (lector del libro y validador de
filas) con las organizaciones, plantas y opciones de lista que ``docs/datos_demo`` pide dar de alta.
"""

import zipfile
from datetime import date

import pytest
from cc_colaboradores.campos_cliente import DefinicionCampo, OpcionCampo
from cc_colaboradores.excel import lector
from cc_colaboradores.excel.validador import FilaValida, Referencias, ValidadorCarga, normalizar

from scripts import datos_demo as dd

pytestmark = pytest.mark.skipif(dd.PLANTILLA is None, reason="Falta la plantilla del cliente")

CURP = r"[A-Z]{4}\d{6}[HMX][A-Z]{2}[B-DF-HJ-NP-TV-Z]{3}[A-Z0-9]\d"
# (clave, nombre, tipo, sensible, opciones, formato) como los campos sugeridos de campos/catalogo.py
CAMPOS = [
    ("area", "Área", "LISTA", False, dd.OPCIONES["Área"], None),
    ("departamento", "Departamento", "LISTA", False, dd.OPCIONES["Departamento"], None),
    ("turno", "Turno", "LISTA", False, dd.OPCIONES["Turno"], None),
    ("sueldo", "Sueldo (MXN)", "NUMERO", True, (), r"(0*[1-9][0-9]*(\.[0-9]*)?|0*\.[0-9]*[1-9][0-9]*)"),
    ("periodicidad_sueldo", "Periodicidad del sueldo", "LISTA", False, ("Semanal", "Catorcenal", "Quincenal", "Mensual"), None),
    ("registro_patronal", "Registro patronal", "TEXTO", False, (), r"[A-Z0-9]{11}"),
    ("nss", "NSS", "TEXTO", True, (), r"\d{11}"),
    ("rfc", "RFC del colaborador", "TEXTO", True, (), r"[A-ZÑ&]{4}\d{6}[A-Z0-9]{3}"),
    ("curp", "CURP", "TEXTO", True, (), CURP),
    ("correo", "Correo electrónico", "TEXTO", False, (), r"[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}"),
]  # fmt: skip


def _definiciones() -> list[DefinicionCampo]:
    defs = []
    for orden, (clave, nombre, tipo, sensible, opciones, formato) in enumerate(CAMPOS, 1):
        opc = tuple(
            OpcionCampo(i, e, e.upper().replace(" ", "_"), orden=i)
            for i, e in enumerate(opciones, 1)
        )
        defs.append(
            DefinicionCampo(
                orden, nombre, clave, f"CAMP-{900 + orden:04d}", tipo, es_sensible=sensible,
                formato_validacion=formato, orden=orden, opciones=opc,
            )
        )  # fmt: skip
    return defs


@pytest.fixture(scope="module")
def xlsx(tmp_path_factory):
    ruta = dd.generar_xlsx(dd.PLANTILLA, tmp_path_factory.mktemp("demo") / dd.NOMBRE_XLSX)
    return ruta


def _validar(xlsx_ruta, referencias):
    archivo = lector.leer(xlsx_ruta.read_bytes())
    validador = ValidadorCarga(_definiciones(), referencias, archivo.columnas)
    return archivo, [validador.validar(f) for f in archivo.filas]


REFERENCIAS = Referencias(
    {normalizar(o.clave): i for i, o in enumerate(dd.ORGANIZACIONES, 1)},
    {normalizar(p): i for i, p in enumerate(dd.PLANTAS, 1)},
)


def test_las_diez_filas_pasan_el_validador_real(xlsx):
    archivo, resultados = _validar(xlsx, REFERENCIAS)
    errores = [r for r in resultados if not isinstance(r, FilaValida)]
    assert not errores, errores
    assert len(archivo.filas) == 10
    assert [r.estatus for r in resultados].count("BAJA") == 1
    assert [r.estatus for r in resultados].count("ACTIVO") == 9


def test_no_queda_la_fila_de_ejemplo_y_los_numeros_son_unicos(xlsx):
    archivo = lector.leer(xlsx.read_bytes())
    numeros = [f.valores["numero_empleado"] for f in archivo.filas]
    assert "EJEMPLO-001" not in numeros
    assert len(set(numeros)) == 10
    celulares = [str(f.valores["celular_whatsapp"]) for f in archivo.filas]
    assert len(set(celulares)) == 10 and all(len(c) == 10 and c.isdigit() for c in celulares)


def test_si_no_se_dieron_de_alta_organizaciones_y_plantas_se_rechaza(xlsx):
    _, resultados = _validar(xlsx, Referencias({}, {}))
    codigos = {e.codigo for r in resultados if isinstance(r, list) for e in r}
    assert {"ORGANIZACION_NO_EXISTE", "PLANTA_NO_EXISTE"} <= codigos


def test_se_conservan_las_listas_desplegables_de_la_plantilla(xlsx):
    with zipfile.ZipFile(dd.PLANTILLA) as a, zipfile.ZipFile(xlsx) as b:
        original = a.read(dd.HOJA_COLABORADORES).decode("utf-8")
        nuevo = b.read(dd.HOJA_COLABORADORES).decode("utf-8")
        assert original.count("x14:dataValidation ") == nuevo.count("x14:dataValidation ") == 8
        assert "<extLst>" in nuevo
        assert a.namelist() == b.namelist()  # mismas partes del libro


def test_los_datos_son_ficticios_y_cumplen_los_formatos():
    import re

    for c in dd.COLABORADORES:
        assert re.fullmatch(r"[A-ZÑ&]{4}\d{6}[A-Z0-9]{3}", dd.rfc_ficticio(c)), c.numero
        assert re.fullmatch(CURP, dd.curp_ficticia(c)), c.numero
        assert re.fullmatch(r"\d{11}", dd.nss_ficticio(c)), c.numero
        assert dd.correo_ficticio(c).endswith("@demo.example")
        assert c.ingreso < date(2026, 12, 31) and c.nacimiento.year < 2005
    assert len({dd.nss_ficticio(c) for c in dd.COLABORADORES}) == 10
