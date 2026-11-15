"""T-204: ``worker-cargas`` con PostgreSQL y LocalStack (CC-REQ-036, 037, 041, CC-NFR-004)."""

import hashlib
import uuid

import psycopg
import pytest
from ayudantes_carga import fila_valida, libro
from botocore.exceptions import ClientError
from cc_colaboradores.campos_cliente import CacheCampos, DefinicionCampo, OpcionCampo, StubCampos
from cc_colaboradores.excel.modelo import CLAVES_FIJAS
from cc_colaboradores.repos import carga as repo_carga
from cc_colaboradores.workers.worker_cargas import procesar_carga
from cc_common.db import transaccion

pytestmark = pytest.mark.docker

FIJAS = list(CLAVES_FIJAS)
CLAVES = [*FIJAS, "nss", "area", "sueldo"]


def _defs(datos):
    c = datos["campos"]
    return [
        DefinicionCampo(
            c["nss"],
            "NSS",
            "nss",
            "CAMP-0001",
            "TEXTO",
            es_sensible=True,
            formato_validacion=r"\d{11}",
            orden=1,
        ),
        DefinicionCampo(
            c["area"],
            "Área",
            "area",
            "CAMP-0002",
            "LISTA",
            orden=2,
            opciones=(OpcionCampo(datos["opcion"], "Ventas", "VENTAS"),),
        ),
        DefinicionCampo(
            c["sueldo"], "Sueldo", "sueldo", "CAMP-0003", "NUMERO", es_sensible=True, orden=3
        ),
    ]


@pytest.fixture
def mundo(datos):
    """Catálogos de la empresa A y una carga por crear con ``nueva_carga``."""
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        datos["org"] = c.execute(
            "INSERT INTO colaboradores.organizacion (empresa_id, clave, razon_social) "
            "VALUES (%s, 'ORG1', 'Org') RETURNING id",
            (datos["a"],),
        ).fetchone()[0]
        datos["planta"] = c.execute(
            "INSERT INTO colaboradores.planta (empresa_id, nombre) VALUES (%s, 'Norte') RETURNING id",
            (datos["a"],),
        ).fetchone()[0]
    return datos


def _campos(datos):
    return CacheCampos(StubCampos({datos["a"]: _defs(datos)}))


def _nueva_carga(datos, almacen, contenido: bytes, *, hash_ok=True, empresa=None) -> int:
    empresa = empresa or datos["a"]
    clave = f"{empresa}/{uuid.uuid4().hex}.xlsx"
    almacen._s3.put_object(Bucket=almacen._bucket, Key=clave, Body=contenido)
    sha = hashlib.sha256(contenido).hexdigest() if hash_ok else "0" * 64
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        return c.execute(
            "INSERT INTO colaboradores.carga_colaboradores (empresa_id, usuario_id, nombre_archivo, "
            "version_plantilla, hash_archivo, total_filas, s3_key) "
            "VALUES (%s, %s, 'a.xlsx', 'EXTERNA', %s, 0, %s) RETURNING id",
            (empresa, datos["ua"], sha, clave),
        ).fetchone()[0]


def _sql(datos, sql, params=()):
    with psycopg.connect(datos["bd"].url_admin, autocommit=True) as c:
        cur = c.execute(sql, params)
        return cur.fetchall() if cur.description else []


async def _correr(datos, motor, cifrador, almacen, carga_id, **kw):
    return await procesar_carga(
        motor, cifrador, _campos(datos), almacen, empresa_id=datos["a"], carga_id=carga_id, **kw
    )


def _fila(n, **kw):
    return fila_valida(n, **kw)


def _existe_objeto(cliente, bucket, clave) -> bool:
    try:
        cliente.head_object(Bucket=bucket, Key=clave)
    except ClientError:
        return False
    return True


