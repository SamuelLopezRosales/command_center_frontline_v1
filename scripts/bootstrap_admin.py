"""Crea la primera empresa y su primera invitación de registro (design.md §11.2, §13.9; D-02).

Es un paso manual, de una sola vez por ambiente. Se ejecuta con la URL del migrador (que
administra el esquema y no está sujeto a la política por empresa):

    $env:CC_MIGRAR_URL = 'postgresql+psycopg://...'
    uv run python scripts/bootstrap_admin.py --razon-social "Mi Empresa SA de CV"

Reglas:
- Idempotente: si ya existe una empresa con esa razón social (sin distinguir mayúsculas), no
  crea otra ni genera invitación. Para una invitación nueva se exige ``--nueva-invitacion``.
- El código de invitación se muestra **una sola vez**, solo en una consola interactiva. En un
  proceso sin consola (CI, redirección, tuberías) el script se niega a crear la invitación, para
  que el código no termine en un archivo de registro. Solo se guarda su SHA-256.
- La URL de la base nunca se imprime.

La siembra de campos sugeridos (INT-CAM-02) la hace el servicio ``campos`` cuando exista
(T-044 en adelante); este script no la incluye todavía.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ), str(RAIZ / "services" / "shared"), str(RAIZ / "services" / "campos")]

RFC_ORG = re.compile(r"^[A-ZÑ&]{3}\d{6}[A-Z0-9]{3}$")
CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ErrorBootstrap(Exception):  # noqa: N818
    """Error de uso con un mensaje seguro para mostrar."""


@dataclass(frozen=True)
class Resultado:
    empresa_id: int
    empresa_creada: bool
    campos_creados: int = 0
    invitacion_id: int | None = None
    codigo: str | None = None
    fecha_expira: datetime | None = None


def sembrar_campos(conn, empresa_id: int) -> int:
    """Siembra los campos sugeridos (catálogo de `cc_campos.catalogo`, design.md §3.4).

    Idempotente por clave; devuelve cuántos creó. Equivale a INT-CAM-02, sin pasar por el
    servicio: el script corre con la URL del migrador antes de que exista ningún servicio.
    """
    from cc_campos.catalogo import SUGERIDOS

    conn.execute("SELECT pg_advisory_xact_lock(hashtext('cc_campos_sembrado'), %s)", (empresa_id,))
    presentes = {
        c[0]
        for c in conn.execute(
            "SELECT clave FROM campos.campo_colaborador WHERE empresa_id = %s", (empresa_id,)
        )
    }
    creados = 0
    for s in SUGERIDOS:
        if s.clave in presentes:
            continue
        ultimo = conn.execute(
            "INSERT INTO campos.contador_campo (empresa_id, ultimo) VALUES (%s, 1) "
            "ON CONFLICT (empresa_id) DO UPDATE SET ultimo = contador_campo.ultimo + 1 "
            "RETURNING ultimo",
            (empresa_id,),
        ).fetchone()[0]
        codigo = f"CAMP-{ultimo:04d}"
        campo_id = conn.execute(
            "INSERT INTO campos.campo_colaborador (empresa_id, nombre_campo, clave, "
            "codigo_interno, tipo_dato, formato_validacion, obligatorio, orden, activo, "
            "es_sensible, es_sugerido) VALUES (%s, %s, %s, %s, %s, %s, false, "
            "(SELECT coalesce(max(orden), 0) + 1 FROM campos.campo_colaborador "
            " WHERE empresa_id = %s AND NOT eliminado), %s, %s, true) RETURNING id",
            (
                empresa_id,
                s.nombre,
                s.clave,
                codigo,
                s.tipo_dato,
                s.formato,
                empresa_id,
                s.activo,
                s.es_sensible,
            ),
        ).fetchone()[0]
        for orden, (etiqueta, valor) in enumerate(s.opciones, start=1):
            conn.execute(
                "INSERT INTO campos.opcion_campo (empresa_id, campo_id, etiqueta, valor, orden) "
                "VALUES (%s, %s, %s, %s, %s)",
                (empresa_id, campo_id, etiqueta, valor, orden),
            )
        conn.execute(
            "INSERT INTO auditoria.bitacora (empresa_id, accion, entidad, entidad_id, origen, "
            "detalle) VALUES (%s, 'CAMPO_CREADO', 'campo_colaborador', %s, 'SISTEMA', %s::jsonb)",
            (empresa_id, campo_id, json.dumps({"codigos_internos": [codigo]})),
        )
        creados += 1
    return creados


def bootstrap(
    url: str,
    *,
    razon_social: str,
    rfc: str | None = None,
    correo_destino: str | None = None,
    horas: int = 72,
    nueva_invitacion: bool = False,
    puede_mostrar_codigo: bool = False,
) -> Resultado:
    import psycopg

    razon_social = razon_social.strip()
    rfc = rfc.strip().upper() if rfc else None
    correo = correo_destino.strip().lower() if correo_destino else None
    if not razon_social:
        raise ErrorBootstrap("La razón social es obligatoria.")
    if rfc and not RFC_ORG.match(rfc):
        raise ErrorBootstrap("El RFC de la empresa no tiene un formato válido.")
    if correo and not CORREO.match(correo):
        raise ErrorBootstrap("El correo de destino no es válido.")
    if not 1 <= horas <= 168:
        raise ErrorBootstrap("La vigencia debe estar entre 1 y 168 horas.")

    crudo = url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(crudo) as conn, conn.transaction():
        # Evita que dos ejecuciones simultáneas creen la misma empresa dos veces.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('cc_bootstrap_admin'))")
        fila = conn.execute(
            "SELECT id FROM identidad.empresa WHERE lower(razon_social) = lower(%s) ORDER BY id",
            (razon_social,),
        ).fetchone()
        creada = fila is None
        if creada:
            empresa_id = conn.execute(
                "INSERT INTO identidad.empresa (razon_social, rfc) VALUES (%s, %s) RETURNING id",
                (razon_social, rfc),
            ).fetchone()[0]
        else:
            empresa_id = fila[0]

        campos_creados = sembrar_campos(conn, empresa_id)
        if not creada and not nueva_invitacion:
            return Resultado(
                empresa_id=empresa_id, empresa_creada=False, campos_creados=campos_creados
            )
        if not puede_mostrar_codigo:
            # Se lanza dentro de la transacción: la empresa recién creada se revierte.
            raise ErrorBootstrap(
                "El código solo se muestra en una consola interactiva. Ejecute el script "
                "directamente en una terminal, sin redirigir la salida."
            )

        codigo = secrets.token_urlsafe(16)  # 128 bits
        inv_id, expira = conn.execute(
            "INSERT INTO identidad.invitacion_registro "
            "(empresa_id, codigo_hash, correo_destino, fecha_expira) "
            "VALUES (%s, %s, %s, now() + make_interval(hours => %s)) RETURNING id, fecha_expira",
            (empresa_id, hashlib.sha256(codigo.encode()).digest(), correo, horas),
        ).fetchone()
        conn.execute(
            "INSERT INTO auditoria.bitacora (empresa_id, accion, entidad, entidad_id, origen) "
            "VALUES (%s, 'INVITACION_CREADA', 'invitacion_registro', %s, 'SISTEMA')",
            (empresa_id, inv_id),
        )
    return Resultado(
        empresa_id=empresa_id,
        empresa_creada=creada,
        campos_creados=campos_creados,
        invitacion_id=inv_id,
        codigo=codigo,
        fecha_expira=expira,
    )


def _interactiva() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def main(argv: list[str] | None = None) -> int:
    p = ArgumentParser(description="Crea la primera empresa y su invitación de registro.")
    p.add_argument("--razon-social", required=True)
    p.add_argument("--rfc", help="RFC de la empresa (opcional).")
    p.add_argument("--correo-destino", help="Si se indica, el registro exigirá este correo.")
    p.add_argument("--horas", type=int, default=72, help="Vigencia de la invitación (1 a 168).")
    p.add_argument(
        "--nueva-invitacion",
        action="store_true",
        help="Genera otra invitación para una empresa que ya existe.",
    )
    a = p.parse_args(argv)

    url = os.environ.get("CC_MIGRAR_URL")
    if not url:
        print("Falta CC_MIGRAR_URL", file=sys.stderr)
        return 2
    try:
        r = bootstrap(
            url,
            razon_social=a.razon_social,
            rfc=a.rfc,
            correo_destino=a.correo_destino,
            horas=a.horas,
            nueva_invitacion=a.nueva_invitacion,
            puede_mostrar_codigo=_interactiva(),
        )
    except ErrorBootstrap as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - se reporta el tipo, nunca la URL
        print(
            f"Falló el arranque: {type(exc).__name__}: {str(exc).splitlines()[0][:300]}",
            file=sys.stderr,
        )
        return 1

    if r.codigo is None:
        print(
            f"La empresa ya existe (id {r.empresa_id}). No se creó ninguna invitación; "
            "use --nueva-invitacion si necesita otra."
        )
        return 0
    print(f"Empresa {'creada' if r.empresa_creada else 'existente'} (id {r.empresa_id}).")
    if r.campos_creados:
        print(f"Campos sugeridos sembrados: {r.campos_creados}.")
    print(f"Invitación {r.invitacion_id}, vigente hasta {r.fecha_expira:%Y-%m-%d %H:%M} UTC.")
    print()
    print(f"  CÓDIGO DE INVITACIÓN: {r.codigo}")
    print()
    print("Cópielo ahora: no se vuelve a mostrar y solo se guarda su huella (SHA-256).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
