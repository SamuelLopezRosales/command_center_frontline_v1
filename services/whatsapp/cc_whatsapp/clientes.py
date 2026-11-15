"""Clientes de los servicios que el bot consulta (design.md §3.8): INT-COL-01 a 03 y 07 en
`colaboradores`; INT-CON-01 a 05 en `constancias`. Usan ``ClienteInterno`` (token de 60 s, 3 s de
espera, corte de circuito). Los sustitutos de las pruebas implementan los mismos métodos."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from cc_common.errores import ErrorProveedor
from cc_common.internal_client import ClienteInterno


class RespuestaError(Exception):  # noqa: N818
    """El servicio respondió con un error de negocio (4xx): ``status`` y ``codigo`` del problema."""

    def __init__(self, status: int, codigo: str | None, detalle: dict | None = None):
        super().__init__(f"{status} {codigo}")
        self.status = status
        self.codigo = codigo
        self.detalle = detalle or {}


@dataclass(frozen=True)
class Busqueda:
    encontrado: bool
    celular_hash: str
    colaborador_id: int | None = None
    elegible: bool | None = None
    motivo: str | None = None


class ClienteColaboradores(Protocol):
    async def buscar_por_celular(self, empresa_id: int, celular: str) -> Busqueda: ...
    async def desafio(self, empresa_id: int, colaborador_id: int) -> str: ...
    async def verificar(self, empresa_id: int, colaborador_id: int, dato: str) -> bool: ...
    async def nombre(self, empresa_id: int, colaborador_id: int) -> str: ...


class ClienteConstancias(Protocol):
    async def plantillas(self, empresa_id: int) -> list[dict[str, Any]]: ...
    async def crear_solicitud(
        self, empresa_id: int, colaborador_id: int, conversacion_id: int, nombre: str
    ) -> int: ...
    async def elegir_plantilla(self, empresa_id: int, solicitud_id: int, plantilla_id: int): ...
    async def generar(self, empresa_id: int, solicitud_id: int) -> None: ...
    async def cancelar(self, empresa_id: int, solicitud_id: int) -> None: ...


def _error(r) -> Exception:
    if r.status_code >= 500:
        return ErrorProveedor()
    try:
        cuerpo = r.json()
    except ValueError:
        cuerpo = {}
    return RespuestaError(r.status_code, cuerpo.get("codigo"), cuerpo.get("detalle"))


class _Base:
    def __init__(self, cliente: ClienteInterno) -> None:
        self._c = cliente

    async def _llamar(self, empresa_id: int, metodo: str, ruta: str, **kw):
        r = await self._c.solicitar(metodo, ruta, headers={"X-Empresa-Id": str(empresa_id)}, **kw)
        if r.status_code >= 300:
            raise _error(r)
        return r


class ColaboradoresHttp(_Base):
    async def buscar_por_celular(self, empresa_id: int, celular: str) -> Busqueda:
        d = (
            await self._llamar(
                empresa_id, "POST", "/internal/colaboradores/buscar-por-celular",
                json={"celular": celular},
            )
        ).json()  # fmt: skip
        return Busqueda(
            d["encontrado"], d["celular_hash"], d.get("colaborador_id"), d.get("elegible"),
            d.get("motivo"),
        )  # fmt: skip

    async def desafio(self, empresa_id: int, colaborador_id: int) -> str:
        r = await self._llamar(
            empresa_id, "POST", f"/internal/colaboradores/{colaborador_id}/desafio"
        )
        return str(r.json()["tipo"])

    async def verificar(self, empresa_id: int, colaborador_id: int, dato: str) -> bool:
        r = await self._llamar(
            empresa_id, "POST", f"/internal/colaboradores/{colaborador_id}/verificar",
            json={"dato": dato},
        )  # fmt: skip
        return bool(r.json()["valido"])

    async def nombre(self, empresa_id: int, colaborador_id: int) -> str:
        r = await self._llamar(
            empresa_id, "GET", f"/internal/colaboradores/{colaborador_id}/resumen"
        )
        return str(r.json()["nombre_completo"])


class ConstanciasHttp(_Base):
    async def plantillas(self, empresa_id: int) -> list[dict[str, Any]]:
        r = await self._llamar(empresa_id, "GET", "/internal/plantillas/activas")
        return list(r.json()["plantillas"])

    async def crear_solicitud(
        self, empresa_id: int, colaborador_id: int, conversacion_id: int, nombre: str
    ) -> int:
        r = await self._llamar(
            empresa_id, "POST", "/internal/solicitudes",
            json={"colaborador_id": colaborador_id, "conversacion_id": conversacion_id,
                  "colaborador_nombre": nombre},
        )  # fmt: skip
        return int(r.json()["id"])

    async def elegir_plantilla(self, empresa_id: int, solicitud_id: int, plantilla_id: int):
        await self._llamar(
            empresa_id, "POST", f"/internal/solicitudes/{solicitud_id}/plantilla",
            json={"plantilla_id": plantilla_id},
        )  # fmt: skip

    async def generar(self, empresa_id: int, solicitud_id: int) -> None:
        await self._llamar(empresa_id, "POST", f"/internal/solicitudes/{solicitud_id}/generar")

    async def cancelar(self, empresa_id: int, solicitud_id: int) -> None:
        await self._llamar(empresa_id, "POST", f"/internal/solicitudes/{solicitud_id}/cancelar")