async def test_alta_de_nuevos_sin_consentimiento_y_con_valores_cifrados(
    mundo, motor, cifrador, s3_cargas
):
    almacen, cliente, bucket = s3_cargas
    filas = [
        _fila(1, nss="12345678901", area="ventas", sueldo=9500),
        _fila(2),
        _fila(3, celular_whatsapp="8112345678"),
    ]
    carga = _nueva_carga(mundo, almacen, libro(filas, claves=CLAVES))
    clave = _sql(
        mundo, "SELECT s3_key FROM colaboradores.carga_colaboradores WHERE id = %s", (carga,)
    )[0][0]
    assert await _correr(mundo, motor, cifrador, almacen, carga) == "TERMINADA"

    colabs = _sql(
        mundo,
        "SELECT numero_empleado, estatus, consentimiento_whatsapp, fecha_consentimiento, "
        "celular_ultimos4, tipo_empleado FROM colaboradores.colaborador ORDER BY numero_empleado",
    )
    assert [c[0] for c in colabs] == ["E-0001", "E-0002", "E-0003"]
    assert all(c[1] == "ACTIVO" and c[2] is False and c[3] is None for c in colabs)  # CC-REQ-041
    assert colabs[0][5] == "OPERATIVO" and colabs[2][4] == "5678"
    valores = _sql(
        mundo,
        "SELECT v.campo_id, v.valor_texto, v.valor_numero, v.valor_opcion_id, v.valor_cifrado "
        "FROM colaboradores.valor_campo v",
    )
    por_campo = {v[0]: v for v in valores}
    assert por_campo[mundo["campos"]["area"]][3] == mundo["opcion"]
    # los sensibles van solo cifrados
    for sensible in ("nss", "sueldo"):
        fila = por_campo[mundo["campos"][sensible]]
        assert fila[4] is not None and fila[1] is None and fila[2] is None
    c = _sql(
        mundo,
        "SELECT estado, total_filas, filas_ok, filas_error, fecha_fin, s3_key "
        "FROM colaboradores.carga_colaboradores WHERE id = %s",
        (carga,),
    )[0]
    assert c[0] == "TERMINADA" and (c[2], c[3]) == (3, 0) and c[4] is not None and c[5] is None
    assert not _existe_objeto(cliente, bucket, clave)  # DS-11
    resultados = _sql(
        mundo, "SELECT numero_fila, resultado FROM colaboradores.fila_carga ORDER BY 1"
    )
    assert resultados == [(3, "NUEVO"), (4, "NUEVO"), (5, "NUEVO")]
    bit = _sql(
        mundo,
        "SELECT accion, detalle FROM auditoria.bitacora WHERE entidad = 'carga_colaboradores'",
    )
    assert bit == [
        ("CARGA_TERMINADA", {"carga_id": carga, "totales": {"filas_ok": 3, "filas_error": 0}})
    ]
    # la bitácora de cada alta no lleva valores
    altas = _sql(mundo, "SELECT detalle FROM auditoria.bitacora WHERE accion = 'ALTA'")
    assert len(altas) == 3 and "12345678901" not in str(altas)


