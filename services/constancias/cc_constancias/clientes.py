"""Clientes de los servicios que `constancias` consulta (design.md §3.5, §3.8).

- ``ClienteCampos.definiciones`` (INT-CAM-01): campos dinámicos con su estado. Se piden también
  los desactivados para distinguir una variable **inactiva** de una **inexistente** (CC-REQ-065).
- ``ClienteColaboradores.datos_constancia`` (INT-COL-04): valores de las variables de un
  colaborador, con las que no tienen valor en ``faltantes``.

Las implementaciones HTTP usan ``ClienteInterno`` (token de 60 s, 3 s de tiempo máximo, reintentos
y corte de circuito). Los sustitutos (``Stub*``) sirven en local y en las pruebas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cc_common.errores import ErrorProveedor
from cc_common.internal_client import ClienteInterno


@dataclass(frozen=True)
class OpcionCampo:
    id: int
    etiqueta: str
    valor: str
    descripcion: str | None = None
    activo: bool = True


@dataclass(frozen=True)
class DefinicionCampo:
    id: int
    nombre_campo: str
    clave: str
    codigo_interno: str
    tipo_dato: str
    es_sensible: bool = False
    activo: bool = True
    obligatorio: bool = False
    orden: int = 0
    opciones: tuple[OpcionCampo, ...] = ()


class ClienteCampos(Protocol):
    async def definiciones(self, empresa_id: int) -> list[DefinicionCampo]: ...


class ClienteColaboradores(Protocol):
    async def datos_constancia(
        self, empresa_id: int, colaborador_id: int, variables: list[str]
    ) -> tuple[dict[str, str], list[str]]: ...


class StubCampos:
    def __init__(self, por_empresa: dict[int, list[DefinicionCampo]] | None = None) -> None:
        self.por_empresa = por_empresa or {}
        self.llamadas = 0

    async def definiciones(self, empresa_id: int) -> list[DefinicionCampo]:
        self.llamadas += 1
        return list(self.por_empresa.get(empresa_id, []))


class StubColaboradores:
    """Devuelve ``valores[colaborador_id]`` filtrado a las variables pedidas."""

    def __init__(self, valores: dict[int, dict[str, str]] | None = None) -> None:
        self.valores = valores or {}
        self.llamadas: list[tuple[int, int, list[str]]] = []

    async def datos_constancia(
        self, empresa_id: int, colaborador_id: int, variables: list[str]
    ) -> tuple[dict[str, str], list[str]]:
        self.llamadas.append((empresa_id, colaborador_id, list(variables)))
        propios = self.valores.get(colaborador_id, {})
        dados = {v: propios[v] for v in variables if v in propios}
        return dados, [v for v in variables if v not in dados]


class CamposHttp:
    def __init__(self, cliente: ClienteInterno) -> None:
        self._c = cliente

    async def definiciones(self, empresa_id: int) -> list[DefinicionCampo]:
        r = await self._c.solicitar(
            "GET",
            "/internal/campos",
            params={"incluir_inactivos": "true"},
            headers={"X-Empresa-Id": str(empresa_id)},
        )
        if r.status_code != 200:
            raise ErrorProveedor()
        return [
            DefinicionCampo(
                id=int(c["id"]),
                nombre_campo=c["nombre_campo"],
                clave=c["clave"],
                codigo_interno=c["codigo_interno"],
                tipo_dato=c["tipo_dato"],
                es_sensible=c["es_sensible"],
                activo=c["activo"],
                obligatorio=c["obligatorio"],
                orden=c["orden"],
                opciones=tuple(
                    OpcionCampo(
                        id=int(o["id"]),
                        etiqueta=o["etiqueta"],
                        valor=o["valor"],
                        descripcion=o.get("descripcion"),
                        activo=o["activo"],
                    )
                    for o in c.get("opciones", [])
                ),
            )
            for c in r.json()["campos"]
        ]


class ColaboradoresHttp:
    def __init__(self, cliente: ClienteInterno) -> None:
        self._c = cliente

    async def datos_constancia(
        self, empresa_id: int, colaborador_id: int, variables: list[str]
    ) -> tuple[dict[str, str], list[str]]:
        if not variables:
            return {}, []
        r = await self._c.solicitar(
            "POST",
            f"/internal/colaboradores/{colaborador_id}/datos-constancia",
            json={"variables": variables},
            headers={"X-Empresa-Id": str(empresa_id)},
        )
        if r.status_code == 404:
            from cc_common.errores import ErrorNoEncontrado

            raise ErrorNoEncontrado()
        if r.status_code != 200:
            raise ErrorProveedor()
        cuerpo = r.json()
        return dict(cuerpo["valores"]), list(cuerpo["faltantes"])
