"""Valores fijos del stack local. TODO lo de aquí es SOLO de desarrollo (datos de prueba)."""

from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
LOCAL = RAIZ / ".local"  # ignorado por git: PIDs, registros, llaves y secretos generados
LOGS = LOCAL / "logs"
ARCHIVO_PIDS = LOCAL / "pids.json"
ARCHIVO_SECRETOS = LOCAL / "secretos.json"
ARCHIVO_USUARIOS = LOCAL / "usuarios.json"
ARCHIVO_LLAVE_IDP = LOCAL / "idp_llave.pem"

# --- Base de datos (docker-compose.yml) ---
DB_HOST = "127.0.0.1"
DB_PUERTO = 55432
DB_NOMBRE = "command_center"
DB_ADMIN_USUARIO = "cc_local"
DB_ADMIN_CONTRASENA = "cc_local_solo_desarrollo"  # pragma: allowlist secret
ROLES_SERVICIO = (
    "svc_dashboard",
    "svc_colaboradores",
    "svc_campos",
    "svc_constancias",
    "svc_notificaciones",
    "svc_whatsapp",
    "migrador",
)

# --- LocalStack ---
LOCALSTACK = "http://localhost:4566"
LOCALSTACK_DESDE_CONTENEDOR = "http://host.docker.internal:4566"
REGION = "us-east-1"
CUENTA = "000000000000"
BUS = "cc-local-eventos"
LLAVE_ALIAS = "alias/cc-local-datos"
BUCKETS = ("cc-local-plantillas", "cc-local-cargas", "cc-local-constancias")
BUCKET_CON_OBJECT_LOCK = "cc-local-constancias"
# Mismas colas y tiempos de visibilidad que infra/stacks/messaging.py.
COLAS: dict[str, int] = {
    "cola-pdf": 180,
    "cola-cargas": 900,
    "wa-entrada.fifo": 60,
    "wa-salida.fifo": 180,
    "wa-estados": 180,
    "notif-despacho": 1800,
    "notif-respaldo": 360,
    "ev-colaboradores": 120,
    "ev-constancias": 120,
    "ev-notificaciones": 120,
}
RUTAS_EVENTOS: dict[str, tuple[str, ...]] = {
    "campo.actualizado": ("ev-colaboradores", "ev-constancias"),
    "wa.mensaje_estado": ("ev-constancias", "ev-notificaciones"),
    "wa.respuesta_recibida": ("ev-notificaciones",),
    "wa.plantilla_estado": ("ev-notificaciones",),
    "wa.numero_invalido": ("ev-colaboradores",),
}
SECRETOS_AWS = {
    "internal_auth": "cc/local/internal-auth",
    "hmac_celular": "cc/local/hmac-celular",
    "whatsapp_hmac": "cc/local/whatsapp-hmac",
}

# --- Procesos ---
PUERTO_PASARELA = 8000
PUERTO_SPA = 5173
PUERTOS_SERVICIOS = {
    "dashboard": 8101,
    "colaboradores": 8102,
    "campos": 8103,
    "constancias": 8104,
    "whatsapp": 8105,
}
EMISOR = f"http://127.0.0.1:{PUERTO_PASARELA}"
CLIENT_ID = "cc-local-spa"
IMAGEN_PDF = "cc-pruebas-pdf"
CONTENEDOR_PDF = "cc-local-worker-pdf"

# --- Usuarios de desarrollo (datos de prueba, documentados en docs/local.md) ---
CONTRASENA_DEV = "Desarrollo-Local-1!"  # pragma: allowlist secret
EMPRESA_DEMO = "Empresa Demo SA de CV"
USUARIOS_DEV = (
    {"nombre": "Ana Ramírez (RH)", "correo": "ana.rh@demo.test", "sub": "local-sub-ana"},
    {"nombre": "Luis Herrera (RH)", "correo": "luis.rh@demo.test", "sub": "local-sub-luis"},
)
