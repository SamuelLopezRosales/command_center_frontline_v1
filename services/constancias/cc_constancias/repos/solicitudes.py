"""Repositorio de ``solicitud_constancia``, ``constancia_generada``, folios y tokens
(design.md §2.2, §5.5, §5.6). Todo bajo RLS: cada llamada corre en la transacción de una empresa.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

SOLICITUD = (
    "id, colaborador_id, conversacion_id, version_plantilla_id, estado, motivo_fallo, "
    "fecha_solicitud, fecha_atencion, colaborador_nombre, folio_reservado, intentos_entrega"
)


async def plantillas_activas(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Activas, no eliminadas y con al menos una versión publicada (CC-REQ-070)."""
    r = await conn.execute(
        text(
            "SELECT p.id, p.nombre, p.descripcion, v.numero AS version "
            "FROM constancias.plantilla_constancia p "
            "JOIN LATERAL (SELECT numero FROM constancias.version_plantilla "
            "              WHERE plantilla_id = p.id ORDER BY numero DESC LIMIT 1) v ON true "
            "WHERE p.activa AND NOT p.eliminada ORDER BY lower(p.nombre), p.id"
        )
    )
    return [dict(f) for f in r.mappings().all()]


async def crear(
    conn: AsyncConnection,
    *,
    empresa_id: int,
    colaborador_id: int,
    conversacion_id: int | None,
    nombre: str,
) -> dict[str, Any]:
    r = await conn.execute(
        text(
            "INSERT INTO constancias.solicitud_constancia "
            "(empresa_id, colaborador_id, conversacion_id, colaborador_nombre) "
            "VALUES (:e, :c, :v, :n) RETURNING " + SOLICITUD  # noqa: S608
        ),
        {"e": empresa_id, "c": colaborador_id, "v": conversacion_id, "n": nombre},
    )
    return dict(r.mappings().one())


