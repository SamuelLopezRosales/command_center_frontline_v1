"""Repositorio de ``colaboradores.colaborador`` con el celular cifrado (design.md §8.3, §8.4).

El celular se guarda tres veces, nunca en claro: cifrado con AES-GCM (``celular_cifrado``),
como HMAC para buscar y detectar duplicados (``celular_hash``) y sus últimos 4 dígitos para
mostrarlo enmascarado (``celular_ultimos4``).

El ``id`` se reserva con ``nextval`` antes de insertar porque forma parte de los datos
autenticados del cifrado (``colaborador|celular_cifrado|{id}|{empresa}``): así un celular
cifrado copiado a otra fila no se puede descifrar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cc_colaboradores.cifrado import Cifrador

TABLA = "colaborador"
COLUMNA_CELULAR = "celular_cifrado"


@dataclass(frozen=True)
class DatosFijos:
    """Los once campos fijos del colaborador (CC-REQ-020), ya validados."""

    numero_empleado: str
    nombres: str
    apellido_paterno: str
    apellido_materno: str
    celular: str  # 10 dígitos
    organizacion_id: int
    planta_id: int
    fecha_ingreso: date
    puesto: str
    tipo_empleado: str


async def reservar_id(conn: AsyncConnection) -> int:
    r = await conn.execute(
        text("SELECT nextval(pg_get_serial_sequence('colaboradores.colaborador', 'id'))")
    )
    return int(r.scalar_one())


def cifrar_celular(cif: Cifrador, *, empresa_id: int, colaborador_id: int, celular: str) -> dict:
    return {
        "celular_cifrado": cif.cifrar(
            celular,
            empresa_id=empresa_id,
            tabla=TABLA,
            columna=COLUMNA_CELULAR,
            registro=colaborador_id,
        ),
        "celular_hash": cif.hash_celular(celular),
        "celular_ultimos4": celular[-4:],
    }


async def insertar(
    conn: AsyncConnection,
    cif: Cifrador,
    *,
    empresa_id: int,
    datos: DatosFijos,
    consentimiento: bool = False,
    registrado_por: int | None = None,
) -> int:
    colaborador_id = await reservar_id(conn)
    celular = cifrar_celular(
        cif, empresa_id=empresa_id, colaborador_id=colaborador_id, celular=datos.celular
    )
    await conn.execute(
        text(
            """
            INSERT INTO colaboradores.colaborador
              (id, empresa_id, organizacion_id, planta_id, numero_empleado, nombres,
               apellido_paterno, apellido_materno, celular_cifrado, celular_hash,
               celular_ultimos4, fecha_ingreso, puesto, tipo_empleado, consentimiento_whatsapp,
               fecha_consentimiento, consentimiento_registrado_por)
            OVERRIDING SYSTEM VALUE
            VALUES
              (:id, :e, :org, :planta, :num, :nombres, :ap, :am, :celular_cifrado,
               :celular_hash, :celular_ultimos4, :ingreso, :puesto, :tipo, :consentimiento,
               CASE WHEN :consentimiento THEN now() END,
               CASE WHEN :consentimiento THEN CAST(:por AS bigint) END)
            """
        ),
        {
            "id": colaborador_id,
            "e": empresa_id,
            "org": datos.organizacion_id,
            "planta": datos.planta_id,
            "num": datos.numero_empleado,
            "nombres": datos.nombres,
            "ap": datos.apellido_paterno,
            "am": datos.apellido_materno,
            "ingreso": datos.fecha_ingreso,
            "puesto": datos.puesto,
            "tipo": datos.tipo_empleado,
            "consentimiento": consentimiento,
            "por": registrado_por,
            **celular,
        },
    )
    return colaborador_id


async def leer_celular(
    conn: AsyncConnection, cif: Cifrador, *, empresa_id: int, colaborador_id: int
) -> str | None:
    r = await conn.execute(
        text("SELECT celular_cifrado FROM colaboradores.colaborador WHERE id = :id"),
        {"id": colaborador_id},
    )
    blob = r.scalar_one_or_none()
    if blob is None:
        return None
    return cif.descifrar(
        blob, empresa_id=empresa_id, tabla=TABLA, columna=COLUMNA_CELULAR, registro=colaborador_id
    )


async def cambiar_celular(
    conn: AsyncConnection, cif: Cifrador, *, empresa_id: int, colaborador_id: int, celular: str
) -> None:
    await conn.execute(
        text(
            "UPDATE colaboradores.colaborador SET celular_cifrado = :celular_cifrado, "
            "celular_hash = :celular_hash, celular_ultimos4 = :celular_ultimos4, "
            "celular_invalido = false, fecha_modificacion = now() WHERE id = :id"
        ),
        {
            "id": colaborador_id,
            **cifrar_celular(
                cif, empresa_id=empresa_id, colaborador_id=colaborador_id, celular=celular
            ),
        },
    )


async def por_hash_celular(conn: AsyncConnection, celular_hash: bytes) -> int | None:
    r = await conn.execute(
        text("SELECT id FROM colaboradores.colaborador WHERE celular_hash = :h"),
        {"h": celular_hash},
    )
    return r.scalar_one_or_none()


# ------------------------------------------------------------------ lectura y cambios (T-202)

_DETALLE = """
    SELECT c.id, c.numero_empleado, c.nombres, c.apellido_paterno, c.apellido_materno,
           c.celular_cifrado, c.celular_ultimos4, c.celular_invalido, c.fecha_ingreso, c.puesto,
           c.tipo_empleado, c.estatus, c.fecha_baja, c.consentimiento_whatsapp,
           c.fecha_consentimiento, c.consentimiento_vigente_hasta, c.fecha_creacion,
           c.fecha_modificacion,
           o.id AS organizacion_id, o.clave AS organizacion_clave,
           o.razon_social AS organizacion_razon_social,
           p.id AS planta_id, p.nombre AS planta_nombre
    FROM colaboradores.colaborador c
    JOIN colaboradores.organizacion o ON o.id = c.organizacion_id
    JOIN colaboradores.planta p ON p.id = c.planta_id
    WHERE c.id = :id
