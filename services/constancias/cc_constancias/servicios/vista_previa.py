"""Vista previa de una plantilla con los datos de un colaborador (CON-14; CC-REQ-063).

Usa el **mismo renderizador** que el PDF, con un folio y un código de verificación de muestra (no
válidos: no existen en la base). Las variables sin valor salen marcadas y se devuelven en
``faltantes``; las que el catálogo no conoce, en ``desconocidas``.

Si la plantilla usa datos sensibles, quien pide la vista previa necesita también el permiso para
verlos, y se registra ``CONSULTA_SENSIBLE`` (con los códigos de los campos, nunca los valores).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cc_common import bitacora
from cc_common.auth import UsuarioActual, requerir_usuario_id
from cc_common.db import transaccion
from cc_common.errores import ErrorNoEncontrado, ErrorProhibido
from cc_common.permisos import Permiso, tiene_permiso

from cc_constancias import contenido as esquema
from cc_constancias.render import derivadas
from cc_constancias.render.catalogo_variables import DERIVADAS, Catalogo
from cc_constancias.render.html import DatosRender, renderizar
from cc_constancias.render.qr import url_verificacion
from cc_constancias.render.resolutor_variables import resolver
from cc_constancias.repos import plantillas as repo
from cc_constancias.repos import versiones as repo_versiones
from cc_constancias.servicios.publicacion import leer_objeto

CODIGO_MUESTRA = "VISTA-PREVIA-SIN-VALIDEZ-0000"


@dataclass(frozen=True)
class VistaPrevia:
    html: str
    faltantes: list[str]
    desconocidas: list[str]


def folio_de_muestra(ahora=None) -> str:
    return f"CG-{derivadas.hoy_en_mexico(ahora).year}-0000"


def codigos_de_sensibles(sensibles: list[str], definiciones) -> list[str]:
    """Códigos internos de los campos sensibles usados (una derivada de sueldo cuenta como
    ``sueldo``). Es lo que queda en la bitácora: nunca los valores."""
    por_clave = {d.clave: d.codigo_interno for d in definiciones}
    codigos: list[str] = []
    for v in sensibles:
        codigo = por_clave.get("sueldo" if v in DERIVADAS else v)
        if codigo and codigo not in codigos:
            codigos.append(codigo)
    return codigos


async def _contenido(motor, almacen, u: UsuarioActual, plantilla_id: int, version, usar_borrador):
    async with transaccion(motor, u.empresa_id) as conn:
        if await repo.obtener(conn, plantilla_id) is None:
            raise ErrorNoEncontrado()
        if usar_borrador:
            fila = await repo.obtener_borrador(conn, plantilla_id)
            if fila is None:
                raise ErrorNoEncontrado(
                    "BORRADOR_NO_EXISTE", "La plantilla todavía no tiene borrador."
                )
        else:
            fila = await repo_versiones.obtener(conn, plantilla_id, version)
            if fila is None:
                raise ErrorNoEncontrado()
    _, contenido = await leer_objeto(almacen, fila["contenido_s3_key"], fila.get("hash_sha256"))
    return contenido


async def _logotipo(colaboradores, cargador, empresa_id: int, colaborador_id: int) -> str | None:
    resumen: dict[str, Any] = await colaboradores.resumen(empresa_id, colaborador_id)
    organizacion_id = (resumen.get("organizacion") or {}).get("id")
    if not organizacion_id:
        return None
    organizacion = await colaboradores.organizacion(empresa_id, int(organizacion_id))
    return await cargador.data_uri(organizacion.get("logotipo_s3_key"))


async def generar(
    motor,
    almacen,
    campos,
    colaboradores,
    cargador,
    cfg,
    u: UsuarioActual,
    plantilla_id: int,
    colaborador_id: int,
    *,
    version: int | None,
    usar_borrador: bool,
    ip: str | None,
    ahora=None,
) -> VistaPrevia:
    usuario_id = requerir_usuario_id(u)
    contenido = await _contenido(motor, almacen, u, plantilla_id, version, usar_borrador)
    definiciones = await campos.definiciones(u.empresa_id)
    catalogo = Catalogo(definiciones)
    usadas = esquema.variables_usadas(contenido)
    sensibles = [v for v in usadas if catalogo.es_sensible(v)]
    if sensibles and not tiene_permiso(u.rol, Permiso.COLABORADORES_VER_SENSIBLES):
        raise ErrorProhibido()

    folio = folio_de_muestra(ahora)
    url = url_verificacion(cfg.dominio, CODIGO_MUESTRA)
    r = await resolver(
        colaboradores,
        empresa_id=u.empresa_id,
        colaborador_id=colaborador_id,
        variables=usadas,
        definiciones=definiciones,
        sistema={"folio": folio, "qr_verificacion": url},
        ahora=ahora,
    )
    logotipo = None
    if esquema.usa_logotipo(contenido):
        logotipo = await _logotipo(colaboradores, cargador, u.empresa_id, colaborador_id)
    html = renderizar(
        contenido,
        DatosRender(
            valores=r.valores,
            folio=folio,
            codigo_verificacion=CODIGO_MUESTRA,
            dominio=cfg.dominio,
            logotipo_data_uri=logotipo,
            vista_previa=True,
        ),
    )
    if r.sensibles_usadas:
        async with transaccion(motor, u.empresa_id) as conn:
            await bitacora.registrar(
                conn,
                empresa_id=u.empresa_id,
                accion="CONSULTA_SENSIBLE",
                entidad="colaborador",
                entidad_id=colaborador_id,
                colaborador_id=colaborador_id,
                usuario_id=usuario_id,
                ip=ip,
                detalle={
                    "codigos_internos": codigos_de_sensibles(r.sensibles_usadas, definiciones),
                    "plantilla_id": plantilla_id,
                },
            )
    return VistaPrevia(html=html, faltantes=r.faltantes, desconocidas=r.desconocidas)