async def test_actualiza_por_numero_sin_tocar_consentimiento_ni_a_quien_no_aparece(
    mundo, motor, cifrador, s3_cargas
):
    almacen, _, _ = s3_cargas
    primera = _nueva_carga(
        mundo, almacen, libro([_fila(1, nss="12345678901"), _fila(2), _fila(3)], claves=CLAVES)
    )
    await _correr(mundo, motor, cifrador, almacen, primera)
    _sql(
        mundo,
        "UPDATE colaboradores.colaborador SET consentimiento_whatsapp = true, "
        "fecha_consentimiento = now() WHERE numero_empleado = 'E-0001'",
    )
    antes_tres = _sql(
        mundo,
        "SELECT puesto, fecha_modificacion FROM colaboradores.colaborador WHERE numero_empleado = 'E-0003'",
    )[0]

    # E-0001 cambia de puesto y celular, con la celda de NSS vacía (no debe borrarlo); E-0002 pasa a
    # BAJA; E-0003 no aparece; E-0004 es nuevo
    segunda = _nueva_carga(
        mundo,
        almacen,
        libro(
            [
                _fila(1, puesto="Supervisora", celular_whatsapp="8199999999", sueldo=100),
                _fila(2, estatus="baja"),
                _fila(4),
            ],
            claves=CLAVES,
        ),
    )
    assert await _correr(mundo, motor, cifrador, almacen, segunda) == "TERMINADA"
    r = {
        f[0]: f
        for f in _sql(
            mundo,
            "SELECT numero_empleado, puesto, estatus, consentimiento_whatsapp, celular_ultimos4, "
            "fecha_baja FROM colaboradores.colaborador",
        )
    }
    assert r["E-0001"][1:5] == ("Supervisora", "ACTIVO", True, "9999")  # consentimiento intacto
    assert r["E-0002"][2] == "BAJA" and r["E-0002"][5] is not None
    assert (
        _sql(
            mundo,
            "SELECT puesto, fecha_modificacion FROM colaboradores.colaborador WHERE numero_empleado = 'E-0003'",
        )[0]
        == antes_tres
    )  # quien no aparece no cambia
    assert r["E-0004"][3] is False
    nss = _sql(
        mundo,
        "SELECT v.valor_cifrado IS NOT NULL FROM colaboradores.valor_campo v "
        "JOIN colaboradores.colaborador c ON c.id = v.colaborador_id "
        "WHERE c.numero_empleado = 'E-0001' AND v.campo_id = %s",
        (mundo["campos"]["nss"],),
    )
    assert nss == [(True,)]  # la celda vacía no borró el NSS
    res = _sql(
        mundo,
        "SELECT numero_fila, resultado FROM colaboradores.fila_carga WHERE carga_id = %s ORDER BY 1",
        (segunda,),
    )
    assert res == [(3, "ACTUALIZADO"), (4, "ACTUALIZADO"), (5, "NUEVO")]
    acciones = _sql(
        mundo,
        "SELECT accion FROM auditoria.bitacora WHERE accion IN ('MODIFICACION', 'BAJA') ORDER BY id",
    )
    assert [a[0] for a in acciones] == ["MODIFICACION", "MODIFICACION", "BAJA"]


async def test_una_fila_con_error_no_detiene_el_resto_y_el_reporte_no_trae_datos(
    mundo, motor, cifrador, s3_cargas
):
    almacen, _, _ = s3_cargas
    filas = [
        _fila(1),
        _fila(2, celular_whatsapp="12"),
        _fila(3, planta="Fantasma", nombres=None),
        _fila(4, numero_empleado="E-0001"),
        _fila(5),
    ]
    carga = _nueva_carga(mundo, almacen, libro(filas, claves=CLAVES))
    assert await _correr(mundo, motor, cifrador, almacen, carga) == "TERMINADA"
    c = _sql(
        mundo,
        "SELECT total_filas, filas_ok, filas_error FROM colaboradores.carga_colaboradores WHERE id = %s",
        (carga,),
    )[0]
    assert c[1:] == (2, 3)
    filas_ = {
        f[0]: f
        for f in _sql(
            mundo,
            "SELECT numero_fila, resultado, mensaje, numero_empleado FROM colaboradores.fila_carga",
        )
    }
    assert filas_[4][1] == "ERROR" and filas_[4][2].startswith("CELULAR_INVALIDO")
    assert "FALTA_OBLIGATORIO: Falta: nombre(s)." in filas_[5][2]
    assert "PLANTA_NO_EXISTE" in filas_[5][2]
    assert filas_[6][2].startswith("NUMERO_REPETIDO_EN_ARCHIVO")
    assert filas_[3][1] == "NUEVO" and filas_[7][1] == "NUEVO"
    for _, _, mensaje, _ in filas_.values():
        assert not mensaje or all(x not in mensaje for x in ("Fantasma", "8112", "María"))
    assert _sql(mundo, "SELECT count(*) FROM colaboradores.colaborador") == [(2,)]


