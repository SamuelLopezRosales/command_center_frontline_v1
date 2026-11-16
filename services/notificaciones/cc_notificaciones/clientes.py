"""Clientes de los servicios que `notificaciones` consulta (design.md §3.6, §3.8).

- ``ClienteCampos.definiciones`` (INT-CAM-01): catálogo de campos activos con sus opciones, para
  validar los criterios de audiencia (solo campos activos y no sensibles).
- ``ClienteColaboradores.evaluar_audiencia`` (INT-COL-06): evalúa criterios en `colaboradores`.
  Devuelve el embudo y, salvo con ``solo_conteo``, los colaboradores seleccionados con datos
  mínimos no sensibles (id, nombre, planta, últimos 4 del celular y motivo de exclusión); el
  celular completo nunca sale de `colaboradores`.

Las implementaciones HTTP usan ``ClienteInterno`` (token de 60 s, 3 s de tiempo máximo y corte
de circuito). Los sustitutos (``Stub*``) sirven en local y en las pruebas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from cc_common.errores import ErrorCampo, ErrorProveedor, ErrorValidacion
from cc_common.internal_client import ClienteInterno


@dataclass(frozen=True)
class OpcionCampo:
    id: int
    valor: str
    etiqueta: str = ""
    activo: bool = True


@dataclass(frozen=True)
class DefinicionCampo:
    id: int
    codigo_interno: str
    nombre_campo: str
    tipo_dato: str  # TEXTO, NUMERO, FECHA, LISTA, SI_NO
    es_sensible: bool = False
    activo: bool = True
    opciones: tuple[OpcionCampo, ...] = ()


@dataclass(frozen=True)
class Embudo:
    seleccionados: int
    con_consentimiento: int
    activos: int
    celular_valido: int


@dataclass(frozen=True)
class ItemAudiencia:
    id: int
    nombre: str
    planta_nombre: str | None
    celular_ultimos4: str
    motivo_exclusion: str | None


@dataclass(frozen=True)
class ResultadoAudiencia:
    total: int
    embudo: Embudo
    items: list[ItemAudiencia] = field(default_factory=list)
    siguiente_cursor: str | None = None


class ClienteCampos(Protocol):
    async def definiciones(self, empresa_id: int) -> list[DefinicionCampo]: ...


class ClienteColaboradores(Protocol):
    async def evaluar_audiencia(
        self,
        empresa_id: int,
        criterios: dict[str, Any],
        *,
        solo_conteo: bool = False,
        cursor: str | None = None,
        limite: int = 1000,
        zona_horaria: str | None = None,
    ) -> ResultadoAudiencia: ...

    async def elegibilidad(
        self, empresa_id: int, colaboradores: list[int]
    ) -> dict[int, str | None]: ...


class StubCampos:
    def __init__(self, por_empresa: dict[int, list[DefinicionCampo]] | None = None) -> None:
        self.por_empresa = por_empresa or {}
        self.llamadas = 0

    async def definiciones(self, empresa_id: int) -> list[DefinicionCampo]:
        self.llamadas += 1
        return list(self.por_empresa.get(empresa_id, []))


class StubColaboradores:
    """Responde con ``items`` fijos por empresa (paginados con un cursor numérico) y registra las
    llamadas. Sin datos, evalúa a una audiencia vacía."""

    def __init__(
        self,
        items: dict[int, list[ItemAudiencia]] | None = None,
        no_elegibles: dict[int, str] | None = None,
    ) -> None:
        self.items = items or {}
        self.llamadas: list[dict[str, Any]] = []
        self.no_elegibles = no_elegibles or {}  # colaborador_id -> motivo (CELULAR_INVALIDO...)
        self.consultas_elegibilidad: list[list[int]] = []

    async def elegibilidad(
        self, empresa_id: int, colaboradores: list[int]
    ) -> dict[int, str | None]:
        self.consultas_elegibilidad.append(list(colaboradores))
        return {c: self.no_elegibles.get(c) for c in colaboradores}

    async def evaluar_audiencia(
        self,
        empresa_id: int,
        criterios: dict[str, Any],
        *,
        solo_conteo: bool = False,
        cursor: str | None = None,
        limite: int = 1000,
        zona_horaria: str | None = None,
    ) -> ResultadoAudiencia:
        self.llamadas.append(
            {"empresa_id": empresa_id, "criterios": criterios, "solo_conteo": solo_conteo}
        )
        todos = self.items.get(empresa_id, [])
        a = sum(1 for i in todos if i.motivo_exclusion != "SIN_CONSENTIMIENTO")
        b = sum(
            1 for i in todos if i.motivo_exclusion not in ("SIN_CONSENTIMIENTO", "ESTATUS_BAJA")
        )
        c = sum(1 for i in todos if i.motivo_exclusion is None)
        embudo = Embudo(len(todos), a, b, c)
        if solo_conteo:
            return ResultadoAudiencia(len(todos), embudo)
        inicio = int(cursor) if cursor else 0
        pagina = todos[inicio : inicio + limite]
        hay_mas = inicio + limite < len(todos)
        return ResultadoAudiencia(
            len(todos), embudo, pagina, str(inicio + limite) if hay_mas else None
        )


class CamposHttp:
    """Cliente de INT-CAM-01 (``GET /internal/campos``): solo campos activos."""

    def __init__(self, cliente: ClienteInterno) -> None:
        self._c = cliente

    async def definiciones(self, empresa_id: int) -> list[DefinicionCampo]:
        r = await self._c.solicitar(
            "GET", "/internal/campos", headers={"X-Empresa-Id": str(empresa_id)}
        )
        if r.status_code != 200:
            raise ErrorProveedor()
        return [
            DefinicionCampo(
                id=int(c["id"]),
                codigo_interno=c["codigo_interno"],
                nombre_campo=c["nombre_campo"],
                tipo_dato=c["tipo_dato"],
                es_sensible=bool(c["es_sensible"]),
                activo=bool(c["activo"]),
                opciones=tuple(
                    OpcionCampo(
                        id=int(o["id"]),
                        valor=o["valor"],
                        etiqueta=o.get("etiqueta", ""),
                        activo=bool(o.get("activo", True)),
                    )
                    for o in c.get("opciones") or []
                ),
            )
            for c in r.json()["campos"]
        ]


class ColaboradoresHttp:
    """Clientes de INT-COL-06 (``audiencias:evaluar``) e INT-COL-05 (``contactos:resolver``)."""

    def __init__(self, cliente: ClienteInterno) -> None:
        self._c = cliente

    async def evaluar_audiencia(
        self,
        empresa_id: int,
        criterios: dict[str, Any],
        *,
        solo_conteo: bool = False,
        cursor: str | None = None,
        limite: int = 1000,
        zona_horaria: str | None = None,
    ) -> ResultadoAudiencia:
        cuerpo: dict[str, Any] = {
            "criterios": criterios,
            "solo_conteo": solo_conteo,
            "limite": limite,
        }
        if cursor:
            cuerpo["cursor"] = cursor
        if zona_horaria:
            cuerpo["zona_horaria"] = zona_horaria
        r = await self._c.solicitar(
            "POST",
            "/internal/colaboradores/audiencias:evaluar",
            json=cuerpo,
            headers={"X-Empresa-Id": str(empresa_id)},
        )
        if r.status_code == 422:
            # `colaboradores` rechazó criterios que aquí parecían válidos (por ejemplo, su caché
            # de campos va atrasada): se pide ajustar sin repetir el detalle.
            raise ErrorValidacion(
                "CRITERIOS_INVALIDOS",
                "Los criterios no son válidos.",
                errores=[ErrorCampo("criterios", "CRITERIOS_INVALIDOS", "Revise los criterios.")],
            )
        if r.status_code != 200:
            raise ErrorProveedor()
        d = r.json()
        return ResultadoAudiencia(
            total=int(d["total"]),
            embudo=Embudo(**{k: int(v) for k, v in d["embudo"].items()}),
            items=[ItemAudiencia(**i) for i in d["items"]],
            siguiente_cursor=d.get("siguiente_cursor"),
        )

    async def elegibilidad(
        self, empresa_id: int, colaboradores: list[int]
    ) -> dict[int, str | None]:
        """INT-COL-05 con propósito ``NOTIFICACION`` y ``solo_elegibilidad``: ``{id: motivo}``
        (``None`` si es elegible: ACTIVO, consentimiento vigente y celular no inválido). No recibe
        celulares. Máximo 500 ids por llamada."""
        r = await self._c.solicitar(
            "POST",
            "/internal/colaboradores/contactos:resolver",
            json={
                "ids": colaboradores,
                "proposito": "NOTIFICACION",
                "solo_elegibilidad": True,
            },
            headers={"X-Empresa-Id": str(empresa_id)},
        )
        if r.status_code != 200:
            raise ErrorProveedor()
        return {
            int(i["id"]): (None if i["elegible"] else (i.get("motivo") or "NO_ELEGIBLE"))
            for i in r.json()["items"]
        }