"""

EDITABLES = frozenset(
    {
        "nombres",
        "apellido_paterno",
        "apellido_materno",
        "organizacion_id",
        "planta_id",
        "fecha_ingreso",
        "puesto",
        "tipo_empleado",
    }
)


async def obtener(conn: AsyncConnection, colaborador_id: int, *, bloquear: bool = False):
    sql = _DETALLE + (" FOR UPDATE OF c" if bloquear else "")
    r = await conn.execute(text(sql), {"id": colaborador_id})
    f = r.mappings().first()
    return dict(f) if f else None


async def actualizar(conn: AsyncConnection, colaborador_id: int, cambios: dict) -> None:
    """Actualiza los fijos editables (lista cerrada) y marca ``fecha_modificacion``."""
    columnas = [c for c in cambios if c in EDITABLES]
    asignaciones = "".join(f"{c} = :{c}, " for c in columnas)  # nombres de una lista fija
    await conn.execute(
        text(
            f"UPDATE colaboradores.colaborador SET {asignaciones}"  # noqa: S608
            "fecha_modificacion = clock_timestamp() WHERE id = :id"
        ),
        {"id": colaborador_id, **{c: cambios[c] for c in columnas}},
    )


async def dar_de_baja(conn: AsyncConnection, colaborador_id: int, fecha_baja: date) -> bool:
    r = await conn.execute(
        text(
            "UPDATE colaboradores.colaborador SET estatus = 'BAJA', fecha_baja = :f, "
            "fecha_modificacion = clock_timestamp() WHERE id = :id AND estatus = 'ACTIVO'"
        ),
        {"id": colaborador_id, "f": fecha_baja},
    )
    return r.rowcount == 1


async def reactivar(conn: AsyncConnection, colaborador_id: int) -> bool:
    r = await conn.execute(
        text(
            "UPDATE colaboradores.colaborador SET estatus = 'ACTIVO', fecha_baja = NULL, "
            "fecha_modificacion = clock_timestamp() WHERE id = :id AND estatus = 'BAJA'"
        ),
        {"id": colaborador_id},
    )
    return r.rowcount == 1


async def fijar_consentimiento(
    conn: AsyncConnection,
    colaborador_id: int,
    *,
    otorgado: bool,
    vigente_hasta,
    registrado_por: int,
) -> None:
    await conn.execute(
        text(
            """
            UPDATE colaboradores.colaborador SET
              consentimiento_whatsapp = :o,
              fecha_consentimiento = CASE WHEN :o THEN now() ELSE fecha_consentimiento END,
              consentimiento_vigente_hasta = CASE WHEN :o THEN CAST(:h AS timestamptz) END,
              consentimiento_registrado_por = :u,
              fecha_modificacion = clock_timestamp()
            WHERE id = :id
            """
        ),
        {"id": colaborador_id, "o": otorgado, "h": vigente_hasta, "u": registrado_por},
    )


async def catalogo_activo(conn: AsyncConnection, tabla: str, fila_id: int) -> bool:
    """``organizacion`` o ``planta`` existente, de la empresa (RLS) y activa."""
    if tabla not in ("organizacion", "planta"):
        raise ValueError(tabla)
    r = await conn.execute(
        text(f"SELECT activa FROM colaboradores.{tabla} WHERE id = :id"),  # noqa: S608
        {"id": fila_id},
    )
    return bool(r.scalar_one_or_none())
