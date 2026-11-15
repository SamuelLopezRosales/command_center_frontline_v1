"""Clientes de los servicios que `campos` consulta (design.md §3.4, §3.8).

- ``ClienteColaboradores.campo_con_valores`` (INT-COL-10): ¿algún colaborador tiene valor en el
  campo? Protege el tipo de dato, la sensibilidad y la eliminación (CC-REQ-048, 050).
- ``ClienteConstancias.uso_de_variables`` (INT-CON-06): plantillas que usan cada variable
  (clave). Avisa al cambiar una clave (CC-REQ-052) y llena ``usada_en_plantillas``.

Las implementaciones HTTP usan ``ClienteInterno`` (token de 60 s, 3 s de tiempo máximo, reintentos
y corte de circuito). Los sustitutos (``Stub*``) sirven en local y en las pruebas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cc_common.errores import ErrorProveedor
from cc_common.internal_client import ClienteInterno


@dataclass(frozen=True)
class PlantillaUso:
    id: int
    nombre: str


class ClienteColaboradores(Protocol):
    async def campo_con_valores(self, empresa_id: int, campo_id: int) -> bool: ...


class ClienteConstancias(Protocol):
    async def uso_de_variables(
        self, empresa_id: int, claves: list[str]
    ) -> dict[str, list[PlantillaUso]]: ...


class StubColaboradores:
    def __init__(self, con_valores: set[int] | None = None) -> None:
        self.con_valores = con_valores or set()
        self.llamadas: list[tuple[int, int]] = []

    async def campo_con_valores(self, empresa_id: int, campo_id: int) -> bool:
        self.llamadas.append((empresa_id, campo_id))
        return campo_id in self.con_valores


class StubConstancias:
    def __init__(self, usos: dict[str, list[PlantillaUso]] | None = None) -> None:
        self.usos = usos or {}
        self.llamadas: list[tuple[int, list[str]]] = []

    async def uso_de_variables(
        self, empresa_id: int, claves: list[str]
    ) -> dict[str, list[PlantillaUso]]:
        self.llamadas.append((empresa_id, list(claves)))
        return {c: list(self.usos.get(c, [])) for c in claves}


class ColaboradoresHttp:
    def __init__(self, cliente: ClienteInterno) -> None:
        self._c = cliente

    async def campo_con_valores(self, empresa_id: int, campo_id: int) -> bool:
        r = await self._c.solicitar(
            "GET",
            f"/internal/campos/{campo_id}/uso",
            headers={"X-Empresa-Id": str(empresa_id)},
        )
        if r.status_code != 200:
            raise ErrorProveedor()
        return bool(r.json()["con_valores"])


class ConstanciasHttp:
    def __init__(self, cliente: ClienteInterno) -> None:
        self._c = cliente

    async def uso_de_variables(
        self, empresa_id: int, claves: list[str]
    ) -> dict[str, list[PlantillaUso]]:
        if not claves:
            return {}
        r = await self._c.solicitar(
            "GET",
            "/internal/plantillas/uso-de-variable",
            params=[("variable", c) for c in claves],
            headers={"X-Empresa-Id": str(empresa_id)},
        )
        if r.status_code != 200:
            raise ErrorProveedor()
        usos = r.json().get("usos", {})
        return {
            c: [PlantillaUso(int(p["id"]), str(p["nombre"])) for p in usos.get(c, [])]
            for c in claves
        }
