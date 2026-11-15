"""Siembra del catálogo de campos sugeridos (INT-CAM-02; design.md §3.4; CC-REQ-049).

Idempotente: un campo ya existente (por clave) no se toca ni se duplica, de modo que se puede
repetir al dar de alta una empresa o al reparar una siembra incompleta. Nacen todos no
obligatorios; ``ruta_transporte`` nace inactivo y sueldo, NSS, RFC y CURP, sensibles.
"""

from __future__ import annotations

from cc_common import bitacora
from cc_common.db import transaccion

from cc_campos.catalogo import SUGERIDOS
from cc_campos.repos import campos as repo
from cc_campos.repos import opciones as repo_opciones
from cc_campos.servicios import eventos


async def sembrar(motor, cfg, empresa_id: int) -> tuple[int, int]:
    """Devuelve ``(creados, existentes)``."""
    creados = 0
    async with transaccion(motor, empresa_id) as conn:
        presentes = await repo.por_claves(conn, [s.clave for s in SUGERIDOS])
        for s in SUGERIDOS:
            if s.clave in presentes:
                continue
            codigo = await repo.siguiente_codigo(conn, empresa_id)
            campo_id = await repo.insertar(
                conn,
                empresa_id=empresa_id,
                codigo_interno=codigo,
                datos={
                    "nombre_campo": s.nombre,
                    "clave": s.clave,
                    "tipo_dato": s.tipo_dato,
                    "formato_validacion": s.formato,
                    "obligatorio": False,
                    "orden": await repo.siguiente_orden(conn),
                    "activo": s.activo,
                    "es_sensible": s.es_sensible,
                    "es_sugerido": True,
                },
            )
            for orden, (etiqueta, valor) in enumerate(s.opciones, start=1):
                await repo_opciones.crear(
                    conn,
                    empresa_id=empresa_id,
                    campo_id=campo_id,
                    datos={"etiqueta": etiqueta, "valor": valor, "orden": orden},
                )
            await bitacora.registrar(
                conn,
                empresa_id=empresa_id,
                accion="CAMPO_CREADO",
                entidad="campo_colaborador",
                entidad_id=campo_id,
                origen="SISTEMA",
                detalle={"codigos_internos": [codigo]},
            )
            creados += 1
        if creados:
            await eventos.publicar(conn, cfg, empresa_id, None, "SEMBRADO")
    return creados, len(SUGERIDOS) - creados