async def test_celular_ya_asignado_a_otro_colaborador_de_la_empresa(
    mundo, motor, cifrador, s3_cargas
):
    almacen, _, _ = s3_cargas
    await _correr(
        mundo,
        motor,
        cifrador,
        almacen,
        _nueva_carga(mundo, almacen, libro([_fila(1)], claves=CLAVES)),
    )
    segunda = _nueva_carga(
        mundo,
        almacen,
        libro(
            [_fila(2, celular_whatsapp="8100000001"), _fila(3)], claves=CLAVES
        ),  # E-0003 usa el de E-0001
    )
    # E-0003 trae 8100000003; se le asigna el de E-0001 para provocar el choque
    segunda2 = _nueva_carga(
        mundo, almacen, libro([_fila(3, celular_whatsapp="8100000001")], claves=CLAVES)
    )
    assert await _correr(mundo, motor, cifrador, almacen, segunda) == "TERMINADA"
    assert await _correr(mundo, motor, cifrador, almacen, segunda2) == "TERMINADA"
    fila = _sql(
        mundo,
        "SELECT resultado, mensaje FROM colaboradores.fila_carga WHERE carga_id = %s",
        (segunda2,),
    )[0]
    assert fila[0] == "ERROR" and fila[1].startswith("CELULAR_REPETIDO")
    assert _sql(
        mundo, "SELECT count(*) FROM colaboradores.colaborador WHERE numero_empleado = 'E-0003'"
    ) == [(1,)]  # el alta de E-0003 de la segunda carga sí ocurrió


async def test_repetir_el_mensaje_no_duplica_filas(mundo, motor, cifrador, s3_cargas):
    almacen, cliente, bucket = s3_cargas
    contenido = libro([_fila(1), _fila(2), _fila(3)], claves=CLAVES)
    carga = _nueva_carga(mundo, almacen, contenido)
    # una entrega anterior alcanzó a registrar la fila 3 antes de caerse
    async with transaccion(motor, mundo["a"]) as conn:
        await repo_carga.registrar_fila(
            conn,
            empresa_id=mundo["a"],
            carga_id=carga,
            numero_fila=3,
            numero_empleado="E-0001",
            resultado="NUEVO",
        )
        assert not await repo_carga.registrar_fila(  # UNIQUE (carga_id, numero_fila)
            conn,
            empresa_id=mundo["a"],
            carga_id=carga,
            numero_fila=3,
            numero_empleado="E-0001",
            resultado="NUEVO",
        )
    assert await _correr(mundo, motor, cifrador, almacen, carga) == "TERMINADA"
    assert _sql(
        mundo, "SELECT count(*) FROM colaboradores.fila_carga WHERE carga_id = %s", (carga,)
    ) == [(3,)]
    assert _sql(mundo, "SELECT count(*) FROM colaboradores.colaborador") == [
        (2,)
    ]  # la fila 3 se omitió
    # un segundo mensaje de una carga ya terminada no hace nada
    assert await _correr(mundo, motor, cifrador, almacen, carga) == "IGNORADA"
    assert _sql(
        mundo, "SELECT count(*) FROM colaboradores.fila_carga WHERE carga_id = %s", (carga,)
    ) == [(3,)]


async def test_la_cancelacion_entre_lotes_se_detiene_y_conserva_lo_aplicado(
    mundo, motor, cifrador, s3_cargas
):
    almacen, cliente, bucket = s3_cargas
    carga = _nueva_carga(mundo, almacen, libro([_fila(i) for i in range(1, 7)], claves=CLAVES))
    clave = _sql(
        mundo, "SELECT s3_key FROM colaboradores.carga_colaboradores WHERE id = %s", (carga,)
    )[0][0]

    async def cancelar_tras_el_primero(n: int) -> None:
        if n == 1:
            _sql(
                mundo,
                "UPDATE colaboradores.carga_colaboradores SET estado = 'CANCELADA', "
                "motivo_cierre = 'CANCELADA_POR_USUARIO', fecha_fin = now() WHERE id = %s",
                (carga,),
            )

    resultado = await _correr(
        mundo, motor, cifrador, almacen, carga, lote=2, despues_de_lote=cancelar_tras_el_primero
    )
    assert resultado == "CANCELADA"
    assert _sql(mundo, "SELECT count(*) FROM colaboradores.colaborador") == [(2,)]
    assert _sql(
        mundo, "SELECT count(*) FROM colaboradores.fila_carga WHERE carga_id = %s", (carga,)
    ) == [(2,)]
    assert not _existe_objeto(cliente, bucket, clave)


