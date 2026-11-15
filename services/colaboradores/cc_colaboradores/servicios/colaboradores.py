"""Colaboradores: alta, detalle, edición, baja, reactivación, consentimiento y listado
(COL-01 a COL-07; design.md §3.3, §8.1, §8.2; CC-REQ-020 a 033, 153, 154, 156, 157, 161).

Reglas:
- Una petición es una transacción con su registro de bitácora (§8.2). Nunca se borra un
  colaborador: la baja cambia el estatus (CC-REQ-029, 161).
- Los once fijos son obligatorios en el alta; organización y planta deben existir, ser de la
  empresa y estar activas. Los campos dinámicos se validan con ``ValidadorCampos``.
- El detalle registra ``CONSULTA_DETALLE``; con ``incluir_sensibles`` descifra el celular y los
  campos sensibles y registra ``CONSULTA_SENSIBLE`` con sus códigos, nunca con valores.
- La edición usa bloqueo optimista: ``ETag`` es la ``fecha_modificacion`` y ``If-Match`` debe
  coincidir (412 si no; 428 si falta). No cambia ``estatus`` ni ``numero_empleado``.
- La bitácora guarda nombres de campos y estados, nunca valores (CC-REQ-156, 162).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from cc_common import bitacora
from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.db import transaccion
from cc_common.errores import ErrorCampo, ErrorConflicto, ErrorNoEncontrado, ErrorValidacion
from sqlalchemy.exc import IntegrityError

from cc_colaboradores.campos_cliente import DefinicionCampo
from cc_colaboradores.errores import (
    desde_integridad,
    precondicion_requerida,
    version_desactualizada,
)
from cc_colaboradores.repos import colaborador as repo
from cc_colaboradores.repos import listado as repo_listado
from cc_colaboradores.repos import valor_campo as repo_valor
from cc_colaboradores.servicios import elegibilidad
from cc_colaboradores.validador_campos import ValidadorCampos, ValorValidado

CODIGO_CELULAR = "celular"  # código del dato fijo sensible en la bitácora


@dataclass(frozen=True)
class Detalle:
    fila: dict[str, Any]
    campos: dict[str, Any]
    celular: str | None  # solo con incluir_sensibles
    etag: str


def etag(fecha_modificacion: datetime) -> str:
    return f'"{int(fecha_modificacion.timestamp() * 1_000_000)}"'


def _validar_campos(
    definiciones: list[DefinicionCampo], valores: dict[str, Any], *, parcial: bool
) -> list[ValorValidado]:
    resultado, errores = ValidadorCampos(definiciones).validar(valores, parcial=parcial)
    if errores:
        raise ErrorValidacion(errores=errores)
    return resultado


async def _validar_catalogos(conn, organizacion_id: int | None, planta_id: int | None) -> None:
    errores = []
    if organizacion_id is not None and not await repo.catalogo_activo(
        conn, "organizacion", organizacion_id
    ):
        errores.append(
            ErrorCampo("organizacion_id", "ORGANIZACION_NO_EXISTE", "La organización no existe.")
        )
    if planta_id is not None and not await repo.catalogo_activo(conn, "planta", planta_id):
        errores.append(ErrorCampo("planta_id", "PLANTA_NO_EXISTE", "La planta no existe."))
    if errores:
        raise ErrorValidacion(errores=errores)


async def _registrar(conn, u: UsuarioActual, accion: str, colaborador_id: int, ip, detalle=None):
    await bitacora.registrar(
        conn,
        empresa_id=u.empresa_id,
        accion=accion,
        entidad="colaborador",
        entidad_id=colaborador_id,
        colaborador_id=colaborador_id,
        usuario_id=requerir_usuario_id(u),
        ip=ip,
        detalle=detalle or {},
    )


async def _leer_detalle(
    conn, cif, u: UsuarioActual, colaborador_id: int, definiciones, incluir_sensibles: bool
) -> tuple[Detalle, list[str]]:
    fila = await repo.obtener(conn, colaborador_id)
    if fila is None:
        raise ErrorNoEncontrado()
    campos, descifrados = await repo_valor.leer(
        conn,
        cif,
        empresa_id=u.empresa_id,
        colaborador_id=colaborador_id,
        definiciones=definiciones,
        incluir_sensibles=incluir_sensibles,
    )
    celular = None
    if incluir_sensibles:
        celular = cif.descifrar(
            fila["celular_cifrado"],
            empresa_id=u.empresa_id,
            tabla=repo.TABLA,
            columna=repo.COLUMNA_CELULAR,
            registro=colaborador_id,
        )
        descifrados = [CODIGO_CELULAR, *descifrados]
    return Detalle(fila, campos, celular, etag(fila["fecha_modificacion"])), descifrados


# ------------------------------------------------------------------ COL-02 alta


async def crear(
    motor,
    cif,
    campos_cli,
    u: UsuarioActual,
    fijos: repo.DatosFijos,
    valores: dict,
    consentimiento: bool,
    ip: str | None,
) -> Detalle:
    usuario_id = requerir_usuario_id(u)
    definiciones = await campos_cli.definiciones(u.empresa_id)
    validados = _validar_campos(definiciones, valores, parcial=False)
    try:
        async with transaccion(motor, u.empresa_id) as conn, cif.transaccion(conn, u.empresa_id):
            await _validar_catalogos(conn, fijos.organizacion_id, fijos.planta_id)
            cid = await repo.insertar(
                conn,
                cif,
                empresa_id=u.empresa_id,
                datos=fijos,
                consentimiento=consentimiento,
                registrado_por=usuario_id,
            )
            codigos = await repo_valor.guardar(
                conn, cif, empresa_id=u.empresa_id, colaborador_id=cid, valores=validados
            )
            await _registrar(
                conn, u, "ALTA", cid, ip, {"campos": sorted(codigos)} if codigos else {}
            )
            detalle, _ = await _leer_detalle(conn, cif, u, cid, definiciones, False)
            return detalle
    except IntegrityError as exc:
        raise desde_integridad(exc) from None


# ------------------------------------------------------------------ COL-03 detalle


async def detalle(
    motor,
    cif,
    campos_cli,
    u: UsuarioActual,
    colaborador_id: int,
    incluir_sensibles: bool,
    ip: str | None,
) -> Detalle:
    requerir_usuario_id(u)
    definiciones = await campos_cli.definiciones(u.empresa_id)
    async with transaccion(motor, u.empresa_id) as conn, cif.transaccion(conn, u.empresa_id):
        d, descifrados = await _leer_detalle(
            conn, cif, u, colaborador_id, definiciones, incluir_sensibles
        )
        await _registrar(conn, u, "CONSULTA_DETALLE", colaborador_id, ip)
        if incluir_sensibles:
            await _registrar(
                conn, u, "CONSULTA_SENSIBLE", colaborador_id, ip, {"codigos_internos": descifrados}
            )
        return d


# ------------------------------------------------------------------ COL-04 edición


async def actualizar(
    motor,
    cif,
    campos_cli,
    u: UsuarioActual,
    colaborador_id: int,
    cambios: dict,
    valores: dict | None,
    if_match: str | None,
    ip: str | None,
) -> Detalle:
    requerir_usuario_id(u)
    if not if_match:
        raise precondicion_requerida()
    definiciones = await campos_cli.definiciones(u.empresa_id)
    validados = _validar_campos(definiciones, valores or {}, parcial=True)
    try:
        async with transaccion(motor, u.empresa_id) as conn, cif.transaccion(conn, u.empresa_id):
            actual = await repo.obtener(conn, colaborador_id, bloquear=True)
            if actual is None:
                raise ErrorNoEncontrado()
            if etag(actual["fecha_modificacion"]) != if_match.strip():
                raise version_desactualizada()
            await _validar_catalogos(conn, cambios.get("organizacion_id"), cambios.get("planta_id"))
            fijos = {k: v for k, v in cambios.items() if k in repo.EDITABLES and actual[k] != v}
            nombres = sorted(fijos)
            celular = cambios.get("celular")
            if celular is not None:
                anterior = cif.descifrar(
                    actual["celular_cifrado"],
                    empresa_id=u.empresa_id,
                    tabla=repo.TABLA,
                    columna=repo.COLUMNA_CELULAR,
                    registro=colaborador_id,
                )
                if anterior != celular:
                    await repo.cambiar_celular(
                        conn,
                        cif,
                        empresa_id=u.empresa_id,
                        colaborador_id=colaborador_id,
                        celular=celular,
                    )
                    nombres.append(CODIGO_CELULAR)
            codigos = await repo_valor.guardar(
                conn, cif, empresa_id=u.empresa_id, colaborador_id=colaborador_id, valores=validados
            )
            nombres += codigos
            if nombres:
                await repo.actualizar(conn, colaborador_id, fijos)
                await _registrar(
                    conn, u, "MODIFICACION", colaborador_id, ip, {"campos": sorted(nombres)}
                )
            d, _ = await _leer_detalle(conn, cif, u, colaborador_id, definiciones, False)
            return d
    except IntegrityError as exc:
        raise desde_integridad(exc) from None


# ------------------------------------------------------------------ COL-05 a 07


async def baja(motor, cif, campos_cli, u, colaborador_id: int, fecha_baja: date, ip) -> Detalle:
    requerir_usuario_id(u)
    definiciones = await campos_cli.definiciones(u.empresa_id)
    async with transaccion(motor, u.empresa_id) as conn, cif.transaccion(conn, u.empresa_id):
        actual = await repo.obtener(conn, colaborador_id, bloquear=True)
        if actual is None:
            raise ErrorNoEncontrado()
        if fecha_baja < actual["fecha_ingreso"]:
            raise ErrorValidacion(
                errores=[
                    ErrorCampo("fecha_baja", "FECHA_INVALIDA", "La baja es anterior al ingreso.")
                ]
            )
        if not await repo.dar_de_baja(conn, colaborador_id, fecha_baja):
            raise _estado_invalido(actual["estatus"], "ACTIVO")
        await _registrar(
            conn,
            u,
            "BAJA",
            colaborador_id,
            ip,
            {"estado_anterior": "ACTIVO", "estado_nuevo": "BAJA"},
        )
        d, _ = await _leer_detalle(conn, cif, u, colaborador_id, definiciones, False)
        return d


async def reactivar(
    motor, cif, campos_cli, u, colaborador_id: int, consentimiento: bool, ip
) -> Detalle:
    usuario_id = requerir_usuario_id(u)
    definiciones = await campos_cli.definiciones(u.empresa_id)
    async with transaccion(motor, u.empresa_id) as conn, cif.transaccion(conn, u.empresa_id):
        actual = await repo.obtener(conn, colaborador_id, bloquear=True)
        if actual is None:
            raise ErrorNoEncontrado()
        if actual["estatus"] != "BAJA":
            raise _estado_invalido(actual["estatus"], "BAJA")
        if not consentimiento and not elegibilidad.consentimiento_vigente(actual):
            raise ErrorValidacion(
                "CONSENTIMIENTO_REQUERIDO",
                "Para reactivar se necesita el consentimiento vigente del colaborador.",
                errores=[
                    ErrorCampo(
                        "consentimiento", "CONSENTIMIENTO_REQUERIDO", "Se requiere consentimiento."
                    )
                ],
            )
        await repo.reactivar(conn, colaborador_id)
        if consentimiento:
            await repo.fijar_consentimiento(
                conn, colaborador_id, otorgado=True, vigente_hasta=None, registrado_por=usuario_id
            )
        await _registrar(
            conn,
            u,
            "REACTIVACION",
            colaborador_id,
            ip,
            {"estado_anterior": "BAJA", "estado_nuevo": "ACTIVO"},
        )
        d, _ = await _leer_detalle(conn, cif, u, colaborador_id, definiciones, False)
        return d


async def consentimiento(
    motor, cif, campos_cli, u, colaborador_id: int, otorgado: bool, vigente_hasta, ip
) -> Detalle:
    usuario_id = requerir_usuario_id(u)
    if vigente_hasta is not None and (not otorgado or vigente_hasta <= datetime.now(UTC)):
        raise ErrorValidacion(
            errores=[ErrorCampo("vigente_hasta", "FECHA_INVALIDA", "La vigencia debe ser futura.")]
        )
    definiciones = await campos_cli.definiciones(u.empresa_id)
    async with transaccion(motor, u.empresa_id) as conn, cif.transaccion(conn, u.empresa_id):
        if await repo.obtener(conn, colaborador_id, bloquear=True) is None:
            raise ErrorNoEncontrado()
        await repo.fijar_consentimiento(
            conn,
            colaborador_id,
            otorgado=otorgado,
            vigente_hasta=vigente_hasta,
            registrado_por=usuario_id,
        )
        await _registrar(
            conn,
            u,
            "MODIFICACION",
            colaborador_id,
            ip,
            {"campos": ["consentimiento_vigente_hasta", "consentimiento_whatsapp"]},
        )
        d, _ = await _leer_detalle(conn, cif, u, colaborador_id, definiciones, False)
        return d


def _estado_invalido(actual: str, esperado: str) -> ErrorConflicto:
    return ErrorConflicto(
        "ESTADO_INVALIDO",
        "La operación no aplica al estatus actual del colaborador.",
        detalle={"estado_actual": actual, "estado_esperado": esperado},
    )


# ------------------------------------------------------------------ COL-01 listado


async def listar(
    motor,
    campos_cli,
    u: UsuarioActual,
    consulta: repo_listado.Consulta,
    filtros: dict[str, str],
    columnas: list[str],
) -> tuple[list[dict], int, list[DefinicionCampo]]:
    definiciones = await campos_cli.definiciones(u.empresa_id)
    por_codigo = {d.codigo_interno: d for d in definiciones if d.activo}
    errores: list[ErrorCampo] = []

    def _permitido(codigo: str, ruta: str) -> DefinicionCampo | None:
        d = por_codigo.get(codigo)
        if d is None:
            errores.append(
                ErrorCampo(ruta, "CAMPO_DESCONOCIDO", "El campo no existe o está inactivo.")
            )
            return None
        if d.es_sensible:
            errores.append(
                ErrorCampo(
                    ruta, "CAMPO_SENSIBLE_NO_FILTRABLE", "Un campo sensible no se puede usar aquí."
                )
            )
            return None
        return d

    for codigo, crudo in filtros.items():
        d = _permitido(codigo, f"f.{codigo}")
        if d is None:
            continue
        valores, errs = ValidadorCampos([d]).validar({codigo: crudo}, parcial=True)
        if errs or not valores or valores[0].valor is None:
            errores.extend(
                errs or [ErrorCampo(f"f.{codigo}", "REQUERIDO", "Falta el valor del filtro.")]
            )
            continue
        v = valores[0].valor
        consulta.campos.append(
            repo_listado.FiltroCampo(
                d.id, d.tipo_dato, ("SI" if v else "NO") if d.tipo_dato == "SI_NO" else v
            )
        )
    elegidas = []
    for codigo in columnas:
        d = _permitido(codigo, "columnas")
        if d is not None:
            elegidas.append(d)
            consulta.columnas.append(d.id)
    if errores:
        raise ErrorValidacion(errores=errores)
    async with transaccion(motor, u.empresa_id) as conn:
        items, total = await repo_listado.buscar(conn, consulta)
    return items, total, elegidas