async def obtener(
    conn: AsyncConnection, solicitud_id: int, *, bloquear: bool = False
) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            f"SELECT {SOLICITUD} FROM constancias.solicitud_constancia "  # noqa: S608
            "WHERE id = :id" + (" FOR UPDATE" if bloquear else "")
        ),
        {"id": solicitud_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def plantilla_para_solicitud(
    conn: AsyncConnection, plantilla_id: int
) -> dict[str, Any] | None:
    """Plantilla activa con su última versión (la que usará la constancia)."""
    r = await conn.execute(
        text(
            "SELECT p.id, v.id AS version_id, v.numero FROM constancias.plantilla_constancia p "
            "JOIN LATERAL (SELECT id, numero FROM constancias.version_plantilla "
            "              WHERE plantilla_id = p.id ORDER BY numero DESC LIMIT 1) v ON true "
            "WHERE p.id = :id AND p.activa AND NOT p.eliminada"
        ),
        {"id": plantilla_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def version_por_id(conn: AsyncConnection, version_id: int) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            "SELECT id, plantilla_id, numero, contenido_s3_key, hash_sha256 "
            "FROM constancias.version_plantilla WHERE id = :id"
        ),
        {"id": version_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def fijar_version(conn: AsyncConnection, solicitud_id: int, version_id: int) -> None:
    await conn.execute(
        text(
            "UPDATE constancias.solicitud_constancia SET version_plantilla_id = :v WHERE id = :id"
        ),
        {"id": solicitud_id, "v": version_id},
    )


async def cambiar_estado(
    conn: AsyncConnection,
    solicitud_id: int,
    estado: str,
    *,
    motivo: str | None = None,
    desde: tuple[str, ...] | None = None,
) -> bool:
    """Pasa la solicitud a ``estado`` solo si sigue en uno de los estados ``desde``."""
    r = await conn.execute(
        text(
            "UPDATE constancias.solicitud_constancia SET estado = :estado, motivo_fallo = :m, "
            "fecha_atencion = CASE WHEN :estado IN ('GENERADA', 'FALLIDA', 'CANCELADA') "
            "                      THEN now() ELSE fecha_atencion END "
            "WHERE id = :id AND (CAST(:desde AS text[]) IS NULL OR estado = ANY(CAST(:desde AS text[])))"  # noqa: E501
        ),
        {
            "id": solicitud_id,
            "estado": estado,
            "m": motivo,
            "desde": list(desde) if desde else None,
        },
    )
    return r.rowcount == 1


async def reservar_folio(conn: AsyncConnection, solicitud_id: int, anio: int) -> str:
    """Folio ``CG-AAAA-NNNN`` por empresa y año (design.md §5.5). Un reintento reutiliza el
    ya reservado. Llamar con la solicitud bloqueada; la fila del contador queda bloqueada hasta
    el ``COMMIT``, así que dos reservas nunca reciben el mismo número."""
    previo = (
        await conn.execute(
            text(
                "SELECT folio_reservado, empresa_id FROM constancias.solicitud_constancia WHERE id = :id"  # noqa: E501
            ),
            {"id": solicitud_id},
        )
    ).one()
    if previo[0]:
        return str(previo[0])
    ultimo = (
        await conn.execute(
            text(
                "INSERT INTO constancias.contador_folio (empresa_id, anio, ultimo) VALUES (:e, :a, 1) "  # noqa: E501
                "ON CONFLICT (empresa_id, anio) DO UPDATE SET ultimo = contador_folio.ultimo + 1 "
                "RETURNING ultimo"
            ),
            {"e": previo[1], "a": anio},
        )
    ).scalar_one()
    folio = f"CG-{anio}-{int(ultimo):04d}"
    await conn.execute(
        text("UPDATE constancias.solicitud_constancia SET folio_reservado = :f WHERE id = :id"),
        {"f": folio, "id": solicitud_id},
    )
    return folio


async def constancia_de_solicitud(
    conn: AsyncConnection, solicitud_id: int
) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            "SELECT id, folio, pdf_s3_key, codigo_verificacion, estado_entrega "
            "FROM constancias.constancia_generada WHERE solicitud_id = :id"
        ),
        {"id": solicitud_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def insertar_constancia(
    conn: AsyncConnection,
    *,
    empresa_id: int,
    solicitud: dict[str, Any],
    version_id: int,
    folio: str,
    pdf_clave: str,
    pdf_hash: str,
    snapshot: dict[str, Any],
    numero_empleado: str,
    codigo: str,
) -> int:
    r = await conn.execute(
        text(
            "INSERT INTO constancias.constancia_generada (empresa_id, solicitud_id, colaborador_id, "  # noqa: E501
            "version_plantilla_id, folio, pdf_s3_key, pdf_hash_sha256, datos_snapshot_json, "
            "colaborador_nombre, numero_empleado, codigo_verificacion) "
            "VALUES (:e, :s, :c, :v, :f, :k, :h, CAST(:snap AS jsonb), :n, :num, :cod) RETURNING id"
        ),
        {
            "e": empresa_id,
            "s": solicitud["id"],
            "c": solicitud["colaborador_id"],
            "v": version_id,
            "f": folio,
            "k": pdf_clave,
            "h": pdf_hash,
            "snap": json.dumps(snapshot, ensure_ascii=False),
            "n": solicitud["colaborador_nombre"],
            "num": numero_empleado,
            "cod": codigo,
        },
    )
    return int(r.scalar_one())


async def insertar_token(
    conn: AsyncConnection,
    *,
    empresa_id: int,
    constancia_id: int,
    token_hash: bytes,
    generado_por: str,
    usuario_id: int | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO constancias.token_descarga (empresa_id, constancia_id, token_hash, "
            "fecha_creacion, fecha_expira, generado_por, usuario_id) "
            "VALUES (:e, :c, :h, now(), now() + interval '24 hours', :g, :u)"
        ),
        {"e": empresa_id, "c": constancia_id, "h": token_hash, "g": generado_por, "u": usuario_id},
    )


async def plantillas_con_contenido(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Plantillas no eliminadas con su última versión y su borrador (si existen)."""
    r = await conn.execute(
        text(
            "SELECT p.id, p.nombre, p.activa, v.contenido_s3_key AS version_clave, "
            "b.contenido_s3_key AS borrador_clave "
            "FROM constancias.plantilla_constancia p "
            "LEFT JOIN LATERAL (SELECT contenido_s3_key FROM constancias.version_plantilla "
            "                   WHERE plantilla_id = p.id ORDER BY numero DESC LIMIT 1) v ON true "
            "LEFT JOIN constancias.borrador_plantilla b ON b.plantilla_id = p.id "
            "WHERE NOT p.eliminada ORDER BY p.id"
        )
    )
    return [dict(f) for f in r.mappings().all()]


async def reemplazar_alertas(
    conn: AsyncConnection, *, empresa_id: int, plantilla_id: int, totales: dict[str, int]
) -> None:
    """Deja en ``alerta_plantilla`` exactamente los campos de ``totales`` para la plantilla."""
    await conn.execute(
        text(
            "DELETE FROM constancias.alerta_plantilla WHERE plantilla_id = :p "
            "AND codigo_interno <> ALL(CAST(:c AS text[]))"
        ),
        {"p": plantilla_id, "c": list(totales)},
    )
    for codigo, total in totales.items():
        await conn.execute(
            text(
                "INSERT INTO constancias.alerta_plantilla "
                "(empresa_id, plantilla_id, codigo_interno, total_afectados) "
                "VALUES (:e, :p, :c, :t) ON CONFLICT (plantilla_id, codigo_interno) "
                "DO UPDATE SET total_afectados = EXCLUDED.total_afectados, fecha_calculo = now()"
            ),
            {"e": empresa_id, "p": plantilla_id, "c": codigo, "t": total},
        )


async def constancia_por_id(conn: AsyncConnection, constancia_id: int) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            "SELECT id, folio, pdf_s3_key, estado_entrega, estado_vigencia, colaborador_id, "
            "solicitud_id, (SELECT conversacion_id FROM constancias.solicitud_constancia s "
            "WHERE s.id = c.solicitud_id) AS conversacion_id "
            "FROM constancias.constancia_generada c WHERE id = :id"
        ),
        {"id": constancia_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None


async def marcar_entrega_pendiente(conn: AsyncConnection, constancia_id: int) -> None:
    await conn.execute(
        text(
            "UPDATE constancias.constancia_generada SET estado_entrega = 'PENDIENTE' WHERE id = :id"
        ),
        {"id": constancia_id},
    )


async def detalle_constancia(conn: AsyncConnection, constancia_id: int) -> dict[str, Any] | None:
    r = await conn.execute(
        text(
            "SELECT c.id, c.folio, c.solicitud_id, c.colaborador_id, c.colaborador_nombre, "
            "c.numero_empleado, c.fecha_generacion, c.estado_entrega, c.fecha_entrega, "
            "c.estado_vigencia, p.id AS plantilla_id, p.nombre AS plantilla_nombre, "
            "v.numero AS version "
            "FROM constancias.constancia_generada c "
            "JOIN constancias.version_plantilla v ON v.id = c.version_plantilla_id "
            "JOIN constancias.plantilla_constancia p ON p.id = v.plantilla_id "
            "WHERE c.id = :id"
        ),
        {"id": constancia_id},
    )
    f = r.mappings().first()
    return dict(f) if f else None