async def test_baja_en_la_carga_y_reactivacion_no_permitida(mundo, motor, cifrador, s3_cargas):
    almacen, _, _ = s3_cargas
    primera = _nueva_carga(
        mundo, almacen, libro([_fila(1, estatus="BAJA"), _fila(2), _fila(3)], claves=CLAVES)
    )
    await _correr(mundo, motor, cifrador, almacen, primera)
    est = dict(_sql(mundo, "SELECT numero_empleado, estatus FROM colaboradores.colaborador"))
    assert est == {"E-0001": "BAJA", "E-0002": "ACTIVO", "E-0003": "ACTIVO"}
    assert _sql(
        mundo,
        "SELECT fecha_baja >= fecha_ingreso FROM colaboradores.colaborador WHERE numero_empleado = 'E-0001'",
    ) == [(True,)]
    segunda = _nueva_carga(
        mundo, almacen, libro([_fila(1, estatus="ACTIVO"), _fila(2, estatus="BAJA")], claves=CLAVES)
    )
    await _correr(mundo, motor, cifrador, almacen, segunda)
    res = dict(
        _sql(
            mundo,
            "SELECT numero_fila, resultado FROM colaboradores.fila_carga WHERE carga_id = %s",
            (segunda,),
        )
    )
    assert res == {3: "ERROR", 4: "ACTUALIZADO"}
    mensaje = _sql(
        mundo,
        "SELECT mensaje FROM colaboradores.fila_carga WHERE carga_id = %s AND numero_fila = 3",
        (segunda,),
    )[0][0]
    assert mensaje.startswith("ESTATUS_INVALIDO")
    est = dict(_sql(mundo, "SELECT numero_empleado, estatus FROM colaboradores.colaborador"))
    assert est["E-0001"] == "BAJA" and est["E-0002"] == "BAJA"  # sin borrar a nadie


async def test_archivo_alterado_o_ajeno_se_cancela_sin_procesar(mundo, motor, cifrador, s3_cargas):
    almacen, _, _ = s3_cargas
    alterado = _nueva_carga(mundo, almacen, libro([_fila(1)], claves=CLAVES), hash_ok=False)
    assert await _correr(mundo, motor, cifrador, almacen, alterado) == "CANCELADA"
    ajeno = _nueva_carga(mundo, almacen, b"PK\x03\x04" + b"\x00" * 60)
    assert await _correr(mundo, motor, cifrador, almacen, ajeno) == "CANCELADA"
    motivos = _sql(mundo, "SELECT motivo_cierre FROM colaboradores.carga_colaboradores ORDER BY id")
    assert motivos == [("ARCHIVO_ALTERADO",), ("CARGA_ARCHIVO_INVALIDO",)]
    assert _sql(mundo, "SELECT count(*) FROM colaboradores.colaborador") == [(0,)]


async def test_una_carga_de_otra_empresa_se_ignora(mundo, motor, cifrador, s3_cargas):
    almacen, _, _ = s3_cargas
    carga = _nueva_carga(mundo, almacen, libro([_fila(1)], claves=CLAVES))
    r = await procesar_carga(
        motor, cifrador, _campos(mundo), almacen, empresa_id=mundo["b"], carga_id=carga
    )
    assert r == "IGNORADA"
    assert _sql(mundo, "SELECT estado FROM colaboradores.carga_colaboradores") == [("EN_PROCESO",)]
